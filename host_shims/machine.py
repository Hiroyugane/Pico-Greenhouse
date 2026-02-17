"""Host-compatible shim for MicroPython machine module.

This lets the project run on standard Python (Windows/macOS/Linux)
by emulating GPIO behavior and printing actions to the console.

Improvements over the basic shim:
- Pin: realistic boot-state defaults from probe data, auto-bounce IRQ model,
  ``init()`` re-initialisation, ``high()``/``low()`` aliases.
- SPI: full ``read``/``readinto``/``write``/``write_readinto``/``deinit`` API;
  configurable error injection for SD-eject simulation.
- I2C: ``scan()`` returns real addresses; ``writeto_mem`` stores BCD time;
  configurable drift model; DS3231 temperature register simulation.
- RTC: ``datetime()`` get/set matching MicroPython's tuple format with
  optional drift.
- ADC: reads from probe-calibrated noise distributions.
- UART: stub for CO2 sensor (placeholder).
- ``freq()``, ``unique_id()``, ``reset()``, ``idle()`` module-level helpers.
"""

from __future__ import annotations

import datetime
import os
import random
import sys
import threading
import time
from typing import Callable, Optional

from host_shims._probe_data import PROBE

# ── Module-level helpers (machine.freq(), machine.unique_id(), …) ─────────

_current_freq = PROBE.platform.machine_freq_hz


def freq(new_freq: int | None = None) -> int | None:
    global _current_freq
    if new_freq is None:
        return _current_freq
    _current_freq = new_freq
    _print(f"[HOST machine] freq set to {new_freq}")
    return None


def unique_id() -> bytes:
    uid_hex = PROBE.platform.unique_id
    return bytes.fromhex(uid_hex)


def reset():
    _print("[HOST machine] reset() called — no-op on host")


def idle():
    time.sleep(0.001)


def lightsleep(time_ms: int = 0):
    time.sleep(time_ms / 1000)


def deepsleep(time_ms: int = 0):
    _print(f"[HOST machine] deepsleep({time_ms}) — sleeping on host")
    time.sleep(time_ms / 1000)


# ── Pin ───────────────────────────────────────────────────────────────────

