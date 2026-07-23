"""Verify a built .uf2 actually froze what the manifest asked for.

A firmware build can succeed and still be wrong in a way nothing else catches:
if `FROZEN_MANIFEST` never reached the port build, or `PG_REPO_DIR` pointed
somewhere unexpected, `make` happily produces a **stock** firmware. Flash that
and every symptom is a runtime one — modules still import (from the
filesystem), the heap is unchanged, and the only clue is a `mem_trend` number
that did not move. This closes that gap before the image is written to a Pico.

Two questions, both answered against the image itself:

1. **Is every module that should be frozen present?** Frozen modules leave
   their names in the firmware's qstr/module tables; a stock image has none of
   them.
2. **Is anything present that must NEVER be frozen?** A decision module baked
   into the image costs a fleet reflash to undo, so the negative check matters
   more than the positive one.

Usage:
    python tools/verify_frozen_uf2.py build/firmware.uf2
    python tools/verify_frozen_uf2.py build/firmware.uf2 --expect-version pg-fw-2026.07-2c8353d
    python tools/verify_frozen_uf2.py build/firmware.uf2 --compare-stock build/rollback/stock.uf2
    python tools/verify_frozen_uf2.py build/firmware.uf2 --tier1-only

Exit code 0 = the image matches the manifest; 1 = it does not (do not flash).

Host-only tooling: never imported by device code.
"""

from __future__ import annotations

import argparse
import ast
import struct
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_BLOCK_SIZE = 512
UF2_HEADER_SIZE = 32
RP2040_FAMILY_ID = 0xE48BFF56

# Substring probes, not module objects: this reads a linked binary, not Python.
# Names are distinctive enough that a false positive would need the string to
# appear for an unrelated reason.
NEVER_FROZEN = (
    "updater",
    "oled_display",
    "regulation_engine",
    "regulation_adapters",
    "co2_logger",
    "fan_controllers",
    "build_info",
)


class VerifyError(Exception):
    """Raised when the .uf2 cannot be read as a firmware image."""


def uf2_payload(path: Path) -> bytes:
    """Concatenate the data payloads of every UF2 block into the flash image.

    UF2 wraps each 256-byte chunk in a 512-byte block with a 32-byte header, so
    a naive grep over the raw file would miss any string that straddles a block
    boundary. Reassembling first makes the search exact.
    """
    raw = path.read_bytes()
    if len(raw) < UF2_BLOCK_SIZE:
        raise VerifyError(f"{path} is too small to be a UF2 image")
    out = bytearray()
    for offset in range(0, len(raw) - UF2_BLOCK_SIZE + 1, UF2_BLOCK_SIZE):
        block = raw[offset : offset + UF2_BLOCK_SIZE]
        magic0, magic1, _flags, _addr, size, _blkno, _numblk, _family = struct.unpack("<8I", block[:UF2_HEADER_SIZE])
        if magic0 != UF2_MAGIC_START0 or magic1 != UF2_MAGIC_START1:
            raise VerifyError(f"{path}: block at offset {offset} is not a UF2 block (bad magic)")
        if size > UF2_BLOCK_SIZE - UF2_HEADER_SIZE:
            raise VerifyError(f"{path}: block at offset {offset} declares an impossible payload size {size}")
        out += block[UF2_HEADER_SIZE : UF2_HEADER_SIZE + size]
    if not out:
        raise VerifyError(f"{path} contains no UF2 payload")
    return bytes(out)


def frozen_module_names(manifest_path: Path | None = None, *, tier1_only: bool = False) -> list[str]:
    """The module basenames the freeze manifest declares, without executing it.

    The manifest is a MicroPython manifest file — executing it needs the
    makemanifest globals — so the tier tuples are read out of it as literals.
    """
    manifest_path = manifest_path or (PROJECT_ROOT / "tools" / "freeze_manifest.py")
    source = manifest_path.read_text(encoding="utf-8")
    # Parse rather than exec: the manifest's freeze()/package() calls need
    # globals this process does not have. Parse rather than slice text, too —
    # the tier tuples carry comments containing parentheses, which is exactly
    # what a naive "find the closing paren" search gets wrong.
    tree = ast.parse(source, filename=str(manifest_path))
    tiers: dict[str, tuple] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in ("TIER1", "TIER2"):
            tiers[target.id] = ast.literal_eval(node.value)
    if "TIER1" not in tiers:
        raise VerifyError(f"no TIER1 tuple found in {manifest_path}")

    collected: list[str] = list(tiers["TIER1"])
    if not tier1_only:
        collected.extend(tiers.get("TIER2", ()))
    return [name[:-3] if name.endswith(".py") else name for name in collected]


def verify(
    image: bytes,
    *,
    expected: list[str],
    forbidden: tuple[str, ...] = NEVER_FROZEN,
    expect_version: str | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Return (missing, leaked, notes). Empty missing+leaked means the build is good."""
    missing = [name for name in expected if name.encode() not in image]
    leaked = [name for name in forbidden if name.encode() in image]
    notes = []
    if b"fw_info" not in image:
        missing.append("fw_info")
    if expect_version is not None:
        if expect_version.encode() in image:
            notes.append(f"version stamp present: {expect_version}")
        else:
            missing.append(f"FIRMWARE_VERSION {expect_version}")
    return missing, leaked, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("uf2", help="Path to the built firmware .uf2")
    parser.add_argument(
        "--tier1-only",
        action="store_true",
        help="Expect only the Tier-1 set (matches PG_FREEZE_TIER1_ONLY)",
    )
    parser.add_argument("--expect-version", default=None, help="Require this FIRMWARE_VERSION string in the image")
    parser.add_argument("--compare-stock", default=None, help="Also report the size delta against a stock .uf2")
    parser.add_argument("--manifest", default=None, help="Freeze manifest to read the tier lists from")
    args = parser.parse_args(argv)

    try:
        image = uf2_payload(Path(args.uf2))
    except (OSError, VerifyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    expected = frozen_module_names(Path(args.manifest) if args.manifest else None, tier1_only=args.tier1_only)
    missing, leaked, notes = verify(image, expected=expected, expect_version=args.expect_version)

    print(f"image      : {args.uf2}")
    print(f"payload    : {len(image):,} bytes")
    if args.compare_stock:
        try:
            stock = uf2_payload(Path(args.compare_stock))
        except (OSError, VerifyError) as exc:
            print(f"warning: cannot read stock image: {exc}", file=sys.stderr)
        else:
            print(f"vs stock   : {len(image) - len(stock):+,} bytes ({args.compare_stock})")
    print(f"expected   : {len(expected)} frozen modules")
    for note in notes:
        print(f"note       : {note}")

    if missing:
        print(f"\nFAIL: {len(missing)} expected item(s) not found in the image:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print("\nThe freeze did not take. Most likely FROZEN_MANIFEST never reached the", file=sys.stderr)
        print("port build, or PG_REPO_DIR pointed elsewhere. DO NOT FLASH THIS IMAGE.", file=sys.stderr)
    if leaked:
        print(f"\nFAIL: {len(leaked)} module(s) that must never be frozen are in the image:", file=sys.stderr)
        for name in leaked:
            print(f"  - {name}", file=sys.stderr)
        print("\nEach of these costs a fleet reflash to change. DO NOT FLASH THIS IMAGE.", file=sys.stderr)

    if missing or leaked:
        return 1
    print("\nOK: every expected module is frozen and nothing forbidden leaked in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
