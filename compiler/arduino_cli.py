"""Arduino CLI detection and local compilation."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.errors import ArduinoCLIError, ArduinoCLINotFoundError
from core.models import CompileResult

INSTALL_HINT = (
    "Arduino CLI was not found. Install it with 'winget install ArduinoSA.CLI' (Windows), "
    "or download it from https://arduino.github.io/arduino-cli/, then set the path in Settings."
)

BINARY_EXCLUDE_HINTS = ("bootloader", "partitions", "boot_app0", "merged")


@dataclass
class ArduinoCLIInfo:
    available: bool
    executable: str
    resolved_path: str | None = None
    version: str | None = None
    error: str | None = None

    def summary(self) -> str:
        if self.available:
            return f"Arduino CLI {self.version or 'unknown version'} ({self.resolved_path})"
        return self.error or "Arduino CLI is not available"


@dataclass
class BoardListResult:
    ok: bool
    output: str = ""
    matches: list[str] = field(default_factory=list)


class ArduinoCLI:
    def __init__(
        self,
        executable: str = "arduino-cli",
        *,
        timeout: float = 900.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.executable = executable or "arduino-cli"
        self.timeout = timeout
        self.logger = logger or logging.getLogger("py2cardputer.arduino")

    # ------------------------------------------------------------- detection
    def resolve_executable(self) -> str | None:
        candidate = Path(self.executable).expanduser()
        if candidate.is_file():
            return str(candidate)
        return shutil.which(self.executable)

    def detect(self) -> ArduinoCLIInfo:
        resolved = self.resolve_executable()
        if not resolved:
            return ArduinoCLIInfo(
                available=False,
                executable=self.executable,
                error=INSTALL_HINT,
            )
        try:
            completed = subprocess.run(
                [resolved, "version", "--format", "json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            version = self._parse_json_version(completed.stdout)
            if not version:
                completed = subprocess.run(
                    [resolved, "version"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                version = self._parse_plain_version(completed.stdout + completed.stderr)
            if completed.returncode != 0 and not version:
                return ArduinoCLIInfo(
                    available=False,
                    executable=self.executable,
                    resolved_path=resolved,
                    error=(completed.stderr or completed.stdout).strip()
                    or "Arduino CLI returned an error.",
                )
            return ArduinoCLIInfo(
                available=True,
                executable=self.executable,
                resolved_path=resolved,
                version=version or "unknown",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ArduinoCLIInfo(
                available=False,
                executable=self.executable,
                resolved_path=resolved,
                error=f"Arduino CLI could not be executed: {exc}",
            )

    @staticmethod
    def _parse_json_version(output: str) -> str | None:
        try:
            data = json.loads(output.strip() or "{}")
        except json.JSONDecodeError:
            return None
        for key in ("VersionString", "version", "Version"):
            value = data.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _parse_plain_version(output: str) -> str | None:
        for token in output.replace(":", " ").split():
            cleaned = token.strip()
            if cleaned and cleaned[0].isdigit() and "." in cleaned:
                return cleaned
        return None

    def list_boards(self, search: str = "cardputer") -> BoardListResult:
        resolved = self.resolve_executable()
        if not resolved:
            return BoardListResult(ok=False, output=INSTALL_HINT)
        try:
            completed = subprocess.run(
                [resolved, "board", "listall", search],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return BoardListResult(ok=False, output=f"arduino-cli failed: {exc}")
        output = (completed.stdout or "") + (completed.stderr or "")
        matches = [
            line.strip()
            for line in output.splitlines()
            if search.lower() in line.lower()
        ]
        return BoardListResult(ok=completed.returncode == 0, output=output.strip(), matches=matches)

    # ------------------------------------------------------------- compiling
    def build_command(
        self,
        sketch_dir: Path | str,
        fqbn: str,
        output_dir: Path | str,
        *,
        extra_args: list[str] | None = None,
        build_properties: dict[str, str] | None = None,
    ) -> list[str]:
        resolved = self.resolve_executable() or self.executable
        command = [
            resolved,
            "compile",
            "--fqbn",
            fqbn,
            "--output-dir",
            str(output_dir),
        ]
        for key, value in (build_properties or {}).items():
            command += ["--build-property", f"{key}={value}"]
        command += list(extra_args or [])
        command.append(str(sketch_dir))
        return command

    def compile(
        self,
        sketch_dir: Path | str,
        *,
        fqbn: str,
        output_dir: Path | str,
        extra_args: list[str] | None = None,
        build_properties: dict[str, str] | None = None,
    ) -> CompileResult:
        sketch_path = Path(sketch_dir)
        if not sketch_path.is_dir():
            raise ArduinoCLIError(f"Sketch directory does not exist: {sketch_path}")
        if not fqbn.strip():
            raise ArduinoCLIError("An Arduino FQBN must be configured before compiling.")
        if not self.resolve_executable():
            raise ArduinoCLINotFoundError(INSTALL_HINT)

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        command = self.build_command(
            sketch_path,
            fqbn,
            out,
            extra_args=extra_args,
            build_properties=build_properties,
        )
        self.logger.info("Compiling with %s", " ".join(command))
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ArduinoCLIError(
                f"Compilation timed out after {self.timeout:.0f} seconds."
            ) from exc
        except OSError as exc:
            raise ArduinoCLINotFoundError(f"Arduino CLI could not be started: {exc}") from exc

        duration = time.monotonic() - started
        binary = self.find_binary(out, sketch_name=sketch_path.name) if completed.returncode == 0 else None
        error = None
        if completed.returncode != 0:
            error = "Compilation failed. See the compiler output for details."
        elif binary is None:
            error = (
                "Compilation reported success but no .bin file was produced. "
                "Check the FQBN and the selected output directory."
            )
        result = CompileResult(
            success=completed.returncode == 0 and binary is not None,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            output_dir=str(out),
            binary_path=str(binary) if binary else None,
            duration_seconds=round(duration, 2),
            error=error,
        )
        if result.success:
            self.logger.info("Compilation succeeded: %s", binary)
        else:
            self.logger.warning("Compilation failed (exit %s)", completed.returncode)
        return result

    @staticmethod
    def find_binary(output_dir: Path | str, sketch_name: str | None = None) -> Path | None:
        """Locate the firmware ``.bin`` produced by a successful compile."""
        root = Path(output_dir)
        if not root.is_dir():
            return None
        binaries = [path for path in root.rglob("*.bin") if path.is_file()]
        if not binaries:
            return None
        usable = [
            path
            for path in binaries
            if not any(hint in path.name.lower() for hint in BINARY_EXCLUDE_HINTS)
        ]
        preferred: list[Path] = []
        if sketch_name:
            preferred += [path for path in usable if path.name == f"{sketch_name}.ino.bin"]
            preferred += [path for path in usable if path.name == f"{sketch_name}.bin"]
        preferred += [path for path in usable if path.name.endswith(".ino.bin")]
        preferred += usable
        # A merged image is flashable, but it is never the first choice.
        preferred += [path for path in binaries if path.name.lower() == "merged.bin"]
        for candidate in preferred:
            if candidate.exists():
                return candidate
        return None
