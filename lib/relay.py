# Relay Control Module - Composition Pattern with Stateful Control
# Dennis Hiro, 2026-01-29
#
# RelayController base class with composition-based FanController and GrowlightController.
# Implements state machines for async relay behavior.
# Provides state_get() for debugging and metrics.

import uasyncio as asyncio
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


class FanController(RelayController):
    """
    Fan-specific relay controller with dual-mode async cycling.

    Composes RelayController and adds:
    - Time-of-day scheduling (ON for X seconds every Y seconds from midnight)
    - Temperature-based thermostat override
    - Async cycle task

    State variables:
    - thermostat_active: Whether temperature override is active
    - thermostat_on_count: Number of thermostat activations
    - last_schedule_state: Last known schedule state (for logging changes)

    Attributes:
        pin: GPIO pin number
        time_provider: TimeProvider instance for RTC queries
        dht_logger: DHTLogger instance for temperature reads
        logger: EventLogger instance for logging
        interval_s: Time-of-day cycle interval (seconds)
        on_time_s: ON duration per cycle (seconds)
        max_temp: Temperature threshold (°C)
        temp_hysteresis: Temperature drop before turning off (°C)
    """

    def __init__(
        self,
        pin: int,
        time_provider,
        dht_logger,
        logger,
        interval_s: int = 1800,
        on_time_s: int = 20,
        max_temp: float = 24.0,
        temp_hysteresis: float = 1.0,
        poll_interval_s: int = 5,
        name=None,
    ):
        """
        Initialize FanController with dual-mode scheduling.

        Args:
            pin (int): GPIO pin for relay
            time_provider: TimeProvider instance
            dht_logger: DHTLogger instance for temperature
            logger: EventLogger instance
            interval_s (int): Cycle interval in seconds (default: 1800 = 30 min)
            on_time_s (int): ON duration per cycle (default: 20)
            max_temp (float): Temperature threshold in °C (default: 24.0)
            temp_hysteresis (float): Hysteresis in °C (default: 1.0)
            poll_interval_s (int): Schedule/thermostat check interval (default: 5)
            name (str, optional): Relay name
        """
        super().__init__(pin, invert=True, name=name or f"Fan_{pin}", logger=logger)

        self.time_provider = time_provider
        self.dht_logger = dht_logger
        self.logger = logger
        self.interval_s = interval_s
        self.on_time_s = on_time_s
        self.max_temp = max_temp
        self.temp_hysteresis = temp_hysteresis
        self.poll_interval_s = poll_interval_s

        # State machine
        self.thermostat_active = False
        self.thermostat_on_count = 0
        self.last_schedule_state = None

        # Validate parameters
        if on_time_s <= 0 or interval_s <= 0:
            logger.error("FanController", f"Invalid timing: on_time={on_time_s}s, interval={interval_s}s")
        if on_time_s > interval_s:
            logger.warning("FanController", f"on_time ({on_time_s}s) > interval ({interval_s}s), clamping")
            self.on_time_s = interval_s

        logger.debug(
            "FanController",
            f"Initialized {self.name}: interval={interval_s}s, on_time={on_time_s}s, "
            f"thermostat=[max={max_temp}°C, hyst={temp_hysteresis}°C]",
        )

    async def start_cycle(self) -> None:
        """
        Async coroutine for continuous dual-mode control.

        Runs time-of-day schedule + temperature thermostat.
        Check interval controlled by poll_interval_s.
        """
        while True:
            try:
                # Calculate position in daily cycle from RTC
                seconds_since_midnight = self.time_provider.get_seconds_since_midnight()
                position_in_cycle = int(seconds_since_midnight % self.interval_s)
                schedule_should_be_on = position_in_cycle < self.on_time_s

                # Get current temperature
                current_temp = self.dht_logger.last_temperature

                self.logger.debug(
                    "FanController",
                    f"{self.name} poll: ssm={seconds_since_midnight}, pos={position_in_cycle}, "
                    f"sched={'ON' if schedule_should_be_on else 'OFF'}, temp={current_temp}",
                )

                # Thermostat logic (priority over schedule)
                if current_temp is not None:
                    if not self.thermostat_active and current_temp >= self.max_temp:
                        self.thermostat_active = True
                        self.thermostat_on_count += 1
                        try:
                            self.turn_on()
                            self.logger.info(
                                "FanController",
                                f"{self.name} THERMOSTAT ON at {current_temp:.1f}°C "
                                f">= {self.max_temp}°C (activation #{self.thermostat_on_count})",
                            )
                        except Exception as e:
                            self.logger.error("FanController", f"{self.name} failed to turn ON: {e}")

                    elif self.thermostat_active and current_temp < (self.max_temp - self.temp_hysteresis):
                        # Thermostat no longer required: resume schedule control
                        self.thermostat_active = False
                        threshold = self.max_temp - self.temp_hysteresis
                        self.logger.debug(
                            "FanController",
                            f"{self.name} thermostat deactivating: {current_temp:.1f}°C < {threshold}°C",
                        )
                        # Explicitly synchronize fan state with current schedule
                        if not schedule_should_be_on:
                            try:
                                self.turn_off()
                            except Exception as e:
                                self.logger.error(
                                    "FanController",
                                    f"{self.name} failed to turn OFF after thermostat deactivation: {e}",
                                )
                        # Force schedule state re-evaluation
                        self.last_schedule_state = None
                        self.logger.info(
                            "FanController",
                            f"{self.name} THERMOSTAT RESUME SCHEDULE at "
                            f"{current_temp:.1f}°C < {self.max_temp - self.temp_hysteresis}°C",
                        )

                    elif self.thermostat_active:
                        # In hysteresis band — no action
                        self.logger.debug(
                            "FanController",
                            f"{self.name} thermostat: hysteresis band "
                            f"({self.max_temp - self.temp_hysteresis}°C <= {current_temp:.1f}°C < {self.max_temp}°C)",
                        )

                # Apply time-of-day schedule (only when thermostat inactive)
                if not self.thermostat_active:
                    if schedule_should_be_on != self.last_schedule_state:
                        try:
                            if schedule_should_be_on:
                                self.turn_on()
                                self.logger.info("FanController", f"{self.name} SCHEDULE ON")
                            else:
                                self.turn_off()
                                self.logger.info("FanController", f"{self.name} SCHEDULE OFF")
                        except Exception as e:
                            self.logger.error("FanController", f"{self.name} failed to update: {e}")
                        self.last_schedule_state = schedule_should_be_on

                await asyncio.sleep(self.poll_interval_s)

            except asyncio.CancelledError:
                self.turn_off()
                self.logger.warning("FanController", f"{self.name} cycle cancelled")
                raise
            except Exception as e:
                self.logger.error("FanController", f"{self.name} unexpected error: {e}")
                await asyncio.sleep(1)

    def get_state(self) -> dict:
        """Return state dict including thermostat state."""
        state = super().get_state()
        state.update(
            {
                "thermostat_active": self.thermostat_active,
                "thermostat_activations": self.thermostat_on_count,
                "max_temp": self.max_temp,
                "current_temp": self.dht_logger.last_temperature,
            }
        )
        return state


