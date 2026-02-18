# Status LED Manager — Centralized LED control
# Dennis Hiro, 2026-02-18
#
# Owns all status LEDs (except GP5 / reminder, which stays with ServiceReminder).
# Design principle: solid = problem, blink = activity, dark = all good.
#
# LED mapping:
#   GP4  — activity_led   : brief blink on I/O actions
#   GP6  — sd_led         : solid ON when SD missing/failed
#   GP7  — warning_led    : solid ON when any warning condition active
#   GP8  — error_led      : solid ON when any error condition active
#   GP25 — onboard_led    : heartbeat toggle (proves main loop alive)
#
# Consumers call set_warning("key", True/False) or set_error("key", True/False).
# The LED stays lit as long as *any* condition in the set is active.
# get_status() returns a dict for future OLED display integration.

import uasyncio as asyncio

from lib.led_button import LED


class StatusManager:
    """
    Centralized manager for all status LEDs.

    Owns LED instances for activity, SD, warning, error, and heartbeat.
    Provides a simple API for modules to report conditions without
    touching GPIO directly.

    Optional integrations (via set_buzzer / set_logger):
    - Buzzer: plays error tone on first error condition, alert on first warning.
    - Logger: logs warning/error condition transitions.

    Attributes:
        _activity_led: LED for I/O activity blink (GP4)
        _sd_led: LED for SD problem indication (GP6)
        _warning_led: LED for warning conditions (GP7)
        _error_led: LED for error/fault conditions (GP8)
        _heartbeat_led: LED for main-loop heartbeat (GP25)
        _active_warnings: set of active warning condition keys
        _active_errors: set of active error condition keys
        _sd_healthy: current SD health state
        _heartbeat_count: number of heartbeat toggles
        _activity_blink_ms: duration of activity pulse in ms
        _buzzer: optional BuzzerController for audible alerts
        _logger: optional EventLogger for condition-change logging
        _post_passed: whether POST has been run and passed
    """

    def __init__(
        self,
        activity_pin,
        sd_pin,
        warning_pin,
        error_pin,
        heartbeat_pin,
        activity_blink_ms=50,
    ):
        """
        Initialize StatusManager with LED pin numbers.

        Args:
            activity_pin (int): GPIO for activity LED (GP4)
            sd_pin (int): GPIO for SD problem LED (GP6)
            warning_pin (int): GPIO for warning LED (GP7)
            error_pin (int): GPIO for error LED (GP8)
            heartbeat_pin (int): GPIO for heartbeat LED (GP25)
            activity_blink_ms (int): Activity pulse duration in ms (default: 50)
        """
        self._activity_led = LED(activity_pin)
        self._sd_led = LED(sd_pin)
        self._warning_led = LED(warning_pin)
        self._error_led = LED(error_pin)
        self._heartbeat_led = LED(heartbeat_pin)

        self._active_warnings = set()
        self._active_errors = set()
        self._sd_healthy = True
        self._heartbeat_count = 0
        self._activity_blink_ms = activity_blink_ms
        self._buzzer = None
        self._logger = None
        self._post_passed = False

    # ── Optional integration setters ───────────────────────────────────

    def set_buzzer(self, buzzer) -> None:
        """
        Attach a BuzzerController for audible alerts.

        When attached, plays error tone on first error and alert tone
        on first warning (empty→non-empty transitions only).

        Args:
            buzzer: BuzzerController instance (or None to detach)
        """
        self._buzzer = buzzer

    def set_logger(self, logger) -> None:
        """
        Attach an EventLogger for condition-change logging.

        When attached, logs each warning/error add/remove and SD
        status transitions.

        Args:
            logger: EventLogger instance (or None to detach)
        """
        self._logger = logger

    # ── Power-on Self-Test (POST) ─────────────────────────────────────

    async def run_post(self, step_ms: int = 150) -> bool:
        """
        Power-on self-test: walk all owned LEDs to verify visual output.

        Sequence:
        1. Walk each LED on→wait→off (activity, SD, warning, error, heartbeat)
        2. Flash all LEDs on simultaneously, then off
        3. All LEDs left OFF on success

        Args:
            step_ms (int): Duration each LED stays on during the walk (ms).

        Returns:
            bool: True (POST passed). Always returns True since GPIO
                  is hardwired, but the visual walk lets the operator
                  confirm every LED is physically working.
        """
        step_s = step_ms / 1000.0
        leds = [
            self._activity_led,
            self._sd_led,
            self._warning_led,
            self._error_led,
            self._heartbeat_led,
        ]

        # Phase 1: sequential walk
        for led in leds:
            led.on()
            await asyncio.sleep(step_s)
            led.off()

        # Phase 2: all-on flash
        await asyncio.sleep(step_s)
        for led in leds:
            led.on()
        await asyncio.sleep(step_s * 2)
        for led in leds:
            led.off()

        self._post_passed = True
        return True

    # ── Activity LED (GP4) ─────────────────────────────────────────────

    async def blink_activity(self) -> None:
        """
        Briefly pulse the activity LED.

        Non-blocking async pulse: ON for activity_blink_ms, then OFF.
        Call on DHT reads, SD writes, log flushes, etc.
        """
        self._activity_led.on()
        await asyncio.sleep(self._activity_blink_ms / 1000.0)
        self._activity_led.off()

    # ── SD Status LED (GP6) ────────────────────────────────────────────

    def set_sd_status(self, healthy: bool) -> None:
        """
        Update SD card health status.

        Args:
            healthy (bool): True = SD mounted and working (LED off).
                            False = SD missing/failed (LED solid on).
        """
        changed = healthy != self._sd_healthy
        self._sd_healthy = healthy
        if healthy:
            self._sd_led.off()
        else:
            self._sd_led.on()

        if changed and self._logger:
            state = "healthy" if healthy else "FAILED"
            self._logger.info("StatusMgr", f"SD status changed: {state}")

    # ── Warning LED (GP7) ──────────────────────────────────────────────

    def set_warning(self, key: str, active: bool) -> None:
        """
        Add or remove a named warning condition.

        LED stays solid ON as long as any warning is active.
        Plays buzzer alert on empty→non-empty transition (if buzzer attached).
        Logs each transition (if logger attached).

        Args:
            key (str): Condition identifier (e.g. 'rtc_invalid', 'dht_intermittent')
            active (bool): True to add, False to remove
        """
        was_empty = len(self._active_warnings) == 0
        changed = False
        if active:
            if key not in self._active_warnings:
                self._active_warnings.add(key)
                changed = True
        else:
            if key in self._active_warnings:
                self._active_warnings.discard(key)
                changed = True

        self._update_warning_led()

        if changed and self._logger:
            action = "SET" if active else "CLEARED"
            self._logger.info("StatusMgr", f"Warning {action}: {key}")

        if changed and active and was_empty and self._buzzer:
            asyncio.create_task(self._buzzer.alert())

    def clear_warning(self, key: str) -> None:
        """Convenience alias for set_warning(key, False)."""
        self.set_warning(key, False)

    def _update_warning_led(self) -> None:
        """Sync warning LED with current warning set."""
        if self._active_warnings:
            self._warning_led.on()
        else:
            self._warning_led.off()

    # ── Error LED (GP8) ────────────────────────────────────────────────

    def set_error(self, key: str, active: bool) -> None:
        """
        Add or remove a named error condition.

        LED stays solid ON as long as any error is active.
        Plays buzzer error tone on empty→non-empty transition (if buzzer attached).
        Logs each transition (if logger attached).

        Args:
            key (str): Condition identifier (e.g. 'dht_dead', 'sd_write_fail')
            active (bool): True to add, False to remove
        """
        was_empty = len(self._active_errors) == 0
        changed = False
        if active:
            if key not in self._active_errors:
                self._active_errors.add(key)
                changed = True
        else:
            if key in self._active_errors:
                self._active_errors.discard(key)
                changed = True

        self._update_error_led()

        if changed and self._logger:
            action = "SET" if active else "CLEARED"
            self._logger.error("StatusMgr", f"Error {action}: {key}")

        if changed and active and was_empty and self._buzzer:
            asyncio.create_task(self._buzzer.error())

    def clear_error(self, key: str) -> None:
        """Convenience alias for set_error(key, False)."""
        self.set_error(key, False)

    def _update_error_led(self) -> None:
        """Sync error LED with current error set."""
        if self._active_errors:
            self._error_led.on()
        else:
            self._error_led.off()

    # ── Heartbeat LED (GP25) ───────────────────────────────────────────

    def heartbeat_tick(self) -> None:
        """
        Toggle the heartbeat LED.

        Call once per health-check iteration to prove the main async loop is alive.
        """
        self._heartbeat_led.toggle()
        self._heartbeat_count += 1

    # ── Status Reporting (for OLED integration) ─────────────────────────

    def get_status(self) -> dict:
        """
        Return current status summary for display.

        Returns:
            dict: {
                'warnings': list of active warning keys,
                'errors': list of active error keys,
                'sd_healthy': bool,
                'heartbeat_count': int,
                'post_passed': bool,
            }
        """
        return {
            "warnings": sorted(self._active_warnings),
            "errors": sorted(self._active_errors),
            "sd_healthy": self._sd_healthy,
            "heartbeat_count": self._heartbeat_count,
            "post_passed": self._post_passed,
        }
