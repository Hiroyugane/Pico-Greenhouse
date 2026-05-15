# Tests for lib/sht31.py
# Covers CRC-8 helper, soft-reset, single-shot measure conversion, and
# the I2C error / CRC-mismatch failure paths.

from unittest.mock import Mock

import pytest


def _crc(data: bytes) -> int:
    """Reference CRC-8 (poly 0x31, init 0xFF) — same as the driver."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def _frame(t_raw: int, h_raw: int) -> bytes:
    t_hi, t_lo = (t_raw >> 8) & 0xFF, t_raw & 0xFF
    h_hi, h_lo = (h_raw >> 8) & 0xFF, h_raw & 0xFF
    return bytes(
        [
            t_hi,
            t_lo,
            _crc(bytes([t_hi, t_lo])),
            h_hi,
            h_lo,
            _crc(bytes([h_hi, h_lo])),
        ]
    )


class _FakeI2C:
    """I2C stub: records writeto, replays a programmable read buffer."""

    def __init__(self, frame: bytes = b"", reset_raises: bool = False):
        self.frame = frame
        self.writeto_calls = []
        self.read_calls = []
        self.reset_raises = reset_raises

    def writeto(self, addr, data):
        self.writeto_calls.append((addr, bytes(data)))
        if self.reset_raises and bytes(data) == b"\x30\xa2":
            raise OSError("bus error")

    def readfrom(self, addr, n):
        self.read_calls.append((addr, n))
        return self.frame


class TestCRC:
    def test_crc8_matches_known_vector(self):
        # Known Sensirion vector: bytes 0xBE 0xEF → CRC 0x92
        from lib.sht31 import _crc8

        assert _crc8(b"\xbe\xef") == 0x92

    def test_crc8_zero_bytes(self):
        from lib.sht31 import _crc8

        # Two zero data bytes → CRC of initial state after two XORs
        assert _crc8(b"\x00\x00") == _crc(b"\x00\x00")


class TestInit:
    def test_init_issues_soft_reset(self):
        from lib.sht31 import SHT31

        i2c = _FakeI2C()
        SHT31(i2c)
        # First writeto should be the soft-reset command 0x30A2
        assert i2c.writeto_calls
        assert i2c.writeto_calls[0][1] == b"\x30\xa2"

    def test_init_swallows_reset_failure(self):
        """If the I2C bus is dead at boot, __init__ must not raise."""
        from lib.sht31 import SHT31

        i2c = _FakeI2C(reset_raises=True)
        # Constructor should swallow the OSError per the try/except in reset()
        sensor = SHT31(i2c)
        assert sensor.temperature() == 0.0
        assert sensor.humidity() == 0.0

    def test_default_address_is_0x44(self):
        from lib.sht31 import SHT31

        i2c = _FakeI2C()
        sensor = SHT31(i2c)
        assert sensor.address == 0x44

    def test_custom_address_honored(self):
        from lib.sht31 import SHT31

        i2c = _FakeI2C()
        sensor = SHT31(i2c, address=0x45)
        assert sensor.address == 0x45


class TestMeasure:
    def test_measure_decodes_temperature_and_humidity(self):
        from lib.sht31 import SHT31

        # 25 °C, 50 %RH (approximate raw values from datasheet conversion)
        # T_raw such that -45 + 175*(t/65535) ≈ 25 → t_raw ≈ 26214
        # H_raw such that 100*(h/65535) ≈ 50 → h_raw ≈ 32768
        i2c = _FakeI2C(frame=_frame(26214, 32768))
        sensor = SHT31(i2c)
        sensor.measure()
        assert sensor.temperature() == pytest.approx(25.0, abs=0.1)
        assert sensor.humidity() == pytest.approx(50.0, abs=0.1)

    def test_measure_sends_single_shot_command(self):
        from lib.sht31 import SHT31

        i2c = _FakeI2C(frame=_frame(20000, 30000))
        sensor = SHT31(i2c)
        sensor.measure()
        # Second writeto (after soft-reset) is the single-shot 0x2400 command
        assert i2c.writeto_calls[-1][1] == b"\x24\x00"

    def test_measure_short_read_raises(self):
        from lib.sht31 import SHT31

        i2c = _FakeI2C(frame=b"\x00\x00\x00")  # only 3 bytes
        sensor = SHT31(i2c)
        with pytest.raises(OSError, match="short read"):
            sensor.measure()

    def test_measure_temperature_crc_mismatch_raises(self):
        from lib.sht31 import SHT31

        # Corrupt the temperature CRC byte
        good = bytearray(_frame(20000, 30000))
        good[2] ^= 0xFF
        i2c = _FakeI2C(frame=bytes(good))
        sensor = SHT31(i2c)
        with pytest.raises(OSError, match="temperature CRC mismatch"):
            sensor.measure()

    def test_measure_humidity_crc_mismatch_raises(self):
        from lib.sht31 import SHT31

        good = bytearray(_frame(20000, 30000))
        good[5] ^= 0xFF
        i2c = _FakeI2C(frame=bytes(good))
        sensor = SHT31(i2c)
        with pytest.raises(OSError, match="humidity CRC mismatch"):
            sensor.measure()


class TestAccessors:
    def test_temperature_returns_cached_zero_before_measure(self):
        from lib.sht31 import SHT31

        sensor = SHT31(_FakeI2C())
        assert sensor.temperature() == 0.0

    def test_humidity_returns_cached_zero_before_measure(self):
        from lib.sht31 import SHT31

        sensor = SHT31(_FakeI2C())
        assert sensor.humidity() == 0.0

    def test_reset_calls_i2c_writeto(self):
        from lib.sht31 import SHT31

        i2c = Mock()
        sensor = SHT31(i2c)
        i2c.writeto.reset_mock()
        sensor.reset()
        i2c.writeto.assert_called_once_with(0x44, b"\x30\xa2")
