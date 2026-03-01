# Event Logger - System Event Logging with DI
# Dennis Hiro, 2026-01-29
#
# Refactored from original main.py.
# Uses dependency injection for TimeProvider and BufferManager.
# Decoupled from global RTC and SD initialization.

# ── Log-level constants ──────────────────────────────────────────────
LOG_DEBUG = 0
LOG_INFO = 1
LOG_WARN = 2
LOG_ERR = 3

LEVEL_NAMES = {
    "DEBUG": LOG_DEBUG,
    "INFO": LOG_INFO,
    "WARN": LOG_WARN,
    "ERR": LOG_ERR,
}


class EventLogger:
    """
    Centralized system event logger.

    Logs events to console and SD card (via BufferManager) with timestamps.
    Supports four severity levels: debug, info, warning, error.
    Implements buffering, log-level gating, and log rotation.

    Level gating (``log_level``):
        DEBUG < INFO < WARN < ERR.  Messages below the configured level
        are silently discarded (applies to info/warning; debug uses
        ``debug_enabled``).

    Debug-to-file (``debug_to_file``):
        When *False* (default), ``debug()`` messages are printed to the
        console but never buffered or written to SD — keeping the card
        lean in normal operation.  Set *True* to persist debug output.

    Dependencies injected:
    - time_provider: For consistent timestamp formatting
    - buffer_manager: For resilient writes (SD with fallback)

    Attributes:
        time_provider: TimeProvider instance
        buffer_manager: BufferManager instance
        logfile: Path to system log file
        max_size: Max file size before rotation (bytes)
        buffer: In-memory buffer for log entries (flushed periodically)
        flush_count: Number of successful flush operations
        debug_enabled: Whether debug messages are printed to console
        debug_to_file: Whether debug messages are also written to SD
    """

    def __init__(
        self,
        time_provider,
        buffer_manager,
        logfile="/sd/system.log",
        max_size=50000,
        status_manager=None,
        info_flush_threshold: int = 5,
        warn_flush_threshold: int = 3,
        log_level: str = "INFO",
        debug_enabled: bool = False,
        debug_to_file: bool = False,
    ):
        """
        Initialize EventLogger with dependency injection.

        Does not attempt to create log file (deferred to first write).

        Args:
            time_provider: TimeProvider instance for timestamps
            buffer_manager: BufferManager instance for writes
            logfile (str): Path to log file (default: '/sd/system.log')
            max_size (int): Max log size before rotation in bytes (default: 50000)
            status_manager: StatusManager instance for LED feedback (optional)
            info_flush_threshold (int): Flush after N info entries buffered (default: 5)
            warn_flush_threshold (int): Flush after N warning entries buffered (default: 3)
            log_level (str): Minimum level to emit — "DEBUG", "INFO", "WARN", or "ERR" (default: "INFO")
            debug_enabled (bool): Enable debug messages to console (default: False)
            debug_to_file (bool): Also write debug messages to SD log (default: False)
        """
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.logfile = logfile
        self.max_size = max_size
        self.buffer = []
        self.flush_count = 0
        self._log_size = 0
        self.status_manager = status_manager
        self.info_flush_threshold = info_flush_threshold
        self.warn_flush_threshold = warn_flush_threshold
        self._level = LEVEL_NAMES.get(log_level, LOG_INFO)
        self.debug_enabled = debug_enabled
        self.debug_to_file = debug_to_file

        self._refresh_log_size()
        print(f"[EventLogger] Initialized: {self.logfile} (level={log_level})")
        if self.debug_enabled:
            print(
                f"[EventLogger][DEBUG] init config | logfile={self.logfile} max_size={self.max_size} "
                f"info_flush={info_flush_threshold} warn_flush={warn_flush_threshold} "
                f"debug_enabled={debug_enabled} debug_to_file={debug_to_file}"
            )

    def _refresh_log_size(self) -> None:
        """Refresh cached log size from primary storage when available."""
        if self.buffer_manager is None:
            return
        relpath = self._strip_sd_prefix(self.logfile)
        size = self.buffer_manager.get_primary_file_size(relpath)
        if size is not None:
            self._log_size = size
        if self.debug_enabled:
            print(f"[EventLogger][DEBUG] refresh log size | relpath={relpath} size={size}")

    # ── Formatting helpers ────────────────────────────────────────────

    def _get_timestamp(self) -> str:
        """
        Get formatted timestamp from TimeProvider.

        Returns:
            str: Timestamp 'YYYY-MM-DD HH:MM:SS' or 'TIME_ERROR' if provider fails
        """
        try:
            return self.time_provider.now_timestamp()
        except Exception as exc:
            # Use raw print to avoid recursion through debug()
            print(f"[EventLogger] _get_timestamp error: {exc}")
            return "TIME_ERROR"

    def _format(self, level_tag: str, module: str, message: str) -> str:
        """
        Build a formatted log line.

        Args:
            level_tag: One of "DEBUG", "INFO", "WARN", "ERR"
            module: Module/component name
            message: Log message

        Returns:
            str: Formatted log entry with trailing newline
        """
        timestamp = self._get_timestamp()
        return f"[{timestamp}] [{level_tag}] [{module}] {message}\n"

    # ── Public logging methods ────────────────────────────────────────

    def info(self, module: str, message: str) -> None:
        """
        Log informational message (low severity).

        Args:
            module (str): Module/component name
            message (str): Log message
        """
        if self._level > LOG_INFO:
            return
        log_entry = self._format("INFO", module, message)
        print(log_entry.rstrip())
        self.buffer.append(log_entry)

        if len(self.buffer) >= self.info_flush_threshold:
            self.flush()

    def debug(self, module: str, message: str, **fields) -> None:
        """
        Log debug message with optional structured fields.

        Console-only by default. Only written to SD when debug_to_file is True.
        Skipped entirely when debug_enabled is False (zero overhead).

        Debug entries support structured key=value fields for machine-parseable
        diagnostics that AI agents can analyze:

            logger.debug("FanController", "cycle tick",
                         temp=23.5, state="ON", elapsed_s=45)
            # → [2026-03-01 14:23:45] [DEBUG] [FanController] cycle tick | temp=23.5 state=ON elapsed_s=45

        Args:
            module (str): Module/component name
            message (str): Human-readable log message
            **fields: Optional key=value pairs appended after ' | '
        """
        if not self.debug_enabled:
            return

        timestamp = self._get_timestamp()
        if fields:
            field_str = " ".join(f"{k}={v}" for k, v in fields.items())
            log_entry = f"[{timestamp}] [DEBUG] [{module}] {message} | {field_str}\n"
        else:
            log_entry = f"[{timestamp}] [DEBUG] [{module}] {message}\n"

        print(log_entry.rstrip())

        if self.debug_to_file:
            self.buffer.append(log_entry)

    def warning(self, module: str, message: str) -> None:
        """
        Log warning message (medium severity).

        Args:
            module (str): Module/component name
            message (str): Warning message
        """
        if self._level > LOG_WARN:
            return
        log_entry = self._format("WARN", module, message)
        print(log_entry.rstrip())
        self.buffer.append(log_entry)

        if len(self.buffer) >= self.warn_flush_threshold:
            self.flush()

    def error(self, module: str, message: str) -> None:
        """
        Log error message (high severity).

        Triggers immediate flush to ensure error is persisted.

        Args:
            module (str): Module/component name
            message (str): Error message
        """
        # error() is never gated — always emitted regardless of _level
        log_entry = self._format("ERR", module, message)
        print(log_entry.rstrip())
        self.buffer.append(log_entry)
        self.flush()  # Flush errors immediately

        if self.status_manager is not None:
            self.status_manager.set_error("logged_error", True)

    # ── Flush / rotation ──────────────────────────────────────────────

    def flush(self) -> None:
        """
        Write all buffered log entries to storage via BufferManager.

        If BufferManager not yet available, logs to stdout only.
        Attempts primary (SD) write; falls back to fallback file if SD unavailable.
        """
        if not self.buffer:
            return

        # If buffer_manager not yet initialized, skip persistent write
        if self.buffer_manager is None:
            count = len(self.buffer)
            self.buffer = []
            # Use raw print to avoid recursion
            print(f"[EventLogger] flush: discarded {count} entries (no buffer_manager)")
            return

        entry_count = len(self.buffer)
        try:
            # Normalize logfile path (strip only '/sd/' prefix)
            relpath = self._strip_sd_prefix(self.logfile)

            # Batch all entries into one write to avoid N SD probes per flush
            # (one is_primary_available() call instead of one per entry).
            combined = "".join(self.buffer)
            self.buffer_manager.write(relpath, combined)
            self._log_size += len(combined)

            self.flush_count += 1
            if self.debug_enabled:
                print(
                    f"[EventLogger][DEBUG] flush complete | entries={entry_count} "
                    f"relpath={relpath} flush_count={self.flush_count} log_size={self._log_size}"
                )
        except Exception as e:
            print(f"[EventLogger] WARNING: Error during flush: {e}")
        finally:
            self.buffer = []

    def check_size(self) -> None:
        """
        Check log file size and rotate if needed.

        When the log exceeds max_size the current file is renamed with a
        timestamp (e.g. system_2026-02-16_143022.log) and a fresh
        system.log is started on the next write — similar to Linux logrotate.
        """
        self._refresh_log_size()

        if self._log_size > self.max_size:
            if self.debug_enabled:
                print(
                    f"[EventLogger][DEBUG] log rotation triggered | log_size={self._log_size} max_size={self.max_size}"
                )
            try:
                # Flush any pending entries so the rotated file is complete
                self.flush()

                # Build a filesystem-safe timestamp for the archive name
                ts = self._get_timestamp().replace(" ", "_").replace(":", "")
                # e.g. 'system.log' -> 'system_2026-02-16_143022.log'
                rotated_name = self.logfile.replace(".log", f"_{ts}.log")

                relpath = self._strip_sd_prefix(self.logfile)
                rotated_relpath = self._strip_sd_prefix(rotated_name)

                renamed = self.buffer_manager.rename(relpath, rotated_relpath)

                self._log_size = 0

                if renamed:
                    self.info("EventLogger", f"Log rotated -> {rotated_name}")
                else:
                    self.info("EventLogger", "Log rotation rename failed; size counter reset")
            except Exception as e:
                print(f"[EventLogger] WARNING: Log rotation failed: {e}")

    @staticmethod
    def _strip_sd_prefix(path: str) -> str:
        if path.startswith("/sd/"):
            return path[4:]
        return path
