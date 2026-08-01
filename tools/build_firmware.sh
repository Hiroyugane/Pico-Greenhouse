#!/usr/bin/env bash
# Build the Pi Greenhouse custom MicroPython firmware (.uf2) - Linux/WSL side.
#
# Mirrors tools/build_firmware.ps1 step for step; that file carries the full
# rationale. This exists because building the RP2 port natively on Windows
# means fighting pico-sdk's host tools (pioasm, picotool), while under WSL the
# whole chain is three apt packages. The PowerShell script remains the
# Windows-native path if that ever becomes preferable.
#
# One deliberate difference: the MicroPython checkout defaults to $HOME inside
# the Linux filesystem, NOT a /mnt path. Building on a 9p-mounted NTFS drive is
# roughly an order of magnitude slower and has bitten enough people that it is
# worth the extra copy of the tree.
#
# Usage:
#   tools/build_firmware.sh
#   tools/build_firmware.sh --repin
#   tools/build_firmware.sh --freeze-only 'sdcard.py,ds3231.py'
#   tools/build_firmware.sh --tier1-only
#   tools/build_firmware.sh --mpy-dir /path/to/micropython --jobs 8
#
# BEFORE FLASHING (plan section 3.1, non-negotiable):
#   - the device must have booted once on its current firmware with the version
#     line in /boot.log; afterwards that line is the only record of what it ran.
#   - keep the previous firmware-<version>.uf2. BOOTSEL + drag-drop of it is the
#     only recovery path a bad frozen build has.

set -euo pipefail

BOARD="RPI_PICO"
UPSTREAM_URL="https://github.com/micropython/micropython"
SOURCE_NAME="upstream"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOCK_FILE="$SCRIPT_DIR/micropython.lock"
MANIFEST_FILE="$SCRIPT_DIR/freeze_manifest.py"
BUILD_DIR="$REPO_ROOT/build"
FROZEN_DIR="$BUILD_DIR/frozen"

MPY_DIR="${MPY_DIR:-$HOME/micropython}"
REF_OVERRIDE=""
REPIN=0
TIER1_ONLY=0
FREEZE_ONLY=""
JOBS="$(nproc 2>/dev/null || echo 4)"

while [ $# -gt 0 ]; do
    case "$1" in
        --mpy-dir)      MPY_DIR="$2"; shift 2 ;;
        --board)        BOARD="$2"; shift 2 ;;
        --ref)          REF_OVERRIDE="$2"; shift 2 ;;
        --repin)        REPIN=1; shift ;;
        --tier1-only)   TIER1_ONLY=1; shift ;;
        --freeze-only)  FREEZE_ONLY="$2"; shift 2 ;;
        --jobs)         JOBS="$2"; shift 2 ;;
        -h|--help)      sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

step() { printf '\n==> %s\n' "$1"; }

# --- 1. Preflight -----------------------------------------------------------
# Report every missing tool at once. Finding them one build at a time is the
# difference between one install session and four.
step "Preflight"
missing=""
for tool in git cmake make gcc arm-none-eabi-gcc python3; do
    command -v "$tool" >/dev/null 2>&1 || missing="$missing  $tool"
done
if [ -n "$missing" ]; then
    echo "Missing build tools:$missing" >&2
    echo "  sudo apt-get install -y build-essential cmake gcc-arm-none-eabi libnewlib-arm-none-eabi" >&2
    echo "See docs/hardware/firmware-build-runbook.md." >&2
    exit 1
fi
[ -f "$MANIFEST_FILE" ] || { echo "freeze manifest missing: $MANIFEST_FILE" >&2; exit 1; }
# The repo lives on a Windows mount; git refuses to read it as another owner.
git config --global --add safe.directory "$REPO_ROOT" 2>/dev/null || true
echo "repo        : $REPO_ROOT"
echo "micropython : $MPY_DIR"
echo "board       : $BOARD"
echo "jobs        : $JOBS"

