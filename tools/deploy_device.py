"""Deploy the mutable application set to a Pico over mpremote.

Replaces the two-file bench-refresh that `run deploy` used to be. What a deploy
has to get right after the freeze work landed:

1. **Create the directories.** `mpremote cp` does not create them, so the first
   deploy onto a freshly-flashed board fails with
   `cp: lib/<mod>.py: No such file or directory` — which names the *source*
   and reads like the local file is missing when the real problem is that
   `/lib` does not exist on the device.
2. **Ship compiled bytecode, not `.py`.** The P0.5 measurement (2026-07-23)
   found the raw `.py` set no longer fits the Pico's flash at all. Compiled is
   not an optimisation here, it is the only shape that fits.
3. **Skip the frozen modules.** They live in the firmware now. Copying them
   wastes the flash that point 2 proved is scarce, and the copy is a silent
   no-op: the import still resolves to the frozen module (plan section 6.1).
4. **Prove the bytecode matches the firmware.** Every produced `.mpy` is
   checked against the running firmware's `MPY_ABI` before anything is
   written. A mismatched payload imports nowhere, and on a board with no REPL
   that is discovered the hard way.

`main.py` always ships raw: the boot sequence looks for that exact filename.

Usage:
    python tools/deploy_device.py                 # compile + deploy the mutable set
    python tools/deploy_device.py --dry-run       # show what would be sent
    python tools/deploy_device.py --raw           # ship .py (only fits pre-freeze)
    python tools/deploy_device.py --no-skip-frozen
    python tools/deploy_device.py --mpy-cross /path/to/mpy-cross

Host-only tooling: never imported by device code.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.verify_frozen_uf2 import frozen_module_names  # noqa: E402

DEPLOY_DIR = PROJECT_ROOT / "build" / "deploy"
BUILD_NOTE = PROJECT_ROOT / "build" / "firmware-build.json"
FW_INFO = PROJECT_ROOT / "build" / "frozen" / "fw_info.py"

# Never shipped: generated per build, or not part of the app.
LIB_SKIP = {"__init__.py"}

_MPY_MAGIC = 0x4D


class DeployError(Exception):
    """Raised when the deploy set cannot be built or verified."""


def firmware_abi() -> int | None:
    """The .mpy ABI of the firmware this repo last built, or None if unknown.

    Read from the generated fw_info.py, falling back to the build note. None
    means "no local firmware build to compare against" — the caller decides
    whether that is acceptable.
    """
    if FW_INFO.is_file():
        match = re.search(r"^MPY_ABI\s*=\s*(\d+)", FW_INFO.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return int(match.group(1))
    if BUILD_NOTE.is_file():
        try:
            return int(json.loads(BUILD_NOTE.read_text(encoding="utf-8"))["mpy_abi"])
        except (ValueError, KeyError, TypeError):
            return None
    return None


def firmware_mpy_cross() -> str | None:
    """Path to the mpy-cross the firmware was built with, per the build note."""
    if not BUILD_NOTE.is_file():
        return None
    try:
        return json.loads(BUILD_NOTE.read_text(encoding="utf-8")).get("mpy_cross")
    except ValueError:
        return None


def deploy_set(*, skip_frozen: bool = True, lib_dir: Path | None = None) -> list[tuple[Path, str]]:
    """Return [(local_source, remote_relative_path), ...] for the mutable app.

    Order matters: ``main.py`` last, so a half-finished deploy cannot leave a
    board booting new wiring against old modules.
    """
    lib_dir = lib_dir or (PROJECT_ROOT / "lib")
    frozen = set(frozen_module_names()) if skip_frozen else set()

    entries: list[tuple[Path, str]] = []
    config = PROJECT_ROOT / "config.py"
    if not config.is_file():
        raise DeployError("config.py not found at the project root")
    entries.append((config, "config.py"))

    if not lib_dir.is_dir():
        raise DeployError(f"lib/ not found at {lib_dir}")
    for source in sorted(lib_dir.iterdir()):
        if not source.is_file() or source.suffix != ".py" or source.name in LIB_SKIP:
            continue
        if source.stem in frozen:
            continue
        entries.append((source, f"lib/{source.name}"))

    main = PROJECT_ROOT / "main.py"
    if not main.is_file():
        raise DeployError("main.py not found at the project root")
    entries.append((main, "main.py"))
    return entries


def mpy_abi_of(path: Path) -> int:
    """ABI byte out of a .mpy header (byte 0 is 'M', byte 1 is the version)."""
    with path.open("rb") as handle:
        header = handle.read(2)
    if len(header) < 2 or header[0] != _MPY_MAGIC:
        raise DeployError(f"{path} is not a .mpy file (bad magic)")
    return header[1]


def compile_set(
    entries: list[tuple[Path, str]],
    *,
    mpy_cross: str,
    out_dir: Path = DEPLOY_DIR,
    expected_abi: int | None = None,
) -> list[tuple[Path, str]]:
    """Compile everything but main.py, returning the deployable pairs.

    Refuses to return a set whose bytecode ABI differs from the firmware's:
    that payload would import nowhere, and the board has no REPL to say so.
    """
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "lib").mkdir(parents=True, exist_ok=True)

    compiled: list[tuple[Path, str]] = []
    seen_abis: set[int] = set()
    for source, remote in entries:
        if remote == "main.py":
            target = out_dir / "main.py"
            shutil.copyfile(source, target)
            compiled.append((target, remote))
            continue
        target = out_dir / remote[:-3] if remote.endswith(".py") else out_dir / remote
        target = target.with_suffix(".mpy")
        target.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [mpy_cross, str(source), "-o", str(target)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise DeployError(f"mpy-cross failed on {source.name}: {result.stderr.strip() or result.stdout.strip()}")
        seen_abis.add(mpy_abi_of(target))
        compiled.append((target, remote[:-3] + ".mpy" if remote.endswith(".py") else remote))

    if len(seen_abis) > 1:
        raise DeployError(f"compiler emitted mixed .mpy ABIs {sorted(seen_abis)} - one mpy-cross per deploy")
    if expected_abi is not None and seen_abis and expected_abi not in seen_abis:
        produced = seen_abis.pop()
        raise DeployError(
            f"mpy-cross emits ABI {produced} but the firmware imports ABI {expected_abi}. "
            "Use the mpy-cross built from the firmware's own checkout (see the runbook, section 5)."
        )
    return compiled


def remote_dirs(entries: list[tuple[Path, str]]) -> list[str]:
    """Device directories the deploy needs, parents first."""
    dirs: list[str] = []
    for _source, remote in entries:
        parent = remote.rsplit("/", 1)[0] if "/" in remote else ""
        if parent and parent not in dirs:
            dirs.append(parent)
    return sorted(dirs, key=lambda item: item.count("/"))


def _already_exists(message: str) -> bool:
    """True when an mpremote mkdir failed only because the directory is there."""
    lowered = message.lower()
    return "eexist" in lowered or "file exists" in lowered


def _display(path: Path) -> str:
    """Repo-relative path for logging, or the full path when it lies outside."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def device_lib_files(*, mpremote: str = "mpremote") -> list[str]:
    """Filenames currently in the device's /lib, or [] if it cannot be listed."""
    result = _run_mpremote(["fs", "ls", ":lib"], mpremote=mpremote)
    if result.returncode != 0:
        return []
    names = []
    for line in result.stdout.splitlines():
        parts = line.split()
        # "<size> <name>" rows; the header line ("ls :lib") has no size.
        if len(parts) == 2 and parts[0].isdigit():
            names.append(parts[1].rstrip("/"))
    return names


