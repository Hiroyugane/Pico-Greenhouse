# CO2 Logger - SenseAir-style UART CO2 sensor with hysteresis-driven fan override
# Dennis Hiro, 2026-05-14
#
# Wire: GP16 (UART0 TX, via R9) → CO2_CON.4, GP17 (UART0 RX, via R11) ← CO2_CON.3.
# Protocol: 7-byte read-holding-register request, 7-byte reply with ppm in bytes [3:5].
# Mirrors TempHumidityLogger's shape (BufferManager-backed CSV with date rollover).
# Exposes is_override_active() so a FanController can poll it as an external override.

import time

import uasyncio as asyncio

REQUEST_FRAME = b"\xfe\x44\x00\x08\x02\x9f\x25"
_MAX_PLAUSIBLE_PPM = 10000

try:
    _ticks_ms = time.ticks_ms  # MicroPython
except AttributeError:

    def _ticks_ms() -> int:  # CPython fallback
        return int(time.time() * 1000)


def parse_frame(buf):
    """
    Parse a SenseAir-style 7-byte reply.

    The ppm value is the big-endian word at bytes [3:5]. Returns None for
    malformed or implausible frames so the caller can treat parse failures
    the same as a missed read.
    """
    if buf is None or len(buf) < 5:
        return None
    ppm = buf[3] * 256 + buf[4]
    if ppm < 0 or ppm > _MAX_PLAUSIBLE_PPM:
        return None
    return ppm


