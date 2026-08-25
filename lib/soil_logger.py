# Soil Logger - Adafruit STEMMA #4026 moisture + root-zone temperature.
# Dennis Hiro, 2026-05-14
#
# Wire: the probe hangs off an existing I2C0 drop (SDA GP0 / SCL GP1, 3V3,
# GND) at address 0x36 — no ADC, no divider, GP28/ADC2 freed. The driver is
# lib/stemma_soil.py and is injected, so this module never touches a bus.
#
# Calibration lives in raw seesaw counts and the convention is INVERTED
# versus the analog probe this replaced: with the capacitive STEMMA, higher
# raw = wetter (air ~200, saturated substrate ~2000), so raw_wet > raw_dry.
#
# Root-zone temperature is logged and alarmed, never regulated: the
# regulation pipeline stays three-dimensional (see lib/regulation_normalizer).

import uasyncio as asyncio


def raw_to_percent(raw: int, dry: int, wet: int) -> int:
    """
    Map a raw seesaw capacitance count to a 0-100 moisture percentage.

    ``dry`` is the count with the probe in air / bone-dry substrate (low
    capacitance, LOW raw value). ``wet`` is the saturated count (HIGH raw
    value). Out-of-range readings are clamped: drier than dry -> 0%, wetter
    than wet -> 100%.
    """
    if raw <= dry:
        return 0
    if raw >= wet:
        return 100
    span = wet - dry
    pct = (raw - dry) * 100 // span
    if pct < 0:
        return 0
    if pct > 100:
        return 100
    return pct


def print_raw(sensor) -> tuple:
    """
    Single-shot calibration helper for the REPL.

    Reads one raw count plus the probe temperature and prints them. Run
    twice: once with the probe in air (or bone-dry potting mix) to find
    ``raw_dry``, once in saturated substrate to find ``raw_wet``. Update the
    soil_logger config and reboot.

    Usage on the Pico::

        from machine import Pin, SoftI2C
        try:
            from lib.stemma_soil import StemmaSoil
            from lib.soil_logger import print_raw
        except ImportError:  # frozen into the firmware as a top-level module
            from stemma_soil import StemmaSoil
            from soil_logger import print_raw
        print_raw(StemmaSoil(SoftI2C(scl=Pin(1), sda=Pin(0))))
    """
    raw = sensor.moisture()
    temp_c = sensor.temperature()
    print("soil_logger raw: {} | root temp: {:.1f} C".format(raw, temp_c))
    return raw, temp_c


