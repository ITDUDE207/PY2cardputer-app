from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import Config, EnvFile, load_env_file
from core.errors import ConfigError


def load(tmp_path: Path, env: dict[str, str] | None = None) -> Config:
    return Config.load(tmp_path, env=env or {}, load_dotenv=False)


def test_defaults(tmp_path: Path) -> None:
    config = load(tmp_path)
    assert config.openhands_api_url == "https://app.all-hands.dev"
    assert config.github_repository == "ITDUDE207/Py2Cardputer-Workspace"
    assert config.arduino_fqbn == "m5stack:esp32:m5stack_cardputer"
    assert config.poll_interval_seconds == 5.0
    assert config.openhands_api_key == ""
    assert config.root == tmp_path


def test_config_json_and_env_precedence(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "poll_interval_seconds": 7,
                "github_repository": "someone/from-json",
                "arduino_fqbn": "vendor:arch:board",
            }
        ),
        encoding="utf-8",
    )
    config = load(
        tmp_path,
        env={
            "PY2CARDPUTER_POLL_INTERVAL": "9.5",
            "PY2CARDPUTER_GITHUB_REPOSITORY": "env/repo",
            "OPENHANDS_API_KEY": "env-key-value",
        },
    )
    assert config.poll_interval_seconds == 9.5
    assert config.github_repository == "env/repo"
    assert config.arduino_fqbn == "vendor:arch:board"
    assert config.openhands_api_key == "env-key-value"


def test_api_key_is_never_written_to_config(tmp_path: Path) -> None:
    config = load(tmp_path, env={"OPENHANDS_API_KEY": "super-secret-key"})
    config.save()
    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert "openhands_api_key" not in data
    assert "super-secret-key" not in json.dumps(data)


def test_secret_in_config_json_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"openhands_api_key": "leaked"}), encoding="utf-8"
    )
    config = load(tmp_path)
    assert config.openhands_api_key == ""


def test_invalid_json_raises(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(tmp_path)


def test_env_file_roundtrip(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\nFOO=bar\n\nOPENHANDS_API_KEY=old\n", encoding="utf-8")
    env = EnvFile(env_path)
    assert env.get("FOO") == "bar"
    env.set("OPENHANDS_API_KEY", "new-key")
    env.set("NEW_KEY", "value")
    text = env_path.read_text(encoding="utf-8")
    assert "# comment" in text
    assert "OPENHANDS_API_KEY=new-key" in text
    assert "NEW_KEY=value" in text
    env.unset("FOO")
    assert "FOO=" not in env_path.read_text(encoding="utf-8")


def test_load_env_file_does_not_override(monkeypatch, tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("PY2CARDPUTER_TEST_VALUE=from-file\n", encoding="utf-8")
    monkeypatch.setenv("PY2CARDPUTER_TEST_VALUE", "from-env")
    load_env_file(env_path)
    import os

    assert os.environ["PY2CARDPUTER_TEST_VALUE"] == "from-env"


def test_save_api_key_uses_env_file(tmp_path: Path) -> None:
    config = load(tmp_path)
    config.save_api_key("abc123456789")
    assert config.openhands_api_key == "abc123456789"
    assert "abc123456789" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert not (tmp_path / "config.json").exists()
    config.save_api_key("")
    assert config.openhands_api_key == ""
    assert "abc123456789" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_masked_api_key(tmp_path: Path) -> None:
    config = load(tmp_path, env={"OPENHANDS_API_KEY": "abcdefghijklmnop"})
    masked = config.masked_api_key()
    assert masked.startswith("abcd")
    assert masked.endswith("mnop")
    assert "efghijkl" not in masked


def test_validation_problems(tmp_path: Path) -> None:
    config = load(tmp_path)
    config.openhands_api_url = "ftp://nope"
    config.github_repository = "not-a-repo"
    config.poll_interval_seconds = 0
    problems = config.validate()
    assert len(problems) >= 3


def test_require_credentials(tmp_path: Path) -> None:
    config = load(tmp_path)
    with pytest.raises(ConfigError):
        config.require_openhands_credentials()


def test_resolve_relative_paths(tmp_path: Path) -> None:
    config = load(tmp_path)
    assert config.build_path == tmp_path / "builds"
    absolute = tmp_path / "elsewhere"
    config.build_dir = str(absolute)
    assert config.build_path == absolute
