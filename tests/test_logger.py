from __future__ import annotations

import io
import logging
from pathlib import Path

from core.logger import (
    REDACTED,
    RedactingFilter,
    add_job_log_file,
    clear_secrets,
    redact,
    register_secret,
)


def setup_function() -> None:
    clear_secrets()


def teardown_function() -> None:
    clear_secrets()


def test_redact_registered_secret() -> None:
    register_secret("super-secret-value")
    assert redact("token=super-secret-value") == f"token={REDACTED}"


def test_short_secrets_are_ignored() -> None:
    register_secret("abc")
    assert redact("abc") == "abc"


def test_redact_bearer_header() -> None:
    output = redact("Authorization: Bearer abcdef123456")
    assert "abcdef123456" not in output
    assert REDACTED in output


def test_redact_github_tokens() -> None:
    token = "ghp_" + "a" * 36
    assert token not in redact(f"token {token}")


def test_redacting_filter_on_record() -> None:
    logger = logging.getLogger("test.logger.filter")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    register_secret("filter-me-please")
    logger.info("value=%s", "filter-me-please")
    assert "filter-me-please" not in stream.getvalue()
    assert REDACTED in stream.getvalue()


def test_add_job_log_file_redacts(tmp_path: Path) -> None:
    logger = logging.getLogger("test.logger.file")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    log_path = tmp_path / "job.log"
    handler = add_job_log_file(logger, log_path)
    register_secret("file-secret-value")
    logger.info("using file-secret-value")
    handler.flush()
    handler.close()
    logger.removeHandler(handler)
    content = log_path.read_text(encoding="utf-8")
    assert "file-secret-value" not in content
    assert REDACTED in content


def test_redact_embedded_https_credentials() -> None:
    masked = redact("fatal: unable to access https://user:secret@github.com/owner/repo.git")
    assert "user:secret" not in masked
    assert "https://" in masked
