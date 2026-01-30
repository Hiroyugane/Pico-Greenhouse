"""Host-compatible stub for MicroPython `dht` module."""

class DHT22:
    def __init__(self, pin):
        self.pin = pin
        self._temperature = 22.0
        self._humidity = 50.0

    def measure(self):
        # No-op for host testing
        return None

    def temperature(self):
        return self._temperature

    def humidity(self):
        return self._humidity