class SoilLogger:
    """
    Async soil logger backed by BufferManager.

    Polls the injected STEMMA driver every ``interval_s`` seconds, converts
    the moisture count to a percentage using ``raw_dry``/``raw_wet``, and
    persists ``Timestamp,Raw,Percent,RootTempC`` rows the same way
    TempHumidityLogger / CO2Logger do. When the percentage falls below
    ``warn_pct_below`` and a ``status_manager`` is wired, the soil-moisture
    warning is raised on the warning LED; it clears once the value recovers.
    Root-zone temperature outside ``root_temp_min_c``..``root_temp_max_c``
    raises ``root_temp_low`` / ``root_temp_high`` the same way.

    Missed reads follow the shared edge-triggered policy (lib/sensor_health):
    one WARN on the way into "unreachable" plus the durable
    ``soil_unreachable`` StatusManager warning, silence while it stays dead,
    one INFO on recovery, and backed-off polling in between.

    No automatic watering action — sensing + display + warn only.
    """

    WARNING_KEY = "soil_low"
    UNREACHABLE_KEY = "soil_unreachable"
    ROOT_TEMP_LOW_KEY = "root_temp_low"
    ROOT_TEMP_HIGH_KEY = "root_temp_high"

    def __init__(
        self,
        sensor,
        time_provider,
        buffer_manager,
        logger,
        interval_s: int = 60,
        raw_dry: int = 200,
        raw_wet: int = 2000,
        warn_pct_below: int = 20,
        root_temp_min_c: float = 20.0,
        root_temp_max_c: float = 26.0,
        sensor_root: str = "/sd/sensors",
        sensor_type: str = "soil",
        write_queue=None,
        status_manager=None,
        warn_after_failures: int = 3,
        backoff_start_s: int = 60,
        backoff_max_s: int = 300,
        unreachable_heartbeat_s: int = 0,
    ):
        if raw_wet <= raw_dry:
            raise ValueError("SoilLogger requires raw_wet > raw_dry (capacitive probe: wetter = higher)")
        if root_temp_max_c <= root_temp_min_c:
            raise ValueError("SoilLogger requires root_temp_max_c > root_temp_min_c")

        self.sensor = sensor
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.logger = logger
        self.interval_s = interval_s
        self.raw_dry = raw_dry
        self.raw_wet = raw_wet
        self.warn_pct_below = warn_pct_below
        self.root_temp_min_c = root_temp_min_c
        self.root_temp_max_c = root_temp_max_c
        self.write_queue = write_queue
        self.status_manager = status_manager

        try:
            from lib.sensor_health import SensorHealth
        except ImportError:  # frozen into the firmware as a top-level module
            from sensor_health import SensorHealth

        self.health = SensorHealth(
            normal_interval_s=interval_s,
            warn_after_failures=warn_after_failures,
            backoff_start_s=backoff_start_s,
            backoff_max_s=backoff_max_s,
            unreachable_heartbeat_s=unreachable_heartbeat_s,
        )

        self.last_raw = None
        self.last_percent = None
        self.last_root_temp_c = None
        self.read_failures = 0
        self.write_failures = 0
        # Cause of the most recent failed read, so the single edge WARN can
        # name it. Set only on the failure path; never cleared, because a
        # recovery message has no use for it.
        self._last_read_error = "unknown"
        self._warn_active = False
        self._unreachable_flagged = False
        self._root_low_flagged = False
        self._root_high_flagged = False

        self._sensor_root = sensor_root
        self._sensor_type = sensor_type
        self.current_date = None
        self._update_filename_for_date()
        self._ensure_header()

        logger.debug(
            "SoilLogger",
            "init",
            interval_s=interval_s,
            dry=raw_dry,
            wet=raw_wet,
            warn_below=warn_pct_below,
            filename=self.filename,
        )

    # ------------------------------------------------------------------ filename

    def _update_filename_for_date(self) -> None:
        try:
            from lib.sensor_paths import daily_csv_path
        except ImportError:  # frozen into the firmware as a top-level module
            from sensor_paths import daily_csv_path

        try:
            year, month, day = self.time_provider.now_date_tuple()[:3]
            self.current_date = (year, month, day)
            self.filename = daily_csv_path(self._sensor_root, self._sensor_type, year, month, day)
        except Exception as exc:
            self.logger.error("SoilLogger", f"filename rollover failed: {exc}")
            self.filename = f"{self._sensor_root.rstrip('/')}/{self._sensor_type}/{self._sensor_type}.csv"

    def _check_date_changed(self) -> None:
        try:
            year, month, day = self.time_provider.now_date_tuple()[:3]
            if (year, month, day) != self.current_date:
                self._update_filename_for_date()
                self._ensure_header()
        except Exception as exc:
            self.logger.error("SoilLogger", f"date check failed: {exc}")

    @staticmethod
    def _strip_sd_prefix(path: str) -> str:
        return path[4:] if path.startswith("/sd/") else path

    def _ensure_header(self) -> None:
        relpath = self._strip_sd_prefix(self.filename)
        if not self.buffer_manager.has_data_for(relpath):
            try:
                self.buffer_manager.write(relpath, "Timestamp,Raw,Percent,RootTempC\n")
            except Exception as exc:
                self.logger.error("SoilLogger", f"header write failed: {exc}")

    # ------------------------------------------------------------------ warning

    def _update_warning(self, percent: int) -> None:
        if self.status_manager is None:
            return
        should_warn = percent < self.warn_pct_below
        if should_warn and not self._warn_active:
            self.status_manager.set_warning(self.WARNING_KEY, True)
            self._warn_active = True
            self.logger.warning(
                "SoilLogger",
                f"soil moisture low: {percent}% (< {self.warn_pct_below}%)",
            )
        elif not should_warn and self._warn_active:
            self.status_manager.set_warning(self.WARNING_KEY, False)
            self._warn_active = False
            self.logger.info("SoilLogger", f"soil moisture recovered: {percent}%")
        elif not should_warn:
            self.status_manager.set_warning(self.WARNING_KEY, False)

    def _update_root_temp_alerts(self, temp_c) -> None:
        """Raise/clear root_temp_low / root_temp_high on edges only.

        Root temperature has no actuator — the pot is warmed by the tent, not
        by anything the controller drives — so the whole value of this reading
        is one operator-visible warning per excursion. Level-triggered
        reporting here would reproduce exactly the log flood that
        lib/sensor_health.py exists to prevent.
        """
        if self.status_manager is None or temp_c is None:
            return
        low = temp_c < self.root_temp_min_c
        high = temp_c > self.root_temp_max_c
        if low != self._root_low_flagged:
            self._root_low_flagged = low
            try:
                self.status_manager.set_warning(self.ROOT_TEMP_LOW_KEY, low)
            except Exception as exc:
                self.logger.debug("SoilLogger", f"root temp alert failed: {exc}")
            if low:
                self.logger.warning("SoilLogger", f"root zone cold: {temp_c:.1f} C (< {self.root_temp_min_c} C)")
            else:
                self.logger.info("SoilLogger", f"root zone back in range: {temp_c:.1f} C")
        if high != self._root_high_flagged:
            self._root_high_flagged = high
            try:
                self.status_manager.set_warning(self.ROOT_TEMP_HIGH_KEY, high)
            except Exception as exc:
                self.logger.debug("SoilLogger", f"root temp alert failed: {exc}")
            if high:
                self.logger.warning("SoilLogger", f"root zone hot: {temp_c:.1f} C (> {self.root_temp_max_c} C)")
            else:
                self.logger.info("SoilLogger", f"root zone back in range: {temp_c:.1f} C")

    # -------------------------------------------------------------- reachability

    def _update_unreachable_alert(self, active) -> None:
        """Raise/clear the operator-visible soil_unreachable warning on edges."""
        if self.status_manager is None:
            return
        if active == self._unreachable_flagged:
            return
        self._unreachable_flagged = active
        try:
            self.status_manager.set_warning(self.UNREACHABLE_KEY, active)
        except Exception as exc:
            self.logger.debug("SoilLogger", f"unreachable alert failed: {exc}")

    def _note_read_failure(self) -> None:
        """Report a missed reading per the shared edge-triggered policy."""
        if self.health.record_failure():
            # The per-failure detail is DEBUG (it has to be — that is the whole
            # point of the edge policy), so the ONE line an operator sees has
            # to carry the cause with it. "no answer on the bus" and "short
            # read" want different cables checked.
            self.logger.warning(
                "SoilLogger",
                "sensor unreachable after {} failed reads; polling backed off to {}s ({})".format(
                    self.health.consecutive_failures, self.health.interval_s(), self._last_read_error
                ),
            )
            self._update_unreachable_alert(True)
            return
        if self.health.is_unreachable():
            if self.health.heartbeat_due():
                self.logger.warning(
                    "SoilLogger",
                    "sensor still unreachable ({} failed reads)".format(self.health.consecutive_failures),
                )
            else:
                self.logger.debug("SoilLogger", "no reading (unreachable)")
            return
        self.logger.debug(
            "SoilLogger",
            "no reading",
            consecutive=self.health.consecutive_failures,
            failures=self.read_failures,
        )

    def _note_read_success(self) -> None:
        """Report the end of an outage exactly once."""
        if self.health.record_success():
            self.logger.info(
                "SoilLogger",
                "sensor recovered after {}s unreachable ({} failed reads total)".format(
                    self.health.last_outage_s, self.health.total_failures
                ),
            )
        self._update_unreachable_alert(False)

    # ------------------------------------------------------------------ polling

    async def _poll_once(self) -> None:
        self._check_date_changed()

        try:
            raw = self.sensor.moisture()
            root_temp_c = self.sensor.temperature()
        except Exception as exc:
            self.read_failures += 1
            # Allocates only on the failure path; truncated so a driver that
            # stringifies a whole frame cannot blow the log line up.
            self._last_read_error = str(exc)[:80]
            self.logger.debug("SoilLogger", f"sensor read failed: {exc}")
            self._note_read_failure()
            return

        self._note_read_success()

        percent = raw_to_percent(raw, self.raw_dry, self.raw_wet)
        self.last_raw = raw
        self.last_percent = percent
        self.last_root_temp_c = root_temp_c

        self._update_warning(percent)
        self._update_root_temp_alerts(root_temp_c)

        timestamp = self.time_provider.now_timestamp()
        row = f"{timestamp},{raw},{percent},{root_temp_c:.1f}\n"
        relpath = self._strip_sd_prefix(self.filename)
        try:
            if self.write_queue is not None:
                self.write_queue.enqueue_write(relpath, row)
            else:
                self.buffer_manager.write(relpath, row)
        except Exception as exc:
            self.write_failures += 1
            self.logger.error("SoilLogger", f"write failed: {exc}")

    async def log_loop(self) -> None:
        """Async poll loop. Yields between polls so the watchdog stays fed.

        The sleep is the health machine's effective interval, so an
        unreachable probe drops onto the backoff ladder instead of being
        asked every interval_s; poll_due() keeps the 1 s error-path retry
        from hammering a dead bus.
        """
        while True:
            try:
                if self.health.poll_due():
                    await self._poll_once()
                await asyncio.sleep(self.health.interval_s())
            except asyncio.CancelledError:
                self.logger.warning("SoilLogger", "log loop cancelled")
                raise
            except Exception as exc:
                self.logger.error("SoilLogger", f"unexpected error: {exc}")
                await asyncio.sleep(1)

    # ------------------------------------------------------------------ state

    def get_state(self) -> dict:
        return {
            "last_raw": self.last_raw,
            "last_percent": self.last_percent,
            "last_root_temp_c": self.last_root_temp_c,
            "warn_pct_below": self.warn_pct_below,
            "warn_active": self._warn_active,
            "read_failures": self.read_failures,
            "write_failures": self.write_failures,
        }
