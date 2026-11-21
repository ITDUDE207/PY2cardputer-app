from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from core.errors import GitAuthError, GitError
from github.downloader import FirmwareDownloader
from github.repository import GitHubRepository, GitResult


class FakeGit:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[list[str]] = []

    def run(self, args, cwd=None, timeout=None, binary=False):
        self.calls.append(list(args))
        return self.handler(list(args), cwd, binary)


def ok(stdout: str = "", stdout_bytes: bytes = b"") -> GitResult:
    return GitResult(returncode=0, stdout=stdout, stderr="", stdout_bytes=stdout_bytes)


def fail(stderr: str = "boom", code: int = 128) -> GitResult:
    return GitResult(returncode=code, stderr=stderr)


def make_repo(tmp_path: Path, handler) -> tuple[GitHubRepository, FakeGit]:
    git = FakeGit(handler)
    return GitHubRepository("owner/repo", tmp_path, git=git), git


def test_validate_slug() -> None:
    assert GitHubRepository.validate_slug("owner/repo") == "owner/repo"
    for bad in ("owner", "owner/repo/extra", "/repo", "owner/", "own er/repo"):
        with pytest.raises(GitError):
            GitHubRepository.validate_slug(bad)


def test_check_auth_success(tmp_path: Path) -> None:
    repo, git = make_repo(tmp_path, lambda args, cwd, binary: ok())
    result = repo.check_auth()
    assert result.ok is True
    assert "OK" in result.message
    assert git.calls[0][:2] == ["ls-remote", "--heads"]


def test_check_auth_failure_mentions_login(tmp_path: Path) -> None:
    repo, _ = make_repo(
        tmp_path, lambda args, cwd, binary: fail("fatal: Authentication failed for repo")
    )
    result = repo.check_auth()
    assert result.ok is False
    assert "authenticate" in result.message
    assert "git credential-manager" in result.message


def test_require_auth_raises(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, lambda args, cwd, binary: fail("Repository not found"))
    with pytest.raises(GitAuthError):
        repo.require_auth()


def test_ensure_clone_clones_once(tmp_path: Path) -> None:
    seen_cwds: list = []

    def handler(args, cwd, binary):
        seen_cwds.append(cwd)
        return ok()

    repo, git = make_repo(tmp_path, handler)
    repo.ensure_clone()
    assert git.calls[0][0] == "clone"
    assert "https://github.com/owner/repo.git" in git.calls[0]
    assert seen_cwds[0] == repo.workspace_dir
    assert seen_cwds[0].exists()

    (repo.local_path / ".git").mkdir(parents=True)
    repo.ensure_clone()
    assert any(call[:2] == ["remote", "set-url"] for call in git.calls)
    assert any(call[:2] == ["fetch", "--prune"] for call in git.calls)


def test_ensure_clone_refuses_leftover_directory(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, lambda args, cwd, binary: ok())
    repo.local_path.mkdir(parents=True)
    (repo.local_path / "stale.txt").write_text("x", encoding="utf-8")
    with pytest.raises(GitError):
        repo.ensure_clone()
    assert (repo.local_path / "stale.txt").exists()


def test_default_branch_prefers_origin_head(tmp_path: Path) -> None:
    repo, _ = make_repo(
        tmp_path,
        lambda args, cwd, binary: ok("origin/develop") if args[0] == "symbolic-ref" else ok(),
    )
    assert repo.default_branch() == "develop"


def test_default_branch_falls_back_to_main(tmp_path: Path) -> None:
    def handler(args, cwd, binary):
        if args[0] == "symbolic-ref":
            return fail()
        if args[0] == "rev-parse" and args[-1] == "origin/main":
            return ok("sha")
        return fail()

    repo, _ = make_repo(tmp_path, handler)
    assert repo.default_branch() == "main"


def test_default_branch_empty_repo_returns_main(tmp_path: Path) -> None:
    def handler(args, cwd, binary):
        if args[0] == "rev-parse" and args[1] == "--abbrev-ref":
            return ok("HEAD")
        return fail()

    repo, _ = make_repo(tmp_path, handler)
    assert repo.default_branch() == "main"


def test_create_branch_uses_orphan_for_empty_repo(tmp_path: Path) -> None:
    def handler(args, cwd, binary):
        if args[0] == "ls-remote":
            return ok("")
        if args[0] == "switch":
            return ok()
        return fail()

    repo, git = make_repo(tmp_path, handler)
    repo.create_branch("py2cardputer/20261121-150000-app")
    switch = next(call for call in git.calls if call[0] == "switch")
    assert switch[:2] == ["switch", "--orphan"]


def test_create_branch_fetch_failure_raises(tmp_path: Path) -> None:
    def handler(args, cwd, binary):
        if args[0] == "ls-remote":
            return ok("abc refs/heads/main")
        if args[0] == "fetch":
            return fail("could not resolve host")
        return fail()

    repo, _ = make_repo(tmp_path, handler)
    with pytest.raises(GitError):
        repo.create_branch("py2cardputer/20261121-150000-app")


def test_remote_branch_exists(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, lambda args, cwd, binary: ok("abc refs/heads/x"))
    assert repo.remote_branch_exists("py2cardputer/x") is True

    repo, _ = make_repo(tmp_path, lambda args, cwd, binary: ok(""))
    assert repo.remote_branch_exists("py2cardputer/x") is False


