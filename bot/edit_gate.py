"""
Centralized message edit rate-limiter and queue (EditCoordinator).
Paces edits per chat and per message to prevent Telegram 429 RetryAfter storms.
"""
import os
import time
import logging
from typing import Optional, Callable, Awaitable, Dict, Any, Tuple
from collections import OrderedDict
import asyncio

try:
    from telegram.error import RetryAfter, BadRequest
except ImportError:
    class RetryAfter(Exception):
        def __init__(self, retry_after=1):
            super().__init__(f"Flood control exceeded. Retry in {retry_after} seconds")
            self.retry_after = retry_after

    class BadRequest(Exception):
        pass


class _EditRequest:
    """Internal representation of a requested message edit."""
    __slots__ = ("message", "text", "parse_mode", "reply_markup", "terminal", "request_time")

    def __init__(
        self,
        message: Any,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup: Any = None,
        terminal: bool = False,
        request_time: float = 0.0,
    ):
        self.message = message
        self.text = text
        self.parse_mode = parse_mode
        self.reply_markup = reply_markup
        self.terminal = terminal
        self.request_time = request_time


class EditCoordinator:
    """
    Coordinates and paces Telegram message edits.
    
    Guarantees:
    - request_edit returns immediately without blocking.
    - Latest-wins per message: newer pending edits replace older ones.
    - Skips edits if text and markup match the last successfully sent version.
    - Shared per-chat pacing: at least EDIT_MIN_INTERVAL_SECONDS (default 1.5) between any two edits.
    - Per-message pacing: non-terminal edits are spaced at least 3.5s apart per message.
    - RetryAfter(n): opens a per-chat gate until now + n + 1. Terminal edits are never dropped and flush when the gate opens.
    - BadRequest "Message is not modified" is treated as success without error logging.
    - Injectable clock and sleep_func for fast deterministic testing.
    """

    def __init__(
        self,
        edit_min_interval: Optional[float] = None,
        msg_min_interval: Optional[float] = None,
        clock: Optional[Callable[[], float]] = None,
        sleep_func: Optional[Callable[[float], Awaitable[None]]] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        if edit_min_interval is None:
            self.edit_min_interval = float(os.getenv("EDIT_MIN_INTERVAL_SECONDS", "1.5"))
        else:
            self.edit_min_interval = float(edit_min_interval)

        if msg_min_interval is None:
            self.msg_min_interval = float(os.getenv("EDIT_MSG_MIN_INTERVAL_SECONDS", "3.5"))
        else:
            self.msg_min_interval = float(msg_min_interval)

        self.clock: Callable[[], float] = clock if clock is not None else time.time
        self.sleep_func: Callable[[float], Awaitable[None]] = sleep_func if sleep_func is not None else asyncio.sleep
        self._loop: Optional[asyncio.AbstractEventLoop] = loop

        # chat_id -> OrderedDict[msg_id, _EditRequest]
        self._pending_edits: Dict[str, OrderedDict[int, _EditRequest]] = {}
        # chat_id -> asyncio.Task
        self._chat_tasks: Dict[str, asyncio.Task] = {}
        # chat_id -> gate_until_timestamp
        self._chat_gate_until: Dict[str, float] = {}
        # chat_id -> timestamp of last edit sent
        self._last_chat_edit_time: Dict[str, float] = {}
        # (chat_id, msg_id) -> timestamp of last edit sent
        self._last_msg_edit_time: Dict[Tuple[str, int], float] = {}
        # (chat_id, msg_id) -> (last_sent_text, last_sent_markup)
        self._last_sent_content: Dict[Tuple[str, int], Tuple[str, Any]] = {}

    @staticmethod
    def _extract_chat_id(message: Any) -> Optional[str]:
        if message is None:
            return None
        if hasattr(message, "chat_id") and message.chat_id is not None:
            return str(message.chat_id)
        if hasattr(message, "chat") and message.chat is not None:
            if hasattr(message.chat, "id") and message.chat.id is not None:
                return str(message.chat.id)
        return None

    @staticmethod
    def _extract_msg_id(message: Any) -> Optional[int]:
        if message is None:
            return None
        if hasattr(message, "message_id") and message.message_id is not None:
            return int(message.message_id)
        if hasattr(message, "id") and message.id is not None:
            return int(message.id)
        return id(message)

    def request_edit(
        self,
        message: Any,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup: Any = None,
        terminal: bool = False,
    ) -> None:
        """
        Request a message edit. Returns immediately without awaiting network.
        """
        if message is None:
            return

        chat_id = self._extract_chat_id(message)
        msg_id = self._extract_msg_id(message)
        if not chat_id or msg_id is None:
            return

        msg_key = (chat_id, msg_id)

        # Check deduplication against last successfully sent content for this (chat_id, msg_id)
        last_sent = self._last_sent_content.get(msg_key)
        if last_sent == (text, reply_markup):
            # If a pending edit exists that reverted to last_sent, remove it
            if chat_id in self._pending_edits:
                self._pending_edits[chat_id].pop(msg_id, None)
            return

        if chat_id not in self._pending_edits:
            self._pending_edits[chat_id] = OrderedDict()

        existing = self._pending_edits[chat_id].get(msg_id)
        # Terminal state must never be downgraded
        is_terminal = terminal or (existing.terminal if existing else False)

        now = self.clock()
        req = _EditRequest(
            message=message,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            terminal=is_terminal,
            request_time=now,
        )
        # Latest-wins per message
        self._pending_edits[chat_id][msg_id] = req

        self._ensure_worker(chat_id)

    def _get_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        if self._loop is not None and self._loop.is_running():
            return self._loop
        try:
            loop = asyncio.get_running_loop()
            if self._loop is None:
                self._loop = loop
            return loop
        except RuntimeError:
            return self._loop

    def _ensure_worker(self, chat_id: str) -> None:
        task = self._chat_tasks.get(chat_id)
        if task is not None and not task.done():
            return

        loop = self._get_loop()
        if loop and loop.is_running():
            try:
                curr_loop = asyncio.get_running_loop()
                if curr_loop is loop:
                    self._chat_tasks[chat_id] = loop.create_task(self._chat_worker(chat_id))
                else:
                    self._chat_tasks[chat_id] = asyncio.run_coroutine_threadsafe(
                        self._chat_worker(chat_id), loop
                    )  # type: ignore
            except RuntimeError:
                self._chat_tasks[chat_id] = asyncio.run_coroutine_threadsafe(
                    self._chat_worker(chat_id), loop
                )  # type: ignore

    async def _chat_worker(self, chat_id: str) -> None:
        try:
            while True:
                pending = self._pending_edits.get(chat_id)
                if not pending:
                    break

                now = self.clock()

                # 1. Respect RetryAfter gate
                gate_until = self._chat_gate_until.get(chat_id, 0)
                if now < gate_until:
                    sleep_time = gate_until - now
                    await self.sleep_func(sleep_time)
                    continue

                # 2. Respect per-chat minimum interval
                last_chat_time = self._last_chat_edit_time.get(chat_id, 0)
                chat_delay = self.edit_min_interval - (now - last_chat_time)
                if chat_delay > 0:
                    await self.sleep_func(chat_delay)
                    continue

                # 3. Find candidate ready to send
                now = self.clock()
                ready_msg_id = None
                min_wait = None

                # Prioritize terminal edits (never delayed by per-message pacing)
                for mid, req in pending.items():
                    if req.terminal:
                        ready_msg_id = mid
                        break

                # If no terminal edit, find first non-terminal edit satisfying message interval
                if ready_msg_id is None:
                    for mid, req in pending.items():
                        last_msg_time = self._last_msg_edit_time.get((chat_id, mid), 0)
                        msg_delay = self.msg_min_interval - (now - last_msg_time)
                        if msg_delay <= 0:
                            ready_msg_id = mid
                            break
                        else:
                            if min_wait is None or msg_delay < min_wait:
                                min_wait = msg_delay

                if ready_msg_id is None:
                    # Cooldown for non-terminal edit
                    wait_to_sleep = min_wait if (min_wait is not None and min_wait > 0) else 0.05
                    await self.sleep_func(wait_to_sleep)
                    continue

                req = pending.get(ready_msg_id)
                if not req:
                    continue

                ready_msg_key = (chat_id, ready_msg_id)

                # Deduplication check
                last_sent = self._last_sent_content.get(ready_msg_key)
                if last_sent == (req.text, req.reply_markup):
                    pending.pop(ready_msg_id, None)
                    continue

                # Execute edit_text
                try:
                    kwargs = {}
                    if req.parse_mode is not None:
                        kwargs["parse_mode"] = req.parse_mode
                    if req.reply_markup is not None:
                        kwargs["reply_markup"] = req.reply_markup

                    await req.message.edit_text(req.text, **kwargs)

                    sent_time = self.clock()
                    self._last_sent_content[ready_msg_key] = (req.text, req.reply_markup)
                    self._last_msg_edit_time[ready_msg_key] = sent_time
                    self._last_chat_edit_time[chat_id] = sent_time

                    if pending.get(ready_msg_id) is req:
                        pending.pop(ready_msg_id, None)

                except Exception as e:
                    err_str = str(e).lower()
                    is_retry_after = (
                        hasattr(e, "retry_after")
                        or isinstance(e, RetryAfter)
                        or e.__class__.__name__ == "RetryAfter"
                    )
                    if is_retry_after:
                        retry_seconds = getattr(e, "retry_after", 1)
                        if hasattr(retry_seconds, "total_seconds"):
                            retry_seconds = retry_seconds.total_seconds()
                        else:
                            try:
                                retry_seconds = float(retry_seconds)
                            except (ValueError, TypeError):
                                retry_seconds = 1.0
                        now_err = self.clock()
                        gate_until = now_err + retry_seconds + 1
                        self._chat_gate_until[chat_id] = max(
                            self._chat_gate_until.get(chat_id, 0),
                            gate_until,
                        )
                        logging.warning(
                            f"Telegram RetryAfter({retry_seconds}s) for chat {chat_id}. Gate open until {gate_until}."
                        )
                        # Keep pending edit so it flushes when the gate opens
                        continue

                    is_not_modified = (
                        isinstance(e, BadRequest)
                        or e.__class__.__name__ == "BadRequest"
                        or "not modified" in err_str
                    ) and "not modified" in err_str

                    if is_not_modified:
                        sent_time = self.clock()
                        self._last_sent_content[ready_msg_key] = (req.text, req.reply_markup)
                        self._last_msg_edit_time[ready_msg_key] = sent_time
                        self._last_chat_edit_time[chat_id] = sent_time
                        if pending.get(ready_msg_id) is req:
                            pending.pop(ready_msg_id, None)
                        logging.debug(f"Message {ready_msg_id} not modified; treated as success.")
                        continue

                    logging.warning(f"Failed to edit message {ready_msg_id} in chat {chat_id}: {e}")
                    if pending.get(ready_msg_id) is req:
                        pending.pop(ready_msg_id, None)

        finally:
            if not self._pending_edits.get(chat_id):
                self._pending_edits.pop(chat_id, None)
            self._chat_tasks.pop(chat_id, None)

    async def flush(self, chat_id: Optional[str] = None) -> None:
        """Wait for pending edits in chat_id (or all chats) to finish processing."""
        if chat_id:
            task = self._chat_tasks.get(chat_id)
            if task and not task.done():
                await task
        else:
            tasks = [t for t in list(self._chat_tasks.values()) if not t.done()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


_default_coordinator: Optional[EditCoordinator] = None


def get_edit_coordinator() -> EditCoordinator:
    """Retrieve the global EditCoordinator instance."""
    global _default_coordinator
    if _default_coordinator is None:
        _default_coordinator = EditCoordinator()
    return _default_coordinator


def set_edit_coordinator(coordinator: EditCoordinator) -> None:
    """Override the global EditCoordinator instance (useful for testing)."""
    global _default_coordinator
    _default_coordinator = coordinator


def request_edit(
    message: Any,
    text: str,
    parse_mode: Optional[str] = None,
    reply_markup: Any = None,
    terminal: bool = False,
) -> None:
    """Request a message edit through the active EditCoordinator."""
    get_edit_coordinator().request_edit(
        message=message,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        terminal=terminal,
    )
