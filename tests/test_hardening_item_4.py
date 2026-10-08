"""
Tests for hardening item 4:
Add coordinator.discard(message) and call it before every status_msg.delete();
a pending edit for a discarded message is dropped. Also log BadRequest
"message to edit not found" at DEBUG and drop the edit.
"""
import asyncio
import logging
import time
import pytest

from bot.edit_gate import (
    EditCoordinator,
    set_edit_coordinator,
    discard,
    BadRequest,
)


class FakeClock:
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time

    def time(self) -> float:
        return self.current_time

    async def sleep(self, seconds: float) -> None:
        self.current_time += max(0.0, seconds)
        await asyncio.sleep(0)


class FakeMessage:
    def __init__(self, chat_id: int = 100, message_id: int = 1, clock_func=None):
        self.chat_id = chat_id
        self.message_id = message_id
        self.edit_calls: list = []
        self._clock = clock_func

    async def edit_text(self, text, parse_mode=None, reply_markup=None):
        ts = self._clock() if self._clock else time.time()
        self.edit_calls.append({"text": text, "timestamp": ts})


@pytest.mark.asyncio
async def test_discard_drops_pending_edit():
    """edit requested, message discarded, gate opens -> zero edit calls for it."""
    fake_clock = FakeClock(start_time=1000.0)
    coord = EditCoordinator(
        edit_min_interval=0.0,
        msg_min_interval=0.0,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    set_edit_coordinator(coord)

    chat_id = "8001"
    msg = FakeMessage(chat_id=int(chat_id), message_id=1, clock_func=fake_clock.time)

    # 1. Edit requested
    coord.request_edit(msg, "Pending edit")

    # 2. Message discarded
    discard(msg)

    # 3. Gate opens (e.g. RetryAfter backoff)
    coord.open_send_gate(chat_id, retry_after=5)

    # Advance clock past the gate
    fake_clock.current_time = 1000.0 + 7
    await coord.flush(chat_id)

    # Zero edit calls for discarded message
    assert msg.edit_calls == [], f"Expected zero edit calls, got {msg.edit_calls}"


@pytest.mark.asyncio
async def test_discard_drops_future_edits():
    """Future edits for discarded message are dropped."""
    fake_clock = FakeClock(start_time=1000.0)
    coord = EditCoordinator(
        edit_min_interval=0.0,
        msg_min_interval=0.0,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    set_edit_coordinator(coord)

    msg = FakeMessage(chat_id=8002, message_id=2, clock_func=fake_clock.time)
    discard(msg)

    coord.request_edit(msg, "Should be dropped")
    await coord.flush(str(msg.chat_id))

    assert msg.edit_calls == []


@pytest.mark.asyncio
async def test_bad_request_message_not_found_logged_at_debug_and_dropped(caplog):
    """BadRequest 'message to edit not found' is logged at DEBUG and dropped."""
    fake_clock = FakeClock(start_time=1000.0)
    coord = EditCoordinator(
        edit_min_interval=0.0,
        msg_min_interval=0.0,
        clock=fake_clock.time,
        sleep_func=fake_clock.sleep,
    )
    set_edit_coordinator(coord)

    msg = FakeMessage(chat_id=9001, message_id=1, clock_func=fake_clock.time)

    async def hook(text, **kwargs):
        raise BadRequest("Bad Request: message to edit not found")

    msg.edit_text = hook

    with caplog.at_level(logging.DEBUG):
        coord.request_edit(msg, "Edit that will find message deleted")
        await coord.flush(str(msg.chat_id))

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    debug_records = [
        r for r in caplog.records
        if r.levelno == logging.DEBUG and "not found" in r.message.lower()
    ]

    assert len(error_records) == 0, f"Expected zero ERROR records, got: {[r.message for r in error_records]}"
    assert len(debug_records) >= 1, f"Expected at least one DEBUG record, got {debug_records}"
