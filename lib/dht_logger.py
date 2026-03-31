# DHT Logger - Temperature/Humidity Logging with DI
# Dennis Hiro, 2026-01-29
#
# Refactored from original main.py.
# Uses dependency injection for TimeProvider, BufferManager, EventLogger.
# Decoupled from global state; supports hot-swap SD and date-based file rollover.

import sys
import time

import dht
import machine
import uasyncio as asyncio

try:
    _ticks_ms = time.ticks_ms  # MicroPython
except AttributeError:

    def _ticks_ms() -> int:  # CPython fallback
        return int(time.time() * 1000)


class DHTLogger:
    """
    DHT22 temperature/humidity sensor logger with SD hot-swap and date-based rollover.

    Reads DHT22 sensor and logs timestamped CSV entries.
    All storage resilience delegated to BufferManager:
    - Writes to primary (SD) when available
    - Falls back to fallback file when SD unavailable
    - Buffers in-memory when both unavailable
    - Auto-migrates fallback entries when SD reconnects

    Automatically rolls over CSV file at midnight.

    Dependencies injected:
    - time_provider: For timestamps and date-based rollover
    - buffer_manager: For all write operations (handles resilience)
    - logger: For event logging

    Attributes:
        dht_sensor: DHT22 sensor instance
        interval: Logging interval in seconds
        filename_base: CSV filename base
        time_provider: TimeProvider instance
        buffer_manager: BufferManager instance
        logger: EventLogger instance
        current_date: Current date (year, month, day) for rollover detection
        last_temperature: Cached temperature for thermostat queries
        last_humidity: Cached humidity reading
        read_failures: Count of sensor read failures
        write_failures: Count of failed writes
    """

    def __init__(
        self,
        pin,
        time_provider,
        buffer_manager,
        logger,
        interval=60,
        filename="dht_log.csv",
        max_retries=3,
        status_manager=None,
        dht_warn_threshold=3,
        dht_error_threshold=10,
        retry_delay_s: float = 0.5,
        max_history: int = 120,
    ):
        """
        Initialize DHTLogger with dependency injection.

        Args:
            pin (int): GPIO pin for DHT22 data line
            time_provider: TimeProvider instance
            buffer_manager: BufferManager instance
            logger: EventLogger instance
            interval (int): Logging interval in seconds (default: 60)
            filename (str): CSV filename (default: 'dht_log.csv')
            max_retries (int): Sensor read retries (default: 3)
            status_manager: StatusManager instance for LED feedback (optional)
            dht_warn_threshold (int): Consecutive failures before warning (default: 3)
            dht_error_threshold (int): Consecutive failures before error (default: 10)
            retry_delay_s (float): Delay between sensor read retries in seconds (default: 0.5)
            max_history (int): Maximum readings to keep for stats (default: 120)
        """
        self.dht_sensor = dht.DHT22(machine.Pin(pin))
        self.interval = interval
        self.filename_base = filename if filename.startswith("/sd/") else f"/sd/{filename}"
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.logger = logger
        self.max_retries = max_retries
        self.status_manager = status_manager
        self._dht_warn_threshold = dht_warn_threshold
        self._dht_error_threshold = dht_error_threshold
        self.retry_delay_s = retry_delay_s
        self._max_history = max_history

        # State
        self.last_temperature = None
        self.last_humidity = None
        self.read_failures = 0
        self.write_failures = 0
        self._consecutive_failures = 0
        self.current_date = None
        self._created_files = set()  # relpaths confirmed created this session
        # Bounded history for stats: list of (ticks_ms, temp, hum)
        self._readings_history = []
        self._temp_stats = {"now": None, "hi": None, "lo": None, "avg": None, "count": 0}
        self._hum_stats = {"now": None, "hi": None, "lo": None, "avg": None, "count": 0}
        self._reset_stats()

        # Initialize filename with current date
        self._update_filename_for_date()

        # Create CSV file if needed
        try:
            if not self._file_exists():
                self._create_file()
            logger.info("DHTLogger", f"Initialized: {self.filename}")
            logger.debug(
                "DHTLogger",
                "init config",
                pin=pin,
                interval=interval,
                max_retries=max_retries,
                dht_warn_threshold=dht_warn_threshold,
                dht_error_threshold=dht_error_threshold,
                retry_delay_s=retry_delay_s,
                filename=self.filename,
                has_status_mgr=status_manager is not None,
            )
        except Exception as e:
            logger.error("DHTLogger", f"Init error: {e}")

    def _update_filename_for_date(self) -> None:
        """
        Update log filename based on current RTC date.

        Format: dht_log_YYYY-MM-DD.csv (auto date-based rollover).
        """
        try:
            date_tuple = self.time_provider.now_date_tuple()
            year, month, day = date_tuple[0], date_tuple[1], date_tuple[2]
            self.current_date = (year, month, day)

            base = self.filename_base.replace(".csv", "")
            self.filename = f"{base}_{year:04d}-{month:02d}-{day:02d}.csv"
            self.logger.debug(
                "DHTLogger",
                "filename updated",
                date=f"{year:04d}-{month:02d}-{day:02d}",
                filename=self.filename,
            )
        except Exception as e:
            self.logger.error("DHTLogger", f"Error updating filename: {e}")
            self.filename = self.filename_base

    def _file_exists(self) -> bool:
        """Check if CSV data for this file already exists (primary, fallback, or buffer)."""
        relpath = self._strip_sd_prefix(self.filename)
        # Fast path: already created this session (avoids unreliable FAT VFS check)
        if relpath in self._created_files:
            self.logger.debug("DHTLogger", "file exists (created cache)", relpath=relpath)
            return True
        exists = self.buffer_manager.has_data_for(relpath)
        if exists:
            # Cache the confirmed existence so a later SD outage won't re-trigger header creation
            self._created_files.add(relpath)
        self.logger.debug("DHTLogger", "file exists check", relpath=relpath, found=exists)
        return exists

    def _resolve_path(self, file_path: str) -> str:
        if getattr(sys.implementation, "name", "") == "micropython":
            return file_path
        if file_path.startswith("/sd/"):
            return f"{self.buffer_manager.sd_mount_point}/{file_path[4:]}"
        return file_path

    def _create_file(self) -> None:
        """
        Create CSV file with header via BufferManager.

        Header: 'Timestamp,Temperature,Humidity'
        Logs actual destination (primary SD or fallback) based on write result.
        Adds relpath to ``_created_files`` so subsequent same-session checks
        skip the slow (and sometimes unreliable) FAT VFS existence probe.
        """
        relpath = self._strip_sd_prefix(self.filename)
        self.logger.debug("DHTLogger", "creating CSV file", relpath=relpath)
        try:
            wrote_to_primary = self.buffer_manager.write(relpath, "Timestamp,Temperature,Humidity\n")
            self._created_files.add(relpath)
            if wrote_to_primary:
                self.logger.debug("DHTLogger", f"Created CSV file: {self.filename}")
            else:
                self.logger.debug("DHTLogger", f"Created CSV header (fallback): {self.filename}")
        except Exception as e:
            self.logger.error("DHTLogger", f"Failed to create file: {e}")
            raise

    def read_sensor(self):
        """
        Read temperature and humidity from DHT22.

        Implements retry logic with configurable delay between attempts.
        Validates readings are in range: -40°C to 80°C, 0% to 100%.

        Returns:
            tuple: (temperature, humidity) or (None, None) on failure
        """
        for attempt in range(self.max_retries):
            try:
                self.dht_sensor.measure()
                temp = self.dht_sensor.temperature()
                hum = self.dht_sensor.humidity()

                if -40 <= temp <= 80 and 0 <= hum <= 100:
                    self._consecutive_failures = 0
                    self._update_dht_status()
                    self.logger.debug(
                        "DHTLogger",
                        "sensor read ok",
                        temp=temp,
                        hum=hum,
                        attempt=attempt + 1,
                    )
                    return temp, hum
                else:
                    self.logger.debug(
                        "DHTLogger",
                        "sensor read out of range",
                        temp=temp,
                        hum=hum,
                        attempt=attempt + 1,
                    )
                    self.logger.warning("DHTLogger", f"Reading out of range: {temp}°C, {hum}%")
            except Exception as e:
                self.logger.debug(
                    "DHTLogger",
                    f"Read attempt {attempt + 1}/{self.max_retries} failed: {e}",
                )
                if attempt < self.max_retries - 1:
                    import time  # importing time here to avoid global import in async context - useful?

                    time.sleep(self.retry_delay_s)

        self.read_failures += 1
        self._consecutive_failures += 1
        self._update_dht_status()
        self.logger.debug(
            "DHTLogger",
            "sensor read exhausted",
            read_failures=self.read_failures,
            consecutive=self._consecutive_failures,
            max_retries=self.max_retries,
        )
        return None, None

    def _update_dht_status(self) -> None:
        """Update StatusManager warning/error based on consecutive DHT failures."""
        if self.status_manager is None:
            return
        self.logger.debug(
            "DHTLogger",
            "status update check",
            consecutive=self._consecutive_failures,
            warn_thresh=self._dht_warn_threshold,
            err_thresh=self._dht_error_threshold,
        )
        if self._consecutive_failures >= self._dht_error_threshold:
            self.logger.debug("DHTLogger", f"Status: error (failures={self._consecutive_failures})")
            self.status_manager.set_error("dht_dead", True)
            self.status_manager.set_warning("dht_intermittent", False)
        elif self._consecutive_failures >= self._dht_warn_threshold:
            self.logger.debug("DHTLogger", f"Status: warning (failures={self._consecutive_failures})")
            self.status_manager.set_warning("dht_intermittent", True)
            self.status_manager.set_error("dht_dead", False)
        else:
            self.status_manager.clear_warning("dht_intermittent")
            self.status_manager.clear_error("dht_dead")

    def _check_date_changed(self) -> bool:
        """
        Check if date has changed; update filename if so.

        Returns True if date changed and file was switched, False otherwise.
        """
        try:
            date_tuple = self.time_provider.now_date_tuple()
            current_date = (date_tuple[0], date_tuple[1], date_tuple[2])

            if current_date != self.current_date:
                self.logger.debug(
                    "DHTLogger",
                    "date changed",
                    old_date=str(self.current_date),
                    new_date=str(current_date),
                )

                self._update_filename_for_date()
            self._reset_stats()

            self.logger.debug("DHTLogger", "Date rollover check: no change")
            return False
        except Exception as e:
            self.logger.error("DHTLogger", f"Error during date check: {e}")
            return False

    async def log_loop(self) -> None:
        """
        Main async coroutine for continuous sensor logging.

        Reads sensor periodically, logs to CSV via BufferManager.
        BufferManager handles all storage resilience:
        - Writes to primary (SD) when available
        - Falls back to fallback file when SD unavailable
        - Buffers in-memory when both unavailable
        - Auto-migrates fallback entries when SD reconnects
        - Auto-flushes in-memory buffer when SD reconnects

        Handles date-based file rollover at midnight.

        LED feedback (via StatusManager):
        - Activity blink on each successful read+write cycle.
        - Warning LED (solid) on 3+ consecutive failures.
        - Error LED (solid) on 10+ consecutive failures.
        """
        sm = self.status_manager

        while True:
            try:
                # Check for date rollover
                self._check_date_changed()

                # Read sensor
                temp, hum = self.read_sensor()

                if temp is not None and hum is not None:
                    # Activity blink on successful read
                    if sm:
                        await sm.blink_activity()

                    # Cache for thermostat queries
                    self.last_temperature = temp
                    self.last_humidity = hum

                    # Append to bounded history for OLED stats
                    self._readings_history.append((_ticks_ms(), temp, hum))
                    if len(self._readings_history) > self._max_history:
                        self._readings_history.pop(0)

                    self._update_stats(temp, hum)

                    timestamp = self.time_provider.now_timestamp()
                    relpath = self._strip_sd_prefix(self.filename)
                    row = f"{timestamp},{temp:.1f},{hum:.1f}\n"

                    self.logger.debug("DHTLogger", f"Writing row to {relpath}: {row.rstrip()}")

                    # Ensure CSV file exists on SD (recreate header if
                    # init-time creation failed, e.g. SD timing issues).
                    if not self._file_exists():
                        try:
                            self._create_file()
                        except Exception as exc:
                            self.logger.debug(
                                "DHTLogger",
                                f"CSV re-create failed (will use fallback): {exc}",
                            )
                            pass  # write() below will route to fallback

                    # Write to storage via BufferManager
                    # BufferManager handles: primary → fallback → in-memory buffer
                    try:
                        wrote_primary = self.buffer_manager.write(relpath, row)
                        self.logger.debug(
                            "DHTLogger",
                            "log iteration",
                            temp=temp,
                            hum=hum,
                            relpath=relpath,
                            wrote_primary=wrote_primary,
                            read_failures=self.read_failures,
                            write_failures=self.write_failures,
                        )
                        if not wrote_primary:
                            self.logger.warning(
                                "DHTLogger",
                                f"Write went to fallback (SD unavailable?) for {relpath}",
                            )
                    except Exception as e:
                        self.logger.error("DHTLogger", f"Failed to write: {e}")
                        self.write_failures += 1
                else:
                    self.logger.warning("DHTLogger", f"Sensor read failed (total: {self.read_failures})")

                self.logger.check_size()
                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                self.logger.debug("DHTLogger", "log loop cancelled")
                self.logger.warning("DHTLogger", "Log loop cancelled")
                raise
            except Exception as e:
                self.logger.debug("DHTLogger", "unexpected error in log loop", error=str(e))
                self.logger.error("DHTLogger", f"Unexpected error: {e}")
                await asyncio.sleep(1)

    @staticmethod
    def _strip_sd_prefix(path: str) -> str:
        if path.startswith("/sd/"):
            return path[4:]
        return path

    def get_stats(self) -> dict:
        """
        Return temperature/humidity statistics.
        Returns:
            dict: {
                'temp_now': float | None,
                'temp_hi': float | None,
                'temp_lo': float | None,
                'temp_avg': float | None,
                'hum_now': float | None,
                'hum_hi': float | None,
                'hum_lo': float | None,
                'hum_avg': float | None,
                'count': int,
            }
        """
        return {
            "temp_now": self._temp_stats["now"],
            "temp_hi": self._temp_stats["hi"],
            "temp_lo": self._temp_stats["lo"],
            "temp_avg": self._temp_stats["avg"],
            "hum_now": self._hum_stats["now"],
            "hum_hi": self._hum_stats["hi"],
            "hum_lo": self._hum_stats["lo"],
            "hum_avg": self._hum_stats["avg"],
            "count": self._temp_stats["count"],
        }

    def clear_history(self) -> None:
        """Clear all in-memory reading history (used by OLED long-press action)."""
        self._readings_history.clear()

    def _reset_stats(self):
        self._temp_stats = {"now": None, "hi": None, "lo": None, "avg": None, "count": 0}
        self._hum_stats = {"now": None, "hi": None, "lo": None, "avg": None, "count": 0}

    def _update_stats(self, temp, hum):
        # Update temperature stats
        if self._temp_stats["hi"] is None or temp > self._temp_stats["hi"]:
            self._temp_stats["hi"] = temp
        if self._temp_stats["lo"] is None or temp < self._temp_stats["lo"]:
            self._temp_stats["lo"] = temp

        # Update humidity stats
        if self._hum_stats["hi"] is None or hum > self._hum_stats["hi"]:
            self._hum_stats["hi"] = hum
        if self._hum_stats["lo"] is None or hum < self._hum_stats["lo"]:
            self._hum_stats["lo"] = hum

        # Update averages
        if self._temp_stats["avg"] is None:
            self._temp_stats["avg"] = temp
        else:
            # Simple moving average
            count = self._temp_stats["count"]
            self._temp_stats["avg"] = (self._temp_stats["avg"] * count + temp) / (count + 1)

        if self._hum_stats["avg"] is None:
            self._hum_stats["avg"] = hum
        else:
            count = self._hum_stats["count"]
            self._hum_stats["avg"] = (self._hum_stats["avg"] * count + hum) / (count + 1)

        self._temp_stats["count"] += 1
        self._hum_stats["count"] += 1
        self._temp_stats["now"] = temp
        self._hum_stats["now"] = hum
