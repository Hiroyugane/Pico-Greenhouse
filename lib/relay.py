# Relay Control Module
# Dennis Hiro, 2026-01-29
#
# RelayController: generic stateful GPIO switch used for every relay channel
# and (with invert=False) the active-HIGH heater MOSFET gate. The scheduling
# policies that used to live here (FanController, GrowlightController) were
# superseded by the RegulationEngine pipeline (lib/regulation_*).

from machine import Pin


class RelayController:
    """
    Generic relay controller wrapping a GPIO pin.

    Handles inverted logic (HIGH=off, LOW=on typical for relay modules).
    Provides simple on/off/toggle API and state tracking.

    Attributes:
        pin: machine.Pin instance
        name: Relay name (for logging)
        invert: Whether to invert logic (HIGH=off)
        _state: Current relay state (True=on, False=off)
    """

    def __init__(self, pin: int, invert: bool = True, name=None, logger=None):
        """
        Initialize relay controller.

        Args:
            pin (int): GPIO pin number
            invert (bool): If True, HIGH=off (default: True for relay modules)
            name (str, optional): Relay name for logging
            logger: EventLogger instance (optional, for debug output)
        """
        self.pin = Pin(pin, Pin.OUT)
        self.name = name or f"Relay_{pin}"
        self.invert = invert
        self._state = False
        self._logger = logger

        # Initialize to OFF (HIGH if inverted) without calling overridable methods
        off_value = 1 if self.invert else 0
        self.pin.value(off_value)
        if self._logger:
            self._logger.debug("Relay", f"{self.name} init: pin={pin}, invert={invert}, initial_value={off_value}")

    def turn_on(self) -> None:
        """Activate relay (physical on)."""
        value = 0 if self.invert else 1
        self.pin.value(value)
        self._state = True
        if self._logger:
            self._logger.debug("Relay", f"{self.name} turn_on: gpio={value}")

    def turn_off(self) -> None:
        """Deactivate relay (physical off)."""
        value = 1 if self.invert else 0
        self.pin.value(value)
        self._state = False
        if self._logger:
            self._logger.debug("Relay", f"{self.name} turn_off: gpio={value}")

    def toggle(self) -> None:
        """Toggle relay state."""
        if self._state:
            self.turn_off()
        else:
            self.turn_on()

    def is_on(self) -> bool:
        """Return current state."""
        return self._state

    def get_state(self) -> dict:
        """Return state dict for debugging."""
        return {
            "name": self.name,
            "is_on": self._state,
            "pin": self.pin,
            "invert": self.invert,
        }
