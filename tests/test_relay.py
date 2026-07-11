# Tests for lib/relay.py
# Covers RelayController (the FanController/GrowlightController policies were
# superseded by the RegulationEngine adapters — see tests/test_regulation_*).

# ============================================================================
# RelayController
# ============================================================================


class TestRelayController:
    """Tests for RelayController base class."""

    def test_initialization_off(self, relay_controller):
        """Relay initializes to OFF state."""
        assert relay_controller.is_on() is False
        assert relay_controller.name == "TestRelay"
        assert relay_controller.invert is True

    def test_turn_on(self, relay_controller):
        """turn_on() sets state to True."""
        relay_controller.turn_on()
        assert relay_controller.is_on() is True

    def test_turn_off(self, relay_controller):
        """turn_off() sets state to False."""
        relay_controller.turn_on()
        relay_controller.turn_off()
        assert relay_controller.is_on() is False

    def test_toggle(self, relay_controller):
        """toggle() alternates state."""
        relay_controller.toggle()
        assert relay_controller.is_on() is True
        relay_controller.toggle()
        assert relay_controller.is_on() is False

    def test_get_state(self, relay_controller):
        """get_state() returns dict with expected keys."""
        state = relay_controller.get_state()
        assert "name" in state
        assert "is_on" in state
        assert "pin" in state
        assert "invert" in state
        assert state["name"] == "TestRelay"
        assert state["is_on"] is False

    def test_non_inverted_mode(self):
        """Relay with invert=False: ON=HIGH, OFF=LOW."""
        from lib.relay import RelayController

        relay = RelayController(16, invert=False, name="NonInv")
        assert relay.invert is False
        relay.turn_on()
        assert relay.is_on() is True
        relay.turn_off()
        assert relay.is_on() is False

    def test_pin_value_inverted(self):
        """Inverted relay: turn_on() calls pin.value(0), turn_off() calls pin.value(1)."""
        from lib.relay import RelayController

        relay = RelayController(16, invert=True)
        relay.turn_on()
        relay.pin.value.assert_called_with(0)  # type: ignore
        relay.turn_off()
        relay.pin.value.assert_called_with(1)  # type: ignore

    def test_pin_value_non_inverted(self):
        """Non-inverted relay: turn_on() calls pin.value(1)."""
        from lib.relay import RelayController

        relay = RelayController(16, invert=False)
        relay.turn_on()
        relay.pin.value.assert_called_with(1)  # type: ignore

    def test_default_name_from_pin(self):
        """Default name is 'Relay_{pin}'."""
        from lib.relay import RelayController

        relay = RelayController(42, invert=True)
        assert relay.name == "Relay_42"