class Pin:
    # Mode constants
    IN = 0
    OUT = 1
    OPEN_DRAIN = 2
    ALT = 3
    ALT_OPEN_DRAIN = 7

    # Pull constants
    PULL_UP = 1
    PULL_DOWN = 2
    PULL_HOLD = 4

    # IRQ trigger constants
    IRQ_FALLING = 4
    IRQ_RISING = 8
    IRQ_LOW_LEVEL = 16
    IRQ_HIGH_LEVEL = 32

    # Drive strength constants
    LOW_POWER = 0
    MED_POWER = 1
    HIGH_POWER = 2

    def __init__(
        self,
        pin: int,
        mode: int = -1,
        pull: Optional[int] = None,
        *,
        value: Optional[int] = None,
        drive: Optional[int] = None,
        alt: Optional[int] = None,
    ):
        self.id = pin
        self._mode = mode if mode != -1 else self.IN
        self._pull = pull
        self._drive = drive
        self._alt = alt
        self._irq_handler: Optional[Callable] = None
        self._irq_trigger: int = 0
        self._irq_hard: bool = False
        self._bounce_thread: Optional[threading.Thread] = None

        # Set initial value based on probe data boot state or explicit value
        if value is not None:
            self._value = 1 if value else 0
        elif pin in PROBE.gpio.boot_state:
            self._value = PROBE.gpio.boot_state[pin]
        else:
            self._value = 0

        _print(
            f"[HOST GPIO] Pin {self.id} init mode={_mode_name(self._mode)} "
            f"pull={_pull_name(pull)} value={self._value}"
        )

    def init(
        self,
        mode: int = -1,
        pull: Optional[int] = None,
        *,
        value: Optional[int] = None,
        drive: Optional[int] = None,
        alt: Optional[int] = None,
    ):
        """Re-initialise the pin (matches MicroPython API)."""
        if mode != -1:
            self._mode = mode
        if pull is not None:
            self._pull = pull
        if drive is not None:
            self._drive = drive
        if alt is not None:
            self._alt = alt
        if value is not None:
            self._value = 1 if value else 0
        _print(
            f"[HOST GPIO] Pin {self.id} re-init mode={_mode_name(self._mode)} "
            f"pull={_pull_name(self._pull)}"
        )

    def value(self, v: Optional[int] = None) -> Optional[int]:
        if v is None:
            return self._value
        new = 1 if v else 0
        if new != self._value:
            self._value = new
            _print(f"[HOST GPIO] Pin {self.id} -> {new}")
        else:
            self._value = new
        return None

    def __call__(self, v: Optional[int] = None) -> Optional[int]:
        return self.value(v)

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)

    def high(self):
        self.value(1)

    def low(self):
        self.value(0)

    def irq(
        self,
        handler: Optional[Callable] = None,
        trigger: Optional[int] = None,
        *,
        priority: int = 1,
        wake: Optional[int] = None,
        hard: bool = False,
    ):
        """Configure interrupt handler.

        The handler is stored and can be triggered manually via
        ``simulate_falling_edge()`` / ``simulate_rising_edge()``,
        or automatically via ``simulate_press()``.
        """
        if trigger is None:
            trigger = self.IRQ_FALLING | self.IRQ_RISING
        self._irq_trigger = trigger
        self._irq_handler = handler
        self._irq_hard = hard
        _print(
            f"[HOST GPIO] Pin {self.id} IRQ trigger={trigger} "
            f"handler={'set' if handler else 'None'} hard={hard}"
        )

    # ── Manual edge simulation (existing API) ─────────────────────────

    def simulate_falling_edge(self):
        """Simulate a button press (HIGH→LOW)."""
        self._value = 0
        if self._irq_handler and (self._irq_trigger & self.IRQ_FALLING):
            self._irq_handler(self)

    def simulate_rising_edge(self):
        """Simulate a button release (LOW→HIGH)."""
        self._value = 1
        if self._irq_handler and (self._irq_trigger & self.IRQ_RISING):
            self._irq_handler(self)

    # ── Automatic bounce simulation (new) ─────────────────────────────

    def simulate_press(self, hold_ms: int = 200):
        """Simulate a complete button press with realistic bounce.

        Fires a burst of FALLING/RISING edges (bounce), then holds low
        for *hold_ms*, then fires bounce edges again on release.
        Runs on a background thread to not block the caller.
        """
        def _bounce_sequence():
            bounce_count = max(1, int(PROBE.button.avg_bounce_edges))
            bounce_us = PROBE.button.avg_bounce_duration_us

            # Press bounce
            for i in range(bounce_count):
                self._value = i % 2  # alternate 0/1
                if self._irq_handler:
                    if (self._value == 0 and self._irq_trigger & self.IRQ_FALLING) or \
                       (self._value == 1 and self._irq_trigger & self.IRQ_RISING):
                        self._irq_handler(self)
                time.sleep(bounce_us / bounce_count / 1_000_000)

            # Settled LOW (pressed)
            self._value = 0
            if self._irq_handler and (self._irq_trigger & self.IRQ_FALLING):
                self._irq_handler(self)

            # Hold
            time.sleep(hold_ms / 1000)

            # Release bounce
            for i in range(bounce_count):
                self._value = (i + 1) % 2
                if self._irq_handler:
                    if (self._value == 0 and self._irq_trigger & self.IRQ_FALLING) or \
                       (self._value == 1 and self._irq_trigger & self.IRQ_RISING):
                        self._irq_handler(self)
                time.sleep(bounce_us / bounce_count / 1_000_000)

            # Settled HIGH (released)
            self._value = 1
            if self._irq_handler and (self._irq_trigger & self.IRQ_RISING):
                self._irq_handler(self)

        t = threading.Thread(target=_bounce_sequence, daemon=True)
        t.start()
        self._bounce_thread = t


