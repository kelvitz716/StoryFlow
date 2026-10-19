"""URL message handler and backlog rate-limiting engine."""

import re
import random
import logging
import asyncio
from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

from auth.access import AccessManager
from core.platform import identify_platform
from core.config import _env_float
from bot.uploader import batch_upload_media
from bot.edit_gate import request_edit, get_edit_coordinator, discard
from utils.bot_utils import (
    register_job_message,
    resolve_shortlink,
    UnsafeRedirectError,
    JOB_MESSAGES
)

PROCESSING_MSGS = [
    "🔍 Checking URL...",
    "🧐 Analyzing link...",
    "💾 Processing request...",
    "⚡ One moment please..."
]

# Backlog mode tracking
_CHAT_BURSTS: dict = {}
_LAST_BACKLOG_SUBMIT: dict = {}
_BACKLOG_LOCKS: dict = {}
_BACKLOG_JOBS: dict = {}
_DEFERRED_SUMMARY_TASKS: dict = {}


def _get_backlog_lock(chat_id: str) -> asyncio.Lock:
    if chat_id not in _BACKLOG_LOCKS:
        _BACKLOG_LOCKS[chat_id] = asyncio.Lock()
    return _BACKLOG_LOCKS[chat_id]


async def _safe_reply(msg, text: str, parse_mode: str = None, **kwargs) -> None:
    """Send a reply_text, silently swallowing RetryAfter (gate is already open)."""
    try:
        await msg.reply_text(text, parse_mode=parse_mode, **kwargs)
    except RetryAfter:
        pass


def _format_burst_summary(burst: dict) -> str:
    """Format the single summary message for a backlog burst with queued/done/failed counts."""
    done = burst.get("done", 0)
    failed = burst.get("failed", 0)
    queued = burst.get("count", 0)
    left = max(0, queued - done - failed)

    text = f"Back online: {done} done, {failed} failed, {left} left"
    failed_links = burst.get("failed_links", [])
    if failed_links:
        text += "\n\nFailed links:"
        for link in failed_links[:5]:
            text += f"\n• {link}"
        if len(failed_links) > 5:
            more = len(failed_links) - 5
            text += f"\nand {more} more"
    return text


def register_backlog_job(job_id: str, chat_id: str, url: str) -> None:
    """Register a queued backlog job to track its outcome in its chat burst."""
    _BACKLOG_JOBS[str(job_id)] = {
        "chat_id": str(chat_id),
        "url": str(url),
    }


def record_backlog_job_outcome(job) -> None:
    """Record completion or failure of a backlog job and update the burst summary."""
    status = getattr(job, "status", None)
    status_str = str(getattr(status, "value", status)).lower()
    is_completed = "completed" in status_str
    is_failed = "failed" in status_str
    if not (is_completed or is_failed):
        return

    job_id = str(getattr(job, "job_id", ""))
    chat_id = None
    url = getattr(job, "url", "")

    if job_id and job_id in _BACKLOG_JOBS:
        info = _BACKLOG_JOBS.pop(job_id)
        chat_id = info["chat_id"]
        url = info.get("url", url)
    elif getattr(job, "chat_id", None) is not None:
        chat_id = str(job.chat_id)

    if not chat_id or chat_id not in _CHAT_BURSTS:
        return

    burst = _CHAT_BURSTS[chat_id]
    if is_completed:
        burst["done"] = burst.get("done", 0) + 1
    elif is_failed:
        burst["failed"] = burst.get("failed", 0) + 1
        if url:
            failed_links = burst.setdefault("failed_links", [])
            failed_links.append(url)

    summary_msg = burst.get("summary_msg")
    if summary_msg:
        summary_text = _format_burst_summary(burst)
        request_edit(summary_msg, summary_text)


