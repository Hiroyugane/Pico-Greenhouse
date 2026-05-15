"""Build an SD-update payload from the current working tree.

Walks `main.py`, `config.py`, and `lib/*.py` (excluding vendored drivers),
computes SHA-256 of each file, writes `manifest.json` to OUT_DIR alongside
the files in the expected layout, then optionally mirrors the whole tree
into a destination folder on the SD card (e.g. `G:/update`).

Usage:
    python tools/build_update_payload.py
    python tools/build_update_payload.py --out build/update_payload
    python tools/build_update_payload.py --version 2026-05-15.2
    python tools/build_update_payload.py --copy-to G:/update
    python tools/build_update_payload.py --copy-to G:/update --no-confirm

The payload layout matches what `lib/updater.py` expects:

    <OUT_DIR>/manifest.json
    <OUT_DIR>/main.py
    <OUT_DIR>/config.py
    <OUT_DIR>/lib/<file>.py

The manifest format:

    {
        "version": "YYYY-MM-DD.N",
        "created_at": "YYYY-MM-DDTHH:MM:SSZ",
        "files": [
            {"path": "main.py", "sha256": "<hex>", "bytes": <int>},
            ...
        ]
    }

Vendored drivers (lib/picozero*, lib/sdcard*, lib/ds3231.py, lib/ds2321_gen.py,
lib/ssd1306*) are excluded by default — they ship with the firmware image and
should not be churned by an update.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Files included from the project root.
ROOT_FILES = ("main.py", "config.py")

# Vendored / driver files under lib/ that must NOT be shipped via update payload.
LIB_EXCLUDES = {
    "ds3231.py",
    "ds2321_gen.py",
    "sdcard.py",
    "ssd1306.py",
}
LIB_EXCLUDE_PREFIXES = ("picozero", "sdcard-", "ssd1306-")

# Read in 64 KiB chunks — fine on host, irrelevant on Pico (this script is host-only).
_HASH_CHUNK = 64 * 1024


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _should_include_lib(name: str) -> bool:
    if not name.endswith(".py"):
        return False
    if name == "__init__.py":
        return False
    if name in LIB_EXCLUDES:
        return False
    for prefix in LIB_EXCLUDE_PREFIXES:
        if name.startswith(prefix):
            return False
    return True


def _collect_sources() -> list[tuple[str, Path]]:
    """Return [(relative_path, absolute_path), ...] for everything to ship."""
    sources: list[tuple[str, Path]] = []
    for rel in ROOT_FILES:
        abs_path = PROJECT_ROOT / rel
        if not abs_path.is_file():
            raise FileNotFoundError(f"missing required source: {rel}")
        sources.append((rel, abs_path))
    lib_dir = PROJECT_ROOT / "lib"
    if not lib_dir.is_dir():
        raise FileNotFoundError("missing lib/ directory at project root")
    for entry in sorted(lib_dir.iterdir()):
        if not entry.is_file():
            continue
        if _should_include_lib(entry.name):
            sources.append((f"lib/{entry.name}", entry))
    return sources


def _auto_version(out_dir: Path) -> str:
    """Pick a version string YYYY-MM-DD.N where N increments per-day if needed."""
    today = _dt.date.today().isoformat()
    n = 1
    # If the out dir already has a manifest from today, bump N past it.
    manifest_path = out_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text())
            prev = str(existing.get("version", ""))
            m = re.match(rf"^{re.escape(today)}\.(\d+)$", prev)
            if m:
                n = int(m.group(1)) + 1
        except Exception:
            pass
    return f"{today}.{n}"


def _clean_out_dir(out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def _copy_payload(sources: list[tuple[str, Path]], out_dir: Path) -> list[dict]:
    files_meta: list[dict] = []
    for rel, abs_path in sources:
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(abs_path, target)
        files_meta.append(
            {
                "path": rel.replace("\\", "/"),
                "sha256": _sha256_of(target),
                "bytes": target.stat().st_size,
            }
        )
    return files_meta


def _write_manifest(out_dir: Path, version: str, files_meta: list[dict]) -> Path:
    manifest = {
        "version": version,
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files_meta,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    return manifest_path


def _copy_to_sd(out_dir: Path, dest: Path, *, confirm: bool) -> None:
    dest = dest.resolve() if dest.exists() else dest
    parent = dest.parent
    if not parent.exists():
        raise FileNotFoundError(
            f"destination parent does not exist: {parent} — is the SD card mounted?"
        )
    if dest.exists():
        if confirm:
            answer = input(f"Replace existing {dest}? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                print("aborted; existing destination kept")
                return
        shutil.rmtree(dest)
    shutil.copytree(out_dir, dest)
    print(f"deployed payload to {dest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "build" / "update_payload"),
        help="Output directory for the payload (default: build/update_payload)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Version string for the manifest (default: YYYY-MM-DD.N auto-bumped)",
    )
    parser.add_argument(
        "--copy-to",
        default=None,
        help="After building, mirror payload into this directory (e.g. G:/update).",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip interactive confirmation when --copy-to target exists",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out).resolve()
    sources = _collect_sources()
    _clean_out_dir(out_dir)
    files_meta = _copy_payload(sources, out_dir)
    version = args.version or _auto_version(out_dir.parent)
    manifest_path = _write_manifest(out_dir, version, files_meta)

    total_bytes = sum(entry["bytes"] for entry in files_meta)
    print(f"version    : {version}")
    print(f"files      : {len(files_meta)}")
    print(f"total size : {total_bytes:,} bytes")
    print(f"output     : {out_dir}")
    print(f"manifest   : {manifest_path}")

    if args.copy_to:
        dest = Path(args.copy_to)
        _copy_to_sd(out_dir, dest, confirm=not args.no_confirm)

    return 0


if __name__ == "__main__":
    sys.exit(main())
