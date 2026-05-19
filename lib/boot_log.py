# Boot Log - File-backed mirror for pre-EventLogger boot diagnostics
# Dennis Hiro, 2026-05-15
#
# When the SD card fails to mount, the Pico has nothing to write its boot
# diagnostics to except the USB serial console — which is unavailable if
# the device is running standalone. This module mirrors a handful of
# critical print() lines (HardwareFactory SD mount progress + mount_sd
# error output via the debug callback) into a tiny log file on the Pico's
# internal flash, so the operator can mount the Pico over USB MSC after
# the fact and read why the boot mount failed.
#
# The file is truncated on the first write per process, so each boot
# starts clean. A size cap protects against runaway growth.

import os

# Defaults; main.py overrides via configure() at startup.
_path = "/boot.log"
_max_bytes = 10 * 1024
_first_write = True


def configure(path: str = "/boot.log", max_bytes: int = 10 * 1024) -> None:
    """Set the log file path and size cap. Call once at main() start."""
    global _path, _max_bytes
    _path = path
    _max_bytes = int(max_bytes)


def log(message: str) -> None:
    """Echo message to console AND append to the boot log (best-effort).

    On the first call within this Python process, the log file is
    truncated so the new boot starts fresh. After that, writes append
    until the file exceeds ``max_bytes``, at which point it is rewritten
    from scratch to keep the cap honored.

    Errors writing to the file are swallowed: the SD-diagnostic path
    that consumes this helper must never be blocked by a flash full /
    read-only / mount-missing condition on the log side.
    """
    try:
        print(message)
    except Exception:
        pass
    _write_to_file(message)


def write(message: str) -> None:
    """Append ``message`` to the log file only (no console echo)."""
    _write_to_file(message)


def _write_to_file(message: str) -> None:
    """Append ``message`` to the log file, truncating on first write."""
    global _first_write
    try:
        mode = "w"
        if not _first_write:
            try:
                size = os.stat(_path)[6]
            except OSError:
                size = 0
            mode = "w" if size > _max_bytes else "a"
        with open(_path, mode) as f:
            f.write(message + "\n")
        _first_write = False
    except Exception:
        pass


def _reset_for_test() -> None:
    """Reset module-level state. Test-only helper, never called at runtime."""
    global _first_write
    _first_write = True
