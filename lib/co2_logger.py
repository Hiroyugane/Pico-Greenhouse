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
# Modbus RTU reply header: address FE, function 44, byte-count 02.
_REPLY_HEADER = b"\xfe\x44\x02"
_REPLY_LEN = 7

try:
    _ticks_ms = time.ticks_ms  # MicroPython
except AttributeError:

    def _ticks_ms() -> int:  # CPython fallback
        return int(time.time() * 1000)


try:
    _ticks_diff = time.ticks_diff  # MicroPython (wrap-safe)
except AttributeError:

    def _ticks_diff(a, b):  # CPython fallback
        return a - b


def crc16(data):
    """Modbus RTU CRC16 (poly 0xA001, init 0xFFFF) over ``data``."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def parse_frame(buf, min_ppm=0, max_ppm=_MAX_PLAUSIBLE_PPM, verify_checksum=False):
    """
    Parse a SenseAir-style 7-byte reply.

    The ppm value is the big-endian word at bytes [3:5]. Returns None for
    malformed or implausible frames so the caller can treat parse failures
    the same as a missed read.

    With ``verify_checksum`` the header and Modbus CRC16 are checked first.
    That matters more than the range window: a misaligned read (a partial
    previous reply still sitting in the RX buffer) produces a *structurally*
    wrong frame whose ppm word can land anywhere, including inside any
    plausible range. The 2026-07-27..31 field run logged 8320, 8903 and 9470
    ppm alongside 0, 2 and 5 ppm from exactly this. A checksum rejects those
    deterministically; a window only catches the ones that happen to look silly.
    """
    if buf is None or len(buf) < 5:
        return None
    if verify_checksum:
        if len(buf) != _REPLY_LEN:
            return None
        if bytes(buf[0:3]) != _REPLY_HEADER:
            return None
        if crc16(buf[0:5]) != (buf[5] | (buf[6] << 8)):
            return None
    ppm = buf[3] * 256 + buf[4]
    if ppm < min_ppm or ppm > max_ppm:
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
        verify_checksum: bool = False,
        plausible_min_ppm: int = 0,
        plausible_max_ppm: int = _MAX_PLAUSIBLE_PPM,
        stale_after_s: int = 0,
        warn_after_failures: int = 3,
        backoff_start_s: int = 60,
        backoff_max_s: int = 300,
        unreachable_heartbeat_s: int = 0,
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
        self.verify_checksum = verify_checksum
        self.plausible_min_ppm = plausible_min_ppm
        self.plausible_max_ppm = plausible_max_ppm
        self.stale_after_s = stale_after_s

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

        # State
        self._last_ppm = None
        self._last_ok_ms = None
        self._stale_flagged = False
        self._unreachable_flagged = False
        self.override_active = False
        self.read_failures = 0
        self.write_failures = 0
        # Cause of the most recent failed read, so the single edge WARN can
        # name it. Set only on the failure path; never cleared, because a
        # recovery message has no use for it.
        self._last_read_error = "unknown"
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

    # ------------------------------------------------------------------ reading

    @property
    def last_ppm(self):
        """Most recent good reading, or None once it is older than stale_after_s.

        The regulation engine reads this every tick and its normalizer maps None
        to a neutral deviation. Before the timeout existed, a dead sensor left
        the last good value in place forever and the engine kept regulating on
        it: the S8 fell silent at 15:41 on 2026-07-30 and only an unrelated
        reboot stopped 1159 ppm from being treated as live indefinitely.
        """
        if self._last_ppm is None:
            return None
        if not self.stale_after_s or self._last_ok_ms is None:
            return self._last_ppm
        if _ticks_diff(_ticks_ms(), self._last_ok_ms) >= self.stale_after_s * 1000:
            return None
        return self._last_ppm

    @last_ppm.setter
    def last_ppm(self, value):
        """Kept writable so tests and callers can seed a reading directly."""
        self._last_ppm = value
        self._last_ok_ms = None if value is None else _ticks_ms()

    def is_stale(self):
        """True when a reading was seen once but has since aged out."""
        return self._last_ppm is not None and self.last_ppm is None

    def _update_stale_alert(self):
        """Raise/clear the operator-visible co2_stale warning on edges only.

        A silently blind CO2 channel is the failure this whole change exists to
        surface: the sensor produced 7427 read failures over 4.5 days and the
        only outward sign was a warning line buried in the log.
        """
        if self.status_manager is None:
            return
        stale = self.is_stale()
        if stale == self._stale_flagged:
            return
        self._stale_flagged = stale
        try:
            self.status_manager.set_warning("co2_stale", stale)
        except Exception as exc:
            self.logger.debug("CO2Logger", f"stale alert failed: {exc}")

    # -------------------------------------------------------------- reachability

    def _update_unreachable_alert(self, active) -> None:
        """Raise/clear the operator-visible co2_unreachable warning on edges only.

        Mirrors _update_stale_alert: the StatusManager is the DURABLE channel
        for "this sensor is dead", so the log only has to say it once.
        """
        if self.status_manager is None:
            return
        if active == self._unreachable_flagged:
            return
        self._unreachable_flagged = active
        try:
            self.status_manager.set_warning("co2_unreachable", active)
        except Exception as exc:
            self.logger.debug("CO2Logger", f"unreachable alert failed: {exc}")

    def _note_read_failure(self) -> None:
        """Report a missed reading per the edge-triggered policy.

        A dead S8 produced 20 533 identical WARN lines over the 2026-07-31..08-07
        field run — 100 % of every warning logged. Only the transition into
        "unreachable" is worth a WARN; the state itself lives on the StatusManager.
        """
        if self.health.record_failure():
            self.logger.warning(
                "CO2Logger",
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
                    "CO2Logger",
                    "sensor still unreachable ({} failed reads)".format(self.health.consecutive_failures),
                )
            else:
                self.logger.debug("CO2Logger", "no reading (unreachable)")
            return
        self.logger.debug(
            "CO2Logger",
            "no reading",
            consecutive=self.health.consecutive_failures,
            failures=self.read_failures,
        )

    def _note_read_success(self) -> None:
        """Report the end of an outage exactly once."""
        if self.health.record_success():
            self.logger.info(
                "CO2Logger",
                "sensor recovered after {}s unreachable ({} failed reads total)".format(
                    self.health.last_outage_s, self.health.total_failures
                ),
            )
        self._update_unreachable_alert(False)

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
        # Register before writing: a header created while SD is down can be
        # evicted from the fallback (oldest-first) before it ever reaches the
        # card, which is how co2_2026-07-27.csv ended up headerless.
        setter = getattr(self.buffer_manager, "set_header", None)
        if setter is not None:
            setter(relpath, "Timestamp,PPM\n")
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
            # Drain anything left over from a previous exchange before asking
            # again. A partial reply still sitting in the RX buffer makes the
            # next read(7) start mid-frame, and a misaligned frame's ppm word
            # can be any value at all — the most likely source of the 8320 /
            # 9470 ppm readings in the 2026-07-27..31 logs.
            if self.uart.any():
                self.uart.read()
        except Exception as exc:
            self.logger.debug("CO2Logger", f"uart flush failed: {exc}")
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
        read_error = None
        for attempt in range(self.max_retries):
            try:
                if self.uart.any():
                    frame = self.uart.read(7)
                    if frame:
                        break
            except Exception as exc:
                read_error = str(exc)[:80]
                self.logger.debug("CO2Logger", f"uart read attempt failed: {exc}")
            if attempt < self.max_retries - 1:
                await asyncio.sleep_ms(self.retry_delay_ms)

        ppm = parse_frame(
            frame,
            min_ppm=self.plausible_min_ppm,
            max_ppm=self.plausible_max_ppm,
            verify_checksum=self.verify_checksum,
        )
        if ppm is None:
            self.read_failures += 1
            # No exception on this path when the sensor simply says nothing, so
            # spell that out rather than leaving the edge WARN cause-less.
            # Allocates only on the failure path.
            if read_error is not None:
                self._last_read_error = read_error
            elif frame is None:
                self._last_read_error = "no reply frame on the UART"
            else:
                self._last_read_error = "reply rejected (checksum or range)"
            in_warmup = (_ticks_ms() - self._started_ms) < self.warmup_s * 1000
            if in_warmup:
                # Warm-up misses are expected, so they neither escalate nor
                # feed the health machine — a sensor that answers as soon as
                # it is warm must not start life one failure into an outage.
                self.logger.debug("CO2Logger", "no reading (warmup)")
            else:
                self._note_read_failure()
            self._update_stale_alert()
            return

        self.last_ppm = ppm
        self._note_read_success()
        self._update_stale_alert()
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
        """Async poll loop. Yields between polls so the watchdog stays fed.

        The sleep is the health machine's *effective* interval, so an
        unreachable sensor is polled on the backoff ladder (60/120/240/300 s)
        instead of every interval_s. poll_due() is the second guard: the
        error path below retries after 1 s, and without it a wedged UART
        would be hammered once a second.
        """
        while True:
            try:
                if self.health.poll_due():
                    await self._poll_once()
                await asyncio.sleep(self.health.interval_s())
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
