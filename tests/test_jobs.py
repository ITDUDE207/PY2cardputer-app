from __future__ import annotations

import json
from pathlib import Path

from core.jobs import JobStore, new_job_id
from core.models import JobStatus
from core.validation import validate_python_source_file

SOURCE = """\
import time

def setup():
    pass

def loop():
    time.sleep(1)
"""


def make_source(tmp_path: Path, name: str = "my_app.py") -> Path:
    path = tmp_path / name
    path.write_text(SOURCE, encoding="utf-8")
    return path


def make_store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "builds", log_dir=tmp_path / "logs")


def test_new_job_id_is_unique() -> None:
    ids = {new_job_id("app") for _ in range(50)}
    assert len(ids) == 50


def test_create_job_snapshots_source(tmp_path: Path) -> None:
    source_path = make_source(tmp_path)
    source = validate_python_source_file(source_path)
    store = make_store(tmp_path)
    job = store.create_job(source, repository="owner/repo", branch="py2cardputer/x-app")

    assert job.status is JobStatus.PENDING
    assert job.source_sha256 == source.sha256
    assert job.app_name == "MyApp"
    assert Path(job.job_dir).is_dir()
    snapshot = Path(job.source_snapshot_path)
    assert snapshot.read_text(encoding="utf-8") == SOURCE
    assert snapshot != source_path
    assert job.log_path and Path(job.log_path).parent == tmp_path / "logs"
    assert (Path(job.job_dir) / "job.json").is_file()


def test_two_jobs_never_share_a_directory(tmp_path: Path) -> None:
    source = validate_python_source_file(make_source(tmp_path))
    store = make_store(tmp_path)
    first = store.create_job(source, repository="o/r", branch="py2cardputer/a")
    second = store.create_job(source, repository="o/r", branch="py2cardputer/a")
    assert first.job_id != second.job_id
    assert first.job_dir != second.job_dir


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    source = validate_python_source_file(make_source(tmp_path))
    store = make_store(tmp_path)
    job = store.create_job(source, repository="o/r", branch="py2cardputer/a")
    job.status = JobStatus.SUCCEEDED
    job.binary_path = str(tmp_path / "bin" / "MyApp.ino.bin")
    store.save(job)

    loaded = store.load(job.job_id)
    assert loaded.status is JobStatus.SUCCEEDED
    assert loaded.binary_path == job.binary_path
    assert loaded.source_snapshot_path == job.source_snapshot_path


def test_list_jobs_sorted_newest_first(tmp_path: Path) -> None:
    source = validate_python_source_file(make_source(tmp_path))
    store = make_store(tmp_path)
    first = store.create_job(source, repository="o/r", branch="py2cardputer/a")
    second = store.create_job(source, repository="o/r", branch="py2cardputer/b")
    first.created_at = "2020-01-01T00:00:00+00:00"
    store.save(first)
    jobs = store.list_jobs()
    assert jobs[0].job_id == second.job_id
    assert jobs[-1].job_id == first.job_id


def test_list_jobs_skips_corrupt_files(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    bad = tmp_path / "builds" / "broken"
    bad.mkdir(parents=True)
    (bad / "job.json").write_text("{not json", encoding="utf-8")
    assert store.list_jobs() == []


def test_load_missing_job_raises(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        store.load("does-not-exist")
    except Exception as exc:
        assert "not found" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected an error")


def test_job_json_has_no_secret(tmp_path: Path) -> None:
    source = validate_python_source_file(make_source(tmp_path))
    store = make_store(tmp_path)
    job = store.create_job(source, repository="o/r", branch="py2cardputer/a")
    data = json.loads((Path(job.job_dir) / "job.json").read_text(encoding="utf-8"))
    assert "api_key" not in json.dumps(data).lower()
