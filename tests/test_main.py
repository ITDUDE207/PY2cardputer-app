from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import Config
from main import EXIT_CONFIG, EXIT_OK, build_parser, main, run_cli, run_history


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.cli is False
    assert args.check is False
    assert args.file is None


def test_parser_cli_flags(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--cli", "--file", str(tmp_path / "app.py"), "--fqbn", "a:b:c"])
    assert args.cli is True
    assert args.file == tmp_path / "app.py"
    assert args.fqbn == "a:b:c"


def test_version_exits(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "Py2Cardputer" in capsys.readouterr().out


def test_cli_requires_file(tmp_path: Path, capsys) -> None:
    config = Config(root=tmp_path, build_dir="builds", log_dir="logs")
    result = run_cli(
        config,
        logging.getLogger("test.main"),
        SimpleNamespace(file=None, fqbn=None),
    )
    assert result == EXIT_CONFIG
    assert "--file" in capsys.readouterr().err


def test_cli_rejects_invalid_file(tmp_path: Path) -> None:
    config = Config(root=tmp_path, build_dir="builds", log_dir="logs")
    bad = tmp_path / "bad.txt"
    bad.write_text("x", encoding="utf-8")
    result = run_cli(
        config,
        logging.getLogger("test.main"),
        SimpleNamespace(file=bad, fqbn=None),
    )
    assert result == EXIT_CONFIG


def test_history_empty(tmp_path: Path, capsys) -> None:
    config = Config(root=tmp_path, build_dir="builds", log_dir="logs")
    result = run_history(config, logging.getLogger("test.main"))
    assert result == EXIT_OK
    assert "No builds" in capsys.readouterr().out