# ── SPI ───────────────────────────────────────────────────────────────────

class SPI:
    """Host SPI shim with full MicroPython-compatible data transfer API.

    All data methods operate on in-memory buffers.  When ``_error_after``
    is set >0, an ``OSError`` is raised after that many operations to
    simulate SD card ejection.
    """

    MSB = 0
    LSB = 1

    def __init__(
        self,
        spi_id: int,
        baudrate: int = 1_000_000,
        *,
        polarity: int = 0,
        phase: int = 0,
        bits: int = 8,
        firstbit: int = 0,
        sck: Optional[Pin] = None,
        mosi: Optional[Pin] = None,
        miso: Optional[Pin] = None,
    ):
        self.id = spi_id
        self.baudrate = baudrate
        self.polarity = polarity
        self.phase = phase
        self.bits = bits
        self.sck = sck
        self.mosi = mosi
        self.miso = miso
        self._deinited = False
        self._op_count = 0
        self._error_after = 0  # 0 = never error
        _print(f"[HOST SPI] SPI{self.id} init baudrate={self.baudrate}")

    def init(self, baudrate: int = -1, **kwargs):
        if baudrate != -1:
            self.baudrate = baudrate
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self._deinited = False

    def deinit(self):
        self._deinited = True
        _print(f"[HOST SPI] SPI{self.id} deinit")

    def _check(self):
        if self._deinited:
            raise OSError("SPI bus deinited")
        self._op_count += 1
        if self._error_after > 0 and self._op_count > self._error_after:
            raise OSError(5, "EIO")  # Simulate card ejection

    def read(self, nbytes: int, write: int = 0x00) -> bytes:
        self._check()
        return bytes([0xFF] * nbytes)

    def readinto(self, buf: bytearray, write: int = 0x00) -> None:
        self._check()
        for i in range(len(buf)):
            buf[i] = 0xFF

    def write(self, buf: bytes) -> None:
        self._check()

    def write_readinto(self, write_buf: bytes, read_buf: bytearray) -> None:
        self._check()
        for i in range(min(len(write_buf), len(read_buf))):
            read_buf[i] = 0xFF

    def set_error_after(self, n: int):
        """Test helper: raise OSError after *n* more SPI operations."""
        self._error_after = n
        self._op_count = 0


# ── I2C ───────────────────────────────────────────────────────────────────

_DS3231_ADDR = 0x68


