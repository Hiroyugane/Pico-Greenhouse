"""Host-compatible shim for MicroPython machine module.

This lets the project run on standard Python (Windows/macOS/Linux)
by emulating GPIO behavior and printing actions to the console.
"""

from __future__ import annotations

import datetime
import sys
from typing import Callable, Optional


class Pin:
    OUT = 1
    IN = 0
    PULL_UP = 2
    IRQ_FALLING = 4
    IRQ_RISING = 8

    def __init__(self, pin: int, mode: int = OUT, pull: Optional[int] = None):
        self.id = pin
        self.mode = mode
        self.pull = pull
        self._value = 0
        self._irq_handler: Optional[Callable] = None
        self._irq_trigger: Optional[int] = None
        _print(f"[HOST GPIO] Pin {self.id} init mode={_mode_name(mode)} pull={_pull_name(pull)}")

    def value(self, v: Optional[int] = None):
        if v is None:
            return self._value
        self._value = 1 if v else 0
        _print(f"[HOST GPIO] Pin {self.id} set to {self._value}")

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)

    def irq(self, trigger: Optional[int] = None, handler: Optional[Callable] = None):
        self._irq_trigger = trigger
        self._irq_handler = handler
        _print(f"[HOST GPIO] Pin {self.id} IRQ set trigger={trigger} handler={bool(handler)}")

    def simulate_falling_edge(self):
        if self._irq_handler and (self._irq_trigger is not None) and (self._irq_trigger & self.IRQ_FALLING):
            _print(f"[HOST GPIO] Pin {self.id} simulated falling edge")
            self._irq_handler(self)

    def simulate_rising_edge(self):
        if self._irq_handler and (self._irq_trigger is not None) and (self._irq_trigger & self.IRQ_RISING):
            _print(f"[HOST GPIO] Pin {self.id} simulated rising edge")
            self._irq_handler(self)


class SPI:
    def __init__(self, spi_id: int, baudrate: int, sck: Pin, mosi: Pin, miso: Pin):
        self.id = spi_id
        self.baudrate = baudrate
        self.sck = sck
        self.mosi = mosi
        self.miso = miso
        _print(f"[HOST SPI] SPI{self.id} init baudrate={self.baudrate}")


class I2C:
    def __init__(self, port: int, sda: Pin, scl: Pin, freq: int = 100000):
        self.port = port
        self.sda = sda
        self.scl = scl
        self.freq = freq
        _print(f"[HOST I2C] I2C{self.port} init freq={self.freq}")

    def writeto_mem(self, addr: int, reg: int, data: bytes):
        _print(f"[HOST I2C] Write addr=0x{addr:X} reg=0x{reg:X} data={data}")

    def readfrom_mem(self, addr: int, reg: int, length: int) -> bytes:
        # Return DS3231-compatible BCD-encoded datetime for 7-byte reads.
        now = datetime.datetime.now()
        if length >= 7:
            sec = _to_bcd(now.second)
            minute = _to_bcd(now.minute)
            hour = _to_bcd(now.hour)
            weekday = _to_bcd(now.isoweekday())
            day = _to_bcd(now.day)
            month = _to_bcd(now.month)
            year = _to_bcd(now.year % 100)
            data = bytes([sec, minute, hour, weekday, day, month, year])
            _print(f"[HOST I2C] Read addr=0x{addr:X} reg=0x{reg:X} -> {data} ({now.isoformat(sep=' ', timespec='seconds')})")
            return data
        data = bytes([0] * length)
        _print(f"[HOST I2C] Read addr=0x{addr:X} reg=0x{reg:X} -> {data} ({now.isoformat(sep=' ', timespec='seconds')})")
        return data


def _to_bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def _mode_name(mode: int) -> str:
    return {Pin.OUT: "OUT", Pin.IN: "IN"}.get(mode, str(mode))


def _pull_name(pull: Optional[int]) -> str:
    return {Pin.PULL_UP: "PULL_UP", None: "None"}.get(pull, str(pull))


def _print(message: str) -> None:
    sys.stdout.write(message + "\n")
