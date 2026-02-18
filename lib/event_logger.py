# Event Logger - System Event Logging with DI
# Dennis Hiro, 2026-01-29
#
# Refactored from original main.py.
# Uses dependency injection for TimeProvider and BufferManager.
# Decoupled from global RTC and SD initialization.


class EventLogger:
    """
    Centralized system event logger.

    Logs events to console and SD card (via BufferManager) with timestamps.
    Supports three severity levels: info, warning, error.
    Implements buffering and log rotation.

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

        print(f"[EventLogger] Initialized: {self.logfile}")

    def _get_timestamp(self) -> str:
        """
        Get formatted timestamp from TimeProvider.

        Returns:
            str: Timestamp 'YYYY-MM-DD HH:MM:SS' or 'TIME_ERROR' if provider fails
        """
        try:
            return self.time_provider.now_timestamp()
        except Exception:
            return "TIME_ERROR"

    def info(self, module: str, message: str) -> None:
        """
        Log informational message (low severity).

        Args:
            module (str): Module/component name
            message (str): Log message
        """
        timestamp = self._get_timestamp()
        log_entry = f"[{timestamp}] [INFO] [{module}] {message}\n"
        print(log_entry.rstrip())
        self.buffer.append(log_entry)

        if len(self.buffer) >= self.info_flush_threshold:
            self.flush()

    def warning(self, module: str, message: str) -> None:
        """
        Log warning message (medium severity).

        Args:
            module (str): Module/component name
            message (str): Warning message
        """
        timestamp = self._get_timestamp()
        log_entry = f"[{timestamp}] [WARN] [{module}] {message}\n"
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
        timestamp = self._get_timestamp()
        log_entry = f"[{timestamp}] [ERR] [{module}] {message}\n"
        print(log_entry.rstrip())
        self.buffer.append(log_entry)
        self.flush()  # Flush errors immediately

        if self.status_manager is not None:
            self.status_manager.set_error("logged_error", True)

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
            self.buffer = []
            return

        try:
            # Normalize logfile path (strip only '/sd/' prefix)
            relpath = self._strip_sd_prefix(self.logfile)

            for entry in self.buffer:
                self.buffer_manager.write(relpath, entry)
                self._log_size += len(entry)

            self.flush_count += 1
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
        if self._log_size > self.max_size:
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