def stale_shadows(device_files: list[str], entries: list[tuple[Path, str]], frozen: list[str]) -> list[str]:
    """Device /lib files that shadow a frozen module or are no longer shipped.

    This is not housekeeping — it is correctness. Imports try ``lib.<mod>``
    first, so a leftover ``lib/event_logger.mpy`` from a pre-freeze deploy wins
    over the frozen copy and the freeze silently buys nothing for that module.
    Nothing warns you: it imports, it runs, and only the heap figure is wrong.
    """
    shipped = {remote.split("/", 1)[1] for _src, remote in entries if remote.startswith("lib/")}
    frozen_stems = set(frozen)
    stale = []
    for name in device_files:
        if name in shipped:
            continue
        stem = name.rsplit(".", 1)[0]
        if stem in frozen_stems or name.endswith((".py", ".mpy")):
            stale.append(name)
    return stale


def prune(names: list[str], *, mpremote: str = "mpremote", dry_run: bool = False) -> int:
    """Delete the given files from the device's /lib. Returns the count removed."""
    removed = 0
    for name in names:
        if dry_run:
            print(f"  rm     :lib/{name}")
            removed += 1
            continue
        result = _run_mpremote(["fs", "rm", f":lib/{name}"], mpremote=mpremote)
        if result.returncode != 0:
            raise DeployError(f"could not remove :lib/{name} - {result.stderr.strip() or result.stdout.strip()}")
        print(f"  removed lib/{name}")
        removed += 1
    return removed


def _run_mpremote(args: list[str], *, mpremote: str) -> subprocess.CompletedProcess:
    return subprocess.run([mpremote, *args], capture_output=True, text=True)


