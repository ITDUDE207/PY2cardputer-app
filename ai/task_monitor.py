"""Polling monitor for an OpenHands conversion conversation.

Two phases, matching the Cloud V1 API:

1. Poll the start task until ``READY`` (conversation and sandbox created).
2. Poll the app conversation until the agent reaches a terminal execution state.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from ai.openhands_client import OpenHandsClient
from core.errors import JobCancelled
from core.models import MonitorResult

FAILED_EXECUTION_STATUSES = {"error", "stuck", "deleting"}
FAILED_SANDBOX_STATUSES = {"ERROR", "MISSING"}

ProgressCallback = Callable[[str, str, dict[str, Any]], None]


class TaskMonitor:
    def __init__(
        self,
        client: OpenHandsClient,
        *,
        poll_interval: float = 5.0,
        startup_timeout: float = 900.0,
        execution_timeout: float = 5400.0,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
        logger: logging.Logger | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.poll_interval = max(0.05, float(poll_interval))
        self.startup_timeout = float(startup_timeout)
        self.execution_timeout = float(execution_timeout)
        self.on_progress = on_progress
        self.cancel_event = cancel_event
        self.logger = logger or logging.getLogger("py2cardputer.monitor")
        self._sleep = sleep
        self._clock = clock

    def _emit(self, message: str, level: str = "info", **data: Any) -> None:
        self.logger.info("%s", message)
        if self.on_progress:
            try:
                self.on_progress(message, level, data)
            except Exception:  # a UI callback must never break monitoring
                self.logger.debug("Progress callback failed", exc_info=True)

    def _check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise JobCancelled("Monitoring was cancelled by the user.")

    def _pause(self, deadline: float) -> None:
        remaining = deadline - self._clock()
        if remaining <= 0:
            return
        self._sleep(min(self.poll_interval, remaining))

    def monitor(self, start_task_id: str, conversation_id: str | None = None) -> MonitorResult:
        if not start_task_id:
            raise ValueError("start_task_id is required")

        self._start_failure = "OpenHands did not provide a conversation id."
        self._start_timed_out = False
        conversation_id = self._wait_for_start(start_task_id, conversation_id)
        if conversation_id is None:
            return MonitorResult(
                success=False,
                start_task_id=start_task_id,
                message=self._start_failure,
                timed_out=self._start_timed_out,
            )
        return self._wait_for_execution(start_task_id, conversation_id)

    # ------------------------------------------------------------ start phase
    def _wait_for_start(self, start_task_id: str, conversation_id: str | None) -> str | None:
        deadline = self._clock() + self.startup_timeout
        while True:
            self._check_cancel()
            task = self.client.get_start_task(start_task_id)
            if task is None:
                self._emit("Waiting for OpenHands to register the start task…", "warning")
            else:
                status = str(task.get("status") or "")
                if status == "READY":
                    resolved = task.get("app_conversation_id") or conversation_id
                    if not resolved:
                        self._start_failure = "Start task is READY but has no conversation id."
                        self._emit(self._start_failure, "error")
                        return None
                    self._emit("OpenHands conversation is ready.", "success", conversation_id=resolved)
                    return str(resolved)
                if status == "ERROR":
                    detail = task.get("detail") or "OpenHands could not start the conversation."
                    self._start_failure = f"OpenHands startup failed: {detail}"
                    self._emit(self._start_failure, "error")
                    return None
                self._emit(
                    f"OpenHands startup: {status.replace('_', ' ').title()}…",
                    "info",
                    start_status=status,
                )
            if self._clock() >= deadline:
                self._start_failure = (
                    f"Timed out after {self.startup_timeout:.0f}s waiting for OpenHands to start."
                )
                self._start_timed_out = True
                self._emit(self._start_failure, "error")
                return None
            self._pause(deadline)

    # -------------------------------------------------------- execution phase
    def _wait_for_execution(self, start_task_id: str, conversation_id: str) -> MonitorResult:
        deadline = self._clock() + self.execution_timeout
        url = self.client.conversation_url(conversation_id)
        last_exec: str | None = None
        while True:
            self._check_cancel()
            conversation = self.client.get_conversation(conversation_id)
            if conversation is None:
                self._emit("Conversation is not visible yet; continuing to poll.", "warning")
            else:
                url = self.client.conversation_url(
                    conversation_id, conversation.get("conversation_url")
                )
                sandbox_status = conversation.get("sandbox_status")
                execution_status = conversation.get("execution_status")

                if sandbox_status in FAILED_SANDBOX_STATUSES:
                    message = f"OpenHands sandbox entered state {sandbox_status}."
                    self._emit(message, "error", sandbox_status=sandbox_status)
                    return MonitorResult(
                        success=False,
                        start_task_id=start_task_id,
                        conversation_id=conversation_id,
                        conversation_url=url,
                        execution_status=execution_status,
                        sandbox_status=sandbox_status,
                        message=message,
                    )

                if execution_status != last_exec:
                    last_exec = execution_status
                    if execution_status:
                        self._emit(
                            f"Agent status: {str(execution_status).replace('_', ' ')}",
                            "info",
                            execution_status=execution_status,
                            sandbox_status=sandbox_status,
                        )

                if execution_status == "finished":
                    message = "OpenHands finished the conversion task."
                    self._emit(message, "success", execution_status=execution_status)
                    return MonitorResult(
                        success=True,
                        start_task_id=start_task_id,
                        conversation_id=conversation_id,
                        conversation_url=url,
                        execution_status=execution_status,
                        sandbox_status=sandbox_status,
                        message=message,
                    )

                if execution_status in FAILED_EXECUTION_STATUSES:
                    message = (
                        f"OpenHands reported execution status '{execution_status}'. "
                        f"Inspect the conversation: {url}"
                    )
                    self._emit(message, "error", execution_status=execution_status)
                    return MonitorResult(
                        success=False,
                        start_task_id=start_task_id,
                        conversation_id=conversation_id,
                        conversation_url=url,
                        execution_status=execution_status,
                        sandbox_status=sandbox_status,
                        message=message,
                    )

                if execution_status == "waiting_for_confirmation":
                    message = (
                        "OpenHands is waiting for confirmation. Open the conversation, "
                        f"approve the next step, then retry or continue manually: {url}"
                    )
                    self._emit(message, "warning", execution_status=execution_status)
                    return MonitorResult(
                        success=False,
                        start_task_id=start_task_id,
                        conversation_id=conversation_id,
                        conversation_url=url,
                        execution_status=execution_status,
                        sandbox_status=sandbox_status,
                        message=message,
                        waiting_for_user=True,
                    )

            if self._clock() >= deadline:
                message = (
                    f"Timed out after {self.execution_timeout:.0f}s waiting for OpenHands. "
                    f"Check the conversation: {url}"
                )
                self._emit(message, "error")
                return MonitorResult(
                    success=False,
                    start_task_id=start_task_id,
                    conversation_id=conversation_id,
                    conversation_url=url,
                    execution_status=last_exec,
                    message=message,
                    timed_out=True,
                )
            self._pause(deadline)