# --- 2. Resolve the ref -----------------------------------------------------
# "Newest final release" per the council (plan 3.1): vMAJOR.MINOR[.PATCH] only,
# every pre-release rejected, "latest master" never an option.
resolve_newest_final_tag() {
    git ls-remote --tags --refs "$UPSTREAM_URL" \
        | sed 's#.*refs/tags/##' \
        | grep -E '^v[0-9]+(\.[0-9]+){1,2}$' \
        | sort -V \
        | tail -1
}

step "Resolve MicroPython ref"
if [ -n "$REF_OVERRIDE" ]; then
    TARGET_REF="$REF_OVERRIDE"
    echo "using --ref override: $TARGET_REF (lockfile not rewritten)"
elif [ "$REPIN" = "1" ] || [ ! -f "$LOCK_FILE" ]; then
    TARGET_REF="$(resolve_newest_final_tag)"
    [ -n "$TARGET_REF" ] || { echo "no final release tags found upstream" >&2; exit 1; }
    echo "resolved newest final release: $TARGET_REF"
else
    TARGET_REF="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['ref'])" "$LOCK_FILE")"
    echo "using locked ref: $TARGET_REF  (pass --repin to re-resolve)"
fi

# --- 3. Checkout ------------------------------------------------------------
step "Checkout $TARGET_REF"
if [ ! -d "$MPY_DIR/.git" ]; then
    echo "cloning into $MPY_DIR (this takes a while) ..."
    git clone "$UPSTREAM_URL" "$MPY_DIR"
fi
git -C "$MPY_DIR" fetch --tags --force origin
git -C "$MPY_DIR" checkout --detach "$TARGET_REF"
MPY_COMMIT="$(git -C "$MPY_DIR" rev-parse --short HEAD)"
echo "at $TARGET_REF ($MPY_COMMIT)"
echo "fetching submodules (pico-sdk, tinyusb) ..."
make -C "$MPY_DIR/ports/rp2" BOARD="$BOARD" submodules

if [ -z "$REF_OVERRIDE" ]; then
    python3 - "$LOCK_FILE" "$SOURCE_NAME" "$UPSTREAM_URL" "$TARGET_REF" "$MPY_COMMIT" "$BOARD" <<'PYEOF'
import datetime, json, sys
path, source, url, ref, commit, board = sys.argv[1:7]
json.dump({
    "source": source,
    "url": url,
    "ref": ref,
    "commit": commit,
    "board": board,
    "resolved_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "_comment": (
        "Pinned MicroPython ref for tools/build_firmware.{ps1,sh}. Council 2026-07-22 (plan section 3.1): "
        "upstream, newest FINAL release, never 'latest master'. Resolved once and committed so builds are "
        "reproducible; re-resolve deliberately with --repin, which rewrites this file. Changing the ref may "
        "change the .mpy ABI, which makes every field unit's compiled payload stale - see plan section 7 "
        "step 6 before repinning."
    ),
}, open(path, "w"), indent=2)
PYEOF
    echo "lockfile updated: $LOCK_FILE"
fi

# --- 4. mpy-cross from the same tree ---------------------------------------
# The load-bearing step: the .mpy files an OTA payload ships must be compiled by
# the mpy-cross matching the firmware, or the payload applies and then fails
# every import on a board with no REPL (plan 5.2).
step "Build mpy-cross (same tree = same .mpy ABI)"
make -C "$MPY_DIR/mpy-cross" "-j$JOBS"
MPY_CROSS="$MPY_DIR/mpy-cross/build/mpy-cross"
[ -x "$MPY_CROSS" ] || { echo "mpy-cross not found at $MPY_CROSS" >&2; exit 1; }
echo "mpy-cross: $MPY_CROSS"
echo "REMINDER: build OTA payloads with THIS mpy-cross. Any other one carries a"
echo "bytecode ABI this firmware will refuse (plan 6.3)."

# --- 5. Generate the frozen fw_info.py -------------------------------------
step "Generate fw_info.py"
mkdir -p "$FROZEN_DIR"
FW_INFO_PATH="$FROZEN_DIR/fw_info.py"
python3 "$SCRIPT_DIR/gen_fw_info.py" \
    --mpy-tree "$MPY_DIR" \
    --ref "$TARGET_REF" \
    --commit "$MPY_COMMIT" \
    --source-name "$SOURCE_NAME" \
    --out "$FW_INFO_PATH"

