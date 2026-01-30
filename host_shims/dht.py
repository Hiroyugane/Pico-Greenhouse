"""Host-compatible shim for MicroPython dht module."""

import time


class DHT22:
    def __init__(self, pin):
        self.pin = pin
        self._temp = 22.5
        self._hum = 55.0

    def measure(self):
        # Simulate small drift over time
        t = time.time()
        self._temp = 22.0 + (t % 10) * 0.05
        self._hum = 55.0 + (t % 7) * 0.1

    def temperature(self):
        return float(self._temp)

    def humidity(self):
        return float(self._hum)