def record_backlog_job_failure(chat_id: str, url: str) -> None:
    """Record an immediate backlog job failure (e.g. queue full) and update summary."""
    chat_id = str(chat_id)
    if chat_id not in _CHAT_BURSTS:
        return
    burst = _CHAT_BURSTS[chat_id]
    burst["failed"] = burst.get("failed", 0) + 1
    if url:
        failed_links = burst.setdefault("failed_links", [])
        failed_links.append(url)

    summary_msg = burst.get("summary_msg")
    if summary_msg:
        summary_text = _format_burst_summary(burst)
        request_edit(summary_msg, summary_text)


async def _deferred_summary_sender(msg, chat_id: str) -> None:
    """Deferred sender that posts the burst summary message once flood control clears."""
    coord = get_edit_coordinator()
    try:
        while coord.send_gate_open(chat_id):
            gate_until = coord._chat_gate_until.get(str(chat_id), 0)
            wait_time = max(0.01, gate_until - coord.clock())
            await coord.sleep_func(wait_time)

        burst = _CHAT_BURSTS.get(chat_id)
        if not burst or burst.get("summary_msg") is not None:
            return

        if burst.get("done", 0) > 0 or burst.get("failed", 0) > 0:
            summary_text = _format_burst_summary(burst)
        else:
            n = burst.get("count", 1)
            summary_text = f"Back online: processing {n} queued links"

        try:
            summary_msg = await msg.reply_text(summary_text)
            burst["summary_msg"] = summary_msg
        except RetryAfter as e:
            coord.open_send_gate(chat_id, getattr(e, "retry_after", 1))
            _launch_deferred_summary(msg, chat_id)
        except Exception as e:
            logging.debug(f"Deferred summary send failed: {e}")
    except Exception as e:
        logging.debug(f"Deferred summary worker error: {e}")


def _launch_deferred_summary(msg, chat_id: str) -> None:
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_deferred_summary_sender(msg, chat_id))
        _DEFERRED_SUMMARY_TASKS[chat_id] = task
    except RuntimeError:
        pass


