"""The optional OCR pack: what the full Windows build has that the ordinary
one does not, laid over an installed ordinary build to make the full one."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_ocr_pack.py"
spec = importlib.util.spec_from_file_location("make_ocr_pack", SCRIPT)
make_ocr_pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_ocr_pack)


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


@pytest.fixture
def builds(tmp_path):
    lean = _tree(tmp_path / "lean", {
        "ToonStudio.exe": b"lean exe",
        "_internal/base_library.zip": b"same",
        "_internal/PySide6/Qt6Core.dll": b"qt",
        "_internal/samesize.bin": b"AAAA",
        "_internal/only_lean.txt": b"x",
    })
    full = _tree(tmp_path / "full", {
        "ToonStudio.exe": b"full exe, with more modules",
        "_internal/base_library.zip": b"same",
        "_internal/PySide6/Qt6Core.dll": b"qt",
        "_internal/samesize.bin": b"BBBB",
        "_internal/torch/lib/torch_cpu.dll": b"t" * 5000,
        "_internal/easyocr/__init__.py": b"",
    })
    return lean, full


def test_the_pack_carries_what_is_new_or_different_and_nothing_else(builds):
    lean, full = builds
    carry, lean_only = make_ocr_pack.difference(str(lean), str(full))
    assert carry == [
        "ToonStudio.exe",                        # the executable holds the pure-Python modules
        "_internal/easyocr/__init__.py",         # an empty file is still a file
        "_internal/samesize.bin",                # same size, other bytes
        "_internal/torch/lib/torch_cpu.dll",
    ]
    assert lean_only == ["_internal/only_lean.txt"]


def test_laid_over_the_ordinary_build_it_is_the_full_build(builds, tmp_path):
    lean, full = builds
    out = tmp_path / "pack.zip"
    assert make_ocr_pack.main(["--lean", str(lean), "--full", str(full), "--out", str(out)]) == 0
    with zipfile.ZipFile(out) as pack:
        assert all("\\" not in name for name in pack.namelist())      # tar and Inno read forward slashes
        pack.extractall(lean)
    for path in full.rglob("*"):
        if path.is_file():
            assert (lean / path.relative_to(full)).read_bytes() == path.read_bytes()


def test_it_reports_the_facts_the_installer_is_built_with(builds, tmp_path, capsys):
    lean, full = builds
    out = tmp_path / "pack.zip"
    make_ocr_pack.main(["--lean", str(lean), "--full", str(full), "--out", str(out)])
    facts = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert facts["files"] == 4 and facts["lean_only"] == 1
    assert facts["bytes"] == out.stat().st_size
    assert facts["sha256"] == make_ocr_pack.file_hash(str(out))
    assert facts["installed_bytes"] == len(b"full exe, with more modules") + 4 + 5000


def test_two_identical_builds_or_a_folder_without_the_app_are_refused(builds, tmp_path):
    lean, full = builds
    assert make_ocr_pack.main(["--lean", str(lean), "--full", str(lean), "--out", str(tmp_path / "p.zip")]) == 1
    assert make_ocr_pack.main(["--lean", str(tmp_path), "--full", str(full), "--out", str(tmp_path / "p.zip")]) == 1
