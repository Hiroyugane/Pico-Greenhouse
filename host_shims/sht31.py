"""Host-compatible shim for the project's ``lib.sht31`` driver.

Simulates a Sensirion SHT31-D on the shared I2C bus. The shim ignores the
``i2c`` argument (it never talks to a bus); it produces probe-calibrated
temperature / humidity values and injects occasional read failures so the
host run exercises the same retry / fallback paths as the device.

Tunable via class attributes:

    SHT31._fail_rate = 0.0       # disable simulated errors
    SHT31._temp_center = 27.0    # force thermostat activation
    SHT31._humid_center = 80.0   # force high-humidity scenarios
"""

from __future__ import annotations

import random
import time

from host_shims._probe_data import PROBE


def _gauss(mu: float, sigma: float) -> float:
    if hasattr(random, "gauss"):
        return random.gauss(mu, sigma)
    return random.normalvariate(mu, sigma)


class SHT31:
    """Simulated SHT31-D temperature/humidity sensor on I2C."""

    _fail_rate: float = max(0.001, PROBE.sht31.fail_rate * 0.25)
    _max_consecutive_fails: int = PROBE.sht31.max_consecutive_fails
    _min_interval_s: float = PROBE.sht31.min_interval_s
    _temp_center: float = PROBE.sht31.temp_mean
    _temp_stddev: float = PROBE.sht31.temp_stddev
    _temp_min: float = PROBE.sht31.temp_min
    _temp_max: float = PROBE.sht31.temp_max
    _humid_center: float = PROBE.sht31.humid_mean
    _humid_stddev: float = PROBE.sht31.humid_stddev
    _humid_min: float = PROBE.sht31.humid_min
    _humid_max: float = PROBE.sht31.humid_max

    def __init__(self, i2c=None, address: int = 0x44):
        self.i2c = i2c
        self.address = address
        self._temp: float = self._temp_center
        self._hum: float = self._humid_center
        self._last_measure_time: float = 0.0
        self._consecutive_fails: int = 0
        self._total_reads: int = 0
        self._total_fails: int = 0

    def reset(self) -> None:
        """Soft-reset is a no-op on the simulator."""
        return None

    def measure(self) -> None:
        """Simulate a single-shot SHT31 read (I2C-style failures)."""
        now = time.time()
        self._total_reads += 1

        if self._last_measure_time > 0:
            elapsed = now - self._last_measure_time
            if elapsed < self._min_interval_s:
                self._total_fails += 1
                self._consecutive_fails += 1
                raise OSError(
                    "SHT31 read too fast ({:.2f}s < {:.2f}s min)".format(elapsed, self._min_interval_s)
                )
        self._last_measure_time = now

        if self._fail_rate > 0 and self._consecutive_fails < self._max_consecutive_fails:
            if random.random() < self._fail_rate:
                self._total_fails += 1
                self._consecutive_fails += 1
                raise OSError("Simulated SHT31 I2C transport failure")
        self._consecutive_fails = 0

        raw_temp = self._temp_center + _gauss(0, self._temp_stddev)
        self._temp = round(max(self._temp_min, min(self._temp_max, raw_temp)), 2)

        raw_hum = self._humid_center + _gauss(0, self._humid_stddev)
        self._hum = round(max(self._humid_min, min(self._humid_max, raw_hum)), 2)

    def temperature(self) -> float:
        return float(self._temp)

    def humidity(self) -> float:
        return float(self._hum)

    # ── Test helpers ──────────────────────────────────────────────────
    def set_temperature(self, temp: float) -> None:
        self._temp = temp
        self._temp_center = temp

    def set_humidity(self, humid: float) -> None:
        self._hum = humid
        self._humid_center = humid

    def reset_stats(self) -> None:
        self._total_reads = 0
        self._total_fails = 0
        self._consecutive_fails = 0
