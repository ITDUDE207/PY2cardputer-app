from __future__ import annotations

from pathlib import Path

from compiler.validator import validate_sketch_tree

VALID_INO = """\
#include <M5Cardputer.h>
#include <M5Unified.h>

void setup() {
    auto cfg = M5.config();
    M5Cardputer.begin(cfg);
}

void loop() {
    M5Cardputer.update();
}
"""


def make_sketch(root: Path, name: str = "MyApp", ino: str = VALID_INO, companions: bool = True) -> Path:
    sketch = root / "firmware" / name
    sketch.mkdir(parents=True)
    (sketch / f"{name}.ino").write_text(ino, encoding="utf-8")
    if companions:
        (sketch / "README.md").write_text("# App\n", encoding="utf-8")
        (sketch / "CONVERSION_REPORT.md").write_text("# Report\n", encoding="utf-8")
    return sketch


def test_valid_sketch(tmp_path: Path) -> None:
    make_sketch(tmp_path)
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is True
    assert result.sketch_name == "MyApp"
    assert result.ino_path == tmp_path / "firmware" / "MyApp" / "MyApp.ino"
    assert result.errors == []
    assert result.warnings == []


def test_missing_firmware_dir(tmp_path: Path) -> None:
    result = validate_sketch_tree(tmp_path / "nope")
    assert result.valid is False
    assert "does not exist" in result.errors[0]


def test_no_ino(tmp_path: Path) -> None:
    (tmp_path / "firmware" / "MyApp").mkdir(parents=True)
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is False
    assert "No Arduino sketch" in result.errors[0]


def test_folder_name_mismatch(tmp_path: Path) -> None:
    sketch = tmp_path / "firmware" / "WrongName"
    sketch.mkdir(parents=True)
    (sketch / "MyApp.ino").write_text(VALID_INO, encoding="utf-8")
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is False
    assert any("must match" in error for error in result.errors)


def test_missing_setup_and_loop(tmp_path: Path) -> None:
    make_sketch(tmp_path, ino="#include <M5Cardputer.h>\nint x = 1;\n")
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is False
    assert any("setup()" in error for error in result.errors)
    assert any("loop()" in error for error in result.errors)


def test_placeholder_warning(tmp_path: Path) -> None:
    make_sketch(tmp_path, ino=VALID_INO + "\n// TODO implement animation\n")
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is True
    assert any("placeholder" in warning.lower() for warning in result.warnings)


def test_missing_m5_include_warning(tmp_path: Path) -> None:
    make_sketch(tmp_path, ino="void setup() {}\nvoid loop() {}\n")
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is True
    assert any("M5Cardputer" in warning for warning in result.warnings)
    assert any("#include" in warning for warning in result.warnings)


def test_missing_companion_docs_warning(tmp_path: Path) -> None:
    make_sketch(tmp_path, companions=False)
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is True
    assert any("README.md" in warning for warning in result.warnings)
    assert any("CONVERSION_REPORT.md" in warning for warning in result.warnings)


def test_nested_sketch_warning(tmp_path: Path) -> None:
    nested = tmp_path / "firmware" / "group" / "MyApp"
    nested.mkdir(parents=True)
    (nested / "MyApp.ino").write_text(VALID_INO, encoding="utf-8")
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is True
    assert any("nested" in warning.lower() for warning in result.warnings)


def test_additional_files_reported(tmp_path: Path) -> None:
    sketch = make_sketch(tmp_path)
    (sketch / "ui.cpp").write_text("// helper\n", encoding="utf-8")
    (sketch / "ui.h").write_text("// header\n", encoding="utf-8")
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is True
    assert "ui.cpp" in result.additional_files
    assert "ui.h" in result.additional_files


def test_empty_ino(tmp_path: Path) -> None:
    make_sketch(tmp_path, ino="   \n")
    result = validate_sketch_tree(tmp_path / "firmware")
    assert result.valid is False
    assert any("empty" in error.lower() for error in result.errors)


def test_summary_text(tmp_path: Path) -> None:
    make_sketch(tmp_path)
    result = validate_sketch_tree(tmp_path / "firmware")
    assert "MyApp" in result.summary()
