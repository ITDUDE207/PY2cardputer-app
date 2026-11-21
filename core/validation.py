"""Validation and naming helpers.

These functions never execute user code. Python sources are parsed with
:mod:`ast`, which only inspects the syntax tree.
"""

from __future__ import annotations

import ast
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from core.errors import ValidationError

MAX_SOURCE_BYTES = 2 * 1024 * 1024
ALLOWED_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
SLUG_CHARS = re.compile(r"[^a-z0-9]+")
APP_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,47}$")


def _ascii(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def sanitize_filename(filename: str, fallback: str = "app") -> str:
    """Return a safe ``.py`` file name without directories or odd characters."""
    raw = str(filename or "").replace("\\", "/").split("/")[-1]
    stem, dot, suffix = raw.rpartition(".")
    if not dot:
        stem, suffix = raw, "py"
    if suffix.lower() != "py":
        suffix = "py"
    stem = _ascii(stem)
    stem = ALLOWED_FILENAME_CHARS.sub("_", stem).strip("._-")
    stem = re.sub(r"_{2,}", "_", stem)
    stem = stem or fallback
    stem = stem[:80]
    return f"{stem}.py"


def sanitize_slug(text: str, max_length: int = 40, fallback: str = "app") -> str:
    """Lowercase, hyphen-separated identifier safe for a git branch."""
    slug = SLUG_CHARS.sub("-", _ascii(str(text or "")).lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug[:max_length].strip("-")
    if not slug:
        slug = fallback
    if not slug[0].isalnum():
        slug = f"{fallback}-{slug}"[:max_length].strip("-")
    return slug


def derive_app_name(filename: str) -> str:
    """Turn ``my_cool_app.py`` into ``MyCoolApp`` (valid Arduino sketch name)."""
    stem = Path(str(filename)).stem
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", _ascii(stem)) if part]
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    if not name:
        name = "App"
    if not name[0].isalpha():
        name = f"App{name}"
    return name[:48]


def validate_app_name(name: str) -> str:
    if not APP_NAME_PATTERN.match(name or ""):
        raise ValidationError(
            "Application name must start with a letter and contain only letters, digits "
            "and underscores (max 48 characters)."
        )
    return name


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class SourceInspection:
    imports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    line_count: int = 0


@dataclass
class SourceFile:
    path: Path
    filename: str
    size_bytes: int
    sha256: str
    text: str
    inspection: SourceInspection

    @property
    def app_name(self) -> str:
        return derive_app_name(self.filename)


def inspect_python_source(text: str) -> SourceInspection:
    """Collect imports and syntax warnings without executing anything."""
    inspection = SourceInspection(line_count=len(text.splitlines()))
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        inspection.warnings.append(
            f"Python syntax check failed (line {exc.lineno}): {exc.msg}. "
            "UIFlow sources are sometimes MicroPython-only; conversion continues."
        )
        return inspection
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    inspection.imports = sorted(modules)
    if not inspection.imports:
        inspection.warnings.append("No import statements were found in the source file.")
    return inspection


def validate_python_source_file(
    path: Path | str,
    *,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> SourceFile:
    """Validate an uploaded UIFlow ``.py`` file and read it as UTF-8."""
    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise ValidationError(f"File not found: {candidate}")
    if not candidate.is_file():
        raise ValidationError(f"Not a regular file: {candidate}")
    if candidate.suffix.lower() != ".py":
        raise ValidationError("Only MicroPython '.py' files can be converted.")
    try:
        size = candidate.stat().st_size
    except OSError as exc:
        raise ValidationError(f"File cannot be read: {exc}") from exc
    if size == 0:
        raise ValidationError("The selected file is empty.")
    if size > max_bytes:
        raise ValidationError(
            f"The selected file is too large ({size} bytes). Limit is {max_bytes} bytes."
        )
    try:
        text = candidate.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("The file is not valid UTF-8 text.") from exc
    except OSError as exc:
        raise ValidationError(f"File cannot be read: {exc}") from exc
    if "\x00" in text:
        raise ValidationError("The file contains binary (NUL) characters.")
    if not text.strip():
        raise ValidationError("The file contains only whitespace.")
    return SourceFile(
        path=candidate.resolve(),
        filename=sanitize_filename(candidate.name),
        size_bytes=size,
        sha256=sha256_file(candidate),
        text=text,
        inspection=inspect_python_source(text),
    )
