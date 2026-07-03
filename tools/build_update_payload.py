"""Build an SD-update payload from the current working tree.

Walks `main.py`, `config.py`, and `lib/*.py` (excluding vendored drivers),
computes SHA-256 of each file, writes `manifest.json` to OUT_DIR alongside
the files in the expected layout, then optionally mirrors the whole tree
into a destination folder on the SD card (e.g. `G:/ota/pending`).

Usage:
    python tools/build_update_payload.py
    python tools/build_update_payload.py --out build/update_payload
    python tools/build_update_payload.py --version 20260515T143052Z-c8a3a11
    python tools/build_update_payload.py --copy-to G:/ota/pending
    python tools/build_update_payload.py --copy-to G:/ota/pending --no-confirm
    python tools/build_update_payload.py --compiled --copy-to G:/ota/pending --no-confirm

The payload layout matches what `lib/updater.py` expects:

    <OUT_DIR>/manifest.json
    <OUT_DIR>/main.py
    <OUT_DIR>/config.py            (or config.mpy with --compiled)
    <OUT_DIR>/lib/<file>.py        (or <file>.mpy with --compiled)

The manifest format:

    {
        "version": "YYYYMMDDTHHMMSSZ-<shorthash>",
        "created_at": "YYYY-MM-DDTHH:MM:SSZ",
        "files": [
            {"path": "main.py", "sha256": "<hex>", "bytes": <int>},
            ...
        ]
    }

Vendored drivers (lib/sdcard*, lib/ds3231.py, lib/ssd1306*) are excluded by
default — they ship with the firmware image and should not be churned by an
update.

With `--compiled`, sources are read from the `build/` tree produced by the
`build-mpy` VS Code task: `build/main.py` (raw), `build/config.mpy`, and
`build/lib/*.mpy`. The script does not invoke `mpy-cross` itself; run
`build-mpy` first.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Files included from the project root.
ROOT_FILES = ("main.py", "config.py")

# Vendored / driver files under lib/ that must NOT be shipped via update payload.
LIB_EXCLUDES = {
    "ds3231.py",
    "sdcard.py",
    "ssd1306.py",
}
LIB_EXCLUDE_PREFIXES = ("sdcard-", "ssd1306-")

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


def _collect_sources_compiled(build_dir: Path) -> list[tuple[str, Path]]:
    """Return [(relative_path, absolute_path), ...] from a build-mpy tree."""
    if not build_dir.is_dir():
        raise FileNotFoundError(f"missing build directory: {build_dir} — run the build-mpy task first")
    sources: list[tuple[str, Path]] = []

    main_src = build_dir / "main.py"
    if not main_src.is_file():
        raise FileNotFoundError(f"missing {main_src} — run build-mpy first")
    sources.append(("main.py", main_src))

    config_src = build_dir / "config.mpy"
    if not config_src.is_file():
        raise FileNotFoundError(f"missing {config_src} — run build-mpy first")
    sources.append(("config.mpy", config_src))

    lib_dir = build_dir / "lib"
    if not lib_dir.is_dir():
        raise FileNotFoundError(f"missing {lib_dir} — run build-mpy first")
    lib_files = sorted(f for f in lib_dir.iterdir() if f.is_file() and f.suffix == ".mpy")
    if not lib_files:
        raise FileNotFoundError(f"no compiled .mpy files in {lib_dir} — run build-mpy first")
    for entry in lib_files:
        sources.append((f"lib/{entry.name}", entry))
    return sources


def _git_short_hash() -> str:
    """Return the short hash of HEAD, or 'nogit' if git/repo is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            short = result.stdout.strip()
            if short:
                return short
    except (OSError, subprocess.SubprocessError):
        pass
    return "nogit"


def _auto_version() -> str:
    """Version string: YYYYMMDDTHHMMSSZ-<shorthash> (UTC, FAT32-safe)."""
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{now}-{_git_short_hash()}"


def _short_hash_from_version(version: str) -> str:
    """Extract the trailing git short hash from a version string.

    Accepts `YYYYMMDDTHHMMSSZ-<shorthash>` or any string ending in `-<hash>`.
    Returns the whole string when no `-` is present (e.g. a custom --version).
    """
    return version.rsplit("-", 1)[-1] if "-" in version else version


def _write_build_info(target: Path, version: str, built_at_iso: str) -> Path:
    """Write a build_info.py module exposing VERSION and BUILD_TIME to `target`.

    VERSION is the short git hash (so the OLED can show `Ver:<hash>` in 11 chars);
    BUILD_TIME is the full ISO timestamp for diagnostics.
    """
    short_hash = _short_hash_from_version(version)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '"""Generated by tools/build_update_payload.py. Do not edit by hand."""\n'
        f'VERSION = "{short_hash}"\n'
        f'BUILD_TIME = "{built_at_iso}"\n'
    )
    return target


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
        anchor = Path(dest.anchor) if dest.anchor else parent
        if not anchor.exists():
            raise FileNotFoundError(f"SD card root not found at {anchor} — is the SD card mounted?")
        parent.mkdir(parents=True, exist_ok=True)
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
        help="Version string for the manifest (default: YYYYMMDDTHHMMSSZ-<shorthash>)",
    )
    parser.add_argument(
        "--copy-to",
        default=None,
        help="After building, mirror payload into this directory (e.g. G:/ota/pending).",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip interactive confirmation when --copy-to target exists",
    )
    parser.add_argument(
        "--compiled",
        action="store_true",
        help="Read pre-compiled artifacts from --build-dir (run build-mpy first)",
    )
    parser.add_argument(
        "--build-dir",
        default=str(PROJECT_ROOT / "build"),
        help="Directory containing build-mpy output (default: build/)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out).resolve()
    version = args.version or _auto_version()
    built_at_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Stamp the working tree so Thonny-direct flashes and raw-mode payload
    # collection both pick up the same VERSION / BUILD_TIME.
    _write_build_info(PROJECT_ROOT / "lib" / "build_info.py", version, built_at_iso)

    if args.compiled:
        sources = _collect_sources_compiled(Path(args.build_dir).resolve())
    else:
        sources = _collect_sources()
    _clean_out_dir(out_dir)
    files_meta = _copy_payload(sources, out_dir)

    # In --compiled mode the source collector only takes .mpy files; the raw
    # build_info.py needs to be dropped directly into the payload.
    if args.compiled:
        bi_target = out_dir / "lib" / "build_info.py"
        _write_build_info(bi_target, version, built_at_iso)
        files_meta.append(
            {
                "path": "lib/build_info.py",
                "sha256": _sha256_of(bi_target),
                "bytes": bi_target.stat().st_size,
            }
        )

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
