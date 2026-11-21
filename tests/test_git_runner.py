from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.errors import GitError
from github.repository import GitRunner


def test_missing_git_executable(monkeypatch, tmp_path: Path) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr("github.repository.subprocess.run", fake_run)
    with pytest.raises(GitError) as excinfo:
        GitRunner().run(["status"], cwd=tmp_path)
    assert "git was not found" in str(excinfo.value)


def test_missing_working_directory(monkeypatch, tmp_path: Path) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("cwd")

    monkeypatch.setattr("github.repository.subprocess.run", fake_run)
    with pytest.raises(GitError) as excinfo:
        GitRunner().run(["status"], cwd=tmp_path / "missing")
    assert "Working directory" in str(excinfo.value)


def test_timeout_is_reported(monkeypatch, tmp_path: Path) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr("github.repository.subprocess.run", fake_run)
    with pytest.raises(GitError) as excinfo:
        GitRunner(default_timeout=1).run(["status"], cwd=tmp_path)
    assert "timed out" in str(excinfo.value)


def test_environment_disables_prompts() -> None:
    env = GitRunner().environment()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "never"
