# Temperature/Humidity Logger - SHT31 over shared I2C with DI
# Dennis Hiro, 2026-05-14
#
# Replacement for the legacy DHTLogger module. The sensor is now injected
# (an SHT31 instance on the shared I2C0 bus) rather than constructed
# inside the logger from a one-wire GPIO pin.
#
# Same on-disk CSV format ("Timestamp,Temperature,Humidity") so existing
# dashboards keep working. BufferManager still owns all storage resilience.

import time

import uasyncio as asyncio

try:
    _ticks_ms = time.ticks_ms  # MicroPython
except AttributeError:

    def _ticks_ms() -> int:  # CPython fallback
        return int(time.time() * 1000)


class TempHumidityLogger:
    """
    Temperature/humidity logger with SD hot-swap and date-based rollover.

    The sensor object is injected; it must expose ``measure() -> None``,
    ``temperature() -> float`` and ``humidity() -> float``. The shipped
    driver is :mod:`lib.sht31` (SHT31-D on shared I2C0).

    All storage resilience delegated to BufferManager:
    - Writes to primary (SD) when available
    - Falls back to fallback file when SD unavailable
    - Buffers in-memory when both unavailable
    - Auto-migrates fallback entries when SD reconnects

    Automatically rolls over CSV file at midnight.

    Attributes:
        sensor: Injected temperature/humidity sensor instance
        interval: Logging interval in seconds
        time_provider: TimeProvider instance
        buffer_manager: BufferManager instance
        write_queue: WriteQueueManager instance (optional for async writes)
        logger: EventLogger instance
        current_date: Current date (year, month, day) for rollover detection
        last_temperature: Cached temperature for thermostat queries
        last_humidity: Cached humidity reading
        read_failures: Count of sensor read failures
        write_failures: Count of failed writes
    """

    def __init__(
        self,
        sensor,
        time_provider,
        buffer_manager,
        logger,
        interval=60,
        sensor_root: str = "/sd/sensors",
        sensor_type: str = "th",
        max_retries=3,
        status_manager=None,
        th_warn_threshold=3,
        th_error_threshold=10,
        retry_delay_s: float = 0.5,
        max_history: int = 120,
        write_queue=None,
        warn_after_failures=3,
        backoff_start_s=60,
        backoff_max_s=300,
        unreachable_heartbeat_s=0,
    ):
        """
        Initialize TempHumidityLogger with dependency injection.

        Args:
            sensor: Temperature/humidity sensor instance with
                ``measure() / temperature() / humidity()`` methods
                (e.g. ``lib.sht31.SHT31``)
            time_provider: TimeProvider instance
            buffer_manager: BufferManager instance
            logger: EventLogger instance
            interval (int): Logging interval in seconds (default: 60)
            sensor_root (str): Absolute root for sensor data (default: '/sd/sensors')
            sensor_type (str): Folder + filename prefix (default: 'th')
            max_retries (int): Sensor read retries (default: 3)
            status_manager: StatusManager instance for LED feedback (optional)
            th_warn_threshold (int): Consecutive failures before warning (default: 3)
            th_error_threshold (int): Consecutive failures before error (default: 10)
            retry_delay_s (float): Delay between sensor read retries in seconds (default: 0.5)
            max_history (int): Maximum readings to keep for stats (default: 120)
            write_queue: Optional WriteQueueManager for async write batching (default: None)
            warn_after_failures (int): Consecutive misses before the sensor is
                reported unreachable (default: 3)
            backoff_start_s (int): First backed-off poll interval (default: 60)
            backoff_max_s (int): Ceiling for the doubling backoff (default: 300)
            unreachable_heartbeat_s (int): Reminder cadence while unreachable,
                0 = silent (default: 0)
        """
        self.sensor = sensor
        self.interval = interval
        self._sensor_root = sensor_root
        self._sensor_type = sensor_type
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.write_queue = write_queue
        self.logger = logger
        self.max_retries = max_retries
        self.status_manager = status_manager
        self._th_warn_threshold = th_warn_threshold
        self._th_error_threshold = th_error_threshold
        self.retry_delay_s = retry_delay_s
        self._max_history = max_history

        try:
            from lib.sensor_health import SensorHealth
        except ImportError:  # frozen into the firmware as a top-level module
            from sensor_health import SensorHealth

        self.health = SensorHealth(
            normal_interval_s=interval,
            warn_after_failures=warn_after_failures,
            backoff_start_s=backoff_start_s,
            backoff_max_s=backoff_max_s,
            unreachable_heartbeat_s=unreachable_heartbeat_s,
        )

        # State
        self.last_temperature = None
        self.last_humidity = None
        self.read_failures = 0
        self.write_failures = 0
        # Cause of the most recent failed read, so the single edge WARN can
        # name it. Set only on the failure path; never cleared, because a
        # recovery message has no use for it.
        self._last_read_error = "unknown"
        self._consecutive_failures = 0
        self._unreachable_flagged = False
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
            logger.info("TempHumidityLogger", f"Initialized: {self.filename}")
            logger.debug(
                "TempHumidityLogger",
                "init config",
                interval=interval,
                max_retries=max_retries,
                th_warn_threshold=th_warn_threshold,
                th_error_threshold=th_error_threshold,
                retry_delay_s=retry_delay_s,
                filename=self.filename,
                has_status_mgr=status_manager is not None,
            )
        except Exception as e:
            logger.error("TempHumidityLogger", f"Init error: {e}")

    def _update_filename_for_date(self) -> None:
        """
        Update log filename based on current RTC date.

        Builds <sensor_root>/<sensor_type>/YYYY/<sensor_type>_YYYY-MM-DD.csv.
        """
        try:
            from lib.sensor_paths import daily_csv_path
        except ImportError:  # frozen into the firmware as a top-level module
            from sensor_paths import daily_csv_path

        try:
            date_tuple = self.time_provider.now_date_tuple()
            year, month, day = date_tuple[0], date_tuple[1], date_tuple[2]
            self.current_date = (year, month, day)

            self.filename = daily_csv_path(self._sensor_root, self._sensor_type, year, month, day)
            self.logger.debug(
                "TempHumidityLogger",
                "filename updated",
                date=f"{year:04d}-{month:02d}-{day:02d}",
                filename=self.filename,
            )
        except Exception as e:
            self.logger.error("TempHumidityLogger", f"Error updating filename: {e}")
            self.filename = f"{self._sensor_root.rstrip('/')}/{self._sensor_type}/{self._sensor_type}.csv"

    def _file_exists(self) -> bool:
        """Check if CSV data for this file already exists (primary, fallback, or buffer)."""
        relpath = self._strip_sd_prefix(self.filename)
        # Fast path: already created this session (avoids unreliable FAT VFS check)
        if relpath in self._created_files:
            self.logger.debug("TempHumidityLogger", "file exists (created cache)", relpath=relpath)
            return True
        exists = self.buffer_manager.has_data_for(relpath)
        if exists:
            self._created_files.add(relpath)
        self.logger.debug("TempHumidityLogger", "file exists check", relpath=relpath, found=exists)
        return exists

    def _create_file(self) -> None:
        """
        Create CSV file with header via BufferManager.

        Header: 'Timestamp,Temperature,Humidity'
        """
        relpath = self._strip_sd_prefix(self.filename)
        self.logger.debug("TempHumidityLogger", "creating CSV file", relpath=relpath)
        try:
            wrote_to_primary = self.buffer_manager.write(relpath, "Timestamp,Temperature,Humidity\n")
            self._created_files.add(relpath)
            if wrote_to_primary:
                self.logger.debug("TempHumidityLogger", f"Created CSV file: {self.filename}")
            else:
                self.logger.debug("TempHumidityLogger", f"Created CSV header (fallback): {self.filename}")
        except Exception as e:
            self.logger.error("TempHumidityLogger", f"Failed to create file: {e}")
            raise

    def read_sensor(self):
        """
        Read temperature and humidity from the injected sensor.

        Implements retry logic with configurable delay between attempts.
        Validates readings are in range: -40°C to 80°C, 0% to 100%.

        Returns:
            tuple: (temperature, humidity) or (None, None) on failure
        """
        for attempt in range(self.max_retries):
            try:
                self.sensor.measure()
                temp = self.sensor.temperature()
                hum = self.sensor.humidity()

                if -40 <= temp <= 80 and 0 <= hum <= 100:
                    self._consecutive_failures = 0
                    self._update_th_status()
                    self._note_read_success()
                    self.logger.debug(
                        "TempHumidityLogger",
                        "sensor read ok",
                        temp=temp,
                        hum=hum,
                        attempt=attempt + 1,
                    )
                    return temp, hum
                else:
                    self.logger.debug(
                        "TempHumidityLogger",
                        "sensor read out of range",
                        temp=temp,
                        hum=hum,
                        attempt=attempt + 1,
                    )
                    self._last_read_error = "out of range: {}C {}%".format(temp, hum)
                    self.logger.warning("TempHumidityLogger", f"Reading out of range: {temp}degC, {hum}%")
            except Exception as e:
                # Allocates only on the failure path; truncated so a driver
                # that stringifies a frame cannot blow the log line up.
                self._last_read_error = str(e)[:80]
                self.logger.debug(
                    "TempHumidityLogger",
                    f"Read attempt {attempt + 1}/{self.max_retries} failed: {e}",
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay_s)

        self.read_failures += 1
        self._consecutive_failures += 1
        self._update_th_status()
        self.logger.debug(
            "TempHumidityLogger",
            "sensor read exhausted",
            read_failures=self.read_failures,
            consecutive=self._consecutive_failures,
            max_retries=self.max_retries,
        )
        self._note_read_failure()
        return None, None

    def prime(self) -> None:
        """
        Synchronously read the sensor once and populate the cache.

        Meant to be called from main() right after construction, before
        any async task is created. RegulationEngine.run()'s first tick can
        otherwise execute before log_loop() gets its first scheduler turn,
        reading last_temperature/last_humidity while both are still None
        and computing neutral commands for a full tick_s (default 30s)
        after boot before any actuator can respond to real conditions.
        Reuses read_sensor()'s existing retry/backoff config, so it adds
        no new tunable and no more boot latency than the first log_loop()
        iteration would have taken anyway.
        """
        temp, hum = self.read_sensor()
        if temp is not None and hum is not None:
            self.last_temperature = temp
            self.last_humidity = hum

    def _update_th_status(self) -> None:
        """Update StatusManager warning/error based on consecutive failures."""
        if self.status_manager is None:
            return
        self.logger.debug(
            "TempHumidityLogger",
            "status update check",
            consecutive=self._consecutive_failures,
            warn_thresh=self._th_warn_threshold,
            err_thresh=self._th_error_threshold,
        )
        if self._consecutive_failures >= self._th_error_threshold:
            self.logger.debug("TempHumidityLogger", f"Status: error (failures={self._consecutive_failures})")
            self.status_manager.set_error("th_dead", True)
            self.status_manager.set_warning("th_intermittent", False)
        elif self._consecutive_failures >= self._th_warn_threshold:
            self.logger.debug("TempHumidityLogger", f"Status: warning (failures={self._consecutive_failures})")
            self.status_manager.set_warning("th_intermittent", True)
            self.status_manager.set_error("th_dead", False)
        else:
            self.status_manager.clear_warning("th_intermittent")
            self.status_manager.clear_error("th_dead")

    def _update_unreachable_alert(self, active) -> None:
        """Raise/clear the operator-visible sht31_unreachable warning on edges only.

        The StatusManager is the DURABLE channel for "this sensor is dead",
        which is why the log only has to say it once.
        """
        if self.status_manager is None:
            return
        if active == self._unreachable_flagged:
            return
        self._unreachable_flagged = active
        try:
            self.status_manager.set_warning("sht31_unreachable", active)
        except Exception as exc:
            self.logger.debug("TempHumidityLogger", f"unreachable alert failed: {exc}")

    def _note_read_failure(self) -> None:
        """Report a missed reading per the edge-triggered policy.

        This path used to emit one WARN per failed read from the log loop. A
        single dead sensor then writes a warning line every interval forever,
        which is exactly how the CO2 channel produced 20 533 of them in one
        7.2-day field run and rotated the log 3-4 times a day.
        """
        if self.health.record_failure():
            self.logger.warning(
                "TempHumidityLogger",
                # The per-attempt detail is DEBUG by design, so this one line
                # has to carry the cause or nobody ever sees it.
                "sensor unreachable after {} failed reads; polling backed off to {}s ({})".format(
                    self.health.consecutive_failures, self.health.interval_s(), self._last_read_error
                ),
            )
            self._update_unreachable_alert(True)
            return
        if self.health.is_unreachable():
            if self.health.heartbeat_due():
                self.logger.warning(
                    "TempHumidityLogger",
                    "sensor still unreachable ({} failed reads)".format(self.health.consecutive_failures),
                )
            else:
                self.logger.debug("TempHumidityLogger", "sensor read failed (unreachable)")
            return
        self.logger.debug(
            "TempHumidityLogger",
            "sensor read failed",
            consecutive=self.health.consecutive_failures,
            read_failures=self.read_failures,
        )

    def _note_read_success(self) -> None:
        """Report the end of an outage exactly once."""
        if self.health.record_success():
            self.logger.info(
                "TempHumidityLogger",
                "sensor recovered after {}s unreachable ({} failed reads total)".format(
                    self.health.last_outage_s, self.health.total_failures
                ),
            )
        self._update_unreachable_alert(False)

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
                    "TempHumidityLogger",
                    "date changed",
                    old_date=str(self.current_date),
                    new_date=str(current_date),
                )

                self._update_filename_for_date()
                self._reset_stats()
                return True

            self.logger.debug("TempHumidityLogger", "Date rollover check: no change")
            return False
        except Exception as e:
            self.logger.error("TempHumidityLogger", f"Error during date check: {e}")
            return False

    async def log_loop(self) -> None:
        """
        Main async coroutine for continuous sensor logging.

        Reads sensor periodically, logs to CSV via BufferManager.
        BufferManager handles all storage resilience.
        Handles date-based file rollover at midnight.

        LED feedback (via StatusManager):
        - Activity blink on each successful read+write cycle.
        - Warning LED (solid) on warn_threshold+ consecutive failures.
        - Error LED (solid) on error_threshold+ consecutive failures.
        """
        sm = self.status_manager

        while True:
            try:
                # Check for date rollover
                self._check_date_changed()

                # Read sensor. poll_due() honours the backed-off interval, so
                # a sensor that has gone unreachable is retried on the ladder
                # (60/120/240/300 s) instead of every interval, and the error
                # path's 1 s retry sleep below cannot hammer it either.
                temp, hum = (None, None)
                polled = self.health.poll_due()
                if polled:
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

                    self.logger.debug("TempHumidityLogger", f"Writing row to {relpath}: {row.rstrip()}")

                    if not self._file_exists():
                        try:
                            self._create_file()
                        except Exception as exc:
                            self.logger.debug(
                                "TempHumidityLogger",
                                f"CSV re-create failed (will use fallback): {exc}",
                            )

                    try:
                        if self.write_queue is not None:
                            self.write_queue.enqueue_write(relpath, row)
                            wrote_primary = True
                        else:
                            wrote_primary = self.buffer_manager.write(relpath, row)

                        self.logger.debug(
                            "TempHumidityLogger",
                            "log iteration",
                            temp=temp,
                            hum=hum,
                            relpath=relpath,
                            wrote_primary=wrote_primary,
                            read_failures=self.read_failures,
                            write_failures=self.write_failures,
                        )
                        if not wrote_primary and self.write_queue is None:
                            self.logger.warning(
                                "TempHumidityLogger",
                                f"Write went to fallback (SD unavailable?) for {relpath}",
                            )
                    except Exception as e:
                        self.logger.error("TempHumidityLogger", f"Failed to write: {e}")
                        self.write_failures += 1
                elif polled:
                    # read_sensor() already applied the edge-triggered
                    # reporting policy; nothing level-triggered belongs here.
                    self.logger.debug(
                        "TempHumidityLogger",
                        "log iteration produced no reading",
                        read_failures=self.read_failures,
                        state=self.health.state,
                    )

                self.logger.check_size()
                await asyncio.sleep(self.health.interval_s())

            except asyncio.CancelledError:
                self.logger.debug("TempHumidityLogger", "log loop cancelled")
                self.logger.warning("TempHumidityLogger", "Log loop cancelled")
                raise
            except Exception as e:
                self.logger.debug("TempHumidityLogger", "unexpected error in log loop", error=str(e))
                self.logger.error("TempHumidityLogger", f"Unexpected error: {e}")
                await asyncio.sleep(1)

    @staticmethod
    def _strip_sd_prefix(path: str) -> str:
        if path.startswith("/sd/"):
            return path[4:]
        return path

    def get_stats(self, window_s=None) -> dict:
        """
        Return temperature/humidity statistics.

        When ``window_s`` is provided, stats are computed from in-memory
        history entries that fall within the trailing time window.
        """
        if window_s is not None:
            cutoff_ms = _ticks_ms() - max(int(window_s), 0) * 1000
            window = [entry for entry in self._readings_history if entry[0] >= cutoff_ms]

            if window:
                temps = [entry[1] for entry in window]
                hums = [entry[2] for entry in window]
                temp_now = self.last_temperature if self.last_temperature is not None else temps[-1]
                hum_now = self.last_humidity if self.last_humidity is not None else hums[-1]
                return {
                    "temp_now": temp_now,
                    "temp_hi": max(temps),
                    "temp_lo": min(temps),
                    "temp_avg": sum(temps) / len(temps),
                    "hum_now": hum_now,
                    "hum_hi": max(hums),
                    "hum_lo": min(hums),
                    "hum_avg": sum(hums) / len(hums),
                    "count": len(window),
                }

            return {
                "temp_now": self.last_temperature,
                "temp_hi": None,
                "temp_lo": None,
                "temp_avg": None,
                "hum_now": self.last_humidity,
                "hum_hi": None,
                "hum_lo": None,
                "hum_avg": None,
                "count": 0,
            }

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
        if self._temp_stats["hi"] is None or temp > self._temp_stats["hi"]:
            self._temp_stats["hi"] = temp
        if self._temp_stats["lo"] is None or temp < self._temp_stats["lo"]:
            self._temp_stats["lo"] = temp

        if self._hum_stats["hi"] is None or hum > self._hum_stats["hi"]:
            self._hum_stats["hi"] = hum
        if self._hum_stats["lo"] is None or hum < self._hum_stats["lo"]:
            self._hum_stats["lo"] = hum

        if self._temp_stats["avg"] is None:
            self._temp_stats["avg"] = temp
        else:
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
