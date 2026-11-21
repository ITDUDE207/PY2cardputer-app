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
