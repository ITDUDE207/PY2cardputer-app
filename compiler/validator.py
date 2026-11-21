"""Structural validation of generated Arduino sketches.

Validation happens before compiling so obvious AI output problems produce a
clear message instead of a wall of compiler errors.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.models import SketchValidation

PLACEHOLDER_PATTERN = re.compile(r"\b(TODO|FIXME|PLACEHOLDER|NotImplemented)\b", re.IGNORECASE)
M5_INCLUDE_PATTERN = re.compile(
    r"#\s*include\s*[<\"](M5Cardputer|M5Unified|M5GFX)\.h[>\"]"
)
SETUP_PATTERN = re.compile(r"\b(?:void|int)\s+setup\s*\(")
LOOP_PATTERN = re.compile(r"\b(?:void|int)\s+loop\s*\(")


def validate_sketch_tree(firmware_dir: Path | str) -> SketchValidation:
    """Validate ``firmware/<AppName>/<AppName>.ino`` and its companions."""
    root = Path(firmware_dir)
    result = SketchValidation(valid=False, firmware_dir=root)

    if not root.exists():
        result.errors.append(f"Firmware directory does not exist: {root}")
        return result
    if not root.is_dir():
        result.errors.append(f"Firmware path is not a directory: {root}")
        return result

    inos = sorted(path for path in root.rglob("*.ino") if path.is_file())
    if not inos:
        result.errors.append("No Arduino sketch (.ino) file was generated.")
        return result

    primary = _select_primary_sketch(inos)
    result.ino_path = primary
    result.sketch_dir = primary.parent
    result.sketch_name = primary.parent.name

    if primary.stem != primary.parent.name:
        result.errors.append(
            f"Sketch file '{primary.name}' must match its folder name "
            f"('{primary.parent.name}.ino' expected)."
        )

    try:
        relative = primary.relative_to(root)
    except ValueError:  # pragma: no cover - rglob guarantees containment
        relative = Path(primary.name)
    if len(relative.parts) > 2:
        result.warnings.append(
            f"Sketch is nested at '{relative}'. Arduino CLI expects the sketch folder "
            "to contain the .ino file directly."
        )

    try:
        source = primary.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.errors.append(f"Sketch file cannot be read: {exc}")
        return result

    if not source.strip():
        result.errors.append("Sketch file is empty.")
    if not SETUP_PATTERN.search(source):
        result.errors.append("Sketch does not define a setup() function.")
    if not LOOP_PATTERN.search(source):
        result.errors.append("Sketch does not define a loop() function.")
    if "#include" not in source:
        result.warnings.append("Sketch contains no #include directives.")
    if not M5_INCLUDE_PATTERN.search(source):
        result.warnings.append(
            "Sketch does not include M5Cardputer.h, M5Unified.h or M5GFX.h. "
            "Verify the conversion report for the hardware approach."
        )
    placeholders = sorted({match.upper() for match in PLACEHOLDER_PATTERN.findall(source)})
    if placeholders:
        result.warnings.append(
            "Sketch contains placeholder markers: " + ", ".join(placeholders)
        )

    for companion in ("README.md", "CONVERSION_REPORT.md"):
        if not (primary.parent / companion).is_file():
            result.warnings.append(f"{companion} is missing from the sketch folder.")

    result.additional_files = sorted(
        str(path.relative_to(primary.parent))
        for path in primary.parent.rglob("*")
        if path.is_file() and path != primary
    )
    result.valid = not result.errors
    return result


def _select_primary_sketch(inos: list[Path]) -> Path:
    """Prefer ``<Folder>/<Folder>.ino``; fall back to the shallowest .ino."""
    for path in inos:
        if path.stem == path.parent.name:
            return path
    return min(inos, key=lambda path: (len(path.parts), str(path)))
