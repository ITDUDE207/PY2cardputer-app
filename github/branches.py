"""Branch naming rules for conversion workspaces.

Branches are never deleted or merged by Py2Cardputer. Names look like::

    py2cardputer/20261121-150000-myapp
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core.errors import ValidationError
from core.validation import sanitize_slug

DEFAULT_PREFIX = "py2cardputer"
MAX_BRANCH_LENGTH = 120

_INVALID_SEQUENCES = ("..", "//", "@{", "\\", " ", "~", "^", ":", "?", "*", "[")
_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")


def _clean_prefix(prefix: str) -> str:
    segments = [sanitize_slug(part, max_length=24, fallback="py2cardputer") for part in str(prefix).split("/") if part.strip()]
    return "/".join(segments) or DEFAULT_PREFIX


def build_branch_name(
    source_filename: str,
    *,
    prefix: str = DEFAULT_PREFIX,
    now: datetime | None = None,
    suffix: str | None = None,
) -> str:
    """Build a deterministic, human-readable branch name."""
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    stem = Path(str(source_filename)).stem or "app"
    slug = sanitize_slug(stem, max_length=40)
    name = f"{_clean_prefix(prefix)}/{timestamp}-{slug}"
    if suffix:
        name = f"{name}-{sanitize_slug(suffix, max_length=8)}"
    return name[:MAX_BRANCH_LENGTH].rstrip("-/.")


def validate_branch_name(name: str) -> str:
    """Raise :class:`ValidationError` if ``name`` is not a safe git branch."""
    if not name or not name.strip():
        raise ValidationError("Branch name must not be empty.")
    if len(name) > MAX_BRANCH_LENGTH:
        raise ValidationError(f"Branch name is longer than {MAX_BRANCH_LENGTH} characters.")
    if not _BRANCH_PATTERN.match(name):
        raise ValidationError("Branch name contains unsupported characters.")
    if any(sequence in name for sequence in _INVALID_SEQUENCES):
        raise ValidationError("Branch name contains an invalid character sequence.")
    if name.startswith(("/", ".", "-")) or name.endswith(("/", ".", ".lock")):
        raise ValidationError("Branch name has an invalid prefix or suffix.")
    if any(segment.startswith("-") for segment in name.split("/")):
        raise ValidationError("Branch name segments must not start with '-'.")
    if "/" not in name:
        raise ValidationError("Branch name must include a prefix, e.g. 'py2cardputer/myapp'.")
    return name


def unique_branch_name(
    candidate: str,
    exists: Callable[[str], bool],
    *,
    max_attempts: int = 25,
) -> str:
    """Return ``candidate`` or a numbered variant that does not exist yet."""
    validate_branch_name(candidate)
    if not exists(candidate):
        return candidate
    for index in range(2, max_attempts + 1):
        suffix = f"-{index}"
        variant = f"{candidate[: MAX_BRANCH_LENGTH - len(suffix)]}{suffix}"
        if not exists(variant):
            return variant
    raise ValidationError(
        f"Could not find an unused branch name based on {candidate!r}. "
        "Check the workspace repository for leftover branches."
    )
