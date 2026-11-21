from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.errors import ValidationError
from github.branches import build_branch_name, unique_branch_name, validate_branch_name

FIXED = datetime(2026, 11, 21, 15, 0, 0, tzinfo=timezone.utc)


def test_branch_name_format() -> None:
    name = build_branch_name("myapp.py", now=FIXED)
    assert name == "py2cardputer/20261121-150000-myapp"


def test_branch_name_uses_original_stem_and_slugifies() -> None:
    name = build_branch_name("My Cool App!.py", now=FIXED)
    assert name == "py2cardputer/20261121-150000-my-cool-app"


def test_branch_name_custom_prefix_and_suffix() -> None:
    name = build_branch_name("app.py", prefix="py2cardputer/jobs", now=FIXED, suffix="2")
    assert name == "py2cardputer/jobs/20261121-150000-app-2"


def test_branch_name_length_limit() -> None:
    name = build_branch_name("a" * 200 + ".py", now=FIXED)
    assert len(name) <= 120
    validate_branch_name(name)


def test_branch_name_without_extension() -> None:
    assert build_branch_name("firmware", now=FIXED).endswith("-firmware")


@pytest.mark.parametrize(
    "name",
    [
        "py2cardputer/20261121-150000-myapp",
        "py2cardputer/20261121-150000-my_app.v2",
        "user/feature-1",
    ],
)
def test_validate_valid_names(name: str) -> None:
    assert validate_branch_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "no-slash",
        "py2cardputer/bad branch",
        "py2cardputer/..",
        "py2cardputer/name.lock",
        "-leading/slash",
        "py2cardputer/with~tilde",
        "py2cardputer/with:colon",
        "py2cardputer//double",
        "x" * 130 + "/y",
    ],
)
def test_validate_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_branch_name(name)


def test_unique_branch_name_returns_candidate_when_free() -> None:
    candidate = "py2cardputer/20261121-150000-app"
    assert unique_branch_name(candidate, lambda name: False) == candidate


def test_unique_branch_name_appends_counter() -> None:
    existing = {"py2cardputer/20261121-150000-app", "py2cardputer/20261121-150000-app-2"}
    result = unique_branch_name(
        "py2cardputer/20261121-150000-app", lambda name: name in existing
    )
    assert result == "py2cardputer/20261121-150000-app-3"


def test_unique_branch_name_exhaustion() -> None:
    with pytest.raises(ValidationError):
        unique_branch_name("py2cardputer/x", lambda name: True, max_attempts=3)
