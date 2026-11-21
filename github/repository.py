"""Git operations against the permanent workspace repository.

Py2Cardputer never stores GitHub credentials. It relies on the machine's
existing git authentication (Git Credential Manager on Windows, or ``gh auth``)
and runs git non-interactively so a missing credential fails fast instead of
hanging the GUI.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from core.errors import GitAuthError, GitError
from core.logger import redact
from github.branches import validate_branch_name

GIT_AUTHOR_NAME = "Py2Cardputer"
GIT_AUTHOR_EMAIL = "py2cardputer@users.noreply.github.com"

AUTH_HINTS = (
    "Authentication failed",
    "could not read Username",
    "terminal prompts disabled",
    "Permission denied (publickey)",
    "Repository not found",
)


@dataclass
class GitResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)
    stdout_bytes: bytes = b""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def combined_output(self) -> str:
        return redact("\n".join(part for part in (self.stdout.strip(), self.stderr.strip()) if part))


@dataclass
class GitAuthResult:
    ok: bool
    message: str
    detail: str = ""
    remote_url: str = ""


class GitRunner:
    """Thin, non-interactive subprocess wrapper around the git executable."""

    def __init__(
        self,
        git_executable: str = "git",
        *,
        default_timeout: float = 300.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.git_executable = git_executable or "git"
        self.default_timeout = default_timeout
        self.logger = logger or logging.getLogger("py2cardputer.git")

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        env.setdefault("GIT_AUTHOR_NAME", GIT_AUTHOR_NAME)
        env.setdefault("GIT_AUTHOR_EMAIL", GIT_AUTHOR_EMAIL)
        return env

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | str | None = None,
        timeout: float | None = None,
        binary: bool = False,
    ) -> GitResult:
        command = [self.git_executable, *args]
        self.logger.debug("git %s", " ".join(args[:4]))
        kwargs = {
            "capture_output": True,
            "env": self.environment(),
            "timeout": timeout or self.default_timeout,
            "check": False,
        }
        if binary:
            kwargs["text"] = False
        else:
            kwargs.update(text=True, encoding="utf-8", errors="replace")
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                **kwargs,
            )
        except FileNotFoundError as exc:
            if cwd is not None and not Path(cwd).exists():
                raise GitError(f"Working directory does not exist: {cwd}") from exc
            raise GitError(
                "git was not found. Install Git for Windows and make sure it is on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git command timed out after {timeout or self.default_timeout:.0f}s") from exc

        stdout = completed.stdout if not binary else ""
        stderr = completed.stderr if not binary else ""
        result = GitResult(
            returncode=completed.returncode,
            stdout=stdout or "",
            stderr=stderr or "",
            command=command,
            stdout_bytes=completed.stdout if binary else b"",
        )
        if not result.ok:
            self.logger.debug("git failed (%s): %s", completed.returncode, result.combined_output())
        return result


class GitHubRepository:
    """A clone of the configured workspace repository."""

    def __init__(
        self,
        slug: str,
        workspace_dir: Path | str,
        *,
        git: GitRunner | None = None,
        remote_url: str | None = None,
        branch_prefix: str = "py2cardputer",
        logger: logging.Logger | None = None,
    ) -> None:
        self.slug = self.validate_slug(slug)
        self.workspace_dir = Path(workspace_dir)
        self.git = git or GitRunner(logger=logger)
        self.logger = logger or logging.getLogger("py2cardputer.github")
        self.branch_prefix = (branch_prefix or "py2cardputer").strip("/")
        self._remote_url = remote_url or f"https://github.com/{self.slug}.git"

    @staticmethod
    def validate_slug(slug: str) -> str:
        parts = str(slug or "").strip().split("/")
        if len(parts) != 2 or not all(parts):
            raise GitError(f"Repository {slug!r} is invalid. Use the 'owner/repo' format.")
        if not all(part.replace("-", "").replace("_", "").replace(".", "").isalnum() for part in parts):
            raise GitError(f"Repository {slug!r} contains unsupported characters.")
        return "/".join(parts)

    @property
    def remote_url(self) -> str:
        return self._remote_url

    @property
    def local_path(self) -> Path:
        safe = self.slug.replace("/", "__")
        return self.workspace_dir / safe

    # ------------------------------------------------------------------ auth
    def check_auth(self, *, timeout: float = 60.0) -> GitAuthResult:
        """Verify that local git credentials can read the repository."""
        result = self.git.run(
            ["ls-remote", "--heads", "--quiet", self.remote_url],
            timeout=timeout,
        )
        if result.ok:
            return GitAuthResult(
                ok=True,
                message=f"Git authentication OK for {self.slug}",
                remote_url=self.remote_url,
            )
        detail = result.combined_output()
        looks_like_auth = any(hint.lower() in detail.lower() for hint in AUTH_HINTS)
        message = (
            "Git could not authenticate against the workspace repository."
            if looks_like_auth
            else "Git could not reach the workspace repository."
        )
        message += (
            " Run 'git credential-manager github login' or 'gh auth login' in a terminal, "
            "then use Refresh."
        )
        return GitAuthResult(ok=False, message=message, detail=detail, remote_url=self.remote_url)

    def require_auth(self) -> None:
        result = self.check_auth()
        if not result.ok:
            raise GitAuthError(result.message, stderr=result.detail)

    # --------------------------------------------------------------- cloning
    def ensure_clone(self, *, depth: int | None = 1) -> Path:
        """Clone the repository once, then reuse it as a local cache."""
        target = self.local_path
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        if (target / ".git").exists():
            self._run(["remote", "set-url", "origin", self.remote_url], cwd=target)
            self._run(["fetch", "--prune", "origin"], cwd=target, timeout=600)
            return target

        if target.exists():
            raise GitError(
                f"Workspace path exists but is not a git clone: {target}. "
                "Move it aside instead of letting Py2Cardputer delete it."
            )

        args = ["clone", "--no-tags"]
        if depth:
            args += ["--depth", str(depth)]
        args += [self.remote_url, str(target)]
        # The clone target does not exist yet, so run from the workspace root.
        self._run(args, cwd=self.workspace_dir, timeout=900)
        self.logger.info("Cloned %s into %s", self.slug, target)
        return target

    def _ref_exists(self, ref: str) -> bool:
        result = self.git.run(
            ["rev-parse", "--verify", "--quiet", ref], cwd=self.local_path
        )
        return result.ok

    def default_branch(self) -> str:
        """Resolve the base branch, tolerating a freshly created empty repo."""
        target = self.local_path
        result = self.git.run(
            ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=target
        )
        if result.ok and result.stdout.strip():
            name = result.stdout.strip().split("/", 1)[-1]
            # GitHub makes the first pushed branch the default. A conversion
            # branch must never become the base for the next conversion.
            is_conversion = name.lower().startswith(f"{self.branch_prefix.lower()}/")
            if name and name != "HEAD" and not is_conversion and self._ref_exists(f"origin/{name}"):
                return name
        for candidate in ("main", "master", "develop"):
            if self._ref_exists(f"origin/{candidate}"):
                return candidate
        return "main"

    # --------------------------------------------------------------- branches
    def remote_branch_exists(self, branch: str) -> bool:
        result = self.git.run(
            ["ls-remote", "--heads", self.remote_url, f"refs/heads/{branch}"],
            timeout=60,
        )
        if not result.ok:
            raise GitError("Could not list remote branches.", stderr=result.combined_output())
        return bool(result.stdout.strip())

    def create_branch(self, branch: str, *, base: str | None = None) -> str:
        """Create ``branch`` and check it out.

        A brand-new workspace repository has no commits. In that case the branch
        is created as an orphan so the first upload becomes the root commit.
        """
        validate_branch_name(branch)
        target = self.local_path
        base_branch = base or self.default_branch()
        existing = self.git.run(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=target
        )
        if existing.ok:
            raise GitError(f"Local branch {branch!r} already exists in the workspace clone.")

        if self.remote_branch_exists(base_branch):
            fetch = self.git.run(
                ["fetch", "--no-tags", "origin", base_branch], cwd=target, timeout=600
            )
            if not fetch.ok or not self._ref_exists(f"origin/{base_branch}"):
                raise GitError(
                    f"Could not fetch base branch {base_branch!r}.",
                    stderr=fetch.combined_output(),
                )
            self._run(["switch", "--force-create", branch, f"origin/{base_branch}"], cwd=target)
            self.logger.info("Created branch %s from %s", branch, base_branch)
            return branch

        # A brand-new repository, or one that only contains previous conversion
        # branches, has no stable base. An orphan branch keeps conversions from
        # inheriting another conversion's files.
        self.logger.info("No base branch %r; creating orphan branch %s", base_branch, branch)
        self._run(["switch", "--orphan", branch], cwd=target)
        return branch

    def commit_and_push(
        self,
        branch: str,
        files: dict[str, Path],
        message: str,
    ) -> str:
        """Copy ``files`` into the clone, commit them on ``branch`` and push."""
        validate_branch_name(branch)
        target = self.local_path
        if not files:
            raise GitError("No files were provided for the commit.")
        relative_paths: list[str] = []
        for relative, source in files.items():
            destination = target / relative
            if not destination.resolve().is_relative_to(target.resolve()):
                raise GitError(f"Refusing to write outside the workspace clone: {relative}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            relative_paths.append(relative)

        self._run(["add", "--", *relative_paths], cwd=target)
        staged = self.git.run(
            ["diff", "--cached", "--quiet", "--", *relative_paths], cwd=target
        )
        if staged.ok:
            sha = self._run(["rev-parse", "HEAD"], cwd=target).stdout.strip()
            if not sha:
                raise GitError("Nothing to commit and the branch has no commit.")
            self._run(["push", "--set-upstream", "origin", branch], cwd=target, timeout=900)
            self.logger.info("Files already present on %s; reused commit %s", branch, sha[:8])
            return sha
        if staged.returncode != 1:
            raise GitError(
                "Could not determine whether the uploaded files changed.",
                stderr=staged.combined_output(),
            )

        self._run(
            [
                "-c",
                f"user.name={GIT_AUTHOR_NAME}",
                "-c",
                f"user.email={GIT_AUTHOR_EMAIL}",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                message,
            ],
            cwd=target,
        )
        self._run(["push", "--set-upstream", "origin", branch], cwd=target, timeout=900)
        sha = self._run(["rev-parse", "HEAD"], cwd=target).stdout.strip()
        self.logger.info("Pushed %s to %s", sha[:8], branch)
        return sha

    def fetch_branch(self, branch: str) -> str:
        """Fetch a remote branch and return its commit SHA."""
        validate_branch_name(branch)
        target = self.local_path
        self._run(
            [
                "fetch",
                "--no-tags",
                "origin",
                f"refs/heads/{branch}:refs/remotes/origin/{branch}",
            ],
            cwd=target,
            timeout=900,
        )
        sha = self._run(["rev-parse", f"origin/{branch}"], cwd=target).stdout.strip()
        if not sha:
            raise GitError(f"Branch {branch!r} was not found on the remote.")
        return sha

    def list_tree(self, ref: str, path: str | None = None) -> list[str]:
        args = ["ls-tree", "-r", "--name-only", ref]
        if path:
            args += ["--", path]
        result = self._run(args, cwd=self.local_path)
        return [line for line in result.stdout.splitlines() if line.strip()]

    def export_subtree(self, ref: str, subdir: str, destination: Path | str) -> list[str]:
        """Extract ``subdir`` from ``ref`` into ``destination`` via ``git archive``."""
        dest = Path(destination)
        dest.mkdir(parents=True, exist_ok=True)
        archive = self.git.run(
            ["archive", "--format=tar", ref, "--", subdir],
            cwd=self.local_path,
            timeout=900,
            binary=True,
        )
        if not archive.ok:
            raise GitError(
                f"Could not export {subdir!r} from {ref!r}.",
                stderr=archive.combined_output(),
            )
        if not archive.stdout_bytes:
            raise GitError(f"Path {subdir!r} does not exist on branch ref {ref!r}.")
        extracted: list[str] = []
        with tarfile.open(fileobj=io.BytesIO(archive.stdout_bytes), mode="r:") as tar:
            for member in tar.getmembers():
                if not self._is_safe_member(member.name) or member.issym() or member.islnk():
                    self.logger.warning("Skipping unsafe archive member %s", member.name)
                    continue
                try:
                    tar.extract(member, path=dest, filter="data")
                except TypeError:  # Python < 3.12 has no extraction filters
                    tar.extract(member, path=dest)
                if member.isfile():
                    extracted.append(member.name)
        return extracted

    @staticmethod
    def _is_safe_member(name: str) -> bool:
        pure = Path(name)
        if pure.is_absolute() or ".." in pure.parts:
            return False
        return not any(part.startswith("..") for part in pure.parts)

    # ------------------------------------------------------------------ utils
    def _run(
        self,
        args: list[str],
        *,
        cwd: Path | str | None = None,
        timeout: float | None = None,
    ) -> GitResult:
        if cwd is None:
            cwd = self.local_path if self.local_path.exists() else self.workspace_dir
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        result = self.git.run(args, cwd=cwd, timeout=timeout)
        if not result.ok:
            raise GitError(
                f"git {' '.join(args[:2])} failed with exit code {result.returncode}.",
                command=" ".join(result.command),
                stderr=result.combined_output(),
            )
        return result

