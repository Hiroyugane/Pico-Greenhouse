"""Generate the frozen ``fw_info.py`` module baked into a custom firmware build.

``fw_info`` is the one version record an OTA payload cannot forge: it is frozen
into the ``.uf2`` alongside the module set it describes, so a field unit always
reports the firmware it is actually running (plan section 4.2). It carries five
fields:

    FIRMWARE_VERSION = "pg-fw-2026.07-a1b2c3d"   # <product>-<yyyy.mm>-<repo shorthash>
    MPY_ABI          = 6                          # .mpy bytecode ABI this firmware imports
    MPY_SOURCE       = "upstream@v1.24.1@8f2c9d1" # fork @ pinned tag @ commit
    FROZEN_AT        = "2026-07-22T15:40:00Z"
    FROZEN_MODULES   = ("sdcard", "ds3231", ...)  # exactly what this image froze

``MPY_ABI`` is the load-bearing one: it is what the updater compares a compiled
payload's stamp against before applying it (plan section 6.3). It is read out of
the pinned MicroPython checkout's ``py/mpconfig.h`` rather than typed by hand,
because a hand-typed ABI that drifts from the tree is worse than no guard at
all — it would reject good payloads and pass bad ones.

``FROZEN_MODULES`` is load-bearing for a different reason: it is the *only*
authority the OTA prune sweep will accept before deleting a file from ``/lib``.
A leftover ``lib/event_logger.mpy`` shadows its frozen twin (imports resolve
lib-first) and silently negates the freeze, so the sweep must remove it — but
removing a module that has no frozen twin leaves the board unable to import it
at all. The manifest cannot answer that question honestly, because a payload
can be built from a repo commit newer than the flashed firmware. The image
answering for itself can. It therefore MUST describe this build exactly:
``--tier1-only`` and ``--freeze-only`` are mirrored here so the record never
claims a module the manifest did not actually freeze.

Usage:
    python tools/gen_fw_info.py --mpy-tree ../micropython --ref v1.24.1
    python tools/gen_fw_info.py --mpy-tree ../micropython --ref v1.24.1 \
        --out build/frozen/fw_info.py
    python tools/gen_fw_info.py --mpy-abi 6 --ref v1.24.1 --commit 8f2c9d1
    python tools/gen_fw_info.py --mpy-abi 6 --ref v1.24.1 --tier1-only

Normally invoked by ``tools/build_firmware.ps1``, not by hand. Host-only
tooling: never imported by device code.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.verify_frozen_uf2 import frozen_module_names  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "build" / "frozen" / "fw_info.py"
DEFAULT_SOURCE_NAME = "upstream"

# `#define MPY_VERSION (6)` — parenthesised in some releases, bare in others.
_MPY_VERSION_RE = re.compile(r"^\s*#define\s+MPY_VERSION\s+\(?\s*(\d+)\s*\)?", re.MULTILINE)

# Where that define lives has moved between releases: v1.28.0 keeps it in
# py/persistentcode.h, older trees in py/mpconfig.h. Search both rather than
# betting on one — a wrong ABI is worse than a failed build.
_ABI_HEADERS = ("py/persistentcode.h", "py/mpconfig.h")


class FwInfoError(Exception):
    """Raised when the firmware identity cannot be determined."""


def read_mpy_abi(mpy_tree: Path) -> int:
    """Read ``MPY_VERSION`` (the .mpy bytecode ABI) out of a MicroPython checkout.

    This is the same number ``mpy-cross`` writes into byte 1 of every ``.mpy``
    file it emits, and the same one a running firmware exposes as the low byte
    of ``sys.implementation._mpy``.
    """
    searched = []
    for relative in _ABI_HEADERS:
        header = mpy_tree / relative
        searched.append(str(header))
        if not header.is_file():
            continue
        match = _MPY_VERSION_RE.search(header.read_text(encoding="utf-8", errors="replace"))
        if match is not None:
            return int(match.group(1))
    if not any((mpy_tree / relative).is_file() for relative in _ABI_HEADERS):
        raise FwInfoError(f"not a MicroPython checkout: none of {', '.join(searched)} found")
    raise FwInfoError(f"no MPY_VERSION define found in any of: {', '.join(searched)}")


def _git_output(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


def repo_short_hash(repo_root: Path = PROJECT_ROOT) -> str:
    """Short hash of the *greenhouse* repo HEAD — what defined the frozen set."""
    return _git_output(["git", "rev-parse", "--short", "HEAD"], repo_root) or "nogit"


def tree_commit(mpy_tree: Path) -> str:
    """Short hash of the checked-out MicroPython commit, or 'unknown'."""
    return _git_output(["git", "rev-parse", "--short", "HEAD"], mpy_tree) or "unknown"


def firmware_version(built_at: _dt.datetime, repo_root: Path = PROJECT_ROOT) -> str:
    """``pg-fw-<yyyy.mm>-<greenhouse repo shorthash>``.

    The trailing hash is the commit that defined the frozen module set and the
    manifest, so any firmware in the field traces back to source.
    """
    return f"pg-fw-{built_at.strftime('%Y.%m')}-{repo_short_hash(repo_root)}"


def mpy_source(name: str, ref: str, commit: str) -> str:
    """``<fork>@<pinned tag>@<commit>`` — the section 3.1 provenance string."""
    return f"{name}@{ref}@{commit}"


def _stem(name: str) -> str:
    return name[:-3] if name.endswith(".py") else name


def resolve_frozen_modules(
    *,
    tier1_only: bool = False,
    freeze_only: str | None = None,
    manifest_path: Path | None = None,
) -> tuple[str, ...]:
    """The module stems this build will actually freeze, in manifest order.

    Mirrors ``freeze_manifest.py``'s own selection: tier lists, narrowed by
    ``PG_FREEZE_TIER1_ONLY`` and then by ``PG_FREEZE_ONLY``. The mirroring is
    the whole point — a record that over-claims is worse than no record, since
    the OTA prune sweep deletes ``/lib`` files on the strength of it. An unknown
    name in ``freeze_only`` is a typo in the build invocation, and the manifest
    rejects it too, so it fails the build here rather than shipping a lie.
    """
    both = [_stem(n) for n in frozen_module_names(manifest_path)]
    selected = [_stem(n) for n in frozen_module_names(manifest_path, tier1_only=tier1_only)]
    if not freeze_only:
        return tuple(selected)
    wanted = [_stem(n.strip()) for n in freeze_only.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in both]
    if unknown:
        raise FwInfoError("--freeze-only names unknown modules: %s" % ", ".join(unknown))
    return tuple(wanted)


def _render_frozen_modules(modules: tuple[str, ...]) -> str:
    if not modules:
        return "FROZEN_MODULES = ()\n"
    body = "".join(f'    "{name}",\n' for name in modules)
    return f"FROZEN_MODULES = (\n{body})\n"


def render(
    *,
    firmware_version: str,
    mpy_abi: int,
    mpy_source: str,
    frozen_at: str,
    frozen_modules: tuple[str, ...] = (),
) -> str:
    """Render the module body. Kept literal and import-free: this runs on a Pico."""
    return (
        '"""Frozen firmware identity. Generated by tools/gen_fw_info.py — do not edit by hand.\n'
        "\n"
        "Baked into the .uf2 by the freeze manifest, so an OTA payload cannot\n"
        "overwrite it and the version it reports is always the firmware actually\n"
        "running. Consumed by lib/version.py, the updater's ABI guard, and the\n"
        "updater's prune sweep (which will not delete a /lib file unless\n"
        "FROZEN_MODULES proves this image carries a replacement).\n"
        '"""\n'
        "\n"
        f'FIRMWARE_VERSION = "{firmware_version}"\n'
        f"MPY_ABI = {mpy_abi}\n"
        f'MPY_SOURCE = "{mpy_source}"\n'
        f'FROZEN_AT = "{frozen_at}"\n'
        f"{_render_frozen_modules(frozen_modules)}"
    )


