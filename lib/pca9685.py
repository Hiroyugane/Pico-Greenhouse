# PCA9685 16-channel I2C PWM driver
# Dennis Hiro, 2026-05-16
#
# Drives IRLZ44N MOSFET gates for variable-speed fan control on the next
# hardware revision. Shares I2C0 with the DS3231 RTC, SSD1306 OLED and
# MCP4725 grow-light DAC. One PWM frequency applies to all 16 channels;
# per-channel duty is set independently via set_duty(ch, pct).
#
# Register layout per NXP PCA9685 datasheet:
#   0x00 MODE1     bit 4 SLEEP, bit 5 AUTO_INC, bit 7 RESTART
#   0x01 MODE2     (left at chip default — totem-pole output)
#   0x06+4*ch      LEDx_ON_L / ON_H / OFF_L / OFF_H (12-bit counts)
#   0xFE PRE_SCALE prescaler: round(25 MHz / (4096 * freq_hz)) - 1

import time

_MODE1 = 0x00
_PRESCALE = 0xFE
_LED0_ON_L = 0x06

_MODE1_SLEEP = 0x10
_MODE1_RESTART = 0x80
_MODE1_AI = 0x20

# fixed: PCA9685 internal oscillator is a chip constant per the datasheet.
_OSC_FREQ_HZ = 25_000_000
_PRESCALE_MIN = 3
_PRESCALE_MAX = 255
_FREQ_MIN_HZ = 24
_FREQ_MAX_HZ = 1526


class PCA9685:
    """
    Minimal driver for the NXP PCA9685 16-channel 12-bit I2C PWM controller.

    On init: wakes the chip, enables register auto-increment, and applies
    the configured frequency. After construction, all channels are at
    duty 0 (caller must set_duty explicitly to drive any output).
    """

    def __init__(self, i2c, address: int = 0x40, freq_hz: int = 1000):
        self.i2c = i2c
        self.address = address
        self._freq_hz = freq_hz
        self._reset()
        self.set_freq(freq_hz)
        self.all_off()

    def _write8(self, reg: int, val: int) -> None:
        self.i2c.writeto_mem(self.address, reg, bytes([val & 0xFF]))

    def _read8(self, reg: int) -> int:
        return self.i2c.readfrom_mem(self.address, reg, 1)[0]

    def _reset(self) -> None:
        """Wake the chip (clear SLEEP) and enable register auto-increment."""
        self._write8(_MODE1, _MODE1_AI)
        time.sleep_ms(5)

    def set_freq(self, freq_hz: int) -> None:
        """
        Set the PWM frequency for ALL channels (shared on PCA9685).

        Args:
            freq_hz: 24..1526 Hz per datasheet. ValueError if outside that.
        """
        if freq_hz < _FREQ_MIN_HZ or freq_hz > _FREQ_MAX_HZ:
            raise ValueError(f"PCA9685 freq must be {_FREQ_MIN_HZ}-{_FREQ_MAX_HZ} Hz, got {freq_hz}")
        prescale = int(round(_OSC_FREQ_HZ / (4096.0 * freq_hz)) - 1)
        prescale = max(_PRESCALE_MIN, min(_PRESCALE_MAX, prescale))
        old_mode = self._read8(_MODE1)
        # Prescaler is writable only while SLEEP=1; restore mode afterwards.
        self._write8(_MODE1, (old_mode & 0x7F) | _MODE1_SLEEP)
        self._write8(_PRESCALE, prescale)
        self._write8(_MODE1, old_mode)
        time.sleep_ms(5)
        self._write8(_MODE1, old_mode | _MODE1_RESTART | _MODE1_AI)
        self._freq_hz = freq_hz

    def set_duty(self, channel: int, pct: float) -> None:
        """
        Set duty cycle for one channel.

        Args:
            channel: 0..15. ValueError if outside that range.
            pct: 0..100 (clamped). 0 = full off, 100 = full on, mid = PWM.
        """
        if not 0 <= channel <= 15:
            raise ValueError(f"channel must be 0-15, got {channel}")
        if pct < 0:
            pct = 0
        elif pct > 100:
            pct = 100
        if pct <= 0:
            # FULL_OFF flag (bit 12 of OFF) wins over count comparator.
            self._set_pwm(channel, 0, 4096)
        elif pct >= 100:
            # FULL_ON flag (bit 12 of ON) wins over count comparator.
            self._set_pwm(channel, 4096, 0)
        else:
            off_count = int(round(4095 * pct / 100.0))
            self._set_pwm(channel, 0, off_count)

    def _set_pwm(self, channel: int, on: int, off: int) -> None:
        base = _LED0_ON_L + 4 * channel
        data = bytes(
            [
                on & 0xFF,
                (on >> 8) & 0x1F,
                off & 0xFF,
                (off >> 8) & 0x1F,
            ]
        )
        self.i2c.writeto_mem(self.address, base, data)

    def all_off(self) -> None:
        """Drive every channel to duty 0. Used at init and on shutdown."""
        for ch in range(16):
            self.set_duty(ch, 0)

    @property
    def freq_hz(self) -> int:
        return self._freq_hz
