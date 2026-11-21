"""Configuration loading and persistence.

Precedence (lowest to highest): built-in defaults -> ``config.json`` ->
environment variables (including values loaded from ``.env``).

Secrets are never written to ``config.json``. The OpenHands API key lives in
``.env`` only, and ``.env`` is git-ignored.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

from core.errors import ConfigError
from core.logger import register_secret

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_API_URL = "https://app.all-hands.dev"
DEFAULT_REPOSITORY = "ITDUDE207/Py2Cardputer-Workspace"
DEFAULT_BRANCH_PREFIX = "py2cardputer"
DEFAULT_FQBN = "m5stack:esp32:m5stack_cardputer"

ENV_FILE_NAME = ".env"
CONFIG_FILE_NAME = "config.json"

REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

DEFAULT_BOARD_PROFILES: dict[str, str] = {
    "M5Stack Cardputer ADV": DEFAULT_FQBN,
}

# environment variable -> (attribute name, type)
ENV_MAP: dict[str, tuple[str, type]] = {
    "OPENHANDS_API_URL": ("openhands_api_url", str),
    "OPENHANDS_LLM_MODEL": ("openhands_llm_model", str),
    "PY2CARDPUTER_GITHUB_REPOSITORY": ("github_repository", str),
    "GITHUB_REPOSITORY": ("github_repository", str),
    "PY2CARDPUTER_BRANCH_PREFIX": ("github_branch_prefix", str),
    "ARDUINO_CLI_PATH": ("arduino_cli_path", str),
    "ARDUINO_FQBN": ("arduino_fqbn", str),
    "PY2CARDPUTER_BUILD_DIR": ("build_dir", str),
    "PY2CARDPUTER_LOG_DIR": ("log_dir", str),
    "PY2CARDPUTER_WORKSPACE_DIR": ("workspace_dir", str),
    "PY2CARDPUTER_POLL_INTERVAL": ("poll_interval_seconds", float),
    "PY2CARDPUTER_STARTUP_TIMEOUT": ("startup_timeout_seconds", float),
    "PY2CARDPUTER_EXECUTION_TIMEOUT": ("execution_timeout_seconds", float),
    "PY2CARDPUTER_REQUEST_TIMEOUT": ("request_timeout_seconds", float),
    "PY2CARDPUTER_KEEP_WORKSPACE": ("keep_workspace_clone", bool),
}

API_KEY_ENV = "OPENHANDS_API_KEY"


def project_root() -> Path:
    """Directory that contains ``main.py`` (overridable for tests)."""
    return Path(os.environ.get("PY2CARDPUTER_HOME", PROJECT_ROOT)).resolve()


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal ``.env`` parser used when python-dotenv is unavailable."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env_file(path: Path) -> dict[str, str]:
    """Load a ``.env`` file without overriding real environment variables."""
    if not path.is_file():
        return {}
    try:
        from dotenv import dotenv_values  # type: ignore

        raw = {k: v for k, v in dotenv_values(path).items() if v is not None}
    except Exception:
        raw = _parse_env_file(path)
    for key, value in raw.items():
        if key not in os.environ:
            os.environ[key] = value
    return raw


class EnvFile:
    """Read/write individual keys in a ``.env`` file while preserving the rest."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, str]:
        return _parse_env_file(self.path)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.read().get(key, default)

    def set(self, key: str, value: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.is_file() else []
        rendered = f"{key}={value}"
        replaced = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            name = stripped.removeprefix("export ").split("=", 1)[0].strip()
            if name == key:
                lines[index] = rendered
                replaced = True
                break
        if not replaced:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(rendered)
        self._write("\n".join(lines) + "\n")

    def unset(self, key: str) -> None:
        if not self.path.is_file():
            return
        lines = [
            line
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if not (
                line.strip()
                and not line.strip().startswith("#")
                and line.strip().removeprefix("export ").split("=", 1)[0].strip() == key
            )
        ]
        self._write("\n".join(lines) + ("\n" if lines else ""))

    def _write(self, content: str) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=".env-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            try:
                os.chmod(tmp_name, 0o600)
            except OSError:
                pass
            os.replace(tmp_name, self.path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise


@dataclass
class Config:
    """Runtime configuration for Py2Cardputer."""

    openhands_api_url: str = DEFAULT_API_URL
    openhands_api_key: str = field(default="", repr=False)
    openhands_llm_model: str = ""
    github_repository: str = DEFAULT_REPOSITORY
    github_branch_prefix: str = DEFAULT_BRANCH_PREFIX
    arduino_cli_path: str = "arduino-cli"
    arduino_fqbn: str = DEFAULT_FQBN
    build_dir: str = "builds"
    log_dir: str = "logs"
    workspace_dir: str = "workspace"
    poll_interval_seconds: float = 5.0
    startup_timeout_seconds: float = 900.0
    execution_timeout_seconds: float = 5400.0
    request_timeout_seconds: float = 60.0
    compile_timeout_seconds: float = 900.0
    keep_workspace_clone: bool = True
    extra_compile_args: list[str] = field(default_factory=list)
    board_profiles: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BOARD_PROFILES))
    root: Path = field(default_factory=project_root, repr=False, compare=False)

    # ------------------------------------------------------------------ load
    @classmethod
    def load(
        cls,
        root: Path | str | None = None,
        *,
        env: Mapping[str, str] | None = None,
        load_dotenv: bool = True,
    ) -> "Config":
        """Load defaults, ``config.json`` and environment overrides."""
        base = Path(root).resolve() if root is not None else project_root()
        env_source: Mapping[str, str] = env if env is not None else os.environ

        config = cls(root=base)
        config_path = base / CONFIG_FILE_NAME
        if config_path.is_file():
            try:
                raw = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigError(f"config.json could not be read: {exc}") from exc
            if not isinstance(raw, dict):
                raise ConfigError("config.json must contain a JSON object")
            config.apply_mapping(raw)

        if load_dotenv and env is None:
            load_env_file(base / ENV_FILE_NAME)

        config.apply_env(env_source)
        config.openhands_api_key = str(env_source.get(API_KEY_ENV, config.openhands_api_key) or "").strip()
        register_secret(config.openhands_api_key)
        return config

    def apply_mapping(self, raw: Mapping[str, Any]) -> None:
        known = {f.name for f in fields(self)} - {"root"}
        for key, value in raw.items():
            if key == "openhands_api_key":
                # Secrets are never read from config.json.
                continue
            if key not in known or value is None:
                continue
            current = getattr(self, key)
            try:
                if isinstance(current, bool):
                    setattr(self, key, parse_bool(value))
                elif isinstance(current, float):
                    setattr(self, key, float(value))
                elif isinstance(current, list):
                    setattr(self, key, [str(item) for item in value] if isinstance(value, list) else current)
                elif isinstance(current, dict):
                    setattr(self, key, {str(k): str(v) for k, v in dict(value).items()})
                else:
                    setattr(self, key, str(value))
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"Invalid value for {key!r}: {value!r}") from exc

    def apply_env(self, env: Mapping[str, str]) -> None:
        for env_name, (attribute, kind) in ENV_MAP.items():
            if env_name not in env:
                continue
            raw = env[env_name]
            try:
                if kind is bool:
                    setattr(self, attribute, parse_bool(raw))
                elif kind is float:
                    setattr(self, attribute, float(raw))
                else:
                    setattr(self, attribute, str(raw))
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"Invalid value for {env_name}: {raw!r}") from exc

    # ----------------------------------------------------------------- paths
    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (self.root / path)

    @property
    def build_path(self) -> Path:
        return self.resolve_path(self.build_dir)

    @property
    def log_path(self) -> Path:
        return self.resolve_path(self.log_dir)

    @property
    def workspace_path(self) -> Path:
        return self.resolve_path(self.workspace_dir)

    @property
    def env_path(self) -> Path:
        return self.root / ENV_FILE_NAME

    def ensure_directories(self) -> None:
        for path in (self.build_path, self.log_path, self.workspace_path):
            path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- validation
    def validate(self) -> list[str]:
        """Return a list of human-readable configuration problems."""
        problems: list[str] = []
        if not self.openhands_api_url.startswith(("http://", "https://")):
            problems.append("OpenHands API URL must start with http:// or https://")
        if not self.github_repository or not REPOSITORY_PATTERN.match(self.github_repository):
            problems.append("GitHub repository must look like 'owner/repo'")
        if not self.github_branch_prefix.strip("/ "):
            problems.append("Branch prefix must not be empty")
        if not self.arduino_fqbn.strip():
            problems.append("Arduino FQBN must not be empty")
        if not self.build_dir.strip():
            problems.append("Build directory must not be empty")
        if self.poll_interval_seconds <= 0:
            problems.append("Polling interval must be greater than zero")
        if self.startup_timeout_seconds <= 0 or self.execution_timeout_seconds <= 0:
            problems.append("Timeouts must be greater than zero")
        return problems

    def require_openhands_credentials(self) -> None:
        if not self.openhands_api_key:
            raise ConfigError(
                "OPENHANDS_API_KEY is not set. Add it to .env or configure it in Settings."
            )
        if not self.openhands_api_url:
            raise ConfigError("OpenHands API URL is not configured.")

    def require_repository(self) -> None:
        if not REPOSITORY_PATTERN.match(self.github_repository or ""):
            raise ConfigError(
                f"GitHub repository {self.github_repository!r} is invalid. Use 'owner/repo'."
            )

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        """Serializable settings with secrets removed."""
        data = asdict(self)
        data.pop("root", None)
        data.pop("openhands_api_key", None)
        return data

    def save(self, path: Path | str | None = None) -> Path:
        """Atomically write non-secret settings to ``config.json``."""
        target = Path(path) if path is not None else self.root / CONFIG_FILE_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".config-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
            os.replace(tmp_name, target)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return target

    def save_api_key(self, api_key: str) -> None:
        """Persist the API key to ``.env`` (never to config.json)."""
        api_key = api_key.strip()
        env_file = EnvFile(self.env_path)
        if api_key:
            env_file.set(API_KEY_ENV, api_key)
            self.openhands_api_key = api_key
            os.environ[API_KEY_ENV] = api_key
            register_secret(api_key)
        else:
            env_file.unset(API_KEY_ENV)
            self.openhands_api_key = ""
            os.environ.pop(API_KEY_ENV, None)

    def masked_api_key(self) -> str:
        key = self.openhands_api_key
        if not key:
            return "not configured"
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}…{key[-4:]}"
