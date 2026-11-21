from __future__ import annotations

from pathlib import Path

import pytest

from core.errors import ValidationError
from core.validation import (
    derive_app_name,
    inspect_python_source,
    sanitize_filename,
    sanitize_slug,
    validate_app_name,
    validate_python_source_file,
    validate_source_input,
)

VALID_SOURCE = """\
from m5stack import *
from m5ui import *
import time

def setup():
    M5TextBox(10, 10, "Hello", lcd.FONT_Default, 0xFFFFFF)

def loop():
    time.sleep(0.1)
"""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("myapp.py", "myapp.py"),
        ("../../etc/passwd", "passwd.py"),
        ("My App (v2).PY", "My_App_v2.py"),
        ("weird!!name.py", "weird_name.py"),
        ("no_extension", "no_extension.py"),
        ("...hidden.py", "hidden.py"),
        ("café.py", "cafe.py"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_fallback() -> None:
    assert sanitize_filename("!!!.py", fallback="app") == "app.py"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("My Cool App", "my-cool-app"),
        ("hello_world", "hello-world"),
        ("___", "app"),
        ("-leading", "leading"),
        ("a" * 100, "a" * 40),
    ],
)
def test_sanitize_slug(raw: str, expected: str) -> None:
    assert sanitize_slug(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my_app.py", "MyApp"),
        ("my-app.v2.py", "MyAppV2"),
        ("123.py", "App123"),
        ("___.py", "App"),
        ("CardputerDemo.py", "CardputerDemo"),
    ],
)
def test_derive_app_name(raw: str, expected: str) -> None:
    assert derive_app_name(raw) == expected


def test_validate_app_name() -> None:
    assert validate_app_name("MyApp") == "MyApp"
    with pytest.raises(ValidationError):
        validate_app_name("1Bad")
    with pytest.raises(ValidationError):
        validate_app_name("has space")


def test_validate_valid_source(tmp_path: Path) -> None:
    path = tmp_path / "demo.py"
    path.write_text(VALID_SOURCE, encoding="utf-8")
    source = validate_python_source_file(path)
    assert source.filename == "demo.py"
    assert source.app_name == "Demo"
    assert source.size_bytes > 0
    assert len(source.sha256) == 64
    assert "m5stack" in source.inspection.imports
    assert "time" in source.inspection.imports
    assert source.inspection.warnings == []


def test_source_file_is_not_modified(tmp_path: Path) -> None:
    path = tmp_path / "demo.py"
    path.write_text(VALID_SOURCE, encoding="utf-8")
    before = path.read_bytes()
    validate_python_source_file(path)
    assert path.read_bytes() == before


def test_validate_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        validate_python_source_file(tmp_path / "missing.py")


def test_validate_wrong_extension(tmp_path: Path) -> None:
    path = tmp_path / "demo.txt"
    path.write_text("print('hi')", encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_python_source_file(path)


def test_validate_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.py"
    path.touch()
    with pytest.raises(ValidationError):
        validate_python_source_file(path)


def test_validate_binary_file(tmp_path: Path) -> None:
    path = tmp_path / "binary.py"
    path.write_bytes(b"print(1)\x00\x00")
    with pytest.raises(ValidationError):
        validate_python_source_file(path)


def test_validate_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "latin.py"
    path.write_bytes(b"print('\xff')\n")
    with pytest.raises(ValidationError):
        validate_python_source_file(path)


def test_validate_too_large(tmp_path: Path) -> None:
    path = tmp_path / "big.py"
    path.write_text("x = 1\n" * 100, encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_python_source_file(path, max_bytes=20)


def test_validate_directory(tmp_path: Path) -> None:
    directory = tmp_path / "folder.py"
    directory.mkdir()
    with pytest.raises(ValidationError):
        validate_python_source_file(directory)


def test_syntax_error_is_warning_only() -> None:
    inspection = inspect_python_source("def broken(:\n")
    assert inspection.warnings
    assert "syntax" in inspection.warnings[0].lower()


def test_no_imports_warning() -> None:
    inspection = inspect_python_source("x = 1\n")
    assert inspection.warnings


def _write_folder_project(root: Path) -> None:
    (root / "main.py").write_text(VALID_SOURCE, encoding="utf-8")
    assets = root / "assets"
    assets.mkdir()
    (assets / "logo.txt").write_text("logo", encoding="utf-8")
    (root / "notes.txt").write_text("notes", encoding="utf-8")
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "ignored.py").write_text("print('ignored')\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=never-upload\n", encoding="utf-8")


def test_validate_folder_bundle(tmp_path: Path) -> None:
    project = tmp_path / "MyProject"
    project.mkdir()
    _write_folder_project(project)

    source = validate_source_input(project)

    assert source.kind == "folder"
    assert source.primary_relative == "main.py"
    assert source.filename == "main.py"
    assert source.app_name == "MyProject"
    assert source.file_count == 3
    assert source.asset_count == 2
    assert "assets/logo.txt" in source.bundle
    assert "notes.txt" in source.bundle
    assert ".env" not in source.bundle
    assert "__pycache__/ignored.py" not in source.bundle
    assert source.text == VALID_SOURCE
    assert "m5stack" in source.inspection.imports
    assert (project / ".env").read_text(encoding="utf-8") == "SECRET=never-upload\n"


def test_validate_zip_bundle(tmp_path: Path) -> None:
    archive = tmp_path / "MyZipApp.zip"
    import zipfile

    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("src/main.py", VALID_SOURCE)
        bundle.writestr("src/assets/icon.txt", "icon")
        bundle.writestr("__MACOSX/._main.py", "junk")
        bundle.writestr(".env", "SECRET=never-upload")

    source = validate_source_input(archive)

    assert source.kind == "zip"
    assert source.primary_relative == "src/main.py"
    assert source.app_name == "MyZipApp"
    assert source.bundle["src/assets/icon.txt"] == b"icon"
    assert "__MACOSX/._main.py" not in source.bundle
    assert ".env" not in source.bundle
    assert source.inspection.imports == ["m5stack", "m5ui", "time"]


def test_validate_zip_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    import zipfile

    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.py", "print(1)\n")

    with pytest.raises(ValidationError):
        validate_source_input(archive)


def test_validate_zip_requires_python(tmp_path: Path) -> None:
    archive = tmp_path / "assets.zip"
    import zipfile

    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.txt", "no python here")

    with pytest.raises(ValidationError):
        validate_source_input(archive)


def test_validate_folder_rejects_symlink(tmp_path: Path) -> None:
    project = tmp_path / "linked"
    project.mkdir()
    (project / "main.py").write_text(VALID_SOURCE, encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (project / "link.txt").symlink_to(outside)

    with pytest.raises(ValidationError):
        validate_source_input(project)
