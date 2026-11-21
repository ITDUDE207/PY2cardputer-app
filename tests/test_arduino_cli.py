from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from compiler.arduino_cli import ArduinoCLI, ArduinoCLIInfo
from core.errors import ArduinoCLIError, ArduinoCLINotFoundError
from core.models import CompileResult


def make_sketch(tmp_path: Path, name: str = "App") -> Path:
    sketch = tmp_path / name
    sketch.mkdir()
    (sketch / f"{name}.ino").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return sketch


def test_detect_missing_cli(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("compiler.arduino_cli.shutil.which", lambda _name: None)
    info = ArduinoCLI(str(tmp_path / "does-not-exist")).detect()
    assert isinstance(info, ArduinoCLIInfo)
    assert info.available is False
    assert "not found" in (info.error or "").lower()


def test_detect_json_version(monkeypatch) -> None:
    monkeypatch.setattr(ArduinoCLI, "resolve_executable", lambda self: "/usr/bin/arduino-cli")
    monkeypatch.setattr(
        "compiler.arduino_cli.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout='{"VersionString": "1.1.1"}', stderr=""
        ),
    )
    info = ArduinoCLI().detect()
    assert info.available is True
    assert info.version == "1.1.1"


def test_detect_plain_version_fallback(monkeypatch) -> None:
    monkeypatch.setattr(ArduinoCLI, "resolve_executable", lambda self: "/usr/bin/arduino-cli")
    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return SimpleNamespace(returncode=0, stdout="not json", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="arduino-cli  Version: 0.35.3 Commit: abc Date: 2024-01-01",
            stderr="",
        )

    monkeypatch.setattr("compiler.arduino_cli.subprocess.run", fake_run)
    info = ArduinoCLI().detect()
    assert info.available is True
    assert info.version == "0.35.3"


def test_compile_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ArduinoCLI, "resolve_executable", lambda self: "/usr/bin/arduino-cli")
    sketch = make_sketch(tmp_path)

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output-dir") + 1])
        output.mkdir(parents=True, exist_ok=True)
        (output / "App.ino.bin").write_bytes(b"\x00firmware")
        return SimpleNamespace(returncode=0, stdout="Sketch compiled", stderr="")

    monkeypatch.setattr("compiler.arduino_cli.subprocess.run", fake_run)
    result = ArduinoCLI().compile(sketch, fqbn="m5stack:esp32:m5stack_cardputer", output_dir=tmp_path / "out")
    assert isinstance(result, CompileResult)
    assert result.success is True
    assert result.binary_path is not None
    assert Path(result.binary_path).exists()
    assert result.stdout == "Sketch compiled"
    assert "--fqbn" in result.command
    assert "m5stack:esp32:m5stack_cardputer" in result.command


def test_compile_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ArduinoCLI, "resolve_executable", lambda self: "/usr/bin/arduino-cli")
    monkeypatch.setattr(
        "compiler.arduino_cli.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="fatal error"),
    )
    result = ArduinoCLI().compile(
        make_sketch(tmp_path), fqbn="a:b:c", output_dir=tmp_path / "out"
    )
    assert result.success is False
    assert result.returncode == 1
    assert result.stderr == "fatal error"
    assert result.binary_path is None
    assert result.error


def test_compile_success_without_binary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ArduinoCLI, "resolve_executable", lambda self: "/usr/bin/arduino-cli")
    monkeypatch.setattr(
        "compiler.arduino_cli.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    result = ArduinoCLI().compile(
        make_sketch(tmp_path), fqbn="a:b:c", output_dir=tmp_path / "out"
    )
    assert result.success is False
    assert "no .bin" in (result.error or "").lower()


def test_compile_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ArduinoCLI, "resolve_executable", lambda self: "/usr/bin/arduino-cli")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="arduino-cli", timeout=1)

    monkeypatch.setattr("compiler.arduino_cli.subprocess.run", fake_run)
    with pytest.raises(ArduinoCLIError):
        ArduinoCLI(timeout=1).compile(
            make_sketch(tmp_path), fqbn="a:b:c", output_dir=tmp_path / "out"
        )


def test_compile_missing_cli(tmp_path: Path) -> None:
    cli = ArduinoCLI("definitely-not-an-arduino-cli-xyz")
    with pytest.raises(ArduinoCLINotFoundError):
        cli.compile(make_sketch(tmp_path), fqbn="a:b:c", output_dir=tmp_path / "out")


def test_compile_missing_sketch(tmp_path: Path) -> None:
    with pytest.raises(ArduinoCLIError):
        ArduinoCLI("arduino-cli").compile(
            tmp_path / "missing", fqbn="a:b:c", output_dir=tmp_path / "out"
        )


def test_compile_empty_fqbn(tmp_path: Path) -> None:
    with pytest.raises(ArduinoCLIError):
        ArduinoCLI("arduino-cli").compile(
            make_sketch(tmp_path), fqbn="  ", output_dir=tmp_path / "out"
        )


def test_build_command_includes_properties(tmp_path: Path) -> None:
    cli = ArduinoCLI("arduino-cli")
    command = cli.build_command(
        tmp_path,
        "a:b:c",
        tmp_path / "out",
        extra_args=["--verbose"],
        build_properties={"build.partitions": "huge_app"},
    )
    assert command[-1] == str(tmp_path)
    assert "--verbose" in command
    assert "build.partitions=huge_app" in command


def test_find_binary_prefers_sketch_binary(tmp_path: Path) -> None:
    (tmp_path / "bootloader.bin").write_bytes(b"x")
    (tmp_path / "merged.bin").write_bytes(b"x")
    (tmp_path / "App.ino.bin").write_bytes(b"x")
    assert ArduinoCLI.find_binary(tmp_path, "App") == tmp_path / "App.ino.bin"


def test_find_binary_none(tmp_path: Path) -> None:
    assert ArduinoCLI.find_binary(tmp_path, "App") is None


def test_find_binary_ignores_bootloader_only(tmp_path: Path) -> None:
    (tmp_path / "bootloader.bin").write_bytes(b"x")
    (tmp_path / "partitions.bin").write_bytes(b"x")
    (tmp_path / "boot_app0.bin").write_bytes(b"x")
    assert ArduinoCLI.find_binary(tmp_path, "App") is None


def test_find_binary_accepts_merged_as_last_resort(tmp_path: Path) -> None:
    (tmp_path / "merged.bin").write_bytes(b"x")
    assert ArduinoCLI.find_binary(tmp_path, "App") == tmp_path / "merged.bin"


def test_parse_json_version_invalid() -> None:
    assert ArduinoCLI._parse_json_version("not json") is None
    assert ArduinoCLI._parse_json_version('{"Version": "2.0.0"}') == "2.0.0"
