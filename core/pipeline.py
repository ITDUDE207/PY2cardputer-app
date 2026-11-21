"""End-to-end conversion pipeline.

The GUI and the CLI both drive this class. Every step persists the job before
and after it runs, so a crash leaves an inspectable record in ``builds/``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ai.conversion_prompt import build_conversion_prompt
from ai.openhands_client import OpenHandsClient
from ai.task_monitor import TaskMonitor
from compiler.arduino_cli import ArduinoCLI
from compiler.validator import validate_sketch_tree
from core.config import Config
from core.errors import ConfigError, JobCancelled, PipelineError, Py2CardputerError
from core.jobs import JobStore
from core.logger import add_job_log_file, redact
from core.models import (
    Job,
    JobStatus,
    ProgressEvent,
    StepRecord,
    StepStatus,
)
from core.validation import SourceFile, validate_python_source_file
from github.branches import build_branch_name, unique_branch_name
from github.downloader import FirmwareDownloader
from github.repository import GitHubRepository

ProgressSink = Callable[[ProgressEvent], None]

STEP_ORDER = [
    ("validate_source", "Validate Python source"),
    ("github_auth", "Authenticate GitHub"),
    ("prepare_workspace", "Prepare workspace clone"),
    ("create_branch", "Create conversion branch"),
    ("upload_source", "Upload source to branch"),
    ("start_conversation", "Start OpenHands conversation"),
    ("monitor_conversation", "Monitor OpenHands conversion"),
    ("download_firmware", "Download generated firmware"),
    ("validate_sketch", "Validate Arduino sketch"),
    ("compile_firmware", "Compile with Arduino CLI"),
    ("finalize", "Finalize build"),
]
STEP_LABELS = dict(STEP_ORDER)


@dataclass
class Components:
    openhands: OpenHandsClient
    repository: GitHubRepository
    arduino: ArduinoCLI
    downloader: FirmwareDownloader


def build_components(config: Config, logger: logging.Logger) -> Components:
    config.ensure_directories()
    client = OpenHandsClient(
        config.openhands_api_url,
        config.openhands_api_key,
        timeout=config.request_timeout_seconds,
        logger=logger.getChild("openhands"),
    )
    repository = GitHubRepository(
        config.github_repository,
        config.workspace_path,
        branch_prefix=config.github_branch_prefix,
        logger=logger.getChild("github"),
    )
    arduino = ArduinoCLI(
        config.arduino_cli_path,
        timeout=config.compile_timeout_seconds,
        logger=logger.getChild("arduino"),
    )
    downloader = FirmwareDownloader(repository, logger=logger.getChild("downloader"))
    return Components(openhands=client, repository=repository, arduino=arduino, downloader=downloader)


class ConversionPipeline:
    def __init__(
        self,
        config: Config,
        job_store: JobStore,
        logger: logging.Logger,
        *,
        components: Components | None = None,
        monitor: TaskMonitor | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.config = config
        self.job_store = job_store
        self.logger = logger
        self.components = components or build_components(config, logger)
        self._monitor = monitor
        self.cancel_event = cancel_event or threading.Event()
        self._progress: ProgressSink | None = None
        self._job: Job | None = None
        self._log_handler: logging.Handler | None = None

    # ---------------------------------------------------------------- helpers
    def cancel(self) -> None:
        self.cancel_event.set()

    def _emit(self, step: str, message: str, level: str = "info", **data: object) -> None:
        job = self._job
        safe_message = redact(message)
        self.logger.log(
            logging.ERROR if level == "error" else logging.WARNING if level == "warning" else logging.INFO,
            "[%s] %s",
            step,
            safe_message,
        )
        if self._progress is None or job is None:
            return
        try:
            self._progress(
                ProgressEvent(
                    job_id=job.job_id,
                    step=step,
                    message=safe_message,
                    level=level,
                    data=dict(data),
                )
            )
        except Exception:  # pragma: no cover - a UI bug must not abort a build
            self.logger.debug("Progress sink failed", exc_info=True)

    def _save(self) -> None:
        if self._job is not None:
            self.job_store.save(self._job)

    def _run_step(self, name: str, action: Callable[[], str]) -> None:
        job = self._job
        assert job is not None
        label = STEP_LABELS.get(name, name)
        if self.cancel_event.is_set():
            raise JobCancelled("Conversion was cancelled by the user.")
        job.mark_step(name, label, StepStatus.RUNNING)
        job.status = JobStatus.RUNNING
        job.message = label
        self._save()
        self._emit(name, f"{label}…")
        try:
            message = action() or label
        except JobCancelled:
            job.mark_step(name, label, StepStatus.FAILED, "Cancelled")
            self._save()
            raise
        except PipelineError as exc:
            job.mark_step(name, label, StepStatus.FAILED, str(exc))
            self._save()
            raise
        except Py2CardputerError as exc:
            message_text = redact(str(exc))
            job.mark_step(name, label, StepStatus.FAILED, message_text)
            self._save()
            raise PipelineError(name, message_text, cause=exc) from exc
        except Exception as exc:  # unexpected
            self.logger.exception("Unexpected error in step %s", name)
            message_text = redact(f"Unexpected error: {exc}")
            job.mark_step(name, label, StepStatus.FAILED, message_text)
            self._save()
            raise PipelineError(name, message_text, cause=exc) from exc

        job.mark_step(name, label, StepStatus.DONE, message)
        job.message = message
        self._save()
        self._emit(name, message, "success")

    # ------------------------------------------------------------------- job
    def create_job(self, source_path: Path | str) -> Job:
        """Validate a source file and allocate a job with a provisional branch."""
        source = validate_python_source_file(source_path)
        self.config.require_repository()
        branch = build_branch_name(
            source.filename,
            prefix=self.config.github_branch_prefix,
        )
        job = self.job_store.create_job(
            source,
            repository=self.config.github_repository,
            branch=branch,
            app_name=source.app_name,
        )
        job.mark_step("validate_source", STEP_LABELS["validate_source"], StepStatus.PENDING)
        self.job_store.save(job)
        return job

    # ------------------------------------------------------------------- run
    def run(self, job: Job, on_progress: ProgressSink | None = None) -> Job:
        """Execute every pipeline step. Returns the updated job; never raises."""
        self._job = job
        self._progress = on_progress
        started = time.monotonic()
        self._attach_log(job)

        job.status = JobStatus.RUNNING
        job.error = None
        job.message = "Starting conversion"
        self._save()
        self._emit("start", f"Starting conversion for {job.source_filename}")

        early = False
        try:
            problems = self.config.validate()
            if problems:
                raise ConfigError("Configuration problems: " + "; ".join(problems))
            self.config.require_repository()
            self.config.require_openhands_credentials()

            self._run_step("validate_source", lambda: self._step_validate_source(job))
            self._run_step("github_auth", self._step_github_auth)
            self._run_step("prepare_workspace", self._step_prepare_workspace)
            self._run_step("create_branch", lambda: self._step_create_branch(job))
            self._run_step("upload_source", lambda: self._step_upload_source(job))
            self._run_step("start_conversation", lambda: self._step_start_conversation(job))
            self._run_step("monitor_conversation", lambda: self._step_monitor(job))

            if job.status is JobStatus.WAITING_FOR_USER:
                early = True
            else:
                self._run_step("download_firmware", lambda: self._step_download(job))
                self._run_step("validate_sketch", lambda: self._step_validate_sketch(job))
                self._run_step("compile_firmware", lambda: self._step_compile(job))
                self._run_step("finalize", lambda: self._step_finalize(job))
        except JobCancelled as exc:
            job.status = JobStatus.CANCELLED
            job.message = redact(str(exc))
            job.error = None
            self._emit("cancelled", job.message, "warning")
        except PipelineError as exc:
            job.status = JobStatus.FAILED
            job.error = redact(str(exc))
            job.message = f"Failed during {STEP_LABELS.get(exc.step, exc.step)}"
            self._emit(exc.step, f"{job.message}: {job.error}", "error")
        except Py2CardputerError as exc:
            job.status = JobStatus.FAILED
            job.error = redact(str(exc))
            job.message = job.error
            self._emit("error", job.error, "error")
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.exception("Conversion pipeline crashed")
            job.status = JobStatus.FAILED
            job.error = redact(f"Unexpected error: {exc}")
            job.message = job.error
            self._emit("error", job.error, "error")

        finished = self._finish(job, started, early=early)
        self._detach_log()
        return finished

    # ----------------------------------------------------------------- steps
    def _step_validate_source(self, job: Job) -> str:
        path = job.source_snapshot_path or job.source_path
        source: SourceFile = validate_python_source_file(path)
        job.source_sha256 = source.sha256
        job.app_name = source.app_name
        warnings = list(source.inspection.warnings)
        job.warnings.extend(warning for warning in warnings if warning not in job.warnings)
        for warning in warnings:
            self._emit("validate_source", warning, "warning")
        return f"{source.filename}: {source.size_bytes} bytes, {source.inspection.line_count} lines"

    def _step_github_auth(self) -> str:
        auth = self.components.repository.check_auth()
        if not auth.ok:
            detail = f" {auth.detail}" if auth.detail else ""
            raise PipelineError("github_auth", f"{auth.message}{detail}")
        return auth.message

    def _step_prepare_workspace(self) -> str:
        path = self.components.repository.ensure_clone()
        return f"Workspace ready at {path}"

    def _step_create_branch(self, job: Job) -> str:
        repository = self.components.repository
        job.branch = unique_branch_name(job.branch, repository.remote_branch_exists)
        repository.create_branch(job.branch, base=repository.default_branch())
        return f"Branch {job.branch} created"

    def _step_upload_source(self, job: Job) -> str:
        source_path = Path(job.source_snapshot_path or job.source_path)
        relative = f"input/{job.source_filename}"
        sha = self.components.repository.commit_and_push(
            job.branch,
            {relative: source_path},
            message=(
                f"Add {job.source_filename} for conversion\n\n"
                f"Job: {job.job_id}\nApp: {job.app_name}"
            ),
        )
        job.commit_sha = sha
        return f"Pushed {relative} to {job.branch} ({sha[:8]})"

    def _step_start_conversation(self, job: Job) -> str:
        source = validate_python_source_file(job.source_snapshot_path or job.source_path)
        prompt = build_conversion_prompt(
            app_name=job.app_name,
            source_filename=job.source_filename,
            repository=job.repository,
            branch=job.branch,
            job_id=job.job_id,
            inspection=source.inspection,
        )
        result = self.components.openhands.start_conversation(
            repository=job.repository,
            branch=job.branch,
            prompt=prompt,
            title=f"Py2Cardputer: {job.app_name}",
            llm_model=self.config.openhands_llm_model or None,
        )
        job.openhands_start_task_id = result.start_task_id
        job.openhands_conversation_id = result.app_conversation_id
        job.openhands_conversation_url = result.conversation_url
        self._save()
        self._emit(
            "start_conversation",
            f"OpenHands start task {result.start_task_id} ({result.status})",
            "info",
            conversation_url=result.conversation_url or "",
        )
        return f"OpenHands task {result.start_task_id} started"

    def _build_monitor(self) -> TaskMonitor:
        if self._monitor is not None:
            return self._monitor

        def on_progress(message: str, level: str, data: dict) -> None:
            self._emit("monitor_conversation", message, level, **data)

        return TaskMonitor(
            self.components.openhands,
            poll_interval=self.config.poll_interval_seconds,
            startup_timeout=self.config.startup_timeout_seconds,
            execution_timeout=self.config.execution_timeout_seconds,
            on_progress=on_progress,
            cancel_event=self.cancel_event,
            logger=self.logger.getChild("monitor"),
        )

    def _step_monitor(self, job: Job) -> str:
        if not job.openhands_start_task_id:
            raise PipelineError("monitor_conversation", "No OpenHands start task id was recorded.")
        monitor = self._build_monitor()
        result = monitor.monitor(job.openhands_start_task_id, job.openhands_conversation_id)
        job.openhands_conversation_id = result.conversation_id or job.openhands_conversation_id
        job.openhands_conversation_url = result.conversation_url or job.openhands_conversation_url
        job.openhands_execution_status = result.execution_status
        job.openhands_sandbox_status = result.sandbox_status
        self._save()
        if result.waiting_for_user:
            job.status = JobStatus.WAITING_FOR_USER
            job.message = result.message
            return result.message
        if not result.success:
            raise PipelineError("monitor_conversation", result.message or "OpenHands did not finish.")
        return result.message or "OpenHands finished"

    def _step_download(self, job: Job) -> str:
        result = self.components.downloader.download(job.branch, Path(job.job_dir))
        job.firmware_dir = str(result.firmware_dir)
        job.firmware_commit_sha = result.commit_sha
        return f"Downloaded {len(result.files)} file(s) at {result.commit_sha[:8]}"

    def _step_validate_sketch(self, job: Job) -> str:
        if not job.firmware_dir:
            raise PipelineError("validate_sketch", "No firmware directory was downloaded.")
        validation = validate_sketch_tree(Path(job.firmware_dir))
        job.sketch_dir = str(validation.sketch_dir) if validation.sketch_dir else None
        job.sketch_name = validation.sketch_name
        for warning in validation.warnings:
            if warning not in job.warnings:
                job.warnings.append(warning)
            self._emit("validate_sketch", warning, "warning")
        if not validation.valid:
            raise PipelineError("validate_sketch", validation.summary())
        return f"Sketch {validation.sketch_name} validated ({len(validation.additional_files)} extra file(s))"

    def _step_compile(self, job: Job) -> str:
        if not job.sketch_dir:
            raise PipelineError("compile_firmware", "No sketch directory is available.")
        output_dir = Path(job.job_dir) / "bin"
        result = self.components.arduino.compile(
            job.sketch_dir,
            fqbn=self.config.arduino_fqbn,
            output_dir=output_dir,
            extra_args=self.config.extra_compile_args,
        )
        job.compile_result = result
        job.compile_succeeded = result.success
        job.binary_path = result.binary_path
        log_path = Path(job.job_dir) / "compile.log"
        log_path.write_text(self._format_compile_log(result), encoding="utf-8")
        job.compile_log_path = str(log_path)
        self._save()

        for chunk in self._terminal_chunks(result):
            self._emit("compile_firmware", chunk, "terminal")

        if not result.success:
            raise PipelineError(
                "compile_firmware",
                result.error or "Arduino CLI reported a compilation failure.",
            )
        return f"Compiled in {result.duration_seconds:.1f}s"

    def _step_finalize(self, job: Job) -> str:
        job.status = JobStatus.SUCCEEDED
        job.message = f"Firmware compiled: {job.binary_path}"
        return job.message

    # ---------------------------------------------------------------- finish
    def _finish(self, job: Job, started: float, *, early: bool = False) -> Job:
        job.duration_seconds = round(time.monotonic() - started, 2)
        if job.status is JobStatus.WAITING_FOR_USER:
            job.message = job.message or "Waiting for user confirmation in OpenHands."
        if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
            for name, label in STEP_ORDER:
                record = job.step(name)
                if record is None:
                    job.steps.append(StepRecord(name=name, label=label, status=StepStatus.SKIPPED, message="Not reached"))
                elif record.status is StepStatus.PENDING:
                    record.status = StepStatus.SKIPPED
                    record.message = record.message or "Not reached"
        elif early:
            for name, label in STEP_ORDER:
                record = job.step(name)
                if record is None:
                    job.steps.append(
                        StepRecord(
                            name=name,
                            label=label,
                            status=StepStatus.SKIPPED,
                            message="Waiting for OpenHands confirmation",
                        )
                    )
        job.touch()
        self.job_store.save(job)
        level = {
            JobStatus.SUCCEEDED: "success",
            JobStatus.WAITING_FOR_USER: "warning",
            JobStatus.CANCELLED: "warning",
        }.get(job.status, "error")
        self._emit("done", f"{job.status.value.upper()}: {job.message}", level, binary=job.binary_path or "")
        return job

    def _attach_log(self, job: Job) -> None:
        if job.log_path:
            try:
                self._log_handler = add_job_log_file(self.logger, job.log_path)
            except OSError:
                self.logger.warning("Could not open job log file %s", job.log_path)

    def _detach_log(self) -> None:
        if self._log_handler is not None:
            self.logger.removeHandler(self._log_handler)
            self._log_handler.close()
            self._log_handler = None

    @staticmethod
    def _format_compile_log(result) -> str:
        parts = [
            "$ " + " ".join(result.command),
            "",
            f"exit code: {result.returncode}",
            f"duration: {result.duration_seconds:.2f}s",
            "",
            "----- stdout -----",
            result.stdout,
            "",
            "----- stderr -----",
            result.stderr,
            "",
        ]
        if result.binary_path:
            parts += [f"binary: {result.binary_path}", ""]
        return "\n".join(parts)

    @staticmethod
    def _terminal_chunks(result, size: int = 3000) -> list[str]:
        chunks: list[str] = []
        for label, text in (("stdout", result.stdout), ("stderr", result.stderr)):
            text = (text or "").strip()
            if not text:
                continue
            chunks.append(f"--- {label} ---")
            for index in range(0, len(text), size):
                chunks.append(text[index : index + size])
        if not chunks:
            chunks.append("Arduino CLI produced no output.")
        return chunks
