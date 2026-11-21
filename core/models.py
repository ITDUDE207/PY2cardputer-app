"""Data models shared by the pipeline, the job store and the GUI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobStatus.WAITING_FOR_USER,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepRecord:
    name: str
    label: str
    status: StepStatus = StepStatus.PENDING
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepRecord":
        return cls(
            name=data.get("name", ""),
            label=data.get("label", data.get("name", "")),
            status=StepStatus(data.get("status", StepStatus.PENDING.value)),
            message=data.get("message", ""),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )


@dataclass
class CompileResult:
    success: bool
    command: list[str] = field(default_factory=list)
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    output_dir: str = ""
    binary_path: str | None = None
    duration_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompileResult":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Job:
    """One conversion run. Persisted as ``builds/<job_id>/job.json``."""

    job_id: str
    created_at: str
    updated_at: str
    source_filename: str
    source_path: str
    app_name: str
    repository: str
    branch: str
    status: JobStatus = JobStatus.PENDING
    current_step: str = ""
    message: str = ""
    source_sha256: str = ""
    source_snapshot_path: str | None = None
    openhands_start_task_id: str | None = None
    openhands_conversation_id: str | None = None
    openhands_conversation_url: str | None = None
    openhands_execution_status: str | None = None
    openhands_sandbox_status: str | None = None
    job_dir: str = ""
    firmware_dir: str | None = None
    sketch_dir: str | None = None
    sketch_name: str | None = None
    binary_path: str | None = None
    compile_log_path: str | None = None
    compile_succeeded: bool = False
    compile_result: CompileResult | None = None
    error: str | None = None
    log_path: str | None = None
    commit_sha: str | None = None
    firmware_commit_sha: str | None = None
    duration_seconds: float = 0.0
    steps: list[StepRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # -------------------------------------------------------------- helpers
    def touch(self) -> None:
        self.updated_at = iso_now()

    def step(self, name: str) -> StepRecord | None:
        for record in self.steps:
            if record.name == name:
                return record
        return None

    def mark_step(
        self,
        name: str,
        label: str,
        status: StepStatus,
        message: str = "",
    ) -> StepRecord:
        record = self.step(name)
        if record is None:
            record = StepRecord(name=name, label=label)
            self.steps.append(record)
        record.label = label or record.label
        record.status = status
        if message:
            record.message = message
        if status is StepStatus.RUNNING and not record.started_at:
            record.started_at = iso_now()
        if status in {StepStatus.DONE, StepStatus.FAILED, StepStatus.SKIPPED}:
            record.finished_at = iso_now()
        self.current_step = name
        self.touch()
        return record

    def summary(self) -> str:
        return f"{self.app_name} ({self.status.value})"

    # ---------------------------------------------------------- persistence
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["steps"] = [step.to_dict() for step in self.steps]
        data["compile_result"] = self.compile_result.to_dict() if self.compile_result else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in data.items() if k in known}
        payload["status"] = JobStatus(data.get("status", JobStatus.PENDING.value))
        payload["steps"] = [StepRecord.from_dict(item) for item in data.get("steps", [])]
        compile_data = data.get("compile_result")
        payload["compile_result"] = CompileResult.from_dict(compile_data) if compile_data else None
        return cls(**payload)

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        tmp.replace(target)
        return target

    @classmethod
    def load(cls, path: Path | str) -> "Job":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class ProgressEvent:
    """A single progress notification emitted by the pipeline."""

    job_id: str
    step: str
    message: str
    level: str = "info"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenHandsStartResult:
    start_task_id: str
    status: str
    app_conversation_id: str | None = None
    sandbox_id: str | None = None
    conversation_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitorResult:
    success: bool
    start_task_id: str
    conversation_id: str | None = None
    conversation_url: str | None = None
    start_status: str = ""
    execution_status: str | None = None
    sandbox_status: str | None = None
    message: str = ""
    timed_out: bool = False
    waiting_for_user: bool = False


@dataclass
class DownloadResult:
    commit_sha: str
    firmware_dir: Path
    files: list[str] = field(default_factory=list)


@dataclass
class SketchValidation:
    valid: bool
    firmware_dir: Path
    sketch_dir: Path | None = None
    sketch_name: str | None = None
    ino_path: Path | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    additional_files: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.valid and self.sketch_dir:
            return f"Sketch {self.sketch_name} is structurally valid"
        return "; ".join(self.errors) or "Sketch validation failed"
