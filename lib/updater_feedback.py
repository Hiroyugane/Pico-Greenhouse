# Updater Feedback - Loading-screen LEDs + Buzzer Jingles
# Dennis Hiro, 2026-05-15
#
# Drives the existing status-LED row and passive buzzer during an SD-payload
# update (see lib/updater.py). The boot-time hook in lib.updater calls:
#
#   feedback.step(audio=True)   # once per file in verify + apply
#   feedback.step(audio=False)  # once per chunk in hash + copy
#   feedback.success()          # 3-note rising arpeggio on apply_ok
#   feedback.failure()          # 2-note descending on verify/apply_fail
#   feedback.finish()           # always-safe cleanup
#
# Standalone from StatusManager/BuzzerController: the updater runs BEFORE
# EventLogger init (per main.py:168-181) so the rest of the system is not
# wired yet. This module touches machine.Pin and machine.PWM directly and
# swallows hardware errors — a misbehaving buzzer must never block a working
# update.

import time

import machine


def _ticks_ms() -> int:
    """Return millisecond tick count; falls back to time.time() under CPython."""
    try:
        return time.ticks_ms()  # type: ignore[attr-defined]
    except AttributeError:
        return int(time.time() * 1000)


def _sleep_ms(ms: int) -> None:
    """Portable millisecond sleep. Negative / zero is a no-op."""
    if ms <= 0:
        return
    try:
        if hasattr(time, "sleep_ms"):
            time.sleep_ms(ms)  # type: ignore[attr-defined]
        else:
            time.sleep(ms / 1000.0)
    except Exception:
        pass


class UpdateFeedback:
    """
    Loading-screen LEDs + buzzer ticks during SD-payload update.

    Drives a cylon-style chase across led_pins (one LED on at a time, bouncing
    at the ends) and an optional per-step buzzer chirp on the passive buzzer.
    success()/failure() play distinct jingles at the end of the update.

    All hardware access is wrapped in try/except — a failed LED or PWM call
    never prevents the update from continuing. Construct once per boot; call
    finish() (or success()/failure()) before machine.reset() to leave outputs
    quiet.

    Attributes:
        _leds (list): machine.Pin instances for chase LEDs (left-to-right order)
        _pwm (machine.PWM | None): buzzer PWM, or None if init failed
        _tick_freq (int): per-step chirp frequency (Hz)
        _tick_ms (int): per-step chirp duration (ms)
        _success_pattern (list): (freq, dur_ms, pause_ms) triples
        _fail_pattern (list): (freq, dur_ms, pause_ms) triples
        _step_delay_ms (int): minimum ms between visible chase steps (0 = none)
        _index (int): current lit LED index, -1 before first step
        _direction (int): chase direction (+1 forward, -1 reverse)
        _last_step_ms (int): timestamp of last advance (for step_delay_ms gating)
    """

    def __init__(
        self,
        led_pins,
        buzzer_pin,
        *,
        tick_freq_hz: int = 1500,
        tick_duration_ms: int = 25,
        success_pattern=None,
        fail_pattern=None,
        step_delay_ms: int = 0,
    ):
        """
        Initialize feedback controller.

        Args:
            led_pins (list[int]): GPIO numbers in physical row order (left→right).
                Empty list disables the chase but other operations still work.
            buzzer_pin (int | None): Passive buzzer GPIO; None disables audio.
            tick_freq_hz (int): Per-step chirp frequency in Hz.
            tick_duration_ms (int): Per-step chirp duration in ms.
                <= 0 disables the chirp while still advancing the chase.
            success_pattern (list[tuple]): (freq, dur_ms, pause_ms) triples for
                the success jingle. freq=0 is a rest.
            fail_pattern (list[tuple]): Same shape, played on failure.
            step_delay_ms (int): Minimum ms between visible chase steps. 0 means
                advance on every step() call. Use a positive value to throttle
                a chunk-rate ticker so the chase remains readable.
        """
        self._leds = []
        for pin_num in led_pins or []:
            try:
                pin = machine.Pin(pin_num, machine.Pin.OUT)
                pin.off()
                self._leds.append(pin)
            except Exception:
                pass

        self._pwm = None
        if buzzer_pin is not None:
            try:
                self._pwm = machine.PWM(machine.Pin(buzzer_pin))
                self._pwm.duty_u16(0)
            except Exception:
                self._pwm = None

        self._tick_freq = int(tick_freq_hz)
        self._tick_ms = int(tick_duration_ms)
        self._success_pattern = list(success_pattern or [])
        self._fail_pattern = list(fail_pattern or [])
        self._step_delay_ms = int(step_delay_ms)

        self._index = -1
        self._direction = 1
        self._last_step_ms = 0

    # ── Internal helpers ──────────────────────────────────────────────

    def _clear_all_leds(self) -> None:
        for pin in self._leds:
            try:
                pin.off()
            except Exception:
                pass

    def _advance_index(self) -> None:
        """Move chase one step, bouncing at the row ends."""
        n = len(self._leds)
        if n == 0:
            return
        if n == 1:
            self._index = 0
            return
        if self._index < 0:
            self._index = 0
            self._direction = 1
            return
        nxt = self._index + self._direction
        if nxt >= n:
            self._direction = -1
            nxt = n - 2
        elif nxt < 0:
            self._direction = 1
            nxt = 1
        self._index = nxt

    def _light_current(self) -> None:
        for i, pin in enumerate(self._leds):
            try:
                if i == self._index:
                    pin.on()
                else:
                    pin.off()
            except Exception:
                pass

    def _chirp(self) -> None:
        if self._pwm is None or self._tick_ms <= 0 or self._tick_freq <= 0:
            return
        try:
            self._pwm.freq(self._tick_freq)
            self._pwm.duty_u16(32768)
            _sleep_ms(self._tick_ms)
            self._pwm.duty_u16(0)
        except Exception:
            try:
                self._pwm.duty_u16(0)
            except Exception:
                pass

    def _play(self, pattern) -> None:
        """Play (freq, dur_ms, pause_ms) triples. Silent if PWM unavailable."""
        if self._pwm is None:
            for _, dur, pause in pattern:
                _sleep_ms(int(dur) + int(pause))
            return
        for freq, dur, pause in pattern:
            try:
                if freq > 0:
                    self._pwm.freq(int(freq))
                    self._pwm.duty_u16(32768)
                    _sleep_ms(int(dur))
                    self._pwm.duty_u16(0)
                else:
                    self._pwm.duty_u16(0)
                    _sleep_ms(int(dur))
                if pause:
                    _sleep_ms(int(pause))
            except Exception:
                try:
                    self._pwm.duty_u16(0)
                except Exception:
                    pass

    # ── Public API ────────────────────────────────────────────────────

    def step(self, audio: bool = False) -> None:
        """
        Advance the chase one step and optionally chirp the buzzer.

        Throttled by step_delay_ms — calls within that window are dropped so a
        chunk-rate ticker can't outrun the LED row visibly. step() never
        raises; hardware faults are swallowed so the update keeps running.

        Args:
            audio (bool): When True, emit a short tick at tick_freq_hz.
        """
        if self._step_delay_ms > 0:
            now = _ticks_ms()
            if self._last_step_ms and (now - self._last_step_ms) < self._step_delay_ms:
                return
            self._last_step_ms = now

        self._advance_index()
        self._light_current()
        if audio:
            self._chirp()

    def success(self) -> None:
        """
        Light all LEDs and play the success jingle, then leave outputs quiet.
        """
        self._clear_all_leds()
        for pin in self._leds:
            try:
                pin.on()
            except Exception:
                pass
        self._play(self._success_pattern)
        self.finish()

    def failure(self) -> None:
        """
        Light only the first LED and play the failure jingle, then quiet.
        """
        self._clear_all_leds()
        if self._leds:
            try:
                self._leds[0].on()
            except Exception:
                pass
        self._play(self._fail_pattern)
        self.finish()

    def finish(self) -> None:
        """Silence the buzzer and turn all LEDs off. Always safe to call."""
        self._clear_all_leds()
        if self._pwm is not None:
            try:
                self._pwm.duty_u16(0)
            except Exception:
                pass