def push(
    entries: list[tuple[Path, str]],
    *,
    mpremote: str = "mpremote",
    dry_run: bool = False,
) -> int:
    """mkdir the directories, then copy every pair. Returns files copied."""
    for directory in remote_dirs(entries):
        if dry_run:
            print(f"  mkdir  :{directory}")
            continue
        # Tolerate "already there": mpremote has no mkdir -p, and an existing
        # directory is the normal case on every deploy after the first. The
        # wording varies by mpremote version — it reports "File exists" on
        # 1.28 and "EEXIST" elsewhere — so match both rather than one.
        result = _run_mpremote(["fs", "mkdir", f":{directory}"], mpremote=mpremote)
        if result.returncode != 0 and not _already_exists(result.stderr + result.stdout):
            raise DeployError(f"could not create :{directory} - {result.stderr.strip() or result.stdout.strip()}")

    copied = 0
    for source, remote in entries:
        if dry_run:
            print(f"  cp     {_display(source)} -> :{remote}")
            copied += 1
            continue
        result = _run_mpremote(["fs", "cp", str(source), f":{remote}"], mpremote=mpremote)
        if result.returncode != 0:
            raise DeployError(f"copy failed for {remote}: {result.stderr.strip() or result.stdout.strip()}")
        print(f"  {remote}")
        copied += 1
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", action="store_true", help="Ship .py instead of .mpy (does not fit post-2026-07 flash)")
    parser.add_argument("--no-skip-frozen", action="store_true", help="Also send modules that are frozen in firmware")
    parser.add_argument("--mpy-cross", default=None, help="mpy-cross to compile with (default: firmware's, then PATH)")
    parser.add_argument("--mpremote", default="mpremote", help="mpremote executable")
    parser.add_argument("--dry-run", action="store_true", help="List what would be sent; touch nothing")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete /lib files that shadow a frozen module or are no longer shipped",
    )
    parser.add_argument("--allow-abi-mismatch", action="store_true", help="Skip the ABI check (you had better be sure)")
    args = parser.parse_args(argv)

    try:
        entries = deploy_set(skip_frozen=not args.no_skip_frozen)
    except DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    frozen = frozen_module_names()
    abi = firmware_abi()
    print(f"deploy set : {len(entries)} files")
    if not args.no_skip_frozen:
        print(f"skipping   : {len(frozen)} frozen module(s) - they live in the firmware")
    if abi is not None:
        print(f"firmware   : .mpy ABI {abi}")
    else:
        print("firmware   : unknown (no local build) - ABI check skipped")

    if not args.raw:
        mpy_cross = args.mpy_cross or firmware_mpy_cross() or shutil.which("mpy-cross")
        if mpy_cross and not Path(mpy_cross).exists() and not shutil.which(mpy_cross):
            # The firmware's mpy-cross is a Linux binary when the build ran in
            # WSL; fall back rather than fail, and let the ABI check decide.
            print(f"note       : {mpy_cross} not runnable here, falling back to PATH mpy-cross")
            mpy_cross = shutil.which("mpy-cross")
        if not mpy_cross:
            print("error: no mpy-cross found. Install it, or pass --raw (see runbook 5).", file=sys.stderr)
            return 1
        print(f"mpy-cross  : {mpy_cross}")
        try:
            entries = compile_set(
                entries,
                mpy_cross=mpy_cross,
                expected_abi=None if args.allow_abi_mismatch else abi,
            )
        except DeployError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    # Stale shadows are a correctness problem, not clutter: lib-first imports
    # mean a leftover pre-freeze copy wins over the frozen module and the
    # freeze silently buys nothing. Always report; delete only when asked.
    try:
        on_device = device_lib_files(mpremote=args.mpremote)
        stale = stale_shadows(on_device, entries, frozen)
    except DeployError:
        stale = []
    if stale:
        print(f"\nstale on device: {len(stale)} file(s) in /lib that are no longer shipped")
        for name in stale:
            marker = "  <- SHADOWS A FROZEN MODULE" if name.rsplit(".", 1)[0] in frozen else ""
            print(f"  lib/{name}{marker}")
        if not args.prune:
            print("Re-run with --prune to remove them (a shadow silently negates the freeze).")
    if stale and args.prune:
        print()
        try:
            prune(stale, mpremote=args.mpremote, dry_run=args.dry_run)
        except DeployError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    try:
        copied = push(entries, mpremote=args.mpremote, dry_run=args.dry_run)
    except DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("\nIf this says 'No such file or directory' for a file that exists locally,", file=sys.stderr)
        print("the missing path is on the DEVICE, not here.", file=sys.stderr)
        return 1

    print(f"\n{'would copy' if args.dry_run else 'copied'} {copied} file(s)")
    if not args.dry_run:
        print("Reset the board (or power-cycle) to run the new code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
