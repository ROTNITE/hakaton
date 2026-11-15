"""Safely test integrity checks on a COPY of a finished MetaRescue native archive.

Usage from the repository root (Windows PowerShell):
  python -B -X utf8 tools/u07_check_archive.py --run "D:\\MetaRescue-output\\missions\\standalone-03-disk"
Or pass a native archive directory directly:
  python -B -X utf8 tools/u07_check_archive.py --archive "D:\\MetaRescue-output\\core-runs\\EPISODE_ID"

This is a READ/CORRUPTION check. It does NOT simulate disk-full during writing,
and DOES NOT close U07 by itself.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

# Put this file in the repository's tools/ directory.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.native_archive import verify_archive

FILES = (
    "manifest.json", "public.records", "public.index",
    "truth.records", "truth.index", "replay.records", "replay.index",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def resolve_archive(args) -> Path:
    if args.archive:
        return args.archive.resolve()
    manifest = json.loads((args.run / "manifest.json").read_text(encoding="utf-8-sig"))
    location = manifest.get("native_archive")
    if not isinstance(location, str) or not location:
        raise ValueError("Mission manifest has no native_archive. Supply --archive explicitly.")
    return Path(location).resolve()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", type=Path, help="completed mission directory with manifest.json")
    g.add_argument("--archive", type=Path, help="native archive directory with manifest.json")
    p.add_argument("--output-root", type=Path, default=Path(r"D:\MetaRescue-output\manual-journal-check"))
    args = p.parse_args()

    src = resolve_archive(args)
    if not src.is_dir():
        raise FileNotFoundError("Native archive does not exist: " + str(src))
    for name in FILES:
        if not (src / name).is_file():
            raise FileNotFoundError("Missing required file: " + str(src / name))

    print("[1/5] Verifying original archive (READ ONLY):", src, flush=True)
    original = verify_archive(src)
    if not original.get("passed"):
        raise RuntimeError("Original archive did not pass verification")
    initial_hashes = {name: sha256(src / name) for name in FILES}
    print("PASS: original archive is complete and valid", flush=True)

    args.output_root.mkdir(parents=True, exist_ok=True)
    stamped = datetime.now().strftime("u07-%Y%m%d-%H%M%S-%f")
    out = args.output_root / stamped
    out.mkdir(exist_ok=False)
    copydir = out / "copied-archive"
    copydir.mkdir()
    report = {"test": "U07 read-side corruption detection only", "source": str(src),
              "copy": str(copydir), "source_verification_passed": True,
              "copy_verification_passed": False,
              "corrupted_copy_rejected": False,
              "source_unchanged": None,
              "disk_full_write_tested": False}

    try:
        print("[2/5] Copying the seven archive files into:", copydir, flush=True)
        for name in FILES:
            shutil.copy2(src / name, copydir / name)
        if {name: sha256(copydir / name) for name in FILES} != initial_hashes:
            raise RuntimeError("Copy is not byte-identical to original")

        print("[3/5] Verifying unmodified copy", flush=True)
        verify_archive(copydir)
        report["copy_verification_passed"] = True
        print("PASS: unmodified copy is valid", flush=True)

        print("[4/5] Modifying ONE byte ONLY in copied public.records", flush=True)
        datafile = copydir / "public.records"
        if datafile.stat().st_size == 0:
            raise RuntimeError("public.records is empty; choose a nonempty finished archive")
        with datafile.open("r+b") as stream:
            byte = stream.read(1)
            stream.seek(0)
            stream.write(bytes([byte[0] ^ 0x01]))
        try:
            verify_archive(copydir)
        except (ValueError, OSError, KeyError, UnicodeError) as exc:
            report["corrupted_copy_rejected"] = True
            report["corruption_error"] = type(exc).__name__ + ": " + str(exc)
            print("PASS: corruption was detected:", report["corruption_error"], flush=True)
        else:
            raise RuntimeError("FAIL: corrupted copy was accepted by verifier")

        print("[5/5] Rechecking original files' SHA-256", flush=True)
        report["source_unchanged"] = ({name: sha256(src / name) for name in FILES} == initial_hashes)
        if not report["source_unchanged"]:
            raise RuntimeError("Original archive changed during the test; investigate concurrent writes")
        print("PASS: source was not modified", flush=True)
    finally:
        (out / "u07-check-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("REPORT:", out / "u07-check-result.json", flush=True)
    print("RESULT: READ-SIDE TEST PASSED. U07 WRITE-FAILURE TEST IS STILL OPEN.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR:", type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise SystemExit(1)