def build(
    *,
    mpy_tree: Path | None,
    ref: str,
    commit: str | None = None,
    mpy_abi: int | None = None,
    source_name: str = DEFAULT_SOURCE_NAME,
    version: str | None = None,
    built_at: _dt.datetime | None = None,
    repo_root: Path = PROJECT_ROOT,
    tier1_only: bool = False,
    freeze_only: str | None = None,
    manifest_path: Path | None = None,
) -> str:
    """Assemble the fw_info.py body from a checkout and/or explicit overrides."""
    built_at = built_at or _dt.datetime.now(_dt.timezone.utc)
    if mpy_abi is None:
        if mpy_tree is None:
            raise FwInfoError("need --mpy-tree or --mpy-abi to determine the bytecode ABI")
        mpy_abi = read_mpy_abi(mpy_tree)
    if commit is None:
        commit = tree_commit(mpy_tree) if mpy_tree is not None else "unknown"
    return render(
        firmware_version=version or firmware_version(built_at, repo_root),
        mpy_abi=mpy_abi,
        mpy_source=mpy_source(source_name, ref, commit),
        frozen_at=built_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        frozen_modules=resolve_frozen_modules(
            tier1_only=tier1_only,
            freeze_only=freeze_only,
            manifest_path=manifest_path,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mpy-tree", default=None, help="Path to the pinned MicroPython checkout")
    parser.add_argument("--ref", required=True, help="Pinned tag/commit the firmware is built from (e.g. v1.24.1)")
    parser.add_argument("--commit", default=None, help="MicroPython commit hash (default: read from --mpy-tree)")
    parser.add_argument("--mpy-abi", type=int, default=None, help="Override the ABI instead of reading mpconfig.h")
    parser.add_argument(
        "--source-name",
        default=DEFAULT_SOURCE_NAME,
        help=f"Fork label for MPY_SOURCE (default: {DEFAULT_SOURCE_NAME})",
    )
    parser.add_argument("--version", default=None, help="Override FIRMWARE_VERSION (default: pg-fw-<yyyy.mm>-<hash>)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"Output path (default: {DEFAULT_OUT})")
    parser.add_argument("--print", action="store_true", help="Also echo the generated module to stdout")
    parser.add_argument(
        "--tier1-only",
        action="store_true",
        help="Record only the Tier-1 freeze set (mirror of PG_FREEZE_TIER1_ONLY=1)",
    )
    parser.add_argument(
        "--freeze-only",
        default=None,
        help="Record only these comma-separated modules (mirror of PG_FREEZE_ONLY)",
    )
    parser.add_argument("--manifest", default=None, help="Freeze manifest to read the tier lists from")
    args = parser.parse_args(argv)

    try:
        body = build(
            mpy_tree=Path(args.mpy_tree).resolve() if args.mpy_tree else None,
            ref=args.ref,
            commit=args.commit,
            mpy_abi=args.mpy_abi,
            source_name=args.source_name,
            version=args.version,
            tier1_only=args.tier1_only,
            freeze_only=args.freeze_only,
            manifest_path=Path(args.manifest).resolve() if args.manifest else None,
        )
    except (FwInfoError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"wrote {out_path}")
    if args.print:
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
