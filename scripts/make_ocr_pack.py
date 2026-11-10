"""Build the optional OCR pack the Windows installer can download.

The Windows app is built twice: the ordinary build, and the "full" build with
PyTorch, EasyOCR and PaddleOCR-VL, which is several times the size. The
installer carries the ordinary build and offers the two engines as a
component. This script makes what that component downloads: every file of the
full build that the ordinary build lacks or has different, as one zip. Laid
over an installed ordinary build, it *is* the full build — which is what the
build workflow then proves by running the engines' self-test in the result.

Why a difference and not a folder of extra packages: PyInstaller keeps pure
Python modules inside the executable, so the full build's executable differs
too, and an ordinary executable beside a torch folder cannot import it.

    python scripts/make_ocr_pack.py --lean dist/lean --full dist/full --out pack.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile

#: GitHub refuses a release asset of 2 GiB or more.
MAX_ASSET_BYTES = 2 * 1024 ** 3


def file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_under(root: str) -> dict[str, str]:
    """Relative path (forward slashes) → absolute path, for every file."""
    found = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            absolute = os.path.join(folder, name)
            found[os.path.relpath(absolute, root).replace(os.sep, "/")] = absolute
    return found


def difference(lean_dir: str, full_dir: str) -> tuple[list[str], list[str]]:
    """(files the pack must carry, files only the ordinary build has).

    A file is carried when the ordinary build lacks it or holds other bytes.
    Size is compared first; only same-size files are hashed.
    """
    lean, full = files_under(lean_dir), files_under(full_dir)
    carry = []
    for relative, path in sorted(full.items()):
        other = lean.get(relative)
        if (other is None or os.path.getsize(other) != os.path.getsize(path)
                or file_hash(other) != file_hash(path)):
            carry.append(relative)
    return carry, sorted(set(lean) - set(full))


def write_pack(full_dir: str, files: list[str], out_path: str) -> dict:
    """Zip `files` of `full_dir` at their relative paths; returns its facts."""
    installed = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as pack:
        for relative in files:
            source = os.path.join(full_dir, *relative.split("/"))
            installed += os.path.getsize(source)
            pack.write(source, relative)
    return {
        "files": len(files),
        "installed_bytes": installed,
        "bytes": os.path.getsize(out_path),
        "sha256": file_hash(out_path),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lean", required=True, help="the ordinary build's folder (holds ToonStudio.exe)")
    parser.add_argument("--full", required=True, help="the full build's folder")
    parser.add_argument("--out", required=True, help="the pack to write (.zip)")
    args = parser.parse_args(argv)

    for folder in (args.lean, args.full):
        if not os.path.isfile(os.path.join(folder, "ToonStudio.exe")):
            print(f"error: no ToonStudio.exe in {folder}", file=sys.stderr)
            return 1
    carry, lean_only = difference(args.lean, args.full)
    if not carry:
        print("error: the two builds are the same; there is nothing to pack", file=sys.stderr)
        return 1
    facts = write_pack(args.full, carry, args.out)
    facts["lean_only"] = len(lean_only)
    if facts["bytes"] >= MAX_ASSET_BYTES:
        print(f"error: the pack is {facts['bytes'] / 1e6:.0f} MB, over GitHub's 2 GB asset limit",
              file=sys.stderr)
        return 1
    # Files only the ordinary build has stay where they are when the pack is
    # laid over it. Reported, because a module left behind could shadow one
    # the full build expects elsewhere; the self-test in the workflow decides.
    for relative in lean_only[:20]:
        print(f"only in the ordinary build: {relative}", file=sys.stderr)
    print(json.dumps(facts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
