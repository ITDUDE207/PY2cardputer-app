from __future__ import annotations

import logging
import threading
from pathlib import Path

from core.config import Config
from core.jobs import JobStore
from core.models import (
    CompileResult,
    DownloadResult,
    JobStatus,
    MonitorResult,
    OpenHandsStartResult,
    StepStatus,
)
from core.pipeline import Components, ConversionPipeline
from core.validation import validate_python_source_file
from github.repository import GitAuthResult

SOURCE = """\
from m5stack import *
import time

def setup():
    pass

def loop():
    time.sleep(1)
"""

VALID_INO = """\
#include <M5Cardputer.h>
#include <M5Unified.h>

void setup() {
    M5Cardputer.begin();
}

void loop() {
    M5Cardputer.update();
}
"""


class FakeRepository:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = set(existing or set())
        self.created: str | None = None
        self.uploaded: dict[str, Path] | None = None
        self.branch: str | None = None
        self.checks: list[str] = []

    def check_auth(self):
        return GitAuthResult(ok=True, message="Git authentication OK")

    def ensure_clone(self):
        return Path("/tmp/workspace")

    def remote_branch_exists(self, branch: str) -> bool:
        self.checks.append(branch)
        return branch in self.existing

    def default_branch(self) -> str:
        return "main"

    def create_branch(self, branch: str, base: str | None = None) -> str:
        self.created = branch
        self.base = base
        return branch

    def commit_and_push(self, branch, files, message):
        self.branch = branch
        self.uploaded = dict(files)
        return "a" * 40


class FakeDownloader:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.calls: list[tuple[str, Path]] = []

    def download(self, branch: str, destination) -> DownloadResult:
        self.calls.append((branch, Path(destination)))
        root = Path(destination) / "firmware" / "MyApp"
        root.mkdir(parents=True)
        ino = VALID_INO if self.valid else "#include <M5Cardputer.h>\nvoid setup() {}\n"
        (root / "MyApp.ino").write_text(ino, encoding="utf-8")
        (root / "README.md").write_text("# App\n", encoding="utf-8")
        (root / "CONVERSION_REPORT.md").write_text("# Report\n", encoding="utf-8")
        return DownloadResult(
            commit_sha="b" * 40,
            firmware_dir=Path(destination) / "firmware",
            files=["firmware/MyApp/MyApp.ino"],
        )


class FakeArduino:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.calls: list[dict] = []

    def compile(self, sketch_dir, *, fqbn, output_dir, extra_args=None) -> CompileResult:
        self.calls.append(
            {"sketch_dir": sketch_dir, "fqbn": fqbn, "output_dir": output_dir}
        )
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        binary = None
        if self.success:
            binary = out / "MyApp.ino.bin"
            binary.write_bytes(b"firmware")
        return CompileResult(
            success=self.success,
            command=["arduino-cli", "compile"],
            returncode=0 if self.success else 1,
            stdout="compiled output",
            stderr="" if self.success else "fatal error: missing symbol",
            output_dir=str(out),
            binary_path=str(binary) if binary else None,
            duration_seconds=0.25,
            error=None if self.success else "Compilation failed.",
        )


class FakeOpenHands:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def start_conversation(self, **kwargs) -> OpenHandsStartResult:
        self.kwargs = kwargs
        return OpenHandsStartResult(
            start_task_id="task-1",
            status="WORKING",
            app_conversation_id="conv-1",
            conversation_url="https://app.all-hands.dev/conversations/conv-1",
        )


class FakeMonitor:
    def __init__(self, result: MonitorResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str | None]] = []

    def monitor(self, start_task_id: str, conversation_id: str | None = None) -> MonitorResult:
        self.calls.append((start_task_id, conversation_id))
        return self.result


def success_monitor() -> FakeMonitor:
    return FakeMonitor(
        MonitorResult(
            success=True,
            start_task_id="task-1",
            conversation_id="conv-1",
            conversation_url="https://app.all-hands.dev/conversations/conv-1",
            execution_status="finished",
            sandbox_status="RUNNING",
            message="OpenHands finished the conversion task.",
        )
    )


