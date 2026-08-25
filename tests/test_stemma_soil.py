# Tests for lib/stemma_soil.py
# Covers the minimal seesaw driver: the exact bytes written for each register,
# big-endian parsing, the NACK retry path, and signed 16.16 temperature.

import pytest


class FakeI2C:
    """Records writes and replays scripted replies, seesaw-style.

    ``replies`` is consumed one entry per ``readfrom``; an entry may be a
    bytes object (returned) or an exception instance (raised). ``write_fail``
    exceptions are raised from ``writeto`` instead.
    """

    def __init__(self, replies=None, write_errors=None):
        self.replies = list(replies or [])
        self.write_errors = list(write_errors or [])
        self.writes = []
        self.reads = []

    def writeto(self, addr, buf):
        self.writes.append((addr, bytes(buf)))
        if self.write_errors:
            err = self.write_errors.pop(0)
            if err is not None:
                raise err

    def readfrom(self, addr, nbytes):
        self.reads.append((addr, nbytes))
        if not self.replies:
            raise OSError("no scripted reply")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _driver(i2c, **kwargs):
    from lib.stemma_soil import StemmaSoil

    kwargs.setdefault("conversion_delay_ms", 0)
    return StemmaSoil(i2c=i2c, **kwargs)


class TestProtocol:
    def test_moisture_writes_touch_base_and_channel_zero(self):
        i2c = FakeI2C(replies=[bytes([0x03, 0xE8])])
        driver = _driver(i2c)
        assert driver.moisture() == 1000
        assert i2c.writes == [(0x36, b"\x0f\x10")]
        assert i2c.reads == [(0x36, 2)]

    def test_temperature_writes_status_base_and_temp_function(self):
        # 22.5 C == 0x00_16_80_00 in 16.16 fixed point.
        i2c = FakeI2C(replies=[bytes([0x00, 0x16, 0x80, 0x00])])
        driver = _driver(i2c)
        assert driver.temperature() == pytest.approx(22.5)
        assert i2c.writes == [(0x36, b"\x00\x04")]
        assert i2c.reads == [(0x36, 4)]

    def test_custom_address_is_used(self):
        i2c = FakeI2C(replies=[bytes([0x00, 0xC8])])
        driver = _driver(i2c, address=0x39)
        assert driver.moisture() == 200
        assert i2c.writes[0][0] == 0x39


class TestTemperatureFixedPoint:
    def test_negative_temperature_is_signed(self):
        # -5.5 C == 0xFFFA8000 as a signed 16.16 value.
        i2c = FakeI2C(replies=[bytes([0xFF, 0xFA, 0x80, 0x00])])
        assert _driver(i2c).temperature() == pytest.approx(-5.5)

    def test_zero_is_zero(self):
        i2c = FakeI2C(replies=[bytes([0x00, 0x00, 0x00, 0x00])])
        assert _driver(i2c).temperature() == pytest.approx(0.0)

    def test_fractional_bits_are_kept(self):
        # 0x0015_4000 == 21.25 C
        i2c = FakeI2C(replies=[bytes([0x00, 0x15, 0x40, 0x00])])
        assert _driver(i2c).temperature() == pytest.approx(21.25)


class TestRetries:
    def test_read_nack_is_retried(self):
        """The probe NACKs while still converting; a retry gets the value."""
        i2c = FakeI2C(replies=[OSError("nack"), bytes([0x07, 0xD0])])
        assert _driver(i2c).moisture() == 2000
        assert len(i2c.reads) == 2

    def test_write_nack_is_retried(self):
        i2c = FakeI2C(replies=[bytes([0x00, 0xC8])], write_errors=[OSError("nack"), None])
        assert _driver(i2c).moisture() == 200
        assert len(i2c.writes) == 2

    def test_exhausted_retries_raise_oserror(self):
        i2c = FakeI2C(replies=[OSError("nack"), OSError("nack"), OSError("nack")])
        with pytest.raises(OSError, match="nack"):
            _driver(i2c).moisture()
        assert len(i2c.reads) == 3

    def test_short_read_raises_oserror(self):
        i2c = FakeI2C(replies=[b"\x01", b"\x01", b"\x01"])
        with pytest.raises(OSError, match="short read"):
            _driver(i2c).moisture()

    def test_implausible_moisture_is_retried_then_rejected(self):
        """A wedged bus reads 0xFFFF; that must not log as 'soaking wet'."""
        i2c = FakeI2C(replies=[b"\xff\xff", b"\xff\xff", b"\xff\xff"])
        with pytest.raises(OSError, match="implausible"):
            _driver(i2c).moisture()

    def test_implausible_then_good_reading_is_accepted(self):
        i2c = FakeI2C(replies=[b"\xff\xff", bytes([0x02, 0x58])])
        assert _driver(i2c).moisture() == 600

    def test_retries_floor_at_one(self):
        i2c = FakeI2C(replies=[OSError("nack")])
        driver = _driver(i2c, retries=0)
        assert driver.retries == 1
        with pytest.raises(OSError):
            driver.moisture()
        assert len(i2c.reads) == 1
