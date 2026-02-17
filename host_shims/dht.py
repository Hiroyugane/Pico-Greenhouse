"""Host-compatible shim for MicroPython dht module.

Calibrated from real hardware probe data (``host_shims/_probe_data.py``).

Features over the original shim:
- Statistical temperature/humidity model (mean + stddev from probe data)
  that can drift into fan-thermostat trigger zones.
- Configurable error injection at realistic failure rates.
- Burst-error model (consecutive failures).
- Minimum inter-read interval enforcement.
- Controllable via class attributes for test scenarios.
"""

from __future__ import annotations

import math
import random
import time

from host_shims._probe_data import PROBE


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
        """Simulate a DHT22 sensor read.

        Raises ``OSError`` at the configured ``_fail_rate``, with burst
        errors limited to ``_max_consecutive_fails``.  Enforces minimum
        inter-read interval (raises ``OSError`` if called too fast).

        Temperature drifts on a slow sine wave to naturally cross
        thermostat thresholds during long host-sim runs.
        """
        now = time.time()
        self._total_reads += 1

        # Enforce minimum interval (real DHT22 needs ≥2s, probe finds minimum)
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
                    # Pick error type based on weight distribution
                    err_type = self._pick_error_type()
                    raise OSError(f"Simulated {err_type} — sensor read failed")
            # Force success after max consecutive fails
            # (real sensors recover after a few retries)

        self._consecutive_fails = 0

        # Temperature: slow sine wave + Gaussian noise
        # Period ~6 hours so it crosses thresholds during a typical run
        elapsed_hours = (now - self._t0) / 3600
        sine_component = self._temp_amplitude * math.sin(2 * math.pi * elapsed_hours / 6)
        noise = random.gauss(0, self._temp_stddev)
        raw_temp = self._temp_center + sine_component + noise
        self._temp = round(max(self._temp_min, min(self._temp_max, raw_temp)), 1)

        # Humidity: inversely correlated with temperature + noise
        humid_noise = random.gauss(0, self._humid_stddev)
        temp_effect = -(self._temp - self._temp_center) * 1.5  # warmer → drier
        raw_humid = self._humid_center + temp_effect + humid_noise
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