def build_environment(tmp_path: Path, *, api_key: str = "test-key", existing: set[str] | None = None):
    source_path = tmp_path / "my_app.py"
    source_path.write_text(SOURCE, encoding="utf-8")
    config = Config(
        root=tmp_path,
        openhands_api_key=api_key,
        github_repository="owner/repo",
        build_dir="builds",
        log_dir="logs",
        workspace_dir="workspace",
    )
    config.ensure_directories()
    logger = logging.getLogger(f"test.pipeline.{tmp_path.name}")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    store = JobStore(tmp_path / "builds", logger, log_dir=tmp_path / "logs")
    components = Components(
        openhands=FakeOpenHands(),
        repository=FakeRepository(existing),
        arduino=FakeArduino(),
        downloader=FakeDownloader(),
    )
    monitor = success_monitor()
    pipeline = ConversionPipeline(
        config,
        store,
        logger,
        components=components,
        monitor=monitor,
    )
    job = pipeline.create_job(source_path)
    return pipeline, job, store, components, monitor, source_path


def test_successful_end_to_end_pipeline(tmp_path: Path) -> None:
    pipeline, job, store, components, monitor, source_path = build_environment(tmp_path)
    original = source_path.read_bytes()
    events: list = []

    finished = pipeline.run(job, on_progress=events.append)

    assert finished.status is JobStatus.SUCCEEDED
    assert finished.error is None
    assert finished.binary_path and Path(finished.binary_path).is_file()
    assert finished.compile_succeeded is True
    assert finished.compile_log_path and Path(finished.compile_log_path).is_file()
    assert "compiled output" in Path(finished.compile_log_path).read_text(encoding="utf-8")
    assert finished.firmware_commit_sha == "b" * 40
    assert Path(finished.firmware_dir) == Path(finished.job_dir) / "firmware"
    assert finished.openhands_conversation_id == "conv-1"
    assert finished.openhands_conversation_url.endswith("/conversations/conv-1")
    assert finished.sketch_name == "MyApp"
    assert source_path.read_bytes() == original
    assert components.repository.uploaded is not None
    assert "input/my_app.py" in components.repository.uploaded
    assert components.repository.created == finished.branch
    assert monitor.calls == [("task-1", "conv-1")]
    assert all(step.status is StepStatus.DONE for step in finished.steps)
    assert any(event.level == "terminal" for event in events)
    assert any(event.level == "success" for event in events)

    reloaded = store.load(finished.job_id)
    assert reloaded.status is JobStatus.SUCCEEDED
    assert reloaded.binary_path == finished.binary_path


def test_prompt_sent_to_openhands_contains_branch_and_rules(tmp_path: Path) -> None:
    pipeline, job, _store, components, _monitor, _source = build_environment(tmp_path)
    finished = pipeline.run(job)
    prompt = components.openhands.kwargs["prompt"]
    assert components.openhands.kwargs["repository"] == "owner/repo"
    assert components.openhands.kwargs["branch"] == finished.branch
    assert finished.branch in prompt
    assert "Never merge into main." in prompt
    assert "firmware/MyApp/MyApp.ino" in prompt


def test_branch_collision_gets_numeric_suffix(tmp_path: Path) -> None:
    source_path = tmp_path / "my_app.py"
    source_path.write_text(SOURCE, encoding="utf-8")
    source = validate_python_source_file(source_path)
    from github.branches import build_branch_name

    provisional = build_branch_name(source.filename)
    pipeline, job, _store, _components, _monitor, _source = build_environment(
        tmp_path, existing={provisional}
    )
    finished = pipeline.run(job)
    assert finished.branch == f"{provisional}-2"
    assert finished.status is JobStatus.SUCCEEDED


