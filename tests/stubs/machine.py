"""Host-compatible stubs for MicroPython `machine` module.

These mocks enable running and testing on Windows without hardware.
They intentionally implement only the minimal API surface used by this project.
"""

from __future__ import annotations

import time
from typing import Callable, Optional


class Pin:
    OUT = 0
    IN = 1
    PULL_UP = 2
    IRQ_FALLING = 4

    def __init__(self, pin_id: int, mode: Optional[int] = None, pull: Optional[int] = None):
        self.id = pin_id
        self.mode = mode
        self.pull = pull
        self._value = 0
        self._irq_handler: Optional[Callable] = None

    def init(self, mode: Optional[int] = None, value: Optional[int] = None):
        if mode is not None:
            self.mode = mode
        if value is not None:
            self._value = 1 if value else 0

    def value(self, val: Optional[int] = None):
        if val is None:
            return self._value
        self._value = 1 if val else 0

    def on(self):
        self._value = 1

    def off(self):
        self._value = 0

    def irq(self, trigger: Optional[int] = None, handler: Optional[Callable] = None):
        self._irq_handler = handler

    def __call__(self, val: Optional[int] = None):
        return self.value(val)


class SPI:
    MASTER = 0

    def __init__(self, spi_id: int, baudrate: int = 1_000_000, sck: Optional[Pin] = None,
                 mosi: Optional[Pin] = None, miso: Optional[Pin] = None):
        self.id = spi_id
        self.baudrate = baudrate
        self.sck = sck
        self.mosi = mosi
        self.miso = miso

    def init(self, *args, **kwargs):
        baudrate = kwargs.get('baudrate')
        if baudrate is not None:
            self.baudrate = baudrate

    def write(self, buf):
        return len(buf)

    def readinto(self, buf, fill: int = 0xFF):
        for i in range(len(buf)):
            buf[i] = fill
        return buf


class I2C:
    def __init__(self, i2c_id: int, sda: Optional[Pin] = None, scl: Optional[Pin] = None, freq: int = 100_000):
        self.id = i2c_id
        self.sda = sda
        self.scl = scl
        self.freq = freq

    def writeto_mem(self, addr: int, mem: int, data: bytes):
        # No-op for host testing
        return len(data)

    def readfrom_mem(self, addr: int, mem: int, nbytes: int):
        # Provide a deterministic time in BCD format for RTC reads
        t = time.localtime()
        sec, minute, hour, mday, month, year = t[5], t[4], t[3], t[2], t[1], t[0]
        weekday = t[6] + 1  # RTC weekday typically 1-7

        def to_bcd(value: int) -> int:
            return ((value // 10) << 4) | (value % 10)

        if nbytes >= 7:
            buf = bytes([
                to_bcd(sec),
                to_bcd(minute),
                to_bcd(hour),
                to_bcd(weekday),
                to_bcd(mday),
                to_bcd(month),
                to_bcd(year - 2000),
            ])
            return buf[:nbytes]
        return bytes([0] * nbytes)