def test_create_branch_commands(tmp_path: Path) -> None:
    def handler(args, cwd, binary):
        if args[0] == "ls-remote":
            return ok("abc refs/heads/main")
        if args[0] == "show-ref":
            return fail(code=1)
        if args[0] == "rev-parse" and "--verify" in args and "refs/heads/" in args[-1]:
            return fail(code=1)
        return ok()

    repo, git = make_repo(tmp_path, handler)
    repo.create_branch("py2cardputer/20261121-150000-app")
    assert any(call[0] == "fetch" for call in git.calls)
    switch = next(call for call in git.calls if call[0] == "switch")
    assert "py2cardputer/20261121-150000-app" in switch


def test_create_branch_rejects_existing_local_branch(tmp_path: Path) -> None:
    repo, _ = make_repo(
        tmp_path,
        lambda args, cwd, binary: ok("origin/main") if args[0] == "symbolic-ref" else ok(),
    )
    with pytest.raises(GitError):
        repo.create_branch("py2cardputer/existing")


def test_commit_and_push(tmp_path: Path) -> None:
    repo, git = make_repo(tmp_path, lambda args, cwd, binary: ok())
    repo.local_path.mkdir(parents=True)
    source = tmp_path / "my_app.py"
    source.write_text("print('hi')\n", encoding="utf-8")

    def handler(args, cwd, binary):
        if args[0] == "diff":
            return fail(code=1)
        if args[0] == "rev-parse":
            return ok("deadbeef" * 5)
        return ok()

    repo.git.handler = handler
    sha = repo.commit_and_push(
        "py2cardputer/20261121-150000-my-app",
        {"input/my_app.py": source},
        "Add source",
    )
    assert sha == "deadbeef" * 5
    assert (repo.local_path / "input" / "my_app.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert any(call[0] == "push" for call in git.calls)
    commit = next(call for call in git.calls if call[0] == "-c")
    assert "user.name=Py2Cardputer" in commit


def test_commit_and_push_nothing_to_commit_reuses_head(tmp_path: Path) -> None:
    repo, git = make_repo(tmp_path, lambda args, cwd, binary: ok())
    repo.local_path.mkdir(parents=True)
    source = tmp_path / "my_app.py"
    source.write_text("x\n", encoding="utf-8")

    def handler(args, cwd, binary):
        if args[0] == "rev-parse":
            return ok("c" * 40)
        return ok()

    repo.git.handler = handler
    sha = repo.commit_and_push("py2cardputer/x", {"input/my_app.py": source}, "msg")
    assert sha == "c" * 40
    assert not any(call[0] == "commit" for call in git.calls)
    assert any(call[0] == "push" for call in git.calls)


def test_commit_and_push_rejects_path_traversal(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, lambda args, cwd, binary: ok())
    repo.local_path.mkdir(parents=True)
    source = tmp_path / "evil.py"
    source.write_text("x\n", encoding="utf-8")
    with pytest.raises(GitError):
        repo.commit_and_push("py2cardputer/x", {"../evil.py": source}, "msg")


def test_export_subtree_extracts_and_blocks_traversal(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        payload = b"void setup() {}\nvoid loop() {}\n"
        member = tarfile.TarInfo("firmware/App/App.ino")
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))
        evil_payload = b"evil"
        evil = tarfile.TarInfo("../evil.txt")
        evil.size = len(evil_payload)
        tar.addfile(evil, io.BytesIO(evil_payload))
    archive = buffer.getvalue()

    repo, _ = make_repo(
        tmp_path, lambda args, cwd, binary: ok(stdout_bytes=archive if binary else b"")
    )
    destination = tmp_path / "out"
    extracted = repo.export_subtree("origin/branch", "firmware", destination)
    assert "firmware/App/App.ino" in extracted
    assert (destination / "firmware" / "App" / "App.ino").is_file()
    assert not (tmp_path / "evil.txt").exists()


def test_export_subtree_missing_path(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, lambda args, cwd, binary: ok(stdout_bytes=b""))
    with pytest.raises(GitError):
        repo.export_subtree("origin/branch", "firmware", tmp_path / "out")


class FakeRepo:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.subdir = None

    def fetch_branch(self, branch: str) -> str:
        return "abc123"

    def list_tree(self, ref: str) -> list[str]:
        return ["firmware/App/App.ino", "firmware/App/README.md"]

    def export_subtree(self, ref: str, subdir: str, dest) -> list[str]:
        self.subdir = subdir
        root = Path(dest) / "firmware" / "App"
        root.mkdir(parents=True)
        (root / "App.ino").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
        (root / "README.md").write_text("# App\n", encoding="utf-8")
        return ["firmware/App/App.ino", "firmware/App/README.md"]


def test_downloader_exports_firmware(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path)
    downloader = FirmwareDownloader(repo)  # type: ignore[arg-type]
    result = downloader.download("py2cardputer/x", tmp_path / "download")
    assert result.commit_sha == "abc123"
    assert repo.subdir == "firmware/"
    assert (result.firmware_dir / "App" / "App.ino").is_file()
    assert len(result.files) == 2
