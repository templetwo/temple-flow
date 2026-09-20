"""Verify this offline handoff's manifest and preserved originals. No network."""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    manifest_file = ROOT / "MANIFEST.json"
    if not manifest_file.is_file():
        print("FAIL: MANIFEST.json is missing", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_file.read_text())
    failures: list[str] = []
    paths: set[str] = set()
    for row in manifest["files"]:
        rel = Path(row["path"])
        if rel.is_absolute() or ".." in rel.parts or row["path"] in paths:
            failures.append(f"Unsafe/duplicate path: {rel}")
            continue
        paths.add(row["path"])
        path = ROOT / rel
        if path.is_symlink() or not path.is_file():
            failures.append(f"Missing/non-regular file: {rel}")
            continue
        data = path.read_bytes()
        if len(data) != row["bytes"] or sha256(data) != row["sha256"]:
            failures.append(f"Content mismatch: {rel}")
    disk_paths = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.name != "MANIFEST.json"}
    for unexpected in sorted(disk_paths - paths):
        failures.append(f"Unlisted file: {unexpected}")
    original = ROOT / "legacy" / "Temple_Flow_Kraken_CV_Build_Packet_v1.zip"
    if not original.is_file() or sha256(original.read_bytes()) != manifest["legacy_original_zip_sha256"]:
        failures.append("Original ZIP content differs")
    else:
        with zipfile.ZipFile(original) as archive:
            if archive.testzip() is not None:
                failures.append("Original ZIP CRC failure")
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                rel = Path(name)
                if rel.is_absolute() or ".." in rel.parts:
                    failures.append("Unsafe original archive member")
                    continue
                copy = ROOT / "legacy" / "kraken_v1" / rel
                if not copy.is_file() or copy.read_bytes() != archive.read(name):
                    failures.append(f"Original member changed: {name}")
    if failures:
        print("\n".join("FAIL: " + issue for issue in failures), file=sys.stderr)
        return 1
    print(f"PASS: {len(paths)} manifested files verified; original Kraken ZIP and members unchanged.")
    print("Content integrity only. No broker, strategy or live-trading verification is implied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
