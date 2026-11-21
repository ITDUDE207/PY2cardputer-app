"""Validation and naming helpers.

These functions never execute user code. Python sources are parsed with
:mod:`ast`, which only inspects the syntax tree.

A conversion input may be one ``.py`` file, a folder, or a ``.zip`` archive.
Folders and archives are read into an in-memory bundle so the original input is
never modified and no archive is extracted onto disk.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core.errors import ValidationError

MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_BUNDLE_BYTES = 25 * 1024 * 1024
MAX_BUNDLE_FILE_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_FILES = 300
ALLOWED_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
SLUG_CHARS = re.compile(r"[^a-z0-9]+")
APP_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,47}$")

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".idea",
    ".vscode",
    "__MACOSX",
}
IGNORED_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
PRIMARY_NAMES = {"main.py", "app.py", "code.py", "boot.py"}


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


def _bundle_sha256(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[relative])
        digest.update(b"\0")
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
    kind: str = "file"
    primary_relative: str = ""
    bundle: dict[str, bytes] = field(default_factory=dict, repr=False)
    name_hint: str = ""

    @property
    def app_name(self) -> str:
        if self.name_hint:
            return self.name_hint
        return derive_app_name(self.filename)

    @property
    def file_count(self) -> int:
        return len(self.bundle) or 1

    @property
    def asset_count(self) -> int:
        return sum(1 for name in self.bundle if not name.lower().endswith(".py"))

    @property
    def display_name(self) -> str:
        if self.kind == "file":
            return self.filename
        return f"{self.path.name} ({self.file_count} file(s))"


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


def _decode_python(relative: str, data: bytes, *, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise ValidationError(
            f"Python file {relative!r} is too large ({len(data)} bytes). "
            f"Limit is {max_bytes} bytes."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"Python file {relative!r} is not valid UTF-8 text.") from exc
    if "\x00" in text:
        raise ValidationError(f"Python file {relative!r} contains binary (NUL) characters.")
    if not text.strip():
        raise ValidationError(f"Python file {relative!r} contains only whitespace.")
    return text


def _inspect_bundle(
    files: dict[str, bytes],
    primary: str,
    *,
    max_source_bytes: int,
) -> tuple[str, SourceInspection]:
    imports: set[str] = set()
    warnings: list[str] = []
    line_count = 0
    primary_text = ""
    python_files = sorted(name for name in files if name.lower().endswith(".py"))
    for relative in python_files:
        text = _decode_python(relative, files[relative], max_bytes=max_source_bytes)
        inspection = inspect_python_source(text)
        imports.update(inspection.imports)
        line_count += inspection.line_count
        prefix = f"{relative}: " if len(python_files) > 1 else ""
        warnings.extend(prefix + warning for warning in inspection.warnings)
        if relative == primary:
            primary_text = text
    if not primary_text:
        raise ValidationError("The input contains no readable Python source file.")
    return primary_text, SourceInspection(
        imports=sorted(imports),
        warnings=warnings,
        line_count=line_count,
    )


def _ignored(relative: str, *, is_dir: bool = False) -> bool:
    parts = PurePosixPath(relative).parts
    if not parts:
        return True
    if any(part.startswith(".") for part in parts):
        return True
    if any(part in IGNORED_DIRS for part in parts[:-1]):
        return True
    if is_dir and parts[-1] in IGNORED_DIRS:
        return True
    return parts[-1] in IGNORED_FILES


def _select_primary(files: dict[str, bytes]) -> str:
    candidates = [name for name in files if name.lower().endswith(".py")]
    if not candidates:
        raise ValidationError(
            "The selected folder or ZIP contains no Python (.py) source file."
        )

    def rank(relative: str) -> tuple[int, int, str]:
        path = PurePosixPath(relative)
        return (
            len(path.parts),
            0 if path.name.lower() in PRIMARY_NAMES else 1,
            relative.lower(),
        )

    return min(candidates, key=rank)


def _build_bundle(
    path: Path,
    files: dict[str, bytes],
    *,
    kind: str,
    name_hint: str,
    max_source_bytes: int,
) -> SourceFile:
    if not files:
        raise ValidationError("The selected folder or ZIP contains no readable files.")
    if len(files) > MAX_BUNDLE_FILES:
        raise ValidationError(
            f"The input contains too many files ({len(files)}). "
            f"Limit is {MAX_BUNDLE_FILES}."
        )
    total = sum(len(data) for data in files.values())
    if total > MAX_BUNDLE_BYTES:
        raise ValidationError(
            f"The input is too large ({total} bytes). Limit is {MAX_BUNDLE_BYTES} bytes."
        )
    primary = _select_primary(files)
    primary_text, inspection = _inspect_bundle(
        files, primary, max_source_bytes=max_source_bytes
    )
    return SourceFile(
        path=path,
        filename=sanitize_filename(PurePosixPath(primary).name),
        size_bytes=total,
        sha256=_bundle_sha256(files),
        text=primary_text,
        inspection=inspection,
        kind=kind,
        primary_relative=primary,
        bundle=dict(files),
        name_hint=name_hint,
    )


def _validate_folder(
    root: Path,
    *,
    max_source_bytes: int,
) -> SourceFile:
    files: dict[str, bytes] = {}
    total = 0
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirnames.sort()
        filenames.sort()
        kept_dirs: list[str] = []
        for dirname in dirnames:
            directory = current_path / dirname
            if directory.is_symlink():
                raise ValidationError(
                    f"Symbolic links are not allowed in a conversion input: {directory}"
                )
            relative = directory.relative_to(root).as_posix()
            if not _ignored(relative, is_dir=True):
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_symlink():
                raise ValidationError(
                    f"Symbolic links are not allowed in a conversion input: {candidate}"
                )
            relative = candidate.relative_to(root).as_posix()
            if _ignored(relative):
                continue
            try:
                size = candidate.stat().st_size
            except OSError as exc:
                raise ValidationError(f"File cannot be read: {candidate}") from exc
            if size > MAX_BUNDLE_FILE_BYTES:
                raise ValidationError(
                    f"File {relative!r} is too large ({size} bytes). "
                    f"Limit is {MAX_BUNDLE_FILE_BYTES} bytes."
                )
            if len(files) >= MAX_BUNDLE_FILES:
                raise ValidationError(
                    f"The input contains more than {MAX_BUNDLE_FILES} files."
                )
            total += size
            if total > MAX_BUNDLE_BYTES:
                raise ValidationError(
                    f"The input is too large. Limit is {MAX_BUNDLE_BYTES} bytes."
                )
            try:
                files[relative] = candidate.read_bytes()
            except OSError as exc:
                raise ValidationError(f"File cannot be read: {candidate}") from exc
    return _build_bundle(
        root,
        files,
        kind="folder",
        name_hint=derive_app_name(root.name),
        max_source_bytes=max_source_bytes,
    )


def _safe_zip_name(name: str) -> str | None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        raise ValidationError(f"ZIP entry uses an absolute path: {name!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError(f"ZIP entry contains an unsafe path: {name!r}")
    if any(":" in part for part in path.parts):
        raise ValidationError(f"ZIP entry contains a drive or stream path: {name!r}")
    if "\x00" in normalized:
        raise ValidationError("ZIP entry contains a NUL character.")
    return path.as_posix()


def _validate_zip(
    archive: Path,
    *,
    max_source_bytes: int,
) -> SourceFile:
    files: dict[str, bytes] = {}
    total = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > MAX_BUNDLE_FILES * 2:
                raise ValidationError(
                    f"The ZIP contains too many entries ({len(infos)})."
                )
            for info in infos:
                if info.is_dir():
                    continue
                relative = _safe_zip_name(info.filename)
                if relative is None or _ignored(relative):
                    continue
                if info.flag_bits & 0x1:
                    raise ValidationError(f"Encrypted ZIP entries are not supported: {relative!r}")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValidationError(f"Symbolic links are not allowed in a ZIP: {relative!r}")
                if info.file_size > MAX_BUNDLE_FILE_BYTES:
                    raise ValidationError(
                        f"ZIP entry {relative!r} is too large ({info.file_size} bytes). "
                        f"Limit is {MAX_BUNDLE_FILE_BYTES} bytes."
                    )
                if len(files) >= MAX_BUNDLE_FILES:
                    raise ValidationError(
                        f"The ZIP contains more than {MAX_BUNDLE_FILES} files."
                    )
                chunks: list[bytes] = []
                entry_size = 0
                with bundle.open(info) as handle:
                    while True:
                        chunk = handle.read(65536)
                        if not chunk:
                            break
                        entry_size += len(chunk)
                        if entry_size > MAX_BUNDLE_FILE_BYTES:
                            raise ValidationError(
                                f"ZIP entry {relative!r} expands beyond the "
                                f"{MAX_BUNDLE_FILE_BYTES}-byte limit."
                            )
                        if total + entry_size > MAX_BUNDLE_BYTES:
                            raise ValidationError(
                                f"The ZIP expands beyond the {MAX_BUNDLE_BYTES}-byte limit."
                            )
                        chunks.append(chunk)
                data = b"".join(chunks)
                total += len(data)
                files[relative] = data
    except zipfile.BadZipFile as exc:
        raise ValidationError("The selected file is not a valid ZIP archive.") from exc
    except (RuntimeError, NotImplementedError) as exc:
        raise ValidationError(f"The ZIP archive uses an unsupported feature: {exc}") from exc
    except OSError as exc:
        raise ValidationError(f"The ZIP archive cannot be read: {exc}") from exc
    return _build_bundle(
        archive,
        files,
        kind="zip",
        name_hint=derive_app_name(archive.stem),
        max_source_bytes=max_source_bytes,
    )


def validate_source_input(
    path: Path | str,
    *,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> SourceFile:
    """Validate a ``.py`` file, folder or ``.zip`` archive."""
    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise ValidationError(f"Input not found: {candidate}")
    if candidate.is_file():
        if candidate.suffix.lower() == ".zip":
            return _validate_zip(candidate.resolve(), max_source_bytes=max_bytes)
        return validate_python_source_file(candidate, max_bytes=max_bytes)
    if candidate.is_dir():
        return _validate_folder(candidate.resolve(), max_source_bytes=max_bytes)
    raise ValidationError("Select a Python file, a folder, or a .zip archive.")


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
        raw = candidate.read_bytes()
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("The file is not valid UTF-8 text.") from exc
    except OSError as exc:
        raise ValidationError(f"File cannot be read: {exc}") from exc
    if "\x00" in text:
        raise ValidationError("The file contains binary (NUL) characters.")
    if not text.strip():
        raise ValidationError("The file contains only whitespace.")
    filename = sanitize_filename(candidate.name)
    return SourceFile(
        path=candidate.resolve(),
        filename=filename,
        size_bytes=size,
        sha256=sha256_file(candidate),
        text=text,
        inspection=inspect_python_source(text),
        kind="file",
        primary_relative=filename,
        bundle={filename: raw},
    )
