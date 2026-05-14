# Soil Moisture Logger - GP28 ADC2 single-probe reader with calibrated %.
# Dennis Hiro, 2026-05-14
#
# Wire: GP28 (ADC2) → ADC_CON pin 4; ADC_VREF on Pico pin 35; ADC_GND on
# pin 33. Probe is a resistive soil sensor referenced 0-3V3.
# Calibration constants live in 0-1023 space (10-bit) because that's the
# range the REPL helper print_raw() exposes. SoilLogger scales the raw
# 16-bit read_u16() result down to 10 bits internally.

import time

import uasyncio as asyncio

try:
    import machine  # MicroPython
except ImportError:  # pragma: no cover - host_shims always provides one
    machine = None  # type: ignore[assignment]

_RAW10_MAX = 1023
_U16_MAX = 65535


def raw_to_percent(raw10: int, dry: int, wet: int) -> int:
    """
    Map a 0-1023 raw ADC reading to a 0-100 moisture percentage.

    ``dry`` is the raw value with the probe in air / bone-dry soil (high
    resistance, high ADC reading). ``wet`` is the saturated reading
    (low resistance, low ADC reading). Out-of-range readings are
    clamped: drier than dry → 0%, wetter than wet → 100%.
    """
    if raw10 >= dry:
        return 0
    if raw10 <= wet:
        return 100
    span = dry - wet
    pct = (dry - raw10) * 100 // span
    if pct < 0:
        return 0
    if pct > 100:
        return 100
    return pct


def _u16_to_raw10(u16: int) -> int:
    if u16 < 0:
        return 0
    if u16 > _U16_MAX:
        return _RAW10_MAX
    return (u16 * _RAW10_MAX + _U16_MAX // 2) // _U16_MAX


def print_raw(pin: int = 28) -> int:
    """
    Single-shot calibration helper for the REPL.

    Reads one raw 10-bit value from the GP28 ADC and prints it. Run
    twice: once with the probe in air (or bone-dry potting mix) to find
    ``adc_dry_raw``, once with it in saturated soil to find
    ``adc_wet_raw``. Update soil_logger config and reboot.

    Usage on the Pico::

        from lib.soil_logger import print_raw
        print_raw()
    """
    if machine is None:
        raise RuntimeError("machine module not available")
    adc = machine.ADC(machine.Pin(pin))
    raw10 = _u16_to_raw10(adc.read_u16())
    print(f"soil_logger raw (GP{pin}): {raw10} / {_RAW10_MAX}")
    return raw10


class SoilLogger:
    """
    Async soil-moisture logger backed by BufferManager.

    Polls a single ADC channel every ``interval_s`` seconds, converts
    the reading to a percentage using ``adc_dry_raw``/``adc_wet_raw``,
    and persists ``Timestamp,Raw,Percent`` rows the same way DHTLogger /
    CO2Logger do. When the percentage falls below ``warn_pct_below`` and
    a ``status_manager`` is wired, the soil-moisture warning is raised
    on the warning LED; it clears once the value recovers.

    No automatic watering action — sensing + display + warn only.
    """

    WARNING_KEY = "soil_low"

    def __init__(
        self,
        adc,
        time_provider,
        buffer_manager,
        logger,
        interval_s: int = 60,
        adc_dry_raw: int = 850,
        adc_wet_raw: int = 350,
        warn_pct_below: int = 20,
        filename_base: str = "soil_log",
        write_queue=None,
        status_manager=None,
    ):
        if adc_dry_raw <= adc_wet_raw:
            raise ValueError("SoilLogger requires adc_dry_raw > adc_wet_raw")

        self.adc = adc
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.logger = logger
        self.interval_s = interval_s
        self.adc_dry_raw = adc_dry_raw
        self.adc_wet_raw = adc_wet_raw
        self.warn_pct_below = warn_pct_below
        self.write_queue = write_queue
        self.status_manager = status_manager

        self.last_raw = None
        self.last_percent = None
        self.read_failures = 0
        self.write_failures = 0
        self._warn_active = False

        self._filename_base = (
            filename_base if filename_base.startswith("/sd/") else f"/sd/{filename_base}"
        )
        self.current_date = None
        self._update_filename_for_date()
        self._ensure_header()

        logger.debug(
            "SoilLogger",
            "init",
            interval_s=interval_s,
            dry=adc_dry_raw,
            wet=adc_wet_raw,
            warn_below=warn_pct_below,
            filename=self.filename,
        )

    # ------------------------------------------------------------------ filename

    def _update_filename_for_date(self) -> None:
        try:
            year, month, day = self.time_provider.now_date_tuple()[:3]
            self.current_date = (year, month, day)
            base = self._filename_base.replace(".csv", "")
            self.filename = f"{base}_{year:04d}-{month:02d}-{day:02d}.csv"
        except Exception as exc:
            self.logger.error("SoilLogger", f"filename rollover failed: {exc}")
            self.filename = self._filename_base

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
                self.buffer_manager.write(relpath, "Timestamp,Raw,Percent\n")
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

    # ------------------------------------------------------------------ polling

    async def _poll_once(self) -> None:
        self._check_date_changed()

        try:
            u16 = self.adc.read_u16()
        except Exception as exc:
            self.read_failures += 1
            self.logger.error("SoilLogger", f"adc read failed: {exc}")
            return

        raw10 = _u16_to_raw10(u16)
        percent = raw_to_percent(raw10, self.adc_dry_raw, self.adc_wet_raw)
        self.last_raw = raw10
        self.last_percent = percent

        self._update_warning(percent)

        timestamp = self.time_provider.now_timestamp()
        row = f"{timestamp},{raw10},{percent}\n"
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
        """Async poll loop. Yields between polls so the watchdog stays fed."""
        while True:
            try:
                await self._poll_once()
                await asyncio.sleep(self.interval_s)
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
            "warn_pct_below": self.warn_pct_below,
            "warn_active": self._warn_active,
            "read_failures": self.read_failures,
            "write_failures": self.write_failures,
        }


# Suppress unused-import warning while keeping `time` available for any
# future timing instrumentation (mirrors CO2Logger's import shape).
_ = time
