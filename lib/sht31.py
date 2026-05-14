# SHT31 I2C Driver
# Dennis Hiro, 2026-05-14
#
# Minimal Adafruit-style driver for the Sensirion SHT31-D temperature /
# humidity sensor. Shares the I2C0 bus with the DS3231 RTC, the MCP4725
# DAC and the SSD1306 OLED display.
#
# Address: 0x44 (ADDR pin = GND, default) or 0x45 (ADDR pin = VCC).
# Command: single-shot, high repeatability, clock stretching disabled.
# Response: 6 bytes — [t_msb, t_lsb, t_crc, h_msb, h_lsb, h_crc].

import time

_CMD_SINGLE_HIGH_NOCLK = b"\x24\x00"
_CMD_SOFT_RESET = b"\x30\xa2"
_MEASURE_DELAY_MS = 16  # max conversion time at high repeatability
_CRC8_POLY = 0x31


def _crc8(buf: bytes) -> int:
    """SHT31 CRC-8 over the two preceding data bytes (poly 0x31, init 0xFF)."""
    crc = 0xFF
    for byte in buf:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ _CRC8_POLY) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


class SHT31:
    """
    Sensirion SHT31-D temperature/humidity sensor on I2C.

    Drop-in replacement for the DHT22 driver from the MicroPython ``dht``
    module, but with CRC-validated I2C transport instead of single-wire
    pulse decoding. Same usage pattern: ``measure()`` triggers a read and
    caches the result; ``temperature()`` and ``humidity()`` return the
    last cached value.

    Attributes:
        i2c: machine.I2C bus instance (shared with other devices)
        address: 7-bit I2C address (0x44 default, 0x45 if ADDR pin tied high)
    """

    def __init__(self, i2c, address: int = 0x44):
        self.i2c = i2c
        self.address = address
        self._temp: float = 0.0
        self._hum: float = 0.0
        try:
            self.reset()
        except Exception:
            pass

    def reset(self) -> None:
        """Issue soft-reset command (0x30A2). Sensor needs ~1.5 ms to settle."""
        self.i2c.writeto(self.address, _CMD_SOFT_RESET)
        time.sleep_ms(2)

    def measure(self) -> None:
        """
        Trigger a single-shot high-repeatability measurement and cache it.

        Raises:
            OSError: on I2C transport failure or CRC mismatch.
        """
        self.i2c.writeto(self.address, _CMD_SINGLE_HIGH_NOCLK)
        time.sleep_ms(_MEASURE_DELAY_MS)
        raw = self.i2c.readfrom(self.address, 6)
        if len(raw) != 6:
            raise OSError("SHT31 short read: {} bytes".format(len(raw)))

        if _crc8(raw[0:2]) != raw[2]:
            raise OSError("SHT31 temperature CRC mismatch")
        if _crc8(raw[3:5]) != raw[5]:
            raise OSError("SHT31 humidity CRC mismatch")

        t_raw = (raw[0] << 8) | raw[1]
        h_raw = (raw[3] << 8) | raw[4]
        # Datasheet conversion formulas (section 4.13).
        self._temp = -45.0 + 175.0 * (t_raw / 65535.0)
        self._hum = 100.0 * (h_raw / 65535.0)

    def temperature(self) -> float:
        """Return last cached temperature in °C."""
        return self._temp

    def humidity(self) -> float:
        """Return last cached relative humidity in %."""
        return self._hum
