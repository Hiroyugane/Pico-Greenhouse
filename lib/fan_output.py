# Fan Output Abstraction
# Dennis Hiro, 2026-05-16
#
# FanOutput decouples fan policy classes (FanController,
# AlwaysOnFanController, HeaterFollowerFanController) from the physical
# drive layer. Relay-backed fans wrap a RelayController via
# RelayFanOutput; future PCA9685+MOSFET fans wrap a PWM channel via
# Pca9685FanOutput (added in a later step). Both expose
# on/off/set_duty/is_on so the same policy code drives either.


class FanOutput:
    """
    Abstract drive backend for fan controllers.

    Implementations must provide on/off/set_duty/is_on and a name
    attribute. set_duty(pct) takes a percentage 0-100; binary backends
    (relays) treat any positive value as "fully on" and 0 as off.
    """

    @property
    def name(self) -> str:
        raise NotImplementedError

    def on(self) -> None:
        raise NotImplementedError

    def off(self) -> None:
        raise NotImplementedError

    def set_duty(self, pct: float) -> None:
        raise NotImplementedError

    def is_on(self) -> bool:
        raise NotImplementedError


class RelayFanOutput(FanOutput):
    """
    FanOutput adapter over a RelayController.

    Used by today's relay-backed fans (fan_1 / fan_2 on REL_CON). When
    the PCA9685 PCB lands, per-fan wiring in main.py flips to
    Pca9685FanOutput; policy classes are untouched.

    set_duty(0) opens the relay; any positive duty closes it. The relay
    cannot vary speed, so non-zero duty is collapsed to "fully on".
    """

    def __init__(self, relay):
        self._relay = relay

    @property
    def name(self) -> str:
        return self._relay.name

    @property
    def pin(self):
        return self._relay.pin

    def on(self) -> None:
        self._relay.turn_on()

    def off(self) -> None:
        self._relay.turn_off()

    def set_duty(self, pct: float) -> None:
        if pct <= 0:
            self._relay.turn_off()
        else:
            self._relay.turn_on()

    def is_on(self) -> bool:
        return self._relay.is_on()


class Pca9685FanOutput(FanOutput):
    """
    FanOutput driving one PCA9685 PWM channel.

    Used by the next hardware revision: PCA9685 PWM drives an IRLZ44N
    MOSFET gate which switches the fan supply. set_duty(pct) flows
    straight through to the PCA9685; on() applies default_duty_pct so
    schedule-driven binary controllers (FanController) get the
    configured running speed instead of 100%.
    """

    def __init__(self, pca9685, channel: int, name: str, default_duty_pct: float = 100):
        self._pca = pca9685
        self._channel = channel
        self._name = name
        self._default_duty_pct = default_duty_pct
        self._duty_pct = 0
        self._pca.set_duty(channel, 0)

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel(self) -> int:
        return self._channel

    def on(self) -> None:
        self.set_duty(self._default_duty_pct)

    def off(self) -> None:
        self.set_duty(0)

    def set_duty(self, pct: float) -> None:
        if pct < 0:
            pct = 0
        elif pct > 100:
            pct = 100
        self._pca.set_duty(self._channel, pct)
        self._duty_pct = pct

    def is_on(self) -> bool:
        return self._duty_pct > 0