async def _register_backlog_link(msg, chat_id: str) -> None:
    """Send or update a single summary message for a burst of backlog links."""
    now = get_edit_coordinator().clock()
    burst = _CHAT_BURSTS.get(chat_id)
    if burst and (now - burst["last_time"] <= 30.0):
        burst["count"] += 1
        burst["last_time"] = now
        n = burst["count"]
        if burst.get("done", 0) > 0 or burst.get("failed", 0) > 0:
            summary_text = _format_burst_summary(burst)
        else:
            summary_text = f"Back online: processing {n} queued links"
        if burst.get("summary_msg") is not None:
            request_edit(burst["summary_msg"], summary_text)
    else:
        summary_text = "Back online: processing 1 queued links"
        summary_msg = None
        coord = get_edit_coordinator()
        try:
            summary_msg = await msg.reply_text(summary_text)
        except RetryAfter as e:
            coord.open_send_gate(chat_id, getattr(e, "retry_after", 1))
            _launch_deferred_summary(msg, chat_id)

        _CHAT_BURSTS[chat_id] = {
            "summary_msg": summary_msg,
            "count": 1,
            "done": 0,
            "failed": 0,
            "failed_links": [],
            "last_time": now,
        }


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                     access_manager: AccessManager, download_queue,
                     mtproto_client=None) -> None:
    """Handle URL message."""
    # Determine update type
    def _get_update_attr(attr: str):
        if hasattr(update, "_mock_return_value"):
            return getattr(update, "__dict__", {}).get(attr)
        return getattr(update, attr, None)

    if _get_update_attr("edited_message") is not None:
        update_type = "edited_message"
    elif _get_update_attr("edited_channel_post") is not None:
        update_type = "edited_channel_post"
    elif _get_update_attr("channel_post") is not None:
        update_type = "channel_post"
    elif _get_update_attr("message") is not None:
        update_type = "message"
    elif getattr(update, "effective_message", None) is not None:
        update_type = "message"
    else:
        update_type = "unknown"

    msg = getattr(update, "effective_message", None)
    update_id = getattr(update, "update_id", None)
    chat_id_val = getattr(update.effective_chat, "id", None) if getattr(update, "effective_chat", None) else None
    message_id_val = getattr(msg, "message_id", None) if msg else None
    sender_chat_id = getattr(getattr(msg, "sender_chat", None), "id", None) if msg else None
    is_auto_forward = bool(getattr(msg, "is_automatic_forward", False)) if msg else False

    logging.debug(
        f"handle_url update_id={update_id} update_type={update_type} "
        f"chat_id={chat_id_val} message_id={message_id_val} "
        f"sender_chat_id={sender_chat_id} is_automatic_forward={is_auto_forward}"
    )

    if not msg or not msg.text:
        return

    # Silently ignore edits (item 3)
    if update_type in ("edited_message", "edited_channel_post"):
        logging.debug(f"Ignoring edit update {update_id} for message {message_id_val}")
        return

    # Check if this text should be handled by admin input instead (group 0 handles it,
    # but we double check here to prevent duplicate processing)
    if context.user_data and context.user_data.get('awaiting_action'):
        return

    # Check if awaiting cookies
    if context.user_data and context.user_data.get('awaiting_cookies'):
        return

    url_text = msg.text.strip()
    raw_user_id = str(update.effective_user.id) if update.effective_user else None

    # Recognize channel IDs, sender_chat IDs, and automatic forwards
    if msg.sender_chat and msg.sender_chat.id:
        user_id = str(msg.sender_chat.id)
    elif is_auto_forward and update.effective_chat:
        user_id = str(update.effective_chat.id)
    elif not raw_user_id and update.effective_chat:
        user_id = str(update.effective_chat.id)
    else:
        user_id = raw_user_id

    if not access_manager.is_allowed(user_id):
        if not access_manager.is_admin(user_id):
            await msg.reply_text(
                f"⛔ Not authorized.\n"
                f"Ask the admin to authorize your ID: `{user_id}`",
                parse_mode='Markdown'
            )
            return

    # URL extraction
    spaced_text = url_text.replace('http', ' http')
    raw_urls = re.findall(r'https?://[^\s]+', spaced_text)

    def _clean_url(u: str) -> str:
        _ALWAYS = set('.,!?;:\'"›«>‼…')
        while u:
            ch = u[-1]
            if ch in _ALWAYS:
                u = u[:-1]
            elif ch == ')' and u.count('(') < u.count(')'):
                u = u[:-1]
            elif ch == ']' and u.count('[') < u.count(']'):
                u = u[:-1]
            else:
                break
        return u

    urls = []
    for u in raw_urls:
        clean_u = _clean_url(u)
        if clean_u and clean_u not in urls:
            urls.append(clean_u)

    if not urls:
        return

    if len(urls) > 10:
        await msg.reply_text("⚠️ You can only queue up to 10 links at a time. Processing the first 10...")
        urls = urls[:10]

    chat_id = str(update.effective_chat.id)

    # Backlog detection: message older than BACKLOG_AGE_SECONDS (default 60s)
    backlog_age_threshold = _env_float("BACKLOG_AGE_SECONDS", 60.0, 0.0, 86400.0)
    is_backlog = False
    if hasattr(msg, "date") and msg.date:
        if hasattr(msg.date, "timestamp") and callable(msg.date.timestamp):
            try:
                raw_ts = msg.date.timestamp()
                msg_ts = float(raw_ts) if isinstance(raw_ts, (int, float)) else None
            except Exception:
                msg_ts = None
        elif isinstance(msg.date, (int, float)):
            msg_ts = float(msg.date)
        else:
            msg_ts = None
        if msg_ts is not None:
            now_clock = get_edit_coordinator().clock()
            if (now_clock - msg_ts) > backlog_age_threshold:
                is_backlog = True

    for raw_url in urls:
        try:
            url = await resolve_shortlink(raw_url)
        except UnsafeRedirectError:
            logging.warning(f"handle_url: rejected unsafe/unresolvable redirect from {raw_url!r}")
            await msg.reply_text(
                "⛔ *This link can't be downloaded.*",
                parse_mode='Markdown'
            )
            continue

        platform = identify_platform(url)
        if platform == "Unknown":
            await msg.reply_text(
                f"❌ *Invalid Link*\n\n`{raw_url}`\n"
                "Please enter a valid, public HTTP or HTTPS link.",
                parse_mode='Markdown'
            )
            continue
        
        status_msg = None
        coord = get_edit_coordinator()
        if not is_backlog and coord.send_gate_open(chat_id):
            is_backlog = True

        if not is_backlog:
            proc_msg = random.choice(PROCESSING_MSGS)
            try:
                status_msg = await msg.reply_text(f"{proc_msg}")
            except RetryAfter as _e:
                coord.open_send_gate(chat_id, getattr(_e, "retry_after", 1))
                is_backlog = True
                status_msg = None
        
        def make_upload_func(sm):
            async def upload_func(files):
                await batch_upload_media(update, files, sm, mtproto_client)
            return upload_func

        if is_backlog:
            async with _get_backlog_lock(chat_id):
                await _register_backlog_link(msg, chat_id)
                submit_delay = _env_float("BACKLOG_SUBMIT_DELAY_SECONDS", 1.5, 0.0, 60.0)
                now = get_edit_coordinator().clock()
                last_submit = _LAST_BACKLOG_SUBMIT.get(chat_id, 0.0)
                delay_needed = submit_delay - (now - last_submit)
                if delay_needed > 0:
                    await get_edit_coordinator().sleep_func(delay_needed)
                _LAST_BACKLOG_SUBMIT[chat_id] = get_edit_coordinator().clock()

                if download_queue:
                    job = await download_queue.submit(
                        user_id=user_id,
                        url=url,
                        platform=platform,
                        upload_func=make_upload_func(status_msg),
                        chat_id=chat_id,
                        message_id=msg.message_id
                    )
                    if job:
                        register_backlog_job(job.job_id, chat_id, url)
                    else:
                        record_backlog_job_failure(chat_id, url)
                        await _safe_reply(msg, "⚠️ *Queue Full*\nPlease wait for your active downloads to finish.", parse_mode='Markdown')
                else:
                    record_backlog_job_failure(chat_id, url)
                    await _safe_reply(msg, "⚠️ System Error: Queue not active.")
        else:
            if download_queue:
                job = await download_queue.submit(
                    user_id=user_id,
                    url=url,
                    platform=platform,
                    upload_func=make_upload_func(status_msg),
                    chat_id=chat_id,
                    message_id=msg.message_id
                )
                if job:
                    is_already_active = getattr(job, "is_already_active", False) or (
                        job.job_id in JOB_MESSAGES and JOB_MESSAGES[job.job_id] is not status_msg
                    )
                    if is_already_active:
                        logging.debug(f"Job {job.job_id} already active; dropping redundant status message")
                        if status_msg:
                            try:
                                discard(status_msg)
                                await status_msg.delete()
                            except Exception:
                                pass
                    else:
                        if status_msg:
                            register_job_message(job.job_id, status_msg)
                            pos = download_queue.get_queue_position(job.job_id)
                            if pos > 0:
                                request_edit(status_msg, f"⏳ *Queued* (Position: {pos})\nWaiting for worker...", parse_mode='Markdown')
                else:
                    if status_msg:
                        request_edit(status_msg, "⚠️ *Queue Full*\nPlease wait for your active downloads to finish.", terminal=True)
                    else:
                        await _safe_reply(msg, "⚠️ *Queue Full*\nPlease wait for your active downloads to finish.", parse_mode='Markdown')
            else:
                if status_msg:
                    request_edit(status_msg, "⚠️ System Error: Queue not active.", terminal=True)
                else:
                    await _safe_reply(msg, "⚠️ System Error: Queue not active.")
