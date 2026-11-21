from __future__ import annotations

import threading

import pytest

from ai.task_monitor import TaskMonitor
from core.errors import JobCancelled


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0.01)


class FakeClient:
    def __init__(self, start_tasks, conversations) -> None:
        self.start_tasks = list(start_tasks)
        self.conversations = list(conversations)
        self.start_calls = 0
        self.conversation_calls = 0

    def get_start_task(self, _task_id):
        self.start_calls += 1
        return self.start_tasks.pop(0) if len(self.start_tasks) > 1 else self.start_tasks[0]

    def get_conversation(self, _conversation_id):
        self.conversation_calls += 1
        return self.conversations.pop(0) if len(self.conversations) > 1 else self.conversations[0]

    def conversation_url(self, conversation_id, explicit=None):
        return explicit or f"https://app.all-hands.dev/conversations/{conversation_id}"


def build_monitor(client, clock, **kwargs) -> tuple[TaskMonitor, list]:
    events: list = []
    kwargs.setdefault("poll_interval", 1.0)
    kwargs.setdefault("startup_timeout", 10.0)
    kwargs.setdefault("execution_timeout", 10.0)
    monitor = TaskMonitor(
        client,
        on_progress=lambda message, level, data: events.append((message, level, data)),
        sleep=clock.sleep,
        clock=clock.clock,
        **kwargs,
    )
    return monitor, events


def test_success_flow() -> None:
    clock = FakeClock()
    client = FakeClient(
        [{"status": "WORKING"}, {"status": "READY", "app_conversation_id": "c1"}],
        [
            {"sandbox_status": "STARTING", "execution_status": None},
            {"sandbox_status": "RUNNING", "execution_status": "running"},
            {"sandbox_status": "RUNNING", "execution_status": "finished"},
        ],
    )
    monitor, events = build_monitor(client, clock)
    result = monitor.monitor("task-1")
    assert result.success is True
    assert result.conversation_id == "c1"
    assert result.execution_status == "finished"
    assert result.conversation_url.endswith("/conversations/c1")
    assert any(level == "success" for _message, level, _data in events)


def test_startup_error() -> None:
    clock = FakeClock()
    client = FakeClient([{"status": "ERROR", "detail": "repository unavailable"}], [])
    monitor, _ = build_monitor(client, clock)
    result = monitor.monitor("task-1")
    assert result.success is False
    assert "repository unavailable" in result.message


def test_startup_ready_without_conversation_id() -> None:
    clock = FakeClock()
    client = FakeClient([{"status": "READY", "app_conversation_id": None}], [])
    monitor, _ = build_monitor(client, clock)
    result = monitor.monitor("task-1")
    assert result.success is False
    assert "conversation id" in result.message


def test_startup_timeout() -> None:
    clock = FakeClock()
    client = FakeClient([{"status": "WAITING_FOR_SANDBOX"}], [])
    monitor, _ = build_monitor(client, clock, startup_timeout=2.0)
    result = monitor.monitor("task-1")
    assert result.success is False
    assert result.timed_out is True
    assert "Timed out" in result.message


def test_execution_error() -> None:
    clock = FakeClock()
    client = FakeClient(
        [{"status": "READY", "app_conversation_id": "c1"}],
        [{"sandbox_status": "RUNNING", "execution_status": "error"}],
    )
    monitor, _ = build_monitor(client, clock)
    result = monitor.monitor("task-1")
    assert result.success is False
    assert result.execution_status == "error"


def test_execution_stuck() -> None:
    clock = FakeClock()
    client = FakeClient(
        [{"status": "READY", "app_conversation_id": "c1"}],
        [{"sandbox_status": "RUNNING", "execution_status": "stuck"}],
    )
    monitor, _ = build_monitor(client, clock)
    result = monitor.monitor("task-1")
    assert result.success is False


def test_sandbox_missing_is_terminal_failure() -> None:
    clock = FakeClock()
    client = FakeClient(
        [{"status": "READY", "app_conversation_id": "c1"}],
        [{"sandbox_status": "MISSING", "execution_status": None}],
    )
    monitor, _ = build_monitor(client, clock)
    result = monitor.monitor("task-1")
    assert result.success is False
    assert result.sandbox_status == "MISSING"


def test_waiting_for_confirmation() -> None:
    clock = FakeClock()
    client = FakeClient(
        [{"status": "READY", "app_conversation_id": "c1"}],
        [{"sandbox_status": "RUNNING", "execution_status": "waiting_for_confirmation"}],
    )
    monitor, _ = build_monitor(client, clock)
    result = monitor.monitor("task-1")
    assert result.success is False
    assert result.waiting_for_user is True
    assert "/conversations/c1" in result.message


def test_execution_timeout() -> None:
    clock = FakeClock()
    client = FakeClient(
        [{"status": "READY", "app_conversation_id": "c1"}],
        [{"sandbox_status": "RUNNING", "execution_status": "running"}],
    )
    monitor, _ = build_monitor(client, clock, execution_timeout=2.0)
    result = monitor.monitor("task-1")
    assert result.success is False
    assert result.timed_out is True


def test_conversation_not_visible_is_retried() -> None:
    clock = FakeClock()
    client = FakeClient(
        [{"status": "READY", "app_conversation_id": "c1"}],
        [None, {"sandbox_status": "RUNNING", "execution_status": "finished"}],
    )
    monitor, _ = build_monitor(client, clock)
    result = monitor.monitor("task-1")
    assert result.success is True


def test_cancellation() -> None:
    clock = FakeClock()
    cancel = threading.Event()
    cancel.set()
    client = FakeClient([{"status": "WORKING"}], [])
    monitor, _ = build_monitor(client, clock, cancel_event=cancel)
    with pytest.raises(JobCancelled):
        monitor.monitor("task-1")


def test_requires_start_task_id() -> None:
    clock = FakeClock()
    monitor, _ = build_monitor(FakeClient([], []), clock)
    with pytest.raises(ValueError):
        monitor.monitor("")
