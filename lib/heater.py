# Heater Control Module
# Dennis Hiro, 2026-05-14
#
# HeaterController: GP3 → R6 → IRLZ44N gate. Active-HIGH (the opposite of
# the relay modules); turn_on() drives the gate HIGH. Thermostat reads
# the cached temperature from TempHumidityLogger so calibration matches the fans.
# Day/night setpoints inherit the growlight schedule plus offsets.

import uasyncio as asyncio
from machine import Pin


class HeaterController:
    """
    Active-HIGH MOSFET-driven heater with day/night thermostat.

    Attributes:
        pin: machine.Pin instance (output, active HIGH = heater on)
        time_provider: TimeProvider instance
        th_logger: TempHumidityLogger instance (reads last_temperature)
        logger: EventLogger instance
        day_min_temp: setpoint while day window is active (°C)
        night_min_temp: setpoint while night window is active (°C)
        temp_hysteresis: drop below setpoint before re-firing (°C)
        day_start_*, night_start_*: day-window boundaries
        max_stale_reads: tolerated consecutive None temperature reads
            before failing safe to OFF
        poll_interval_s: thermostat check cadence
    """

    def __init__(
        self,
        pin: int,
        time_provider,
        th_logger,
        logger,
        day_min_temp: float = 22.0,
        night_min_temp: float = 16.0,
        temp_hysteresis: float = 0.5,
        day_start_hour: int = 6,
        day_start_minute: int = 0,
        night_start_hour: int = 20,
        night_start_minute: int = 0,
        max_stale_reads: int = 3,
        poll_interval_s: int = 30,
        name=None,
    ):
        self.pin = Pin(pin, Pin.OUT)
        self.name = name or f"Heater_{pin}"
        self.time_provider = time_provider
        self.th_logger = th_logger
        self.logger = logger
        self.day_min_temp = day_min_temp
        self.night_min_temp = night_min_temp
        self.temp_hysteresis = temp_hysteresis
        self.day_start_s = day_start_hour * 3600 + day_start_minute * 60
        self.night_start_s = night_start_hour * 3600 + night_start_minute * 60
        self.max_stale_reads = max_stale_reads
        self.poll_interval_s = poll_interval_s

        self._state = False
        self._stale_count = 0

        # Drive gate LOW (heater off) at boot. ACTIVE HIGH means LOW = off.
        self.pin.value(0)

        logger.debug(
            "Heater",
            "init",
            name=self.name,
            pin=pin,
            day_min=day_min_temp,
            night_min=night_min_temp,
            hyst=temp_hysteresis,
            day_start_s=self.day_start_s,
            night_start_s=self.night_start_s,
            max_stale=max_stale_reads,
            poll_s=poll_interval_s,
        )

    def is_on(self) -> bool:
        return self._state

    def turn_on(self) -> None:
        self.pin.value(1)
        self._state = True
        self.logger.debug("Heater", "gate HIGH", name=self.name)

    def turn_off(self) -> None:
        self.pin.value(0)
        self._state = False
        self.logger.debug("Heater", "gate LOW", name=self.name)

    def current_setpoint(self) -> float:
        """Return the active setpoint for the current time-of-day window."""
        s = self.time_provider.get_seconds_since_midnight()
        if self.day_start_s <= s < self.night_start_s:
            return self.day_min_temp
        return self.night_min_temp

    async def start_cycle(self) -> None:
        """Async thermostat loop. Awaits poll_interval_s each tick."""
        while True:
            try:
                setpoint = self.current_setpoint()
                temp = self.th_logger.last_temperature

                if temp is None:
                    self._stale_count += 1
                    if self._stale_count > self.max_stale_reads and self._state:
                        self.logger.warning(
                            "Heater",
                            f"{self.name} fail-safe OFF after {self._stale_count} stale reads",
                        )
                        self.turn_off()
                else:
                    self._stale_count = 0
                    release_temp = setpoint
                    fire_temp = setpoint - self.temp_hysteresis
                    if not self._state and temp < fire_temp:
                        try:
                            self.turn_on()
                            self.logger.info(
                                "Heater",
                                f"{self.name} ON at {temp:.1f}°C < {fire_temp:.1f}°C (setpoint {setpoint:.1f}°C)",
                            )
                        except Exception as e:
                            self.logger.error("Heater", f"{self.name} turn_on failed: {e}")
                    elif self._state and temp >= release_temp:
                        try:
                            self.turn_off()
                            self.logger.info(
                                "Heater",
                                f"{self.name} OFF at {temp:.1f}°C >= {release_temp:.1f}°C",
                            )
                        except Exception as e:
                            self.logger.error("Heater", f"{self.name} turn_off failed: {e}")

                await asyncio.sleep(self.poll_interval_s)

            except asyncio.CancelledError:
                self.turn_off()
                self.logger.warning("Heater", f"{self.name} cycle cancelled")
                raise
            except Exception as e:
                self.logger.error("Heater", f"{self.name} unexpected error: {e}")
                await asyncio.sleep(1)

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "is_on": self._state,
            "current_temp": self.th_logger.last_temperature,
            "current_setpoint": self.current_setpoint(),
            "stale_count": self._stale_count,
        }
