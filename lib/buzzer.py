# Passive Buzzer Controller - PWM-based Tone Generation
# Dennis Hiro, 2026-02-17
#
# Drives a passive buzzer via PWM on a configurable GPIO pin.
# Provides single-tone, pattern playback, and predefined alert melodies.
# Integrates with EventLogger for audible system feedback.
#
# Passive buzzers require a PWM signal at the desired frequency;
# duty cycle controls volume (50 % ≈ loudest square wave).

import uasyncio as asyncio
from machine import PWM, Pin


class BuzzerController:
    """
    PWM-driven passive buzzer controller.

    Plays tones, patterns, and predefined melodies asynchronously.
    Supports mute/unmute and master enable from config.

    Attributes:
        pin_num (int): GPIO pin number
        pwm (machine.PWM): PWM instance wrapping the pin
        enabled (bool): Master enable flag (from config)
        muted (bool): Runtime mute toggle (user-controllable)
        default_freq (int): Default tone frequency in Hz
        duty_u16 (int): PWM duty cycle (0–65535)
        patterns (dict): Named patterns {name: [(freq, dur_ms, pause_ms), ...]}
    """

    def __init__(
        self,
        pin: int,
        logger=None,
        enabled: bool = True,
        default_freq: int = 1000,
        default_duty_pct: int = 50,
        patterns: dict | None = None,
    ):
        """
        Initialize buzzer controller.

        Args:
            pin (int): GPIO pin number for passive buzzer
            logger: EventLogger instance (optional, for logging events)
            enabled (bool): Master enable/disable (default True)
            default_freq (int): Default tone frequency in Hz (default 1000)
            default_duty_pct (int): Duty cycle as percentage 1–100 (default 50)
            patterns (dict, optional): Named tone patterns
                {name: [(freq_hz, duration_ms, pause_ms), ...]}
        """
        self.pin_num = pin
        self.pwm = PWM(Pin(pin))
        self.logger = logger
        self.enabled = enabled
        self.muted = False
        self.default_freq = default_freq
        self.duty_u16 = int((default_duty_pct / 100) * 65535)
        self.patterns = patterns or {}

        # Ensure PWM is silent at init
        self.pwm.duty_u16(0)

        if logger:
            logger.debug(
                "Buzzer",
                f"Initialized on GP{pin}: freq={default_freq}Hz, "
                f"duty={default_duty_pct}%, patterns={list(self.patterns.keys())}",
            )

    # ── Core tone API ─────────────────────────────────────────────────

    def _is_active(self) -> bool:
        """Return True if buzzer should produce sound."""
        return self.enabled and not self.muted

    def tone(self, freq: int | None = None) -> None:
        """
        Start a continuous tone at the given frequency.

        Args:
            freq (int, optional): Frequency in Hz (default: self.default_freq)
        """
        if not self._is_active():
            if self.logger:
                self.logger.debug("Buzzer", f"tone({freq}) skipped: inactive")
            return
        freq = freq or self.default_freq
        self.pwm.freq(freq)
        self.pwm.duty_u16(self.duty_u16)
        if self.logger:
            self.logger.debug("Buzzer", f"tone started: {freq}Hz")

    def stop(self) -> None:
        """Silence the buzzer immediately."""
        self.pwm.duty_u16(0)
        if self.logger:
            self.logger.debug("Buzzer", "stop")

    async def beep(self, freq: int | None = None, duration_ms: int = 100) -> None:
        """
        Play a single beep asynchronously.

        Args:
            freq (int, optional): Frequency in Hz
            duration_ms (int): Tone duration in milliseconds (default 100)
        """
        if not self._is_active():
            if self.logger:
                self.logger.debug("Buzzer", "beep skipped: inactive")
            return
        if self.logger:
            self.logger.debug("Buzzer", f"beep: freq={freq or self.default_freq}Hz, dur={duration_ms}ms")
        self.tone(freq)
        await asyncio.sleep_ms(duration_ms)
        self.stop()

    async def play_pattern(self, pattern: list) -> None:
        """
        Play a sequence of tones asynchronously.

        Args:
            pattern (list): List of (freq_hz, duration_ms, pause_ms) tuples.
                A freq of 0 produces silence for duration_ms (rest note).
        """
        if not self._is_active():
            if self.logger:
                self.logger.debug("Buzzer", "play_pattern skipped: inactive")
            return
        if self.logger:
            self.logger.debug("Buzzer", f"play_pattern: {len(pattern)} steps")
        for freq, duration_ms, pause_ms in pattern:
            if freq > 0:
                self.tone(freq)
                await asyncio.sleep_ms(duration_ms)
                self.stop()
            else:
                # Rest note
                if self.logger:
                    self.logger.debug("Buzzer", f"rest: {duration_ms}ms")
                await asyncio.sleep_ms(duration_ms)
            if pause_ms > 0:
                await asyncio.sleep_ms(pause_ms)

    async def play_named(self, name: str) -> None:
        """
        Play a named pattern from self.patterns.

        Args:
            name (str): Pattern name (e.g. 'startup_melody', 'error_pattern')

        Logs a warning if the pattern name is not found.
        """
        pattern = self.patterns.get(name)
        if pattern is None:
            if self.logger:
                self.logger.warning("Buzzer", f"Unknown pattern: {name}")
            return
        if self.logger:
            self.logger.debug("Buzzer", f"play_named('{name}'): {len(pattern)} steps")
        await self.play_pattern(pattern)

    # ── Convenience alert methods ─────────────────────────────────────

    async def startup(self) -> None:
        """Play startup melody (if configured)."""
        if self.logger:
            pat = "startup_melody" if "startup_melody" in self.patterns else "default"
            self.logger.debug("Buzzer", f"startup: pattern={pat}")
        if "startup_melody" in self.patterns:
            await self.play_named("startup_melody")
        else:
            await self.beep(1047, 150)

    async def error(self) -> None:
        """Play error alert (if configured)."""
        if self.logger:
            pat = "error_pattern" if "error_pattern" in self.patterns else "default"
            self.logger.debug("Buzzer", f"error alert: pattern={pat}")
        if "error_pattern" in self.patterns:
            await self.play_named("error_pattern")
        else:
            await self.beep(400, 500)

    async def alert(self) -> None:
        """Play generic alert (if configured)."""
        if self.logger:
            pat = "alert_pattern" if "alert_pattern" in self.patterns else "default"
            self.logger.debug("Buzzer", f"alert: pattern={pat}")
        if "alert_pattern" in self.patterns:
            await self.play_named("alert_pattern")
        else:
            await self.beep(2000, 200)

    async def reminder(self) -> None:
        """Play service reminder beep (if configured)."""
        if self.logger:
            pat = "reminder_pattern" if "reminder_pattern" in self.patterns else "default"
            self.logger.debug("Buzzer", f"reminder: pattern={pat}")
        if "reminder_pattern" in self.patterns:
            await self.play_named("reminder_pattern")
        else:
            await self.beep(880, 100)

    # ── Mute / enable controls ────────────────────────────────────────

    def mute(self) -> None:
        """Mute the buzzer (runtime toggle, does not change enabled)."""
        self.muted = True
        self.stop()
        if self.logger:
            self.logger.debug("Buzzer", "Muted")

    def unmute(self) -> None:
        """Unmute the buzzer."""
        self.muted = False
        if self.logger:
            self.logger.debug("Buzzer", "Unmuted")

    def set_enabled(self, enabled: bool) -> None:
        """Set master enable flag."""
        self.enabled = enabled
        if not enabled:
            self.stop()
        if self.logger:
            self.logger.debug("Buzzer", f"Enabled={enabled}")

    # ── State / debug ─────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Return state dict for debugging / metrics."""
        return {
            "pin": self.pin_num,
            "enabled": self.enabled,
            "muted": self.muted,
            "default_freq": self.default_freq,
            "duty_u16": self.duty_u16,
            "patterns": list(self.patterns.keys()),
        }

    def deinit(self) -> None:
        """Release PWM hardware resources."""
        self.stop()
        self.pwm.deinit()
        if self.logger:
            self.logger.debug("Buzzer", "Deinitialized")