def test_monitor_failure_aborts_before_download(tmp_path: Path) -> None:
    pipeline, job, _store, components, _monitor, _source = build_environment(tmp_path)
    pipeline._monitor = FakeMonitor(
        MonitorResult(
            success=False,
            start_task_id="task-1",
            conversation_id="conv-1",
            execution_status="error",
            message="agent failed",
        )
    )
    events: list = []
    finished = pipeline.run(job, on_progress=events.append)

    assert finished.status is JobStatus.FAILED
    assert "agent failed" in (finished.error or "")
    assert components.downloader.calls == []
    download_step = finished.step("download_firmware")
    assert download_step is not None and download_step.status is StepStatus.SKIPPED
    assert any(event.level == "error" for event in events)


def test_waiting_for_confirmation_stops_pipeline(tmp_path: Path) -> None:
    pipeline, job, _store, components, _monitor, _source = build_environment(tmp_path)
    pipeline._monitor = FakeMonitor(
        MonitorResult(
            success=False,
            start_task_id="task-1",
            conversation_id="conv-1",
            conversation_url="https://app.all-hands.dev/conversations/conv-1",
            execution_status="waiting_for_confirmation",
            message="Approve the next step",
            waiting_for_user=True,
        )
    )
    finished = pipeline.run(job)
    assert finished.status is JobStatus.WAITING_FOR_USER
    assert components.downloader.calls == []
    step = finished.step("download_firmware")
    assert step is not None and step.status is StepStatus.SKIPPED


def test_compile_failure_keeps_log_and_marks_failed(tmp_path: Path) -> None:
    pipeline, job, _store, components, _monitor, _source = build_environment(tmp_path)
    components.arduino.success = False
    finished = pipeline.run(job)

    assert finished.status is JobStatus.FAILED
    assert finished.compile_succeeded is False
    assert finished.binary_path is None
    assert finished.compile_result is not None
    assert finished.compile_result.stderr.startswith("fatal error")
    assert finished.compile_log_path and Path(finished.compile_log_path).is_file()
    step = finished.step("compile_firmware")
    assert step is not None and step.status is StepStatus.FAILED


def test_invalid_sketch_is_rejected_before_compiling(tmp_path: Path) -> None:
    pipeline, job, _store, components, _monitor, _source = build_environment(tmp_path)
    components.downloader.valid = False
    finished = pipeline.run(job)

    assert finished.status is JobStatus.FAILED
    assert "loop()" in (finished.error or "")
    assert components.arduino.calls == []
    step = finished.step("validate_sketch")
    assert step is not None and step.status is StepStatus.FAILED


def test_cancelled_before_start(tmp_path: Path) -> None:
    source_path = tmp_path / "my_app.py"
    source_path.write_text(SOURCE, encoding="utf-8")
    config = Config(
        root=tmp_path,
        openhands_api_key="test-key",
        github_repository="owner/repo",
        build_dir="builds",
        log_dir="logs",
        workspace_dir="workspace",
    )
    config.ensure_directories()
    logger = logging.getLogger(f"test.pipeline.cancel.{tmp_path.name}")
    logger.handlers.clear()
    logger.propagate = False
    store = JobStore(tmp_path / "builds", logger, log_dir=tmp_path / "logs")
    cancel = threading.Event()
    cancel.set()
    pipeline = ConversionPipeline(
        config,
        store,
        logger,
        components=Components(
            openhands=FakeOpenHands(),
            repository=FakeRepository(),
            arduino=FakeArduino(),
            downloader=FakeDownloader(),
        ),
        monitor=success_monitor(),
        cancel_event=cancel,
    )
    job = pipeline.create_job(source_path)
    finished = pipeline.run(job)
    assert finished.status is JobStatus.CANCELLED
    assert finished.error is None


def test_missing_api_key_fails_fast(tmp_path: Path) -> None:
    pipeline, job, _store, components, _monitor, _source = build_environment(
        tmp_path, api_key=""
    )
    finished = pipeline.run(job)
    assert finished.status is JobStatus.FAILED
    assert "OPENHANDS_API_KEY" in (finished.error or "")
    assert components.repository.created is None
