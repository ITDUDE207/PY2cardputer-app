"""Download generated firmware from a conversion branch."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from core.errors import GitError
from core.models import DownloadResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from github.repository import GitHubRepository


class FirmwareDownloader:
    """Pull ``firmware/`` (or the whole branch) into the job folder."""

    def __init__(
        self, repository: "GitHubRepository", logger: logging.Logger | None = None
    ) -> None:
        self.repository = repository
        self.logger = logger or logging.getLogger("py2cardputer.downloader")

    def download(self, branch: str, destination: Path | str) -> DownloadResult:
        sha = self.repository.fetch_branch(branch)
        files = self.repository.list_tree("origin/" + branch)
        if not files:
            raise GitError(f"Branch {branch!r} contains no files.")

        firmware_prefix = "firmware/" if any(f.startswith("firmware/") for f in files) else ""
        subdir = firmware_prefix or "."
        dest = Path(destination)
        extracted = self.repository.export_subtree("origin/" + branch, subdir, dest)
        firmware_dir = dest / "firmware" if firmware_prefix else dest
        if not firmware_dir.exists():
            raise GitError(f"No firmware directory was produced on branch {branch!r}.")
        self.logger.info(
            "Downloaded %d file(s) from %s at %s", len(extracted), branch, sha[:8]
        )
        return DownloadResult(commit_sha=sha, firmware_dir=firmware_dir, files=extracted)