class I2C:
    """Host I2C shim with DS3231-aware register model.

    - ``readfrom_mem(0x68, 0x00, 7)`` returns BCD-encoded system time ±drift.
    - ``readfrom_mem(0x68, 0x11, 2)`` returns a simulated temperature register.
    - ``writeto_mem(0x68, 0x00, data)`` stores BCD time (making SetTime work).
    - ``scan()`` returns probe-calibrated addresses.
    """

    def __init__(self, port: int, *, sda: Optional[Pin] = None, scl: Optional[Pin] = None, freq: int = 100_000):
        self.port = port
        self.sda = sda
        self.scl = scl
        self.freq = freq
        self._time_offset = datetime.timedelta(0)  # Adjustable via writeto_mem
        self._custom_time: Optional[bytes] = None   # Set via SetTime
        self._error_mode = False  # If True, all ops raise OSError
        _print(f"[HOST I2C] I2C{self.port} init freq={self.freq}")

    def scan(self) -> list[int]:
        """Return I2C addresses from probe data."""
        _print(f"[HOST I2C] scan -> {[hex(a) for a in PROBE.i2c.addresses]}")
        return list(PROBE.i2c.addresses)

    def readfrom(self, addr: int, nbytes: int) -> bytes:
        if self._error_mode:
            raise OSError("I2C read error")
        return bytes([0] * nbytes)

    def writeto(self, addr: int, buf: bytes) -> None:
        if self._error_mode:
            raise OSError("I2C write error")

    def readfrom_mem(self, addr: int, reg: int, length: int) -> bytes:
        if self._error_mode:
            raise OSError("I2C read error — device not connected")

        # DS3231: register 0x00 — time registers (7-byte or 19-byte dump)
        if addr == _DS3231_ADDR and reg == 0x00:
            if length >= 19:
                return self._ds3231_full_registers()
            if length >= 7:
                return self._ds3231_time_registers(length)

        # DS3231: temperature register (0x11–0x12)
        if addr == _DS3231_ADDR and reg == 0x11 and length >= 2:
            return self._ds3231_temp_register()

        # DS3231: control/status/aging/temp registers (0x0E–0x12)
        if addr == _DS3231_ADDR and reg >= 0x0E:
            return self._ds3231_control_registers(reg, length)

        data = bytes([0] * length)
        return data

    def writeto_mem(self, addr: int, reg: int, data: bytes) -> None:
        if self._error_mode:
            raise OSError("I2C write error — device not connected")

        # DS3231: writing time registers
        if addr == _DS3231_ADDR and reg == 0x00 and len(data) >= 7:
            self._custom_time = bytes(data[:7])
            _print(f"[HOST I2C] DS3231 time set: {[hex(b) for b in data[:7]]}")
            return

        _print(f"[HOST I2C] Write addr=0x{addr:02X} reg=0x{reg:02X} data={data}")

    def _ds3231_time_registers(self, length: int) -> bytes:
        """Return BCD-encoded time for a 7-byte DS3231 read."""
        if self._custom_time:
            data = bytearray(self._custom_time)
            if length > 7:
                data.extend(bytes(length - 7))
            return bytes(data)

        now = datetime.datetime.now() + self._time_offset
        sec = _to_bcd(now.second)
        minute = _to_bcd(now.minute)
        hour = _to_bcd(now.hour)
        weekday = _to_bcd(now.isoweekday())
        day = _to_bcd(now.day)
        month = _to_bcd(now.month)
        year = _to_bcd(now.year % 100)
        data = bytearray([sec, minute, hour, weekday, day, month, year])
        if length > 7:
            data.extend(bytes(length - 7))
        return bytes(data)

    def _ds3231_temp_register(self) -> bytes:
        """Return 2-byte temperature register (0x11–0x12)."""
        temp = PROBE.adc.internal_temp_c_mean + random.gauss(0, 0.25)
        msb = int(temp)
        lsb = int((temp - msb) / 0.25) << 6
        if temp < 0:
            msb = (~abs(int(temp))) & 0xFF
            lsb = int((abs(temp) - abs(int(temp))) / 0.25) << 6
        return bytes([msb & 0xFF, lsb & 0xFF])

    def _ds3231_control_registers(self, start_reg: int, length: int) -> bytes:
        """Return control/status/aging/temp registers (0x0E–0x12)."""
        control = PROBE.i2c.ds3231_control
        status = PROBE.i2c.ds3231_status
        aging = PROBE.i2c.aging_offset & 0xFF
        temp_bytes = self._ds3231_temp_register()
        full = bytes([control, status, aging, temp_bytes[0], temp_bytes[1]])
        offset = start_reg - 0x0E
        return full[offset : offset + length]

    def _ds3231_full_registers(self) -> bytes:
        """Return complete 19-byte register dump."""
        time_regs = bytearray(self._ds3231_time_registers(7))
        alarms = bytes([0x00] * 7)  # Alarm 1 (4 bytes) + Alarm 2 (3 bytes)
        ctrl = self._ds3231_control_registers(0x0E, 5)
        return bytes(time_regs) + alarms + ctrl

    def set_error_mode(self, enabled: bool = True):
        """Test helper: make all I2C ops raise OSError."""
        self._error_mode = enabled