class GrowlightController(RelayController):
    """
    Grow light controller with time-based daily scheduling.

    Composes RelayController and adds:
    - Time-based on/off (dawn/sunset hours)
    - Async scheduler task

    Attributes:
        pin: GPIO pin number
        time_provider: TimeProvider instance
        logger: EventLogger instance
        dawn_hour, dawn_minute: Time to turn light ON
        sunset_hour, sunset_minute: Time to turn light OFF
    """

    def __init__(
        self,
        pin: int,
        time_provider,
        logger,
        dawn_hour=None,
        dawn_minute=None,
        sunset_hour=None,
        sunset_minute=None,
        poll_interval_s: int = 60,
        name=None,
    ):
        """
        Initialize GrowlightController with schedule.

        Args:
            pin (int): GPIO pin for relay
            time_provider: TimeProvider instance
            logger: EventLogger instance
            dawn_hour (int): Hour to turn ON (0-23)
            dawn_minute (int): Minute to turn ON (0-59)
            sunset_hour (int): Hour to turn OFF (0-23)
            sunset_minute (int): Minute to turn OFF (0-59)
            poll_interval_s (int): Schedule check interval in seconds (default: 60)
            name (str, optional): Relay name
        """
        super().__init__(pin, invert=True, name=name or f"Growlight_{pin}", logger=logger)

        self.time_provider = time_provider
        self.logger = logger
        self.poll_interval_s = poll_interval_s

        # If dawn/sunset not provided, derive from sunrise_sunset() for today
        if dawn_hour is None or dawn_minute is None or sunset_hour is None or sunset_minute is None:
            year, month, day = self.time_provider.now_date_tuple()
            (sr_h, sr_m), (ss_h, ss_m) = self.time_provider.sunrise_sunset(year, month, day)
            logger.debug(
                "GrowlightController",
                f"Auto-calc sunrise_sunset({year},{month},{day}): "
                f"sunrise={sr_h:02d}:{sr_m:02d}, sunset={ss_h:02d}:{ss_m:02d}",
            )

            if dawn_hour is None:
                dawn_hour = sr_h
            if dawn_minute is None:
                dawn_minute = sr_m
            if sunset_hour is None:
                sunset_hour = ss_h
            if sunset_minute is None:
                sunset_minute = ss_m

        self.dawn_hour = dawn_hour if dawn_hour is not None else 0
        self.dawn_minute = dawn_minute if dawn_minute is not None else 0
        self.sunset_hour = sunset_hour if sunset_hour is not None else 0
        self.sunset_minute = sunset_minute if sunset_minute is not None else 0

        self.last_state = None

        logger.debug(
            "GrowlightController",
            f"Initialized {self.name}: "
            f"dawn={dawn_hour:02d}:{dawn_minute:02d}, "
            f"sunset={sunset_hour:02d}:{sunset_minute:02d}",
        )

    async def start_scheduler(self) -> None:
        """
        Async coroutine for time-based light scheduling.

        Check interval controlled by poll_interval_s.
        """
        while True:
            try:
                seconds_since_midnight = self.time_provider.get_seconds_since_midnight()
                dawn_seconds = self.dawn_hour * 3600 + self.dawn_minute * 60
                sunset_seconds = self.sunset_hour * 3600 + self.sunset_minute * 60

                should_be_on = dawn_seconds <= seconds_since_midnight < sunset_seconds

                self.logger.debug(
                    "GrowlightController",
                    f"{self.name} poll: ssm={seconds_since_midnight}, "
                    f"dawn={dawn_seconds}, sunset={sunset_seconds}, should={'ON' if should_be_on else 'OFF'}",
                )

                # Only log state changes
                if should_be_on != self.last_state:
                    if should_be_on:
                        self.turn_on()
                        self.logger.info("GrowlightController", f"{self.name} ON")
                    else:
                        self.turn_off()
                        self.logger.info("GrowlightController", f"{self.name} OFF")
                    self.last_state = should_be_on

                await asyncio.sleep(self.poll_interval_s)

            except asyncio.CancelledError:
                self.turn_off()
                self.logger.warning("GrowlightController", f"{self.name} scheduler cancelled")
                raise
            except Exception as e:
                self.logger.error("GrowlightController", f"{self.name} unexpected error: {e}")
                await asyncio.sleep(1)

    def get_state(self) -> dict:
        """Return state dict including schedule."""
        state = super().get_state()
        state.update(
            {
                "dawn": f"{self.dawn_hour:02d}:{self.dawn_minute:02d}",
                "sunset": f"{self.sunset_hour:02d}:{self.sunset_minute:02d}",
            }
        )
        return state
