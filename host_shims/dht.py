"""Host-compatible shim for MicroPython dht module.

Calibrated from real hardware probe data (``host_shims/_probe_data.py``).

Features over the original shim:
- Statistical temperature/humidity model (mean + stddev from probe data)
import random
- Configurable error injection at realistic failure rates.
def _gauss(mu, sigma):
    # Use random.gauss if available, else fallback to Box-Muller
    try:
        return random.gauss(mu, sigma)
    except Exception:
        # Box-Muller transform fallback
        import math
        u1 = random.random()
        u2 = random.random()
        z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)
        return mu + sigma * z0
- Burst-error model (consecutive failures).
- Minimum inter-read interval enforcement.
- Controllable via class attributes for test scenarios.
"""

from __future__ import annotations

import math

import random
import time
from host_shims._probe_data import PROBE

def _gauss(mu, sigma):
    # Use random.gauss if available, else normalvariate
    if hasattr(random, "gauss"):
        return random.gauss(mu, sigma) # type: ignore
    return random.normalvariate(mu, sigma) # type: ignore

class DHT22:
    """Simulated DHT22 (AM2302) sensor.

    Class-level tunables (override for specific test scenarios)::

        DHT22._fail_rate = 0.0       # disable errors
        DHT22._temp_center = 27.0    # force thermostat activation
        DHT22._temp_amplitude = 2.0  # wider swings
        DHT22._error_types = {"OSError": 1.0}  # error types and weights
    """

    # ── Class-level tunables (overridable per-instance or globally) ────
    _fail_rate: float = PROBE.dht.fail_rate
    _max_consecutive_fails: int = PROBE.dht.max_consecutive_fails
    _min_interval_s: float = PROBE.dht.min_interval_s
    _temp_center: float = PROBE.dht.temp_mean
    _temp_stddev: float = PROBE.dht.temp_stddev
    _temp_min: float = PROBE.dht.temp_min
    _temp_max: float = PROBE.dht.temp_max
    _humid_center: float = PROBE.dht.humid_mean
    _humid_stddev: float = PROBE.dht.humid_stddev
    _humid_min: float = PROBE.dht.humid_min
    _humid_max: float = PROBE.dht.humid_max
    _temp_amplitude: float = 3.0  # ±°C daily sine wave
    _error_types: dict[str, float] = dict(PROBE.dht.error_types)

    def __init__(self, pin):
        self.pin = pin
        self._temp: float = self._temp_center
        self._hum: float = self._humid_center
        self._last_measure_time: float = 0.0
        self._consecutive_fails: int = 0
        self._total_reads: int = 0
        self._total_fails: int = 0
        # Seed for deterministic day-cycle simulation
        self._t0 = time.time()

    def measure(self):
        """Simulate a DHT22 sensor read (probe-calibrated endurance).

        Raises ``OSError`` at the configured ``_fail_rate``, with burst
        errors limited to ``_max_consecutive_fails``.  Enforces minimum
        inter-read interval (raises ``OSError`` if called too fast).

        Temperature and humidity match probe-calibrated ranges and drift.
        """
        now = time.time()
        self._total_reads += 1

        # Enforce minimum interval
        if self._last_measure_time > 0:
            elapsed = now - self._last_measure_time
            if elapsed < self._min_interval_s:
                self._total_fails += 1
                self._consecutive_fails += 1
                raise OSError("DHT read too fast ({:.2f}s < {:.2f}s min)".format(
                    elapsed, self._min_interval_s
                ))
        self._last_measure_time = now

        # Error injection with burst limiting
        if self._fail_rate > 0:
            if self._consecutive_fails < self._max_consecutive_fails:
                if random.random() < self._fail_rate:
                    self._total_fails += 1
                    self._consecutive_fails += 1
                    err_type = self._pick_error_type()
                    raise OSError(f"Simulated {err_type} — sensor read failed")
        self._consecutive_fails = 0

        # Temperature: slow drift + probe noise
        noise = _gauss(0, self._temp_stddev)
        raw_temp = self._temp_center + noise
        self._temp = round(max(self._temp_min, min(self._temp_max, raw_temp)), 1)

        # Humidity: probe noise
        humid_noise = _gauss(0, self._humid_stddev)
        raw_humid = self._humid_center + humid_noise
        self._hum = round(max(self._humid_min, min(self._humid_max, raw_humid)), 1)

    def temperature(self) -> float:
        """Return last measured temperature in °C."""
        return float(self._temp)

    def humidity(self) -> float:
        """Return last measured relative humidity in %."""
        return float(self._hum)

    def _pick_error_type(self) -> str:
        """Weighted random selection from configured error types."""
        types = list(self._error_types.keys())
        weights = list(self._error_types.values())
        total = sum(weights)
        if total <= 0:
            return "OSError"
        r = random.random() * total
        cumulative = 0.0
        for t, w in zip(types, weights):
            cumulative += w
            if r <= cumulative:
                return t
        return types[-1]

    # ── Test helpers ──────────────────────────────────────────────────

    def set_temperature(self, temp: float):
        """Force a specific temperature for the next read."""
        self._temp = temp
        self._temp_center = temp
        self._temp_amplitude = 0  # disable sine wave drift

    def set_humidity(self, humid: float):
        """Force a specific humidity for the next read."""
        self._hum = humid
        self._humid_center = humid

    def reset_stats(self):
        """Reset read/fail counters."""
        self._total_reads = 0
        self._total_fails = 0
        self._consecutive_fails = 0
