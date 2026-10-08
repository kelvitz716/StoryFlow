"""
Tests for hardening item 2:
Share the per-chat gate with sends, not just edits: add coordinator.send_gate_open(chat_id)
and have the uploader check/respect it before reply_media_group/reply_text.
"""
import logging
import pytest

from bot.edit_gate import (
    EditCoordinator,
    set_edit_coordinator,
    send_gate_open,
)
from bot.uploader import send_gate_open as uploader_send_gate_open


class FakeClock:
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time

    def time(self) -> float:
        return self.current_time

    async def sleep(self, seconds: float) -> None:
        self.current_time += max(0.0, seconds)


def test_send_gate_open_reflects_coordinator_state():
    """send_gate_open() returns True while gate is active, False after expiry."""
    fake_clock = FakeClock(start_time=1000.0)
    coord = EditCoordinator(clock=fake_clock.time, sleep_func=fake_clock.sleep)
    set_edit_coordinator(coord)

    chat_id = "6001"
    assert not send_gate_open(chat_id), "Gate should start closed"

    # Open gate for 30s
    coord.open_send_gate(chat_id, retry_after=30)
    assert send_gate_open(chat_id), "Gate should be open immediately"

    # Advance clock past the gate
    fake_clock.current_time = 1000.0 + 30 + 1 + 1
    assert not send_gate_open(chat_id), "Gate should be closed after expiry"


def test_uploader_imports_and_checks_send_gate_open(caplog):
    """
    Uploader checks send_gate_open before sending.
    Verify uploader_send_gate_open returns True when gate is active.
    """
    fake_clock = FakeClock(start_time=1000.0)
    coord = EditCoordinator(clock=fake_clock.time, sleep_func=fake_clock.sleep)
    set_edit_coordinator(coord)

    chat_id = "7001"
    assert not uploader_send_gate_open(chat_id)

    with caplog.at_level(logging.WARNING):
        coord.open_send_gate(chat_id, retry_after=10)

    assert uploader_send_gate_open(chat_id)
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1