FW_VERSION="$(sed -n 's/^FIRMWARE_VERSION = "\(.*\)"$/\1/p' "$FW_INFO_PATH")"
MPY_ABI="$(sed -n 's/^MPY_ABI = \([0-9]*\)$/\1/p' "$FW_INFO_PATH")"
[ -n "$FW_VERSION" ] || { echo "could not read FIRMWARE_VERSION back from $FW_INFO_PATH" >&2; exit 1; }
echo "firmware version: $FW_VERSION   (.mpy ABI $MPY_ABI)"

# --- 6. Build the firmware --------------------------------------------------
step "Build ports/rp2 (BOARD=$BOARD)"
export PG_REPO_DIR="$REPO_ROOT"
export PG_FW_INFO_DIR="$FROZEN_DIR"
if [ "$TIER1_ONLY" = "1" ]; then export PG_FREEZE_TIER1_ONLY=1; else unset PG_FREEZE_TIER1_ONLY || true; fi
if [ -n "$FREEZE_ONLY" ]; then export PG_FREEZE_ONLY="$FREEZE_ONLY"; else unset PG_FREEZE_ONLY || true; fi

make -C "$MPY_DIR/ports/rp2" BOARD="$BOARD" FROZEN_MANIFEST="$MANIFEST_FILE" "-j$JOBS"

# --- 7. Collect artifacts ---------------------------------------------------
step "Collect artifacts"
BUILT_UF2="$MPY_DIR/ports/rp2/build-$BOARD/firmware.uf2"
[ -f "$BUILT_UF2" ] || { echo "firmware.uf2 not found at $BUILT_UF2" >&2; exit 1; }

TARGET_UF2="$BUILD_DIR/firmware.uf2"
ARCHIVE_UF2="$BUILD_DIR/firmware-$FW_VERSION.uf2"
cp -f "$BUILT_UF2" "$TARGET_UF2"
cp -f "$BUILT_UF2" "$ARCHIVE_UF2"

# A build can succeed and still be stock: if FROZEN_MANIFEST never reached the
# port, make produces a perfectly good firmware with nothing frozen, and the
# only symptom is a heap number that did not move. Check the image itself.
step "Verify the freeze took"
VERIFY_ARGS=(--expect-version "$FW_VERSION")
[ "$TIER1_ONLY" = "1" ] && VERIFY_ARGS+=(--tier1-only)
python3 "$SCRIPT_DIR/verify_frozen_uf2.py" "$TARGET_UF2" "${VERIFY_ARGS[@]}"

python3 - "$BUILD_DIR/firmware-build.json" <<PYEOF
import datetime, json, sys
json.dump({
    "firmware_version": "$FW_VERSION",
    "mpy_abi": int("$MPY_ABI"),
    "mpy_source": "$SOURCE_NAME@$TARGET_REF@$MPY_COMMIT",
    "board": "$BOARD",
    "tier1_only": bool($TIER1_ONLY),
    "freeze_only": "$FREEZE_ONLY",
    "mpy_cross": "$MPY_CROSS",
    "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "artifact": "$TARGET_UF2",
    "rollback": "$ARCHIVE_UF2",
    "builder": "build_firmware.sh (WSL)",
}, open(sys.argv[1], "w"), indent=2)
PYEOF

echo
echo "firmware : $TARGET_UF2"
echo "rollback : $ARCHIVE_UF2"
echo "note     : $BUILD_DIR/firmware-build.json"
echo
echo "Next steps (docs/hardware/firmware-build-runbook.md):"
echo "  1. Confirm the device logged its CURRENT version to /boot.log before you flash."
echo "  2. Keep the previous firmware-<version>.uf2 - it is the only rollback."
echo "  3. BOOTSEL + drag-drop, then watch boot.log for import errors on every frozen module."
echo "  4. Soak with diagnostics.mem_trend_log = True and compare via tools/heap_baseline.py."
