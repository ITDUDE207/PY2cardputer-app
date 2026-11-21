from __future__ import annotations

from ai.conversion_prompt import (
    CONVERSION_INSTRUCTIONS,
    build_conversion_prompt,
    required_prompt_phrases,
)
from core.validation import SourceInspection


def test_prompt_contains_every_required_instruction() -> None:
    prompt = build_conversion_prompt(
        app_name="MyApp",
        source_filename="my_app.py",
        repository="owner/repo",
        branch="py2cardputer/20261121-150000-my-app",
    )
    for phrase in required_prompt_phrases():
        assert phrase in prompt, f"missing phrase: {phrase}"


def test_prompt_includes_repository_context() -> None:
    prompt = build_conversion_prompt(
        app_name="MyApp",
        source_filename="my_app.py",
        repository="owner/repo",
        branch="py2cardputer/20261121-150000-my-app",
        job_id="job-123",
        inspection=SourceInspection(imports=["m5stack", "time"], line_count=42),
    )
    assert "owner/repo" in prompt
    assert "py2cardputer/20261121-150000-my-app" in prompt
    assert "input/my_app.py" in prompt
    assert "firmware/MyApp/MyApp.ino" in prompt
    assert "job-123" in prompt
    assert "m5stack, time" in prompt
    assert "42 lines" in prompt


def test_prompt_forbids_merging_and_claims() -> None:
    assert "Never merge into main." in CONVERSION_INSTRUCTIONS
    assert "Never delete files or branches." in CONVERSION_INSTRUCTIONS
    assert "Do not claim the generated firmware has been compiled or tested on hardware." in (
        CONVERSION_INSTRUCTIONS
    )
    assert "Avoid placeholder implementations." in CONVERSION_INSTRUCTIONS


def test_prompt_requires_report_sections() -> None:
    for section in (
        "Successfully converted functionality.",
        "Replaced Python APIs.",
        "Unsupported features.",
        "Required libraries.",
        "Hardware assumptions.",
        "Any remaining manual work.",
    ):
        assert section in CONVERSION_INSTRUCTIONS
