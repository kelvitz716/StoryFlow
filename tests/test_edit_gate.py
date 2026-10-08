"""
Tests for bot.edit_gate.EditCoordinator.
Verifies rate-limiting, dedup, RetryAfter backoff, BadRequest handling, and pacing.
"""
import asyncio
import time
import logging
import pytest
from bot.edit_gate import EditCoordinator, RetryAfter, BadRequest


class FakeMessage:
    def __init__(self, chat_id: int = 100, message_id: int = 1, clock_func=None):
        self.chat_id = chat_id
        self.message_id = message_id
        self.calls = []
        self._clock = clock_func
        self._on_edit_hook = None

    async def edit_text(self, text, parse_mode=None, reply_markup=None):
        now = self._clock() if self._clock else time.time()
        self.calls.append({
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
            "timestamp": now,
        })
        if self._on_edit_hook:
            await self._on_edit_hook(text)


class FakeClock:
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time

    def time(self) -> float:
        return self.current_time

    async def sleep(self, seconds: float) -> None:
        self.current_time += seconds
        # Yield to allow any other tasks to run at current simulated tick
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_50_concurrent_edits_for_one_chat():
    """
    50 concurrent request_edit calls for one chat -> at most one API call
    per 1.5s window; the final text is eventually sent.
    """
    fake_clock = FakeClock()
    coord = EditCoordinator(
        edit_min_interval=1.5,
        msg_min_interval=3.5,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )

    msg = FakeMessage(chat_id=101, message_id=1, clock_func=fake_clock.time)

    # 50 rapid calls with incrementing text
    for i in range(1, 51):
        coord.request_edit(msg, f"Update {i}", terminal=(i == 50))

    await coord.flush(str(msg.chat_id))

    # The final text must be sent
    assert len(msg.calls) >= 1
    assert msg.calls[-1]["text"] == "Update 50"

    # Verify per-chat pacing: at most one API call per 1.5s window
    for idx in range(1, len(msg.calls)):
        diff = msg.calls[idx]["timestamp"] - msg.calls[idx - 1]["timestamp"]
        assert diff >= 1.5 - 1e-6, f"API calls {idx-1} and {idx} were only {diff}s apart!"


@pytest.mark.asyncio
async def test_50_concurrent_different_messages_paced():
    """
    50 distinct messages edited concurrently in the same chat -> each spaced >=1.5s apart.
    """
    fake_clock = FakeClock()
    coord = EditCoordinator(
        edit_min_interval=1.5,
        msg_min_interval=3.5,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )

    messages = [FakeMessage(chat_id=202, message_id=i, clock_func=fake_clock.time) for i in range(1, 51)]
    for i, m in enumerate(messages):
        coord.request_edit(m, f"Status for msg {i}", terminal=True)

    await coord.flush("202")

    all_calls = []
    for m in messages:
        all_calls.extend(m.calls)

    all_calls.sort(key=lambda c: c["timestamp"])
    assert len(all_calls) == 50
    for idx in range(1, len(all_calls)):
        diff = all_calls[idx]["timestamp"] - all_calls[idx - 1]["timestamp"]
        assert diff >= 1.5 - 1e-6, f"Chat calls {idx-1} and {idx} were only {diff}s apart!"


@pytest.mark.asyncio
async def test_identical_text_twice():
    """Identical text twice -> exactly one API call."""
    fake_clock = FakeClock()
    coord = EditCoordinator(
        edit_min_interval=1.5,
        msg_min_interval=3.5,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    msg = FakeMessage(chat_id=303, message_id=1, clock_func=fake_clock.time)

    coord.request_edit(msg, "Same text")
    await coord.flush(str(msg.chat_id))
    assert len(msg.calls) == 1

    # Request exact same text again after flushing
    coord.request_edit(msg, "Same text")
    await coord.flush(str(msg.chat_id))
    assert len(msg.calls) == 1  # Still 1, skipped by deduplication


@pytest.mark.asyncio
async def test_retry_after_gating(caplog):
    """
    RetryAfter(40) -> zero calls during the gate; latest pending text sent after;
    terminal edit is sent; no ERROR-level logs; request_edit returns in <50ms.
    """
    fake_clock = FakeClock(start_time=1000.0)
    coord = EditCoordinator(
        edit_min_interval=1.5,
        msg_min_interval=3.5,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    msg = FakeMessage(chat_id=404, message_id=1, clock_func=fake_clock.time)

    # First call will raise RetryAfter(40)
    raised = False

    async def hook(text):
        nonlocal raised
        if not raised:
            raised = True
            raise RetryAfter(retry_after=40)

    msg._on_edit_hook = hook

    start_real = time.perf_counter()
    coord.request_edit(msg, "First attempt")
    duration_ms = (time.perf_counter() - start_real) * 1000
    assert duration_ms < 50.0, f"request_edit took {duration_ms}ms, expected <50ms"

    # Enqueue updates during the gate window
    coord.request_edit(msg, "Intermediate attempt (should be superseded)")
    coord.request_edit(msg, "Final terminal result", terminal=True)

    with caplog.at_level(logging.ERROR):
        await coord.flush("404")

    # Zero ERROR level logs
    error_logs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_logs) == 0

    # Ensure gate duration was respected (now >= start + 40 + 1)
    assert fake_clock.current_time >= 1041.0

    # Latest pending text and terminal edit was sent
    assert len(msg.calls) >= 1
    assert msg.calls[-1]["text"] == "Final terminal result"


@pytest.mark.asyncio
async def test_message_not_modified_no_error_log(caplog):
    """'Message is not modified' -> treated as success, no ERROR log."""
    fake_clock = FakeClock()
    coord = EditCoordinator(
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    msg = FakeMessage(chat_id=505, message_id=1, clock_func=fake_clock.time)

    async def hook(text):
        raise BadRequest("Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message")

    msg._on_edit_hook = hook

    with caplog.at_level(logging.ERROR):
        coord.request_edit(msg, "Same text")
        await coord.flush("505")

    error_logs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_logs) == 0
    # Content recorded as last sent
    assert coord._last_sent_content.get(1) == ("Same text", None)


@pytest.mark.asyncio
async def test_none_message_safety():
    """request_edit handles None message safely without throwing."""
    fake_clock = FakeClock()
    coord = EditCoordinator(clock=fake_clock.time, sleep_func=fake_clock.sleep)
    coord.request_edit(None, "Text")  # Must not crash
