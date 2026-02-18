# Tests for lib/buzzer.py
# Covers BuzzerController: tone, beep, patterns, mute/unmute, enable/disable

from unittest.mock import call

import pytest

# ============================================================================
# BuzzerController — Basic Init & State
# ============================================================================


class TestBuzzerControllerInit:
    """Tests for BuzzerController initialization."""

    def test_initialization(self, buzzer_controller):
        """Buzzer initializes silently with correct defaults."""
        state = buzzer_controller.get_state()
        assert state["pin"] == 20
        assert state["enabled"] is True
        assert state["muted"] is False
        assert state["default_freq"] == 1000
        # duty_u16 ≈ 50% of 65535 = 32767
        assert state["duty_u16"] == 32767
        assert "startup_melody" in state["patterns"]
        assert "error_pattern" in state["patterns"]

    def test_init_silences_pwm(self, buzzer_controller):
        """PWM duty_u16 set to 0 at init (buzzer silent)."""
        # Constructor calls duty_u16(0) to ensure silence
        buzzer_controller.pwm.duty_u16.assert_called_with(0)

    def test_init_logs(self, buzzer_controller, mock_event_logger):
        """Logger.debug called during init."""
        mock_event_logger.debug.assert_called()
        # Find the Buzzer init log call
        calls = [c for c in mock_event_logger.debug.call_args_list if c[0][0] == "Buzzer"]
        assert len(calls) >= 1

    def test_init_no_logger(self):
        """BuzzerController works without a logger."""
        from lib.buzzer import BuzzerController

        b = BuzzerController(pin=20, logger=None)
        assert b.logger is None
        assert b.enabled is True

    def test_custom_duty_pct(self):
        """Custom duty percentage is converted to u16 correctly."""
        from lib.buzzer import BuzzerController

        b = BuzzerController(pin=20, default_duty_pct=25)
        # 25% of 65535 = 16383(.75)
        assert b.duty_u16 == 16383

    def test_empty_patterns(self):
        """Buzzer works with no patterns configured."""
        from lib.buzzer import BuzzerController

        b = BuzzerController(pin=20, patterns=None)
        assert b.patterns == {}


# ============================================================================
# BuzzerController — Tone / Stop
# ============================================================================


class TestBuzzerTone:
    """Tests for tone() and stop() methods."""

    def test_tone_default_freq(self, buzzer_controller):
        """tone() with no args uses default_freq."""
        buzzer_controller.tone()
        buzzer_controller.pwm.freq.assert_called_with(1000)
        buzzer_controller.pwm.duty_u16.assert_called_with(32767)

    def test_tone_custom_freq(self, buzzer_controller):
        """tone(freq) uses the specified frequency."""
        buzzer_controller.tone(440)
        buzzer_controller.pwm.freq.assert_called_with(440)

    def test_stop(self, buzzer_controller):
        """stop() sets duty to 0."""
        buzzer_controller.tone(1000)
        buzzer_controller.stop()
        buzzer_controller.pwm.duty_u16.assert_called_with(0)

    def test_tone_when_muted(self, buzzer_controller):
        """tone() does nothing when muted."""
        buzzer_controller.mute()
        buzzer_controller.pwm.freq.reset_mock()
        buzzer_controller.tone(440)
        buzzer_controller.pwm.freq.assert_not_called()

    def test_tone_when_disabled(self, buzzer_controller):
        """tone() does nothing when disabled."""
        buzzer_controller.set_enabled(False)
        buzzer_controller.pwm.freq.reset_mock()
        buzzer_controller.tone(440)
        buzzer_controller.pwm.freq.assert_not_called()


# ============================================================================
# BuzzerController — Beep (async)
# ============================================================================


class TestBuzzerBeep:
    """Tests for async beep()."""

    @pytest.mark.asyncio
    async def test_beep_default(self, buzzer_controller):
        """beep() plays a tone and then stops."""
        await buzzer_controller.beep()
        # Should have called freq, duty (on), then duty(0) (off)
        buzzer_controller.pwm.freq.assert_called_with(1000)
        # Last call to duty_u16 should be 0 (stop)
        last_duty_call = buzzer_controller.pwm.duty_u16.call_args_list[-1]
        assert last_duty_call == call(0)

    @pytest.mark.asyncio
    async def test_beep_custom(self, buzzer_controller):
        """beep(freq, duration_ms) uses custom values."""
        await buzzer_controller.beep(freq=2000, duration_ms=200)
        buzzer_controller.pwm.freq.assert_called_with(2000)

    @pytest.mark.asyncio
    async def test_beep_muted_noop(self, buzzer_controller):
        """beep() does nothing when muted."""
        buzzer_controller.mute()
        buzzer_controller.pwm.freq.reset_mock()
        await buzzer_controller.beep()
        buzzer_controller.pwm.freq.assert_not_called()


# ============================================================================
# BuzzerController — Pattern Playback (async)
# ============================================================================


