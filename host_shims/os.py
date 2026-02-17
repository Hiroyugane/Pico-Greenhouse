"""Host-compatible shim for MicroPython os module.

Re-exports everything from the standard ``os`` module and adds
MicroPython-specific functions (``mount``, ``umount``, ``uname``,
``ilistdir``, ``sync``, VFS classes, etc.) so the project can run on
standard CPython without modification.

Upgraded to use probe data from ``host_shims/_probe_data.py`` for
realistic ``statvfs`` and ``uname`` results.
"""

from __future__ import annotations

import os as _os
import platform as _platform
from collections import namedtuple as _namedtuple

# Re-export the entire standard os module so callers see the full API.
from os import *  # noqa: F401,F403
from typing import Iterator

from host_shims._probe_data import PROBE

_VERBOSE = _os.environ.get("HOST_SHIM_VERBOSE", "") == "1"

# ---------------------------------------------------------------------------
# uname – MicroPython-compatible system info
# ---------------------------------------------------------------------------

_uname_result = _namedtuple(
    "uname_result", ["sysname", "nodename", "release", "version", "machine"]
)


def uname() -> _uname_result:                        # type: ignore[override]
    """Return a MicroPython-style uname tuple.

    When probe data is available, returns strings that match the real
    device (e.g. ``rp2``, ``Raspberry Pi Pico W with RP2040``).  Falls
    back to host OS values.
    """
    return _uname_result(
        sysname=PROBE.platform.uname_sysname or _platform.system(),  # type: ignore
        nodename=PROBE.platform.uname_nodename or _platform.node(),  # type: ignore
        release=PROBE.platform.uname_release or _platform.release(),  # type: ignore
        version=PROBE.platform.uname_version or f"host-shim CPython {_platform.python_version()}",  # type: ignore
        machine=PROBE.platform.uname_machine or _platform.machine(),  # type: ignore
    )


# ---------------------------------------------------------------------------
# ilistdir – MicroPython-specific directory iterator
# ---------------------------------------------------------------------------

_S_IFDIR = 0x4000
_S_IFREG = 0x8000


def ilistdir(dir: str = ".") -> Iterator[tuple]:
    """Yield ``(name, type, inode, size)`` tuples like MicroPython.

    *type* is ``0x4000`` for directories, ``0x8000`` for regular files.
    """
    for entry in _os.scandir(dir): # type: ignore
        try:
            st = entry.stat()
            if entry.is_dir(follow_symlinks=False):
                yield (entry.name, _S_IFDIR, st.st_ino, 0)
            else:
                yield (entry.name, _S_IFREG, st.st_ino, st.st_size)
        except OSError:
            # Inaccessible entry – skip silently, matching Pico behaviour.
            pass


# ---------------------------------------------------------------------------
# statvfs – ensure availability on all platforms
# ---------------------------------------------------------------------------

if not hasattr(_os, "statvfs"):
    def statvfs(path: str) -> tuple:
        """Return probe-calibrated statvfs result on platforms without it.

        Uses real SD card capacity data from hw_probe if available,
        otherwise returns realistic defaults for a 32 GB FAT32 SD card.
        """
        return PROBE.sd.statvfs_tuple


# ---------------------------------------------------------------------------
# sync – flush all filesystems
# ---------------------------------------------------------------------------

def sync() -> None:
    """No-op on host; MicroPython uses this to flush all filesystems."""
    pass


# ---------------------------------------------------------------------------
# Filesystem mounting
# ---------------------------------------------------------------------------

# Track simulated mounts for introspection in tests / debug.
_mounts: dict[str, object] = {}


def mount(device: object, mount_point: str, *, readonly: bool = False) -> None:
    """Simulate MicroPython ``os.mount(device, mount_point)``."""
    _mounts[mount_point] = device
    if _VERBOSE:
        print(f"[HOST OS] mount({device!r}, {mount_point!r}, readonly={readonly})")


def umount(mount_point: str) -> None:
    """Simulate MicroPython ``os.umount(mount_point)``."""
    _mounts.pop(mount_point, None)
    if _VERBOSE:
        print(f"[HOST OS] umount({mount_point!r})")


# ---------------------------------------------------------------------------
# Terminal redirection stubs
# ---------------------------------------------------------------------------

_dupterm_slots: dict[int, object | None] = {}


def dupterm(stream: object | None = None, index: int = 0) -> object | None:
    """Simulate MicroPython ``os.dupterm()``.

    Returns the previous stream in the given slot (or ``None``).
    """
    prev = _dupterm_slots.get(index)
    _dupterm_slots[index] = stream
    return prev


def dupterm_notify(obj_in: object = None) -> None:
    """Stub for MicroPython ``os.dupterm_notify()`` – no-op on host."""
    pass


# ---------------------------------------------------------------------------
# VFS class stubs (for backward-compat imports)
# ---------------------------------------------------------------------------

class VfsFat:
    """Stub for MicroPython ``os.VfsFat``."""

    def __init__(self, block_dev: object):
        self.block_dev = block_dev


class VfsLfs1:
    """Stub for MicroPython ``os.VfsLfs1``."""

    def __init__(
        self,
        block_dev: object,
        readsize: int = 32,
        progsize: int = 32,
        lookahead: int = 32,
    ):
        self.block_dev = block_dev


class VfsLfs2:
    """Stub for MicroPython ``os.VfsLfs2``."""

    def __init__(
        self,
        block_dev: object,
        readsize: int = 32,
        progsize: int = 32,
        lookahead: int = 32,
        mtime: bool = True,
    ):
        self.block_dev = block_dev


class VfsPosix:
    """Stub for MicroPython ``os.VfsPosix``."""

    def __init__(self, root: str | None = None):
        self.root = root