class CO2Logger:
    """
    Async CO2 logger with a hysteresis-driven fan-override flag.

    Polls a SenseAir-style UART sensor every ``interval_s`` seconds. Each
    successful reading is cached in ``last_ppm`` and written via
    ``BufferManager`` (SD → fallback → in-memory) the same way TempHumidityLogger
    persists temperature/humidity. The override flag latches on at
    ``override_ppm_on`` and clears at ``override_ppm_off``; consumers
    (e.g. FanController.external_override) call ``is_override_active()``.

    Attributes:
        uart: machine.UART instance (already configured)
        time_provider: TimeProvider for RTC timestamps + date rollover
        buffer_manager: BufferManager for resilient writes
        logger: EventLogger for structured logs
        last_ppm: most recent good reading (None until first success)
        override_active: latched override state
    """

    def __init__(
        self,
        uart,
        time_provider,
        buffer_manager,
        logger,
        interval_s: int = 30,
        warmup_s: int = 30,
        max_retries: int = 3,
        override_ppm_on: int = 1000,
        override_ppm_off: int = 800,
        sensor_root: str = "/sd/sensors",
        sensor_type: str = "co2",
        retry_delay_ms: int = 50,
        write_queue=None,
        status_manager=None,
    ):
        self.uart = uart
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.logger = logger
        self.interval_s = interval_s
        self.warmup_s = warmup_s
        self.max_retries = max_retries
        self.override_ppm_on = override_ppm_on
        self.override_ppm_off = override_ppm_off
        self.retry_delay_ms = retry_delay_ms
        self.write_queue = write_queue
        self.status_manager = status_manager

        # State
        self.last_ppm = None
        self.override_active = False
        self.read_failures = 0
        self.write_failures = 0
        self._started_ms = _ticks_ms()
        self._sensor_root = sensor_root
        self._sensor_type = sensor_type
        self.current_date = None
        self._update_filename_for_date()
        self._ensure_header()

        logger.debug(
            "CO2Logger",
            "init",
            interval_s=interval_s,
            warmup_s=warmup_s,
            override_on=override_ppm_on,
            override_off=override_ppm_off,
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
            self.logger.error("CO2Logger", f"filename rollover failed: {exc}")
            self.filename = f"{self._sensor_root.rstrip('/')}/{self._sensor_type}/{self._sensor_type}.csv"

    def _check_date_changed(self) -> None:
        try:
            year, month, day = self.time_provider.now_date_tuple()[:3]
            if (year, month, day) != self.current_date:
                self._update_filename_for_date()
                self._ensure_header()
        except Exception as exc:
            self.logger.error("CO2Logger", f"date check failed: {exc}")

    @staticmethod
    def _strip_sd_prefix(path: str) -> str:
        return path[4:] if path.startswith("/sd/") else path

    def _ensure_header(self) -> None:
        relpath = self._strip_sd_prefix(self.filename)
        if not self.buffer_manager.has_data_for(relpath):
            try:
                self.buffer_manager.write(relpath, "Timestamp,PPM\n")
            except Exception as exc:
                self.logger.error("CO2Logger", f"header write failed: {exc}")

    # ------------------------------------------------------------------ override

    def _update_override(self, ppm) -> None:
        if ppm is None:
            return
        if not self.override_active and ppm >= self.override_ppm_on:
            self.override_active = True
            self.logger.info(
                "CO2Logger",
                f"override ON at {ppm} ppm (>= {self.override_ppm_on})",
            )
        elif self.override_active and ppm < self.override_ppm_off:
            self.override_active = False
            self.logger.info(
                "CO2Logger",
                f"override OFF at {ppm} ppm (< {self.override_ppm_off})",
            )

    def is_override_active(self) -> bool:
        return self.override_active

    # ------------------------------------------------------------------ polling

    async def _poll_once(self) -> None:
        self._check_date_changed()
        try:
            self.uart.write(REQUEST_FRAME)
        except Exception as exc:
            self.logger.error("CO2Logger", f"uart write failed: {exc}")
            self.read_failures += 1
            return

        # Poll uart.any() up to max_retries times. The retry-delay-ms
        # await between attempts gives the sensor time to respond
        # (~50-200 ms typical) without burning watchdog cycles.
        frame = None
        for attempt in range(self.max_retries):
            try:
                if self.uart.any():
                    frame = self.uart.read(7)
                    if frame:
                        break
            except Exception as exc:
                self.logger.debug("CO2Logger", f"uart read attempt failed: {exc}")
            if attempt < self.max_retries - 1:
                await asyncio.sleep_ms(self.retry_delay_ms)

        ppm = parse_frame(frame)
        if ppm is None:
            self.read_failures += 1
            in_warmup = (_ticks_ms() - self._started_ms) < self.warmup_s * 1000
            if in_warmup:
                self.logger.debug("CO2Logger", "no reading (warmup)")
            else:
                self.logger.warning(
                    "CO2Logger",
                    f"no reading (failures={self.read_failures})",
                )
            return

        self.last_ppm = ppm
        self._update_override(ppm)

        timestamp = self.time_provider.now_timestamp()
        row = f"{timestamp},{ppm}\n"
        relpath = self._strip_sd_prefix(self.filename)
        try:
            if self.write_queue is not None:
                self.write_queue.enqueue_write(relpath, row)
            else:
                self.buffer_manager.write(relpath, row)
        except Exception as exc:
            self.write_failures += 1
            self.logger.error("CO2Logger", f"write failed: {exc}")

    async def log_loop(self) -> None:
        """Async poll loop. Yields between polls so the watchdog stays fed."""
        while True:
            try:
                await self._poll_once()
                await asyncio.sleep(self.interval_s)
            except asyncio.CancelledError:
                self.logger.warning("CO2Logger", "log loop cancelled")
                raise
            except Exception as exc:
                self.logger.error("CO2Logger", f"unexpected error: {exc}")
                await asyncio.sleep(1)

    # ------------------------------------------------------------------ state

    def get_state(self) -> dict:
        return {
            "last_ppm": self.last_ppm,
            "override_active": self.override_active,
            "override_ppm_on": self.override_ppm_on,
            "override_ppm_off": self.override_ppm_off,
            "read_failures": self.read_failures,
            "write_failures": self.write_failures,
        }
