"""The conversion task sent to OpenHands.

The instruction block is part of the product contract. Keep it in sync with
README.md and with tests/test_conversion_prompt.py.
"""

from __future__ import annotations

from core.validation import SourceInspection

PROMPT_VERSION = "1.0"

CONVERSION_INSTRUCTIONS = """You are Py2Cardputer's firmware conversion agent.

Convert the supplied UIFlow 2.0 MicroPython application into a complete Arduino C++ application for the M5Stack Cardputer ADV.

Requirements:

- Analyse the entire Python source.
- Identify imported modules and hardware dependencies.
- Preserve original functionality wherever possible.
- Replace MicroPython-specific APIs with Arduino equivalents.
- Use the official M5Cardputer library.
- Use M5Unified and M5GFX where appropriate.
- Support the Cardputer ADV keyboard and display.
- Properly implement callbacks, UI elements, input handling and animations.
- Declare all required variables and functions.
- Avoid placeholder implementations.
- Do not invent hardware APIs.
- Document unsupported functionality.
- Ensure generated code is complete and properly structured.

Output structure:

`firmware/AppName/AppName.ino`

Additional `.h` and `.cpp` files may be included when necessary.

Also create:

`firmware/AppName/README.md`

`firmware/AppName/CONVERSION_REPORT.md`

The conversion report must explain:

- Successfully converted functionality.
- Replaced Python APIs.
- Unsupported features.
- Required libraries.
- Hardware assumptions.
- Any remaining manual work.

Commit the generated files to the current GitHub branch.

Never merge into main.

Never delete files or branches.

Do not claim the generated firmware has been compiled or tested on hardware."""


def build_conversion_prompt(
    *,
    app_name: str,
    source_filename: str,
    repository: str,
    branch: str,
    job_id: str | None = None,
    inspection: SourceInspection | None = None,
    source_relative: str | None = None,
    input_files: list[str] | None = None,
) -> str:
    """Compose the full prompt, including repository context for the agent."""
    relative = source_relative or source_filename
    input_path = f"input/{relative}"
    lines = [
        CONVERSION_INSTRUCTIONS,
        "",
        "---",
        "",
        "Conversion context:",
        "",
        f"- GitHub repository: {repository}",
        f"- Working branch: {branch}",
        f"- Input Python file: {input_path}",
        f"- Required sketch folder: firmware/{app_name}/",
        f"- Required sketch file: firmware/{app_name}/{app_name}.ino",
    ]
    if input_files:
        shown = input_files[:40]
        lines.append(f"- Input bundle: {len(input_files)} file(s) under `input/`")
        for name in shown:
            lines.append(f"  - `input/{name}`")
        if len(input_files) > len(shown):
            lines.append(f"  - …and {len(input_files) - len(shown)} more file(s)")
    if job_id:
        lines.append(f"- Py2Cardputer job id: {job_id}")
    if inspection and inspection.imports:
        lines.append("- Imported modules detected: " + ", ".join(inspection.imports))
    if inspection and inspection.line_count:
        lines.append(f"- Source length: {inspection.line_count} lines")

    lines += [
        "",
        "Working rules:",
        "",
        f"1. Read the complete Python file at `{input_path}` in this repository before writing code."
        + (
            " Read every Python file in the input bundle, not only the primary file."
            if input_files and len(input_files) > 1
            else ""
        ),
        f"2. Create the sketch at `firmware/{app_name}/{app_name}.ino` and keep the folder name "
        "identical to the .ino file name.",
        f"3. Write `firmware/{app_name}/README.md` and "
        f"`firmware/{app_name}/CONVERSION_REPORT.md` as described above.",
        f"4. Commit all generated files to the current branch `{branch}` and push that branch. "
        "Do not open, merge or target a pull request against main.",
        "5. Do not modify or delete the original files in `input/`.",
        "6. Do not compile the firmware, do not flash hardware, and do not state that it was "
        "compiled or tested. Compilation happens on the user's machine after this task.",
        "7. If a feature cannot be reproduced with the available Arduino APIs, keep the sketch "
        "complete and document the gap in CONVERSION_REPORT.md instead of leaving stubs.",
        "8. If the input bundle contains images, fonts, JSON or other assets, copy the required "
        f"files into `firmware/{app_name}/data/` and update the sketch to use those paths. "
        "Document any asset that cannot be used.",
        "",
        "Finish by reporting which files you created and the branch you pushed to.",
    ]
    return "\n".join(lines)


def required_prompt_phrases() -> list[str]:
    """Phrases the prompt must contain (used by tests and documentation)."""
    return [
        "You are Py2Cardputer's firmware conversion agent.",
        "Use the official M5Cardputer library.",
        "Use M5Unified and M5GFX where appropriate.",
        "Support the Cardputer ADV keyboard and display.",
        "Avoid placeholder implementations.",
        "Do not invent hardware APIs.",
        "firmware/AppName/AppName.ino",
        "CONVERSION_REPORT.md",
        "Commit the generated files to the current GitHub branch.",
        "Never merge into main.",
        "Never delete files or branches.",
        "Do not claim the generated firmware has been compiled or tested on hardware.",
    ]