# ── RTC (Pico internal RTC) ──────────────────────────────────────────────

class RTC:
    """Host shim for ``machine.RTC`` — the Pico's internal (non-DS3231) RTC.

    ``datetime()`` returns/sets an 8-tuple:
    ``(year, month, day, weekday, hours, minutes, seconds, subseconds)``
    """

    def __init__(self):
        self._offset = datetime.timedelta(0)

    def datetime(self, dt: Optional[tuple] = None):
        if dt is not None:
            now = datetime.datetime.now()
            target = datetime.datetime(dt[0], dt[1], dt[2], dt[4], dt[5], dt[6])
            self._offset = target - now
            return None
        now = datetime.datetime.now() + self._offset
        return (
            now.year,
            now.month,
            now.day,
            now.weekday(),  # 0=Monday
            now.hour,
            now.minute,
            now.second,
            0,  # subseconds
        )


# ── ADC ───────────────────────────────────────────────────────────────────

class ADC:
    """Host shim for ``machine.ADC``.

    Supports channel numbers (0–4) and Pin objects.
    Channel 4 = internal temperature sensor.
    """

    CORE_TEMP = 4

    def __init__(self, pin_or_channel):
        if isinstance(pin_or_channel, Pin):
            self._channel = pin_or_channel.id - 26  # GP26=ch0, GP27=ch1, …
            self._pin = pin_or_channel
        elif isinstance(pin_or_channel, int):
            self._channel = pin_or_channel
            self._pin = None
        else:
            self._channel = 0
            self._pin = None

    def read_u16(self) -> int:
        """Return a 16-bit ADC reading (0–65535)."""
        if self._channel == 4:
            # Internal temperature sensor: T = 27 - (V - 0.706) / 0.001721
            temp = PROBE.adc.internal_temp_c_mean + random.gauss(0, PROBE.adc.internal_temp_c_stddev)
            voltage = 0.706 - (temp - 27.0) * 0.001721
            return max(0, min(65535, int(voltage / 3.3 * 65535)))
        if self._pin and self._pin.id == 29:
            # Vsys: ~3.3V through a 3:1 divider
            v = PROBE.adc.vsys_v_mean / 3.0 + random.gauss(0, 0.01)
            return max(0, min(65535, int(v / 3.3 * 65535)))
        # Floating analog pin — random noise
        return random.randint(0, PROBE.adc.floating_noise_u16_max)


# ── PWM ───────────────────────────────────────────────────────────────────

class PWM:
    """Host shim for MicroPython machine.PWM.

    Emulates the PWM API used to drive a passive buzzer (or other
    PWM peripherals).  No real hardware output; prints state changes.
    """

    def __init__(self, pin: "Pin", *, freq: int = 0, duty_u16: int = 0):
        self._pin = pin if isinstance(pin, Pin) else Pin(pin, Pin.OUT)
        self._freq = freq
        self._duty_u16 = duty_u16
        _print(
            f"[HOST PWM] PWM on Pin {self._pin.id} "
            f"freq={self._freq} duty_u16={self._duty_u16}"
        )

    def freq(self, value: Optional[int] = None) -> Optional[int]:
        """Get or set the PWM frequency in Hz."""
        if value is None:
            return self._freq
        self._freq = value
        _print(f"[HOST PWM] Pin {self._pin.id} freq -> {value} Hz")
        return None

    def duty_u16(self, value: Optional[int] = None) -> Optional[int]:
        """Get or set 16-bit duty cycle (0–65535)."""
        if value is None:
            return self._duty_u16
        self._duty_u16 = max(0, min(65535, value))
        _print(f"[HOST PWM] Pin {self._pin.id} duty_u16 -> {self._duty_u16}")
        return None

    def duty_ns(self, value: Optional[int] = None) -> Optional[int]:
        """Get or set duty in nanoseconds (approximate)."""
        if value is None:
            if self._freq == 0:
                return 0
            period_ns = 1_000_000_000 // self._freq
            return int(self._duty_u16 / 65535 * period_ns)
        # Convert ns to u16
        if self._freq > 0:
            period_ns = 1_000_000_000 // self._freq
            self._duty_u16 = max(0, min(65535, int(value / period_ns * 65535)))
        return None

    def deinit(self):
        """Release PWM channel."""
        self._duty_u16 = 0
        self._freq = 0
        _print(f"[HOST PWM] Pin {self._pin.id} deinit")


