# Mode-specific fan controllers
# Dennis Hiro, 2026-05-16
#
# FanController (lib/relay.py) covers the original thermostat_schedule
# mode. This module holds the two additional policies the PCA9685 PCB
# revision needs:
#   AlwaysOnFanController     — constant duty (Pico case fan)
#   HeaterFollowerFanController — follow HeaterController state plus
#                                 a configurable post-run afterrun
# Both consume a FanOutput so they work over relays today and over
# PCA9685 PWM channels after the next-rev PCB lands.

import uasyncio as asyncio


class AlwaysOnFanController:
    """
    Fan controller that holds one configured duty cycle from boot.

    Constructor calls output.set_duty(duty_pct) once so the fan starts
    immediately. start_cycle() re-asserts the duty every
    refresh_interval_s as cheap insurance against I2C bus glitches.

    Used today for the Pico case fan (always-on cooling, no schedule,
    no thermostat).
    """

    def __init__(
        self,
        output,
        logger,
        duty_pct: float,
        refresh_interval_s: int,
        name=None,
    ):
        self._output = output
        self.logger = logger
        self.duty_pct = duty_pct
        self.refresh_interval_s = refresh_interval_s
        self.name = name or getattr(output, "name", "AlwaysOnFan")

        self._output.set_duty(duty_pct)
        logger.info(
            "AlwaysOnFanController",
            f"{self.name} held at {duty_pct}% (refresh every {refresh_interval_s}s)",
        )
        logger.debug(
            "AlwaysOnFanController",
            "init config",
            name=self.name,
            duty_pct=duty_pct,
            refresh_interval_s=refresh_interval_s,
        )

    @property
    def pin(self):
        return getattr(self._output, "pin", None)

    def turn_on(self) -> None:
        self._output.set_duty(self.duty_pct)

    def turn_off(self) -> None:
        self._output.set_duty(0)

    def is_on(self) -> bool:
        return self._output.is_on()

    async def start_cycle(self) -> None:
        """Re-assert the configured duty every refresh_interval_s."""
        while True:
            try:
                await asyncio.sleep(self.refresh_interval_s)
                self._output.set_duty(self.duty_pct)
                self.logger.debug(
                    "AlwaysOnFanController",
                    "duty re-asserted",
                    name=self.name,
                    duty_pct=self.duty_pct,
                )
            except asyncio.CancelledError:
                self._output.set_duty(0)
                self.logger.warning("AlwaysOnFanController", f"{self.name} cycle cancelled")
                raise
            except Exception as e:
                self.logger.error("AlwaysOnFanController", f"{self.name} refresh failed: {e}")
                await asyncio.sleep(1)

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "is_on": self._output.is_on(),
            "duty_pct": self.duty_pct,
            "mode": "always_on",
        }
