# Adafruit STEMMA Soil Sensor (#4026) — minimal seesaw driver
# Dennis Hiro, 2026-08-25
#
# Capacitive moisture + temperature probe with an ATSAMD10 running Adafruit's
# "seesaw" firmware, on the shared I2C0 bus. Address 0x36 by default
# (0x36-0x39 via the AD0/AD1 jumpers) — it collides with nothing on this bus:
# 0x3C OLED, 0x40 PCA9685, 0x44/0x45 SHT31s, 0x60 MCP4725, 0x68 DS3231.
#
# This is deliberately NOT a port of the seesaw stack. Seesaw is a whole
# peripheral-multiplexer protocol (GPIO, ADC, PWM, neopixel, EEPROM, …); this
# board uses exactly two of its registers, so only those two are implemented.
#
# Register model: every read is "write [base, function], wait for the
# conversion, read N bytes". The wait is not optional — the ATSAMD10 answers
# the read with a NACK while it is still converting, which surfaces as OSError
# on the Pico. Adafruit's CircuitPython driver waits ~5 ms and retries a
# couple of times; so does this one.
#
#   moisture: base 0x0F (touch), function 0x10 + channel 0, 2 bytes BE.
#             ~200 in air, ~2000 in saturated substrate — HIGHER IS WETTER,
#             the opposite of the resistive probe this replaced.
#   temperature: base 0x00 (status), function 0x04, 4 bytes BE, signed
#             16.16 fixed point degrees C (value / 65536).

import time

_STATUS_BASE = 0x00
_STATUS_TEMP = 0x04
_TOUCH_BASE = 0x0F
_TOUCH_CHANNEL_OFFSET = 0x10
_MOISTURE_CHANNEL = 0
# fixed: seesaw's touch ADC is 10-bit oversampled; anything past 12 bits is a
# transport artefact, not a reading. Same guard value Adafruit's driver uses.
_MAX_PLAUSIBLE_RAW = 4095
_SIGN_BIT = 0x80000000
_WRAP = 0x100000000

try:
    _sleep_ms = time.sleep_ms  # MicroPython
except AttributeError:

    def _sleep_ms(ms):  # CPython fallback (host shims / tests)
        time.sleep(ms / 1000.0)


class StemmaSoil:
    """Adafruit STEMMA soil sensor on a shared I2C bus.

    The bus object is injected (the guarded I2C0 proxy from
    :mod:`lib.i2c_guard` in production), so this driver gains bus recovery
    without knowing about it — same arrangement as :class:`lib.sht31.SHT31`.

    Both reads raise ``OSError`` when the sensor does not answer, which is the
    contract every sensor logger's health machine expects.

    Attributes:
        i2c: I2C bus instance (shared with RTC, OLED, DAC, PWM driver)
        address: 7-bit I2C address (0x36 default)
    """

    def __init__(
        self,
        i2c,
        address: int = 0x36,
        # fixed: seesaw protocol timing from Adafruit's reference driver, not
        # an operator knob — the ATSAMD10 NACKs a read while it is still
        # converting, and the reference driver's answer is a couple of retries.
        retries: int = 3,
        # fixed: seesaw protocol timing from Adafruit's reference driver — the
        # conversion wait the ATSAMD10 needs before it will answer at all.
        conversion_delay_ms: int = 5,
    ):
        self.i2c = i2c
        self.address = address
        self.retries = retries if retries >= 1 else 1
        self.conversion_delay_ms = conversion_delay_ms
        # Preallocated so the poll path allocates only the reply bytes.
        self._cmd = bytearray(2)

    # ------------------------------------------------------------------ transport

    def _read(self, base: int, function: int, count: int) -> bytes:
        """Run one seesaw read, retrying the NACK-while-converting case.

        Raises:
            OSError: when every attempt failed or came back short.
        """
        cmd = self._cmd
        cmd[0] = base
        cmd[1] = function
        last_exc = None
        for attempt in range(self.retries):
            try:
                self.i2c.writeto(self.address, cmd)
                _sleep_ms(self.conversion_delay_ms)
                data = self.i2c.readfrom(self.address, count)
                if len(data) == count:
                    return data
                last_exc = OSError("STEMMA short read: {} of {} bytes".format(len(data), count))
            except OSError as exc:
                last_exc = exc
            if attempt < self.retries - 1:
                _sleep_ms(self.conversion_delay_ms)
        raise last_exc if last_exc is not None else OSError("STEMMA read failed")

    # ------------------------------------------------------------------ readings

    def moisture(self) -> int:
        """Raw capacitance count: ~200 in air, ~2000 saturated.

        Raises:
            OSError: on transport failure, or when the sensor keeps returning
            an out-of-range value (a stuck bus reads as 0xFFFF, which would
            otherwise log as "soaking wet").
        """
        raw = -1
        for attempt in range(self.retries):
            data = self._read(_TOUCH_BASE, _TOUCH_CHANNEL_OFFSET + _MOISTURE_CHANNEL, 2)
            raw = (data[0] << 8) | data[1]
            if raw <= _MAX_PLAUSIBLE_RAW:
                return raw
            if attempt < self.retries - 1:
                _sleep_ms(self.conversion_delay_ms)
        raise OSError("STEMMA implausible moisture reading: {}".format(raw))

    def temperature(self) -> float:
        """On-chip temperature in degrees C (the root-zone reading).

        Adafruit masks the top byte with 0x3F, which throws the sign away;
        this keeps the value signed so a probe below 0 C reads as such
        instead of as +16384 C.

        Raises:
            OSError: on transport failure.
        """
        data = self._read(_STATUS_BASE, _STATUS_TEMP, 4)
        raw = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
        if raw & _SIGN_BIT:
            raw -= _WRAP
        return raw / 65536.0
