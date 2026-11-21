"""End-to-end git test against a local bare repository.

No network or GitHub credentials are required. Skipped when git is not
installed (for example on a minimal CI image).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from github.repository import GitHubRepository

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_empty_remote_orphan_branch_roundtrip(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))

    repository = GitHubRepository(
        "owner/repo", tmp_path / "workspace", remote_url=str(remote)
    )
    repository.ensure_clone(depth=None)
    assert repository.check_auth().ok is True

    branch = "py2cardputer/20261121-150000-app"
    repository.create_branch(branch)

    source = tmp_path / "app.py"
    source.write_text("print('hello')\n", encoding="utf-8")
    sha = repository.commit_and_push(branch, {"input/app.py": source}, "Add source")
    assert len(sha) == 40
    assert repository.remote_branch_exists(branch) is True

    fetched = repository.fetch_branch(branch)
    assert fetched == sha

    destination = tmp_path / "download"
    files = repository.export_subtree(f"origin/{branch}", "input", destination)
    assert "input/app.py" in files
    assert (destination / "input" / "app.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert source.read_text(encoding="utf-8") == "print('hello')\n"


def test_second_conversion_branches_from_existing_main(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "--initial-branch=main", cwd=seed)
    (seed / "README.md").write_text("# Workspace\n", encoding="utf-8")
    git("add", "README.md", cwd=seed)
    git(
        "-c",
        "user.name=Seed",
        "-c",
        "user.email=seed@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "Initial commit",
        cwd=seed,
    )
    git("push", str(remote), "main", cwd=seed)

    repository = GitHubRepository(
        "owner/repo", tmp_path / "workspace", remote_url=str(remote)
    )
    repository.ensure_clone(depth=None)
    assert repository.default_branch() == "main"
    repository.create_branch("py2cardputer/20261121-150001-second")
    assert (repository.local_path / "README.md").is_file()

    source = tmp_path / "second.py"
    source.write_text("print('second')\n", encoding="utf-8")
    repository.commit_and_push(
        "py2cardputer/20261121-150001-second", {"input/second.py": source}, "Add source"
    )
    assert repository.remote_branch_exists("py2cardputer/20261121-150001-second")
    # main must remain untouched by conversions.
    main_files = git("ls-tree", "-r", "--name-only", "main", cwd=remote).splitlines()
    assert "input/second.py" not in main_files


def test_repo_with_only_conversion_branches_uses_orphan(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "--initial-branch=main", cwd=seed)
    (seed / "old.txt").write_text("old conversion\n", encoding="utf-8")
    git("add", "old.txt", cwd=seed)
    git(
        "-c",
        "user.name=Seed",
        "-c",
        "user.email=seed@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "Old conversion",
        cwd=seed,
    )
    git("switch", "-c", "py2cardputer/old", cwd=seed)
    git("push", str(remote), "py2cardputer/old", cwd=seed)
    # GitHub promotes the first pushed branch to default; simulate that.
    git("symbolic-ref", "HEAD", "refs/heads/py2cardputer/old", cwd=remote)

    repository = GitHubRepository(
        "owner/repo", tmp_path / "workspace", remote_url=str(remote)
    )
    repository.ensure_clone(depth=None)
    assert repository.default_branch() == "main"

    branch = "py2cardputer/20261121-150002-third"
    repository.create_branch(branch, base=repository.default_branch())
    assert not (repository.local_path / "old.txt").exists()

    source = tmp_path / "third.py"
    source.write_text("print('third')\n", encoding="utf-8")
    repository.commit_and_push(branch, {"input/third.py": source}, "Add source")
    files = git("ls-tree", "-r", "--name-only", branch, cwd=remote).splitlines()
    assert files == ["input/third.py"]
