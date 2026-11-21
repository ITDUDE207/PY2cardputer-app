"""Job creation and persistence.

Each conversion gets an immutable, unique directory under ``builds/``. Existing
directories are never reused, so a previous successful build cannot be
overwritten.
"""

from __future__ import annotations

import logging
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.errors import Py2CardputerError
from core.models import Job, JobStatus, iso_now
from core.validation import SourceFile, sanitize_slug

JOB_FILE = "job.json"


def new_job_id(app_name: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{sanitize_slug(app_name, max_length=32)}-{secrets.token_hex(3)}"


class JobStore:
    def __init__(
        self,
        builds_dir: Path | str,
        logger: logging.Logger | None = None,
        *,
        log_dir: Path | str | None = None,
    ) -> None:
        self.builds_dir = Path(builds_dir)
        self.builds_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = Path(log_dir) if log_dir else None
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger or logging.getLogger("py2cardputer.jobs")

    def job_dir(self, job_id: str) -> Path:
        return self.builds_dir / job_id

    def create_job(
        self,
        source: SourceFile,
        *,
        repository: str,
        branch: str,
        app_name: str | None = None,
        log_path: Path | str | None = None,
    ) -> Job:
        """Create a unique job directory and snapshot the original source."""
        name = app_name or source.app_name
        for _ in range(5):
            job_id = new_job_id(name)
            directory = self.job_dir(job_id)
            try:
                directory.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                continue
        else:  # pragma: no cover - astronomically unlikely
            raise Py2CardputerError("Could not allocate a unique job directory.")

        snapshot_dir = directory / "source"
        snapshot_dir.mkdir()
        snapshot = snapshot_dir / source.filename
        shutil.copyfile(source.path, snapshot)

        resolved_log_path = log_path
        if resolved_log_path is None and self.log_dir is not None:
            resolved_log_path = self.log_dir / f"{job_id}.log"

        job = Job(
            job_id=job_id,
            created_at=iso_now(),
            updated_at=iso_now(),
            source_filename=source.filename,
            source_path=str(source.path),
            source_snapshot_path=str(snapshot),
            source_sha256=source.sha256,
            app_name=name,
            repository=repository,
            branch=branch,
            job_dir=str(directory),
            log_path=str(resolved_log_path) if resolved_log_path else None,
            status=JobStatus.PENDING,
        )
        self.save(job)
        self.logger.info("Created job %s for %s", job.job_id, source.filename)
        return job

    def save(self, job: Job) -> Path:
        directory = Path(job.job_dir) if job.job_dir else self.job_dir(job.job_id)
        directory.mkdir(parents=True, exist_ok=True)
        job.job_dir = str(directory)
        job.touch()
        return job.save(directory / JOB_FILE)

    def load(self, job_id: str) -> Job:
        path = self.job_dir(job_id) / JOB_FILE
        if not path.is_file():
            raise Py2CardputerError(f"Job {job_id!r} was not found.")
        return Job.load(path)

    def list_jobs(self) -> list[Job]:
        jobs: list[Job] = []
        for path in self.builds_dir.glob(f"*/{JOB_FILE}"):
            try:
                jobs.append(Job.load(path))
            except Exception as exc:  # corrupt job files must not break history
                self.logger.warning("Skipping unreadable job file %s: %s", path, exc)
        jobs.sort(key=lambda job: job.created_at, reverse=True)
        return jobs
