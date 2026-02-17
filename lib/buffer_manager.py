# Buffer Manager - Centralized Storage with SD Fallback
# Dennis Hiro, 2026-01-29
#
# Manages buffered writes to SD (primary) and fallback file when SD unavailable.
# Supports atomic writes, migration from fallback to primary, and graceful initialization.
#
# Design principles:
# - Never block event loop (no blocking I/O directly; returns quickly)
# - Graceful fallback when primary unavailable (write to fallback_path)
# - Deferred initialization (files created on first write, not __init__)
# - Provides metrics for EventLogger to track fallback events

import os
import sys


class BufferManager:
    """
    Centralized manager for buffered writes with SD hot-swap support.

    Writes data to primary (SD) when available, otherwise to fallback file.
    Provides migration mechanism to move fallback entries to primary when SD recovers.
    Handles gracefully when both primary and fallback unavailable (returns False).

    Attributes:
        sd_mount_point (str): SD card mount path (e.g., '/sd')
        fallback_path (str): Local fallback file path (e.g., '/local/fallback.csv')
        max_buffer_entries (int): Cap on in-memory buffer to prevent memory exhaustion
        _fallback_available (bool): Cached state of fallback file availability
    """

    def __init__(self, sd_mount_point="/sd", fallback_path="/local/fallback.csv", max_buffer_entries=1000):
        """
        Initialize BufferManager with SD and fallback paths.

        Does NOT attempt to create or validate files at init (deferred to first write).
        This allows system to start even if storage is partially unavailable.

        Args:
            sd_mount_point (str): Mount point for SD card (default: '/sd')
            fallback_path (str): Local fallback file path (default: '/local/fallback.csv')
            max_buffer_entries (int): Max in-memory buffer size (default: 1000)
        """
        # Host compatibility: map /sd and /local to local folders on CPython
        if self._is_host():
            sd_mount_point = self._normalize_host_path(sd_mount_point, "sd")
            fallback_path = self._normalize_host_path(fallback_path, "local/fallback.csv")

        self.sd_mount_point = sd_mount_point
        self.fallback_path = fallback_path
        self.max_buffer_entries = max_buffer_entries

        if self._is_host():
            try:
                os.makedirs(self.sd_mount_point, exist_ok=True)
            except Exception:
                pass

        # Internal buffers: per-file in-memory storage
        self._buffers = {}  # {relpath: [entry1, entry2, ...]}

        # Metrics
        self.writes_to_primary = 0
        self.writes_to_fallback = 0
        self.fallback_migrations = 0
        self.write_failures = 0

    def is_primary_available(self) -> bool:
        """
        Non-blocking check whether SD mount is accessible.

        Performs a write-then-read-verify to confirm writable access.
        Writing an empty string is not enough: MicroPython's FAT VFS can
        satisfy a zero-byte create/delete from cached directory entries even
        after the physical SD card has been removed.  Writing real data and
        reading it back forces actual block-level I/O.

        Returns:
            bool: True if SD mount is available and writable, False otherwise
        """
        try:
            test_file = f"{self.sd_mount_point}/.test"
            test_data = "SDok"
            # Write real data to force block I/O
            with open(test_file, "w") as f:
                f.write(test_data)
            # Read back and verify to catch ghost writes on removed card
            with open(test_file, "r") as f:
                readback = f.read()
            os.remove(test_file)
            return readback == test_data
        except Exception:
            return False

    def _ensure_fallback_dir(self) -> bool:
        """
        Ensure fallback directory exists.

        Creates parent directory if needed. Returns False if creation fails.

        Returns:
            bool: True if fallback directory is usable, False otherwise
        """
        try:
            fallback_dir = self._path_dirname(self.fallback_path) or "."
            if not self._dir_exists(fallback_dir):
                os.makedirs(fallback_dir, exist_ok=True)
            return True
        except Exception:
            return False

    def _dir_exists(self, path: str) -> bool:
        """Check if directory exists without raising exception."""
        try:
            st = os.stat(path)
            mode = st[0] if isinstance(st, tuple) else st.st_mode
            # MicroPython doesn't expose stat.S_ISDIR; use POSIX dir bit 0x4000
            return bool(mode & 0x4000)
        except Exception:
            return False

    def _path_sep(self) -> str:
        return getattr(os, "sep", "/")

    def _path_join(self, *parts: str) -> str:
        sep = self._path_sep()
        cleaned = []
        for part in parts:
            if part is None:
                continue
            part = str(part)
            if not part:
                continue
            part = part.replace("\\", "/")
            if cleaned:
                part = part.lstrip("/")
            cleaned.append(part.rstrip("/"))
        if not cleaned:
            return ""
        joined = "/".join(cleaned)
        if sep != "/":
            joined = joined.replace("/", sep)
        return joined

    def _path_dirname(self, path: str) -> str:
        normalized = str(path).replace("\\", "/")
        if "/" not in normalized:
            return ""
        return normalized.rsplit("/", 1)[0] or "/"

    def _path_basename(self, path: str) -> str:
        normalized = str(path).replace("\\", "/")
        return normalized.rsplit("/", 1)[-1]

    def _is_host(self) -> bool:
        return sys.implementation.name != "micropython"

    def _normalize_host_path(self, path: str, default_rel: str) -> str:
        if not path:
            return self._path_join(os.getcwd(), default_rel)
        if path.startswith("/sd"):
            return self._path_join(os.getcwd(), "sd")
        if path.startswith("/local"):
            return self._path_join(os.getcwd(), "local", self._path_basename(path))
        return path

    def _has_fallback_entries(self) -> bool:
        """
        Check if fallback file has any entries (non-blocking).

        Used to detect SD reconnection with pending entries.
        Returns True if fallback file is non-empty.

        Returns:
            bool: True if fallback has entries, False otherwise
        """
        try:
            with open(self.fallback_path, "r") as f:
                first_char = f.read(1)
                return len(first_char) > 0
        except Exception:
            return False

    def has_data_for(self, relpath: str) -> bool:
        """
        Check whether data for *relpath* already exists anywhere.

        Looks in primary (SD), fallback file, and in-memory buffers.
        Useful to avoid writing duplicate CSV headers on repeated reboots
        while SD is down.

        Args:
            relpath: Relative path (e.g. 'dht_log_2026-02-16.csv')

        Returns:
            True if data for this relpath already exists somewhere.
        """
        if relpath.startswith("/sd/"):
            relpath = relpath[4:]

        # 1. Check primary
        primary_path = f"{self.sd_mount_point}/{relpath}"
        try:
            with open(primary_path, "r") as f:
                if f.read(1):
                    return True
        except Exception:
            pass

        # 2. Check in-memory buffers
        if relpath in self._buffers and self._buffers[relpath]:
            return True

        # 3. Check fallback file for entries tagged with this relpath
        try:
            with open(self.fallback_path, "r") as f:
                for line in f:
                    if line.startswith(f"{relpath}|"):
                        return True
        except Exception:
            pass

        return False

    def write(self, relpath: str, data: str) -> bool:
        """
        Append data to file on primary, or fallback if primary unavailable.

        CRITICAL: Maintains chronological ordering when SD reconnects.
        If fallback entries exist and primary becomes available, migrates fallback FIRST
        before accepting new writes to primary. This ensures CSV entries remain ordered.

        Attempts to write directly to primary (SD).
        If primary write fails (SD disconnected), writes to fallback file instead.
        If fallback also fails, buffers in memory and returns False.

        Args:
            relpath (str): Relative path from SD mount or local root (e.g., 'dht_log.csv' or '/sd/dht_log.csv')
            data (str): Data to append (should include newline if needed)

        Returns:
            bool: True if written to primary, False if written to fallback or buffered

        Example:
            >>> bm = BufferManager()
            >>> bm.write('dht_log.csv', '2026-01-29 14:35:00,22.5,65.0\n')
            True  # Written to primary SD
            >>> # Later, if SD disconnects:
            >>> bm.write('dht_log.csv', '2026-01-29 14:36:00,22.6,65.2\n')
            False  # Written to fallback instead
            >>> # And if SD reconnects before next write:
            >>> bm.write('dht_log.csv', '2026-01-29 14:37:00,22.7,65.3\n')
            # Fallback entries migrated first, then new entry written (maintains order!)
        """
        # Normalize path
        if relpath.startswith("/sd/"):
            relpath = relpath[4:]  # Remove '/sd/' prefix for consistent handling

        primary_path = f"{self.sd_mount_point}/{relpath}"

        # CRITICAL ORDERING: If primary is available, migrate pending data BEFORE accepting new writes.
        # 1. Migrate fallback entries (SD was disconnected, now reconnected)
        # 2. Flush in-memory buffer (both primary and fallback were unavailable, now primary is back)
        # This prevents out-of-order timestamps in CSV files.
        #
        # Cache the availability check: is_primary_available() performs a
        # full create-write-read-delete cycle on /sd/.test over SPI.
        # Calling it once per write() instead of 2-4 times dramatically
        # reduces SD I/O and avoids timing-related false negatives that
        # silently route data to fallback.
        primary_ok = self.is_primary_available()

        if primary_ok:
            if self._has_fallback_entries():
                self.migrate_fallback()
            if self._buffers:
                self.flush()

        # Try primary first
        if primary_ok:
            try:
                with open(primary_path, "a") as f:
                    f.write(data)
                self.writes_to_primary += 1
                return True
            except Exception:
                # Primary write failed (e.g., file locked, permissions)
                pass

        # Primary unavailable or write failed; try fallback file first,
        # RAM buffer only as absolute last resort.
        try:
            if not self._ensure_fallback_dir():
                raise OSError("fallback dir unavailable")

            # Drain any existing RAM entries to fallback before the new
            # entry so chronological ordering is preserved.
            if relpath in self._buffers and self._buffers[relpath]:
                with open(self.fallback_path, "a") as f:
                    for buffered in self._buffers[relpath]:
                        f.write(f"{relpath}|{buffered}")
                self.writes_to_fallback += len(self._buffers[relpath])
                self._buffers[relpath] = []

            with open(self.fallback_path, "a") as f:
                f.write(f"{relpath}|{data}")  # Include relpath in fallback for migration
            self.writes_to_fallback += 1
            return False
        except Exception:
            # Both primary and fallback failed; buffer in RAM as last resort
            if relpath not in self._buffers:
                self._buffers[relpath] = []
            self._buffers[relpath].append(data)

            # Check buffer overflow
            buffer_size = sum(len(v) for v in self._buffers.values())
            if buffer_size > self.max_buffer_entries:
                # Overflow: drop oldest entry
                for path_key, entries in self._buffers.items():
                    if entries:
                        entries.pop(0)
                        break

            self.write_failures += 1
            return False

    def flush(self, relpath: str | None = None) -> bool:
        """
        Flush in-memory buffers to persistent storage.

        Tries primary (SD) first.  When primary is unavailable, drains
        in-memory entries to the local fallback file so that RAM is freed
        as quickly as possible.  RAM should only hold data while *both*
        primary and fallback are unreachable.

        If relpath specified, flush only that file's buffer.
        If relpath is None, flush all buffers.

        Args:
            relpath (str, optional): Specific file path to flush, or None for all

        Returns:
            bool: True if flushed to primary, False if flushed to fallback or
                  still in memory

        Example:
            >>> bm.flush('dht_log.csv')  # Flush specific file
            False  # Primary still unavailable (went to fallback)
            >>> # ... SD card becomes available ...
            >>> bm.flush('dht_log.csv')
            True  # Flushed to primary
        """
        paths_to_flush = [relpath] if relpath else list(self._buffers.keys())
        flushed_to_primary = False
        primary_available = self.is_primary_available()

        for path in paths_to_flush:
            if path not in self._buffers or not self._buffers[path]:
                continue

            if primary_available:
                clean = path[4:] if path.startswith("/sd/") else path
                primary_path = f"{self.sd_mount_point}/{clean}"
                try:
                    with open(primary_path, "a") as f:
                        for entry in self._buffers[path]:
                            f.write(entry)
                    self._buffers[path] = []
                    flushed_to_primary = True
                    continue
                except Exception:
                    pass  # Fall through to fallback

            # Primary unavailable or write failed — drain to fallback file
            if self._ensure_fallback_dir():
                try:
                    with open(self.fallback_path, "a") as f:
                        for entry in self._buffers[path]:
                            f.write(f"{path}|{entry}")
                    self.writes_to_fallback += len(self._buffers[path])
                    self._buffers[path] = []
                except Exception:
                    pass  # Entries stay in RAM as last resort

        return flushed_to_primary

    def migrate_fallback(self) -> int:
        """
        Attempt to migrate all entries from fallback file to primary.

        Reads fallback file, extracts relpath and data, writes to primary.
        Clears fallback file on success.

        Used when SD becomes available after disconnection.

        Returns:
            int: Number of entries migrated, 0 if primary unavailable or fallback empty

        Example:
            >>> # After SD reconnection:
            >>> bm.migrate_fallback()
            5  # Migrated 5 entries
        """
        if not self.is_primary_available():
            return 0

        try:
            entries_migrated = 0
            lines = []

            # Read fallback file
            try:
                with open(self.fallback_path, "r") as f:
                    lines = f.readlines()
            except Exception:
                return 0

            if not lines:
                return 0

            # Migrate each entry
            for line in lines:
                try:
                    if "|" not in line:
                        continue

                    relpath, data = line.split("|", 1)
                    primary_path = f"{self.sd_mount_point}/{relpath}"

                    with open(primary_path, "a") as f:
                        f.write(data)

                    entries_migrated += 1
                except Exception:
                    pass  # Skip malformed entries

            # Clear fallback file on success
            if entries_migrated > 0:
                try:
                    with open(self.fallback_path, "w") as f:
                        f.write("")
                    self.fallback_migrations += 1
                except Exception:
                    pass

            return entries_migrated
        except Exception:
            return 0

    def rename(self, old_relpath: str, new_relpath: str) -> bool:
        """
        Rename a file on the primary (SD) storage.

        Resolves relative paths against the SD mount point and performs
        a rename operation. Used by EventLogger for log rotation.
        MicroPython fallback: copy content then delete original.

        Args:
            old_relpath (str): Current relative path (e.g., 'system.log')
            new_relpath (str): Desired relative path (e.g., 'system_2026-02-16_143022.log')

        Returns:
            bool: True if rename succeeded, False otherwise
        """
        if old_relpath.startswith("/sd/"):
            old_relpath = old_relpath[4:]
        if new_relpath.startswith("/sd/"):
            new_relpath = new_relpath[4:]

        old_path = self._path_join(self.sd_mount_point, old_relpath)
        new_path = self._path_join(self.sd_mount_point, new_relpath)

        try:
            # Try os.rename first (CPython/most systems)
            if hasattr(os, "rename"):
                os.rename(old_path, new_path)  # type: ignore
            else:
                # MicroPython fallback: copy then delete
                with open(old_path, "r") as src:
                    content = src.read()
                with open(new_path, "w") as dst:
                    dst.write(content)
                os.remove(old_path)
            return True
        except Exception as e:
            print(f"[BufferManager] WARNING: rename failed {old_path} -> {new_path}: {e}")
            return False

    def get_metrics(self) -> dict:
        """
        Return usage metrics for logging/debugging.

        Returns:
            dict: {writes_primary, writes_fallback, migrations, failures, buffer_sizes}
        """
        buffer_sizes = {k: len(v) for k, v in self._buffers.items()}

        return {
            "writes_to_primary": self.writes_to_primary,
            "writes_to_fallback": self.writes_to_fallback,
            "fallback_migrations": self.fallback_migrations,
            "write_failures": self.write_failures,
            "buffer_entries": sum(len(v) for v in self._buffers.values()),
            "buffer_sizes_per_file": buffer_sizes,
        }
