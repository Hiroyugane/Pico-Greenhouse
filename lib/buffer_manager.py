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
import time


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

    def __init__(
        self,
        sd_mount_point="/sd",
        fallback_path="/local/fallback.csv",
        max_buffer_entries=1000,
        max_fallback_size_kb=50,
        debug_callback=None,
        logger=None,
    ):
        """
        Initialize BufferManager with SD and fallback paths.

        Does NOT attempt to create or validate files at init (deferred to first write).
        This allows system to start even if storage is partially unavailable.

        Args:
            sd_mount_point (str): Mount point for SD card (default: '/sd')
            fallback_path (str): Local fallback file path (default: '/local/fallback.csv')
            max_buffer_entries (int): Max in-memory buffer size (default: 1000)
            max_fallback_size_kb (int): Emergency fallback file size limit in KB (default: 50)
            debug_callback: Optional callable(str) for debug output (avoids circular dep with EventLogger)
            logger: Optional EventLogger for debug/diagnostic messages (default: None)
        """
        # Host compatibility: map /sd and /local to local folders on CPython
        if self._is_host():
            sd_mount_point = self._normalize_host_path(sd_mount_point, "sd")
            fallback_path = self._normalize_host_path(fallback_path, "local/fallback.csv")

        self.sd_mount_point = sd_mount_point
        self.fallback_path = fallback_path
        self.max_buffer_entries = max_buffer_entries
        self.max_fallback_size_kb = max_fallback_size_kb
        self._debug = debug_callback
        self._logger = logger

        if self._is_host():
            try:
                os.makedirs(self.sd_mount_point, exist_ok=True)
            except Exception:
                pass

        # Internal buffers: per-file in-memory storage
        self._buffers = {}  # {relpath: [entry1, entry2, ...]}

        # Re-entrancy guard: when True, _log_debug uses print() instead of
        # self._logger.debug() to prevent feedback loops with EventLogger.
        self._in_io = False

        # Metrics
        self.writes_to_primary = 0
        self.writes_to_fallback = 0
        self.fallback_migrations = 0
        self.write_failures = 0

        # Primary availability cache: prevents blocking I/O on every write check
        # cache TTL = 5 seconds (configurable, balances responsiveness vs. I/O overhead)
        self._primary_avail_cache = None
        self._primary_avail_cache_time = 0
        self._primary_avail_cache_ttl_s = 5

    def is_primary_available(self) -> bool:
        """
        Check whether SD mount is accessible (with caching to prevent event loop blocking).

        CRITICAL: Performs a write-then-read-verify to confirm writable access only when
        cache has expired. Caching prevents repeated blocking I/O that can starve the
        event loop on slow/unresponsive SD cards. Result is cached for 5 seconds or
        can be manually invalidated.

        The blocking I/O is only performed once every TTL (default 5s), not on every
        write check. This prevents the health-check loop from blocking if the SD card
        is slow to respond.

        Returns:
            bool: True if SD mount is available and writable, False otherwise
        """
        now = time.time()

        # Return cached result if still valid
        cache_age = now - self._primary_avail_cache_time
        if self._primary_avail_cache is not None and cache_age < self._primary_avail_cache_ttl_s:
            self._log_debug(
                "is_primary_available cached",
                available=self._primary_avail_cache,
                age_s=round(cache_age, 1),
            )
            return self._primary_avail_cache

        # Cache expired; perform actual check
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
            available = readback == test_data
            ttl_str = f"{self._primary_avail_cache_ttl_s}s"
            self._log_debug(
                "is_primary_available check",
                available=available,
                cached_for=ttl_str,
            )
            self._primary_avail_cache = available
            self._primary_avail_cache_time = now
            return available
        except Exception as e:
            self._log_debug("is_primary_available failed", error=str(e))
            self._primary_avail_cache = False
            self._primary_avail_cache_time = now
            return False

    def set_logger(self, logger) -> None:
        """
        Set logger after construction (EventLogger is created after BufferManager).

        Args:
            logger: EventLogger instance for debug/diagnostic messages
        """
        self._logger = logger

    def invalidate_primary_cache(self) -> None:
        """
        Invalidate the SD availability cache.

        Forces the next is_primary_available() call to perform a fresh check.
        Useful when the caller detects the SD card was ejected/reinserted.

        Example:
            >>> bm.invalidate_primary_cache()
            >>> # Next write will force a fresh SD check
        """
        self._primary_avail_cache = None
        self._primary_avail_cache_time = 0
        self._log_debug("primary availability cache invalidated")

    def _log_debug(self, message: str, **fields) -> None:
        """Log debug message if logger is available.

        Uses print() instead of the injected logger when inside a write()
        or flush() call to prevent a feedback loop: EventLogger.flush() →
        BufferManager.write() → _log_debug → EventLogger.debug() → buffer
        grows → next flush writes even more BufferManager debug lines → ∞

        Also invokes the legacy debug_callback (self._debug) when set, so
        callers that injected a callback at construction still receive messages.
        """
        if self._logger and not self._in_io:
            self._logger.debug("BufferMgr", message, **fields)
        else:
            if fields:
                field_str = " ".join(f"{k}={v}" for k, v in fields.items())
                formatted = f"{message} | {field_str}"
            else:
                formatted = message
            # Route through debug_callback if available, otherwise print
            if self._debug:
                self._debug(formatted)
            else:
                print(f"[BufferManager][DEBUG] {formatted}")

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
                self._log_debug("creating fallback dir", path=fallback_dir)
                self._mkdirs(fallback_dir)
            return True
        except Exception as e:
            self._log_debug("fallback dir creation failed", error=str(e))
            return False

    def _mkdirs(self, path: str) -> None:
        """Create nested directories using os.mkdir for MicroPython compatibility."""
        if not path or path == ".":
            return

        normalized = path.replace("\\", "/")
        parts = [p for p in normalized.split("/") if p]
        current = "/" if normalized.startswith("/") else ""

        for part in parts:
            current = self._path_join(current, part) if current else part
            if self._dir_exists(current):
                continue
            os.mkdir(current)

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
        return getattr(sys.implementation, "name", "") != "micropython"

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
            relpath = relpath[4:]  # Remove '/sd/' prefix for consistent handling

        # 1. Check primary
        primary_path = f"{self.sd_mount_point}/{relpath}"
        try:
            with open(primary_path, "r") as f:
                if f.read(1):
                    self._log_debug("has_data_for", relpath=relpath, found_in="primary")
                    return True
        except Exception:
            pass

        # 2. Check in-memory buffers
        if relpath in self._buffers and self._buffers[relpath]:
            self._log_debug("has_data_for", relpath=relpath, found_in="buffer")
            return True

        # 3. Check fallback file for entries tagged with this relpath
        try:
            with open(self.fallback_path, "r") as f:
                for line in f:
                    if line.startswith(f"{relpath}|"):
                        self._log_debug("has_data_for", relpath=relpath, found_in="fallback")
                        return True
        except Exception:
            pass

        self._log_debug("has_data_for", relpath=relpath, found_in="none")
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

        self._in_io = True
        try:
            return self._write_inner(relpath, primary_path, data)
        finally:
            self._in_io = False

    def _write_inner(self, relpath: str, primary_path: str, data: str) -> bool:
        """Inner write logic (called with _in_io guard held)."""
        self._log_debug("write entry", relpath=relpath, data_len=len(data))

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

        self._log_debug("write routing", relpath=relpath, primary_ok=primary_ok)

        if primary_ok:
            if self._has_fallback_entries():
                if self._debug:
                    self._debug("write: migrating fallback entries before primary write")
                self.migrate_fallback()
            if self._buffers:
                if self._debug:
                    self._debug(f"write: flushing {sum(len(v) for v in self._buffers.values())} RAM entries")
                self.flush()

        # Try primary first
        if primary_ok:
            try:
                with open(primary_path, "a") as f:
                    f.write(data)
                self.writes_to_primary += 1
                self._log_debug(
                    "write completed",
                    tier="primary",
                    relpath=relpath,
                    writes_primary=self.writes_to_primary,
                )
                return True
            except Exception as exc:
                # Primary write failed (e.g., file locked, permissions)
                if self._debug:
                    self._debug(f"write: primary FAILED despite ok=True ({exc})")
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
                drained = len(self._buffers[relpath])
                self.writes_to_fallback += drained
                self._buffers[relpath] = []
                if self._debug:
                    self._debug(f"write: drained {drained} RAM entries to fallback")

            with open(self.fallback_path, "a") as f:
                f.write(f"{relpath}|{data}")  # Include relpath in fallback for migration
            self.writes_to_fallback += 1
            
            # Emergency pruning: if fallback exceeds max size, delete oldest entries
            self._emergency_prune_fallback()
            
            self._log_debug(
                "write completed",
                tier="fallback",
                relpath=relpath,
                writes_fallback=self.writes_to_fallback,
            )
            return False
        except Exception as exc:
            # Both primary and fallback failed; buffer in RAM as last resort
            if self._debug:
                self._debug(f"write: both FAILED ({exc}), buffering in RAM")
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
                        self._log_debug(
                            "buffer overflow",
                            buffer_size=buffer_size,
                            max=self.max_buffer_entries,
                            dropped_from=path_key,
                        )
                        break

            self.write_failures += 1
            self._log_debug(
                "write completed",
                tier="ram",
                relpath=relpath,
                write_failures=self.write_failures,
                buffer_entries=buffer_size if "buffer_size" in dir() else len(self._buffers.get(relpath, [])),
            )
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

        self._in_io = True
        try:
            primary_available = self.is_primary_available()
            return self._flush_inner(paths_to_flush, primary_available)
        finally:
            self._in_io = False

    def _flush_inner(self, paths_to_flush: list, primary_available: bool) -> bool:
        """Inner flush logic (called with _in_io guard held)."""
        flushed_to_primary = False

        self._log_debug(
            "flush start",
            paths=str(paths_to_flush),
            primary_available=primary_available,
        )

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
                    entry_count = len(self._buffers[path])
                    self._buffers[path] = []
                    flushed_to_primary = True
                    self._log_debug(
                        "flush to primary",
                        path=path,
                        entries=entry_count,
                    )
                    continue
                except Exception as exc:
                    if self._debug:
                        self._debug(f"flush: primary write FAILED for {path} ({exc})")
                    pass  # Fall through to fallback

            # Primary unavailable or write failed — drain to fallback file
            if self._ensure_fallback_dir():
                try:
                    entry_count = len(self._buffers[path])
                    with open(self.fallback_path, "a") as f:
                        for entry in self._buffers[path]:
                            f.write(f"{path}|{entry}")
                    if self._debug:
                        self._debug(f"flush: {len(self._buffers[path])} entries -> fallback for {path}")
                    self.writes_to_fallback += len(self._buffers[path])
                    self._buffers[path] = []
                    self._log_debug(
                        "flush to fallback",
                        path=path,
                        entries=entry_count,
                    )
                except Exception:
                    self._log_debug("flush failed, entries stay in RAM", path=path)
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
        """
        self._in_io = True
        try:
            return self._migrate_fallback_inner()
        finally:
            self._in_io = False

    def _migrate_fallback_inner(self) -> int:
        """Inner migration logic (called with _in_io guard held)."""
        if not self.is_primary_available():
            self._log_debug("SD not available during migration")
            return 0

        try:
            entries_migrated = 0
            lines = []

            # Read fallback file
            try:
                with open(self.fallback_path, "r") as f:
                    lines = f.readlines()
            except Exception as e:
                self._log_debug(f"Failed to read fallback file: {e}")
                return 0

            if not lines:
                self._log_debug("No lines to migrate from fallback")
                return 0

            if self._debug:
                self._debug(f"migrate_fallback: {len(lines)} lines to migrate")

            # Migrate each entry
            for line in lines:
                try:
                    if "|" not in line:
                        self._log_debug(f"Malformed fallback line: {line.strip()}")
                        continue

                    relpath, data = line.split("|", 1)
                    primary_path = f"{self.sd_mount_point}/{relpath}"
                    self._log_debug(f"Migrating to {primary_path}: {data.strip()}")

                    with open(primary_path, "a") as f:
                        f.write(data)

                    entries_migrated += 1
                except Exception as e:
                    self._log_debug(f"Failed to migrate line: {line.strip()} | Error: {e}")

            # Clear fallback file on success
            if entries_migrated > 0:
                try:
                    with open(self.fallback_path, "w") as f:
                        f.write("")
                    self.fallback_migrations += 1
                    self._log_debug(
                        "fallback cleared",
                        entries_migrated=entries_migrated,
                    )
                except Exception as e:
                    self._log_debug(f"Failed to clear fallback after migration: {e}")

            self._log_debug("Migration complete", entries_migrated=entries_migrated)
            return entries_migrated
        except Exception as e:
            self._log_debug(f"Migration failed: {e}")
            return 0

    def _emergency_prune_fallback(self) -> None:
        """
        Emergency pruning of fallback file when it exceeds max size limit.

        When /local/ filesystem is nearly full, prevent disk exhaustion by
        deleting oldest entries from fallback file. This prevents cascading
        write failures that starve the event loop.

        Removes oldest entries (lines) first until file size is below 80% of max.
        Logs warnings on each prune cycle.

        Called automatically after each fallback write.
        """
        try:
            max_bytes = self.max_fallback_size_kb * 1024
            file_size = self._get_file_size(self.fallback_path)

            if file_size is None or file_size < max_bytes:
                return  # Within limit, no pruning needed

            # File exceeds max; read, trim oldest entries, rewrite
            try:
                with open(self.fallback_path, "r") as f:
                    lines = f.readlines()
            except Exception:
                return  # Can't read fallback, skip pruning

            if not lines:
                return

            # Log warning: fallback is getting dangerously large
            self._log_debug(
                "fallback size warning",
                current_bytes=file_size,
                max_bytes=max_bytes,
                line_count=len(lines),
            )
            if self._logger:
                self._logger.warning(
                    "BufferMgr",
                    f"Fallback file size {file_size//1024}KB exceeds {self.max_fallback_size_kb}KB; pruning oldest entries",
                )

            # Remove oldest entries until file is below target (80% of max)
            target_bytes = int(max_bytes * 0.8)
            current_size = file_size

            kept_lines = []
            for line in reversed(lines):  # Start from newest
                line_bytes = len(line.encode() if isinstance(line, str) else line)
                if current_size - line_bytes > target_bytes:
                    current_size -= line_bytes
                else:
                    kept_lines.append(line)

            # Rewrite fallback with only kept (newest) entries
            try:
                with open(self.fallback_path, "w") as f:
                    for line in reversed(kept_lines):
                        f.write(line)

                pruned_count = len(lines) - len(kept_lines)
                self._log_debug(
                    "fallback pruned",
                    removed_lines=pruned_count,
                    kept_lines=len(kept_lines),
                    new_size=current_size,
                )
                if self._logger:
                    self._logger.info(
                        "BufferMgr",
                        f"Pruned {pruned_count} oldest entries from fallback ({len(kept_lines)} remaining)",
                    )
            except Exception as e:
                self._log_debug("fallback prune write failed", error=str(e))
        except Exception as e:
            # Silently fail pruning to avoid recursive exceptions
            self._log_debug("emergency prune error", error=str(e))

    def rename(self, old_relpath: str, new_relpath: str) -> bool:
        """
        Rename a file on the primary (SD) storage.

        Resolves relative paths against the SD mount point and performs
        a rename operation. Used by EventLogger for log rotation.

        Always uses copy-then-delete approach to ensure atomicity and data safety:
        data is written to new file first, then old file is deleted only after
        successful copy. This prevents data loss if rename fails partway through.

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

        _CHUNK = 512
        copy_ok = False
        try:
            # Chunked copy-then-delete: avoids allocating the entire file as a
            # single contiguous string on MicroPython's heap (heap fragmentation
            # would cause a memory allocation failure for files > ~13 KB).
            with open(old_path, "r") as src:
                with open(new_path, "w") as dst:
                    while True:
                        chunk = src.read(_CHUNK)
                        if not chunk:
                            break
                        dst.write(chunk)
            copy_ok = True
            os.remove(old_path)
            self._log_debug("rename succeeded", old=old_relpath, new=new_relpath)
            return True
        except Exception as e:
            # If the copy was incomplete, remove the partial destination file so
            # the next rotation attempt starts fresh.
            if not copy_ok:
                try:
                    os.remove(new_path)
                except Exception:
                    pass
            if self._logger:
                self._logger.warning("BufferMgr", f"rename failed {old_path} -> {new_path}: {e}")
            else:
                print(f"[BufferManager] WARNING: rename failed {old_path} -> {new_path}: {e}")
            return False

    def get_primary_file_size(self, relpath: str):
        """
        Return file size (bytes) on primary storage, or None if unavailable.

        Args:
            relpath (str): Relative path (e.g., 'system.log') or '/sd/system.log'
        """
        if relpath.startswith("/sd/"):
            relpath = relpath[4:]

        primary_path = self._path_join(self.sd_mount_point, relpath)

        try:
            st = os.stat(primary_path)
            # MicroPython returns a tuple; CPython returns an os.stat_result
            if isinstance(st, tuple):
                size = int(st[6]) if len(st) > 6 else None
            else:
                size = int(st.st_size)
            self._log_debug("get_primary_file_size", relpath=relpath, size=size)
            return size
        except Exception:
            self._log_debug("get_primary_file_size unavailable", relpath=relpath)
            return None

    def _get_file_size(self, path: str):
        """
        Return file size in bytes for any file path, or None if unavailable.

        Args:
            path (str): Full file path

        Returns:
            int or None: File size in bytes, or None if stat fails
        """
        try:
            st = os.stat(path)
            # MicroPython returns a tuple; CPython returns an os.stat_result
            if isinstance(st, tuple):
                return int(st[6]) if len(st) > 6 else None
            else:
                return int(st.st_size)
        except Exception:
            return None

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
