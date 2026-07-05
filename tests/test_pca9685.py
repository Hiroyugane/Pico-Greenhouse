# Tests for lib/pca9685.py

from unittest.mock import MagicMock

import pytest


def _make_i2c():
    """I2C mock that records writeto_mem calls and returns deterministic reads."""
    i2c = MagicMock()
    i2c.writeto_mem = MagicMock()
    i2c.readfrom_mem = MagicMock(return_value=bytes([0x00]))
    return i2c


class TestPCA9685Init:
    def test_init_writes_mode1_and_sets_all_off(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        PCA9685(i2c, address=0x40, freq_hz=1000)
        # After construction the MODE1 reset + set_freq + all_off path
        # must have produced multiple writes to MODE1, PRESCALE and LED regs.
        regs_written = [call.args[1] for call in i2c.writeto_mem.call_args_list]
        assert 0x00 in regs_written  # MODE1
        assert 0xFE in regs_written  # PRESCALE
        # All 16 channels touched (LED0_ON_L .. LED15_ON_L are 0x06+4*ch)
        led_regs = {0x06 + 4 * ch for ch in range(16)}
        assert led_regs.issubset(set(regs_written))

    def test_init_custom_address(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        pca = PCA9685(i2c, address=0x41)
        assert pca.address == 0x41

    def test_freq_too_low_raises(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        with pytest.raises(ValueError, match="freq"):
            PCA9685(i2c, freq_hz=10)

    def test_freq_too_high_raises(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        with pytest.raises(ValueError, match="freq"):
            PCA9685(i2c, freq_hz=2000)


class TestPCA9685SetDuty:
    @pytest.fixture
    def pca(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        return PCA9685(i2c, freq_hz=1000)

    def test_invalid_channel_low_raises(self, pca):
        with pytest.raises(ValueError, match="channel"):
            pca.set_duty(-1, 50)

    def test_invalid_channel_high_raises(self, pca):
        with pytest.raises(ValueError, match="channel"):
            pca.set_duty(16, 50)

    def test_set_duty_zero_writes_full_off(self, pca):
        pca.i2c.writeto_mem.reset_mock()
        pca.set_duty(3, 0)
        # base reg = 0x06 + 4*3 = 0x12
        last = pca.i2c.writeto_mem.call_args
        assert last.args[1] == 0x12
        # FULL_OFF: off=4096 → low=0x00, high=0x10
        assert last.args[2] == bytes([0x00, 0x00, 0x00, 0x10])

    def test_set_duty_100_writes_full_on(self, pca):
        pca.i2c.writeto_mem.reset_mock()
        pca.set_duty(0, 100)
        last = pca.i2c.writeto_mem.call_args
        assert last.args[1] == 0x06
        # FULL_ON: on=4096 → high=0x10
        assert last.args[2] == bytes([0x00, 0x10, 0x00, 0x00])

    def test_set_duty_50_writes_midscale(self, pca):
        pca.i2c.writeto_mem.reset_mock()
        pca.set_duty(0, 50)
        last = pca.i2c.writeto_mem.call_args
        # 50% of 4095 ≈ 2048; little-endian 12-bit = 0x00 0x08
        on_l, on_h, off_l, off_h = last.args[2]
        assert on_l == 0 and on_h == 0
        count = off_l | (off_h << 8)
        assert 2040 <= count <= 2055

    def test_set_duty_clamps_negative(self, pca):
        pca.set_duty(0, -10)
        # Behaves like full-off
        last = pca.i2c.writeto_mem.call_args
        assert last.args[2] == bytes([0x00, 0x00, 0x00, 0x10])

    def test_set_duty_clamps_over_100(self, pca):
        pca.set_duty(0, 150)
        # Behaves like full-on
        last = pca.i2c.writeto_mem.call_args
        assert last.args[2] == bytes([0x00, 0x10, 0x00, 0x00])


class TestPCA9685Invert:
    @pytest.fixture
    def pca(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        return PCA9685(i2c, freq_hz=1000, invert=True)

    def test_invert_zero_writes_full_on(self, pca):
        # 0% requested → inverted to 100% → FULL_ON gate = fan truly off.
        pca.i2c.writeto_mem.reset_mock()
        pca.set_duty(0, 0)
        last = pca.i2c.writeto_mem.call_args
        assert last.args[2] == bytes([0x00, 0x10, 0x00, 0x00])

    def test_invert_100_writes_full_off(self, pca):
        # 100% requested → inverted to 0% → FULL_OFF gate = fan at full speed.
        pca.i2c.writeto_mem.reset_mock()
        pca.set_duty(0, 100)
        last = pca.i2c.writeto_mem.call_args
        assert last.args[2] == bytes([0x00, 0x00, 0x00, 0x10])

    def test_invert_midscale_is_complementary(self, pca):
        # 25% requested → inverted to 75% of 4095 ≈ 3071.
        pca.i2c.writeto_mem.reset_mock()
        pca.set_duty(0, 25)
        _, _, off_l, off_h = pca.i2c.writeto_mem.call_args.args[2]
        count = off_l | (off_h << 8)
        assert 3065 <= count <= 3078

    def test_invert_default_off_matches_non_inverted(self):
        # invert defaults False: 0% keeps the plain FULL_OFF encoding.
        from lib.pca9685 import PCA9685

        pca = PCA9685(_make_i2c(), freq_hz=1000)
        pca.i2c.writeto_mem.reset_mock()
        pca.set_duty(0, 0)
        assert pca.i2c.writeto_mem.call_args.args[2] == bytes([0x00, 0x00, 0x00, 0x10])


class TestPCA9685SetFreq:
    def test_set_freq_writes_prescale(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        pca = PCA9685(i2c, freq_hz=1000)
        i2c.writeto_mem.reset_mock()
        pca.set_freq(200)
        regs = [call.args[1] for call in i2c.writeto_mem.call_args_list]
        assert 0xFE in regs
        assert pca.freq_hz == 200

    def test_set_freq_out_of_range_raises(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        pca = PCA9685(i2c, freq_hz=1000)
        with pytest.raises(ValueError):
            pca.set_freq(2000)


class TestPCA9685AllOff:
    def test_all_off_touches_all_channels(self):
        from lib.pca9685 import PCA9685

        i2c = _make_i2c()
        pca = PCA9685(i2c, freq_hz=1000)
        i2c.writeto_mem.reset_mock()
        pca.all_off()
        regs = [call.args[1] for call in i2c.writeto_mem.call_args_list]
        for ch in range(16):
            assert (0x06 + 4 * ch) in regs