# ── Timer ─────────────────────────────────────────────────────────────────

class Timer:
    ONE_SHOT = 0
    PERIODIC = 1

    def __init__(self, period: int = -1, mode: int = PERIODIC, callback=None, **kwargs):
        self._period = period
        self._mode = mode
        self._callback = callback
        self._timer: Optional[threading.Timer] = None
        if period > 0 and callback:
            self.init(period=period, mode=mode, callback=callback)

    def init(self, *, period: int = -1, mode: int = PERIODIC, callback=None):
        self.deinit()
        self._period = period
        self._mode = mode
        self._callback = callback
        if period > 0 and callback:
            self._start()

    def _start(self):
        def _fire():
            if self._callback:
                self._callback(self)
            if self._mode == self.PERIODIC and self._period > 0:
                self._start()

        self._timer = threading.Timer(self._period / 1000, _fire)
        self._timer.daemon = True
        self._timer.start()

    def deinit(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None


# ── UART (stub) ───────────────────────────────────────────────────────────

class UART:
    """Placeholder UART shim for future CO2 sensor support."""

    def __init__(self, id: int, baudrate: int = 9600, *, tx: Optional[Pin] = None, rx: Optional[Pin] = None):
        self.id = id
        self.baudrate = baudrate
        self._rx_buffer = bytearray()

    def read(self, nbytes: int = -1) -> Optional[bytes]:
        if not self._rx_buffer:
            return None
        if nbytes < 0:
            data = bytes(self._rx_buffer)
            self._rx_buffer.clear()
            return data
        data = bytes(self._rx_buffer[:nbytes])
        self._rx_buffer = self._rx_buffer[nbytes:]
        return data

    def write(self, buf: bytes) -> int:
        return len(buf)

    def any(self) -> int:
        return len(self._rx_buffer)

    def readline(self) -> Optional[bytes]:
        idx = self._rx_buffer.find(b"\n")
        if idx < 0:
            return None
        line = bytes(self._rx_buffer[: idx + 1])
        self._rx_buffer = self._rx_buffer[idx + 1 :]
        return line

    def _inject_rx(self, data: bytes):
        """Test helper: inject data into the receive buffer."""
        self._rx_buffer.extend(data)


# ── WDT (stub) ────────────────────────────────────────────────────────────

class WDT:
    def __init__(self, timeout: int = 5000):
        pass

    def feed(self):
        pass


# ── Helpers ───────────────────────────────────────────────────────────────

def _to_bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def _mode_name(mode: int) -> str:
    return {
        Pin.IN: "IN",
        Pin.OUT: "OUT",
        Pin.OPEN_DRAIN: "OPEN_DRAIN",
        Pin.ALT: "ALT",
    }.get(mode, str(mode))


def _pull_name(pull: Optional[int]) -> str:
    return {
        Pin.PULL_UP: "PULL_UP",
        Pin.PULL_DOWN: "PULL_DOWN",
        None: "None",
    }.get(pull, str(pull))


_VERBOSE = os.environ.get("HOST_SHIM_VERBOSE", "1") != "0"


def _print(message: str) -> None:
    """Print shim debug output; suppressed unless HOST_SHIM_VERBOSE=1."""
    if _VERBOSE:
        sys.stdout.write(message + "\n")
