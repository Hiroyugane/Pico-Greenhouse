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


class HeaterFollowerFanController:
    """
    Fan that runs while the heater is firing, plus a configurable
    afterrun (post_run_s) to purge residual heat from the element.

    Polls HeaterController.is_on() every poll_interval_s. The afterrun
    timer is reset to post_run_s whenever the heater is observed on, so
    flickering on/off cycles keep the fan running smoothly until at
    least post_run_s of continuous heater-off has elapsed.

    Used today for the heater_distribution fan after the PCA9685 PCB
    lands; FanOutput abstraction means the same code drives a relay if
    needed.
    """

    def __init__(
        self,
        output,
        heater,
        logger,
        duty_pct: float,
        post_run_s: int,
        poll_interval_s: int,
        name=None,
    ):
        self._output = output
        self._heater = heater
        self.logger = logger
        self.duty_pct = duty_pct
        self.post_run_s = post_run_s
        self.poll_interval_s = poll_interval_s
        self.name = name or getattr(output, "name", "HeaterFollowerFan")

        self._afterrun_remaining_s = 0
        # Fail safe: start off.
        self._output.set_duty(0)

        logger.info(
            "HeaterFollowerFanController",
            f"{self.name} follows heater (duty {duty_pct}%, afterrun {post_run_s}s)",
        )
        logger.debug(
            "HeaterFollowerFanController",
            "init config",
            name=self.name,
            duty_pct=duty_pct,
            post_run_s=post_run_s,
            poll_interval_s=poll_interval_s,
        )

    @property
    def pin(self):
        return getattr(self._output, "pin", None)

    def turn_on(self) -> None:
        self._output.set_duty(self.duty_pct)

    def turn_off(self) -> None:
        self._output.set_duty(0)
        self._afterrun_remaining_s = 0

    def is_on(self) -> bool:
        return self._output.is_on()

    async def start_cycle(self) -> None:
        """Mirror heater.is_on(); keep fan running for post_run_s after off."""
        while True:
            try:
                heater_on = self._heater.is_on()
                if heater_on:
                    # Heater firing — fan on, afterrun timer fully primed.
                    self._afterrun_remaining_s = self.post_run_s
                    if not self._output.is_on():
                        self._output.set_duty(self.duty_pct)
                        self.logger.info(
                            "HeaterFollowerFanController",
                            f"{self.name} ON (heater firing)",
                        )
                elif self._afterrun_remaining_s > 0:
                    # Heater just stopped — burn down the afterrun budget.
                    self._afterrun_remaining_s = max(0, self._afterrun_remaining_s - self.poll_interval_s)
                    if not self._output.is_on():
                        self._output.set_duty(self.duty_pct)
                    if self._afterrun_remaining_s == 0:
                        self._output.set_duty(0)
                        self.logger.info(
                            "HeaterFollowerFanController",
                            f"{self.name} OFF (afterrun complete)",
                        )
                else:
                    # Heater off, afterrun done — make sure fan stays off.
                    if self._output.is_on():
                        self._output.set_duty(0)

                self.logger.debug(
                    "HeaterFollowerFanController",
                    "cycle tick",
                    name=self.name,
                    heater_on=heater_on,
                    afterrun_s=self._afterrun_remaining_s,
                    fan_on=self._output.is_on(),
                )

                await asyncio.sleep(self.poll_interval_s)

            except asyncio.CancelledError:
                self._output.set_duty(0)
                self.logger.warning("HeaterFollowerFanController", f"{self.name} cycle cancelled")
                raise
            except Exception as e:
                self.logger.error("HeaterFollowerFanController", f"{self.name} unexpected error: {e}")
                await asyncio.sleep(1)

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "is_on": self._output.is_on(),
            "duty_pct": self.duty_pct,
            "post_run_s": self.post_run_s,
            "afterrun_remaining_s": self._afterrun_remaining_s,
            "mode": "heater_follower",
        }