class TestBuzzerPatterns:
    """Tests for pattern playback."""

    @pytest.mark.asyncio
    async def test_play_pattern(self, buzzer_controller):
        """play_pattern() plays each tone in sequence."""
        pattern = [(440, 100, 50), (880, 100, 0)]
        await buzzer_controller.play_pattern(pattern)
        freq_calls = [c for c in buzzer_controller.pwm.freq.call_args_list if c[0]]
        freqs_played = [c[0][0] for c in freq_calls]
        assert 440 in freqs_played
        assert 880 in freqs_played

    @pytest.mark.asyncio
    async def test_play_pattern_with_rest(self, buzzer_controller):
        """play_pattern() handles freq=0 as rest (no tone)."""
        pattern = [(0, 100, 0), (440, 100, 0)]
        buzzer_controller.pwm.freq.reset_mock()
        await buzzer_controller.play_pattern(pattern)
        # freq should only be called for 440, not for the rest
        freq_calls = [c for c in buzzer_controller.pwm.freq.call_args_list if c[0]]
        assert len(freq_calls) == 1
        assert freq_calls[0][0][0] == 440

    @pytest.mark.asyncio
    async def test_play_named_existing(self, buzzer_controller):
        """play_named() plays a known pattern."""
        await buzzer_controller.play_named("startup_melody")
        # Should have played 3 tones
        freq_calls = [c for c in buzzer_controller.pwm.freq.call_args_list if c[0]]
        assert len(freq_calls) >= 3

    @pytest.mark.asyncio
    async def test_play_named_unknown(self, buzzer_controller, mock_event_logger):
        """play_named() logs warning for unknown pattern."""
        await buzzer_controller.play_named("nonexistent")
        mock_event_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_play_pattern_muted_noop(self, buzzer_controller):
        """play_pattern() does nothing when muted."""
        buzzer_controller.mute()
        buzzer_controller.pwm.freq.reset_mock()
        await buzzer_controller.play_pattern([(440, 100, 0)])
        buzzer_controller.pwm.freq.assert_not_called()


# ============================================================================
# BuzzerController — Convenience Methods (async)
# ============================================================================


class TestBuzzerConvenience:
    """Tests for startup(), error(), alert(), reminder()."""

    @pytest.mark.asyncio
    async def test_startup(self, buzzer_controller):
        """startup() plays startup_melody pattern."""
        await buzzer_controller.startup()
        freq_calls = [c for c in buzzer_controller.pwm.freq.call_args_list if c[0]]
        freqs = [c[0][0] for c in freq_calls]
        assert 1047 in freqs  # C6 from startup_melody

    @pytest.mark.asyncio
    async def test_error(self, buzzer_controller):
        """error() plays error_pattern."""
        await buzzer_controller.error()
        freq_calls = [c for c in buzzer_controller.pwm.freq.call_args_list if c[0]]
        freqs = [c[0][0] for c in freq_calls]
        assert 400 in freqs

    @pytest.mark.asyncio
    async def test_alert(self, buzzer_controller):
        """alert() plays alert_pattern."""
        await buzzer_controller.alert()
        freq_calls = [c for c in buzzer_controller.pwm.freq.call_args_list if c[0]]
        freqs = [c[0][0] for c in freq_calls]
        assert 2000 in freqs

    @pytest.mark.asyncio
    async def test_reminder(self, buzzer_controller):
        """reminder() plays reminder_pattern."""
        await buzzer_controller.reminder()
        freq_calls = [c for c in buzzer_controller.pwm.freq.call_args_list if c[0]]
        freqs = [c[0][0] for c in freq_calls]
        assert 880 in freqs

    @pytest.mark.asyncio
    async def test_startup_fallback_no_pattern(self):
        """startup() falls back to single beep when no pattern configured."""
        from lib.buzzer import BuzzerController

        b = BuzzerController(pin=20, patterns={})
        await b.startup()
        b.pwm.freq.assert_called_with(1047)

    @pytest.mark.asyncio
    async def test_error_fallback_no_pattern(self):
        """error() falls back to single beep when no pattern configured."""
        from lib.buzzer import BuzzerController

        b = BuzzerController(pin=20, patterns={})
        await b.error()
        b.pwm.freq.assert_called_with(400)


# ============================================================================
# BuzzerController — Mute / Enable
# ============================================================================


class TestBuzzerMuteEnable:
    """Tests for mute/unmute and enable/disable."""

    def test_mute(self, buzzer_controller):
        """mute() sets muted=True and stops buzzer."""
        buzzer_controller.mute()
        assert buzzer_controller.muted is True
        buzzer_controller.pwm.duty_u16.assert_called_with(0)

    def test_unmute(self, buzzer_controller):
        """unmute() sets muted=False."""
        buzzer_controller.mute()
        buzzer_controller.unmute()
        assert buzzer_controller.muted is False

    def test_set_enabled_false(self, buzzer_controller):
        """set_enabled(False) disables and stops."""
        buzzer_controller.set_enabled(False)
        assert buzzer_controller.enabled is False
        buzzer_controller.pwm.duty_u16.assert_called_with(0)

    def test_set_enabled_true(self, buzzer_controller):
        """set_enabled(True) re-enables."""
        buzzer_controller.set_enabled(False)
        buzzer_controller.set_enabled(True)
        assert buzzer_controller.enabled is True

    def test_mute_logs(self, buzzer_controller, mock_event_logger):
        """mute/unmute log events."""
        buzzer_controller.mute()
        buzzer_controller.unmute()
        info_calls = [c for c in mock_event_logger.debug.call_args_list if "Muted" in str(c) or "Unmuted" in str(c)]
        assert len(info_calls) >= 2


# ============================================================================
# BuzzerController — Deinit
# ============================================================================


class TestBuzzerDeinit:
    """Tests for deinit()."""

    def test_deinit(self, buzzer_controller):
        """deinit() stops and releases PWM."""
        buzzer_controller.deinit()
        buzzer_controller.pwm.duty_u16.assert_called_with(0)
        buzzer_controller.pwm.deinit.assert_called_once()

    def test_deinit_logs(self, buzzer_controller, mock_event_logger):
        """deinit() logs deinitialization."""
        buzzer_controller.deinit()
        deinit_calls = [c for c in mock_event_logger.debug.call_args_list if "Deinitialized" in str(c)]
        assert len(deinit_calls) >= 1