def build_from_config(config: dict):
    """
    Construct an UpdateFeedback from DEVICE_CONFIG, or return None.

    Reads led_pins from config["pins"] in the order given by
    config["status_leds"]["walk_order"]. Returns None when
    config["updater_feedback"]["enabled"] is False or the config is malformed.

    Args:
        config (dict): Full DEVICE_CONFIG dict.

    Returns:
        UpdateFeedback | None
    """
    if not isinstance(config, dict):
        return None
    fb_cfg = config.get("updater_feedback") or {}
    if not fb_cfg.get("enabled", False):
        return None

    pins_cfg = config.get("pins") or {}
    walk_order = (config.get("status_leds") or {}).get("walk_order") or []
    role_to_pin = {
        "activity": pins_cfg.get("activity_led"),
        "sd": pins_cfg.get("sd_led"),
        "reminder": pins_cfg.get("reminder_led"),
        "warning": pins_cfg.get("warning_led"),
        "error": pins_cfg.get("error_led"),
    }
    led_pins = [role_to_pin[r] for r in walk_order if role_to_pin.get(r) is not None]
    buzzer_pin = pins_cfg.get("buzzer")

    try:
        return UpdateFeedback(
            led_pins=led_pins,
            buzzer_pin=buzzer_pin,
            tick_freq_hz=fb_cfg.get("tick_freq_hz", 1500),
            tick_duration_ms=fb_cfg.get("tick_duration_ms", 25),
            success_pattern=fb_cfg.get("success_pattern", []),
            fail_pattern=fb_cfg.get("fail_pattern", []),
            step_delay_ms=fb_cfg.get("step_delay_ms", 0),
        )
    except Exception:
        return None
