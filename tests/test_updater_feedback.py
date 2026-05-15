# Tests for lib/updater_feedback.py
#
# Covers the loading-screen LED chase + buzzer jingles played during an
# SD-payload update. Hardware is provided by conftest's MagicMock machine.Pin
# / machine.PWM stubs (each call returns a fresh tracked mock).


import pytest


@pytest.fixture
def feedback_factory():
    """Build an UpdateFeedback with sane test defaults."""

    def _make(**overrides):
        from lib.updater_feedback import UpdateFeedback

        defaults = dict(
            led_pins=[4, 5, 8, 6, 7],
            buzzer_pin=14,
            tick_freq_hz=1500,
            tick_duration_ms=0,  # silence ticks by default in tests
            success_pattern=[(1047, 1, 0), (1319, 1, 0), (1568, 1, 0)],
            fail_pattern=[(400, 1, 0), (250, 1, 0)],
            step_delay_ms=0,
        )
        defaults.update(overrides)
        return UpdateFeedback(**defaults)

    return _make


class TestUpdateFeedbackInit:
    def test_constructs_with_full_config(self, feedback_factory):
        fb = feedback_factory()
        assert len(fb._leds) == 5
        assert fb._pwm is not None

    def test_empty_led_pins_is_ok(self, feedback_factory):
        fb = feedback_factory(led_pins=[])
        assert fb._leds == []

    def test_no_buzzer_pin_sets_pwm_none(self, feedback_factory):
        fb = feedback_factory(buzzer_pin=None)
        assert fb._pwm is None

    def test_buzzer_init_failure_is_swallowed(self, feedback_factory, monkeypatch):
        import machine as _machine

        def boom(*_a, **_kw):
            raise RuntimeError("simulated PWM init fault")

        monkeypatch.setattr(_machine, "PWM", boom)
        fb = feedback_factory()
        assert fb._pwm is None

    def test_led_init_failure_skips_pin(self, feedback_factory, monkeypatch):
        import machine as _machine

        calls = {"n": 0}
        real_pin = _machine.Pin

        def flaky_pin(num, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated bad pin")
            return real_pin(num, *a, **kw)

        flaky_pin.OUT = _machine.Pin.OUT
        monkeypatch.setattr(_machine, "Pin", flaky_pin)
        fb = feedback_factory(led_pins=[4, 5, 6], buzzer_pin=None)
        # Second LED is dropped; 2 survive.
        assert len(fb._leds) == 2


class TestUpdateFeedbackStep:
    def test_step_lights_first_led(self, feedback_factory):
        fb = feedback_factory()
        fb.step(audio=False)
        assert fb._index == 0
        assert fb._leds[0]._current_value == 1
        for led in fb._leds[1:]:
            assert led._current_value == 0

    def test_step_advances_forward(self, feedback_factory):
        fb = feedback_factory()
        for _ in range(3):
            fb.step()
        assert fb._index == 2

    def test_step_bounces_at_end(self, feedback_factory):
        fb = feedback_factory(led_pins=[4, 5, 6])
        for _ in range(5):
            fb.step()
        # 0 → 1 → 2 → bounce → 1 → 0
        assert fb._index == 0
        assert fb._direction == -1

    def test_step_bounces_at_start(self, feedback_factory):
        fb = feedback_factory(led_pins=[4, 5, 6])
        # Walk forward, hit the end-bounce, walk back, then hit the
        # start-bounce. After 6 steps we should be at index 1, heading forward.
        for _ in range(6):
            fb.step()
        # init → 0 → 1 → 2 → end-bounce → 1 → 0 → start-bounce → 1
        assert fb._index == 1
        assert fb._direction == 1

    def test_step_single_led_is_a_pulse(self, feedback_factory):
        fb = feedback_factory(led_pins=[4])
        fb.step()
        fb.step()
        assert fb._index == 0
        assert fb._leds[0]._current_value == 1

    def test_step_with_no_leds_does_not_raise(self, feedback_factory):
        fb = feedback_factory(led_pins=[])
        fb.step(audio=True)  # should be a no-op

    def test_step_audio_invokes_pwm(self, feedback_factory):
        fb = feedback_factory(tick_duration_ms=1)
        fb.step(audio=True)
        # The chirp wrote a non-zero duty then zeroed it.
        duty_calls = [c.args[0] for c in fb._pwm.duty_u16.call_args_list if c.args]
        assert any(v > 0 for v in duty_calls)
        assert duty_calls[-1] == 0
        fb._pwm.freq.assert_called_with(1500)

    def test_step_audio_zero_duration_is_silent(self, feedback_factory):
        fb = feedback_factory(tick_duration_ms=0)
        fb._pwm.freq.reset_mock()
        fb.step(audio=True)
        fb._pwm.freq.assert_not_called()

    def test_step_delay_throttles_advance(self, feedback_factory, monkeypatch):
        # Two calls in rapid succession with a 100ms step_delay → only one advance.
        import lib.updater_feedback as ufb_mod

        fake_now = {"v": 1000}
        monkeypatch.setattr(ufb_mod, "_ticks_ms", lambda: fake_now["v"])
        fb = feedback_factory(step_delay_ms=100)
        fb.step()
        assert fb._index == 0
        fake_now["v"] += 50  # within throttle window
        fb.step()
        assert fb._index == 0
        fake_now["v"] += 100  # past the window
        fb.step()
        assert fb._index == 1


class TestUpdateFeedbackJingles:
    def test_success_lights_all_then_clears(self, feedback_factory):
        fb = feedback_factory()
        fb.success()
        for led in fb._leds:
            assert led._current_value == 0  # finish() turned them back off
        # Success pattern played 3 notes; each note set a non-zero duty.
        freq_calls = [c.args[0] for c in fb._pwm.freq.call_args_list if c.args]
        assert 1047 in freq_calls
        assert 1568 in freq_calls

    def test_failure_plays_descending(self, feedback_factory):
        fb = feedback_factory()
        fb.failure()
        freq_calls = [c.args[0] for c in fb._pwm.freq.call_args_list if c.args]
        assert 400 in freq_calls
        assert 250 in freq_calls
        # All LEDs off after finish().
        for led in fb._leds:
            assert led._current_value == 0

    def test_jingles_work_without_buzzer(self, feedback_factory):
        fb = feedback_factory(buzzer_pin=None)
        # Both must complete silently without raising.
        fb.success()
        fb.failure()

    def test_jingle_rest_note_zero_freq(self, feedback_factory):
        fb = feedback_factory(success_pattern=[(0, 1, 0), (1568, 1, 0)])
        fb.success()
        # Rest note doesn't call freq(); only the 1568Hz note does.
        freq_calls = [c.args[0] for c in fb._pwm.freq.call_args_list if c.args]
        assert 1568 in freq_calls
        assert 0 not in freq_calls

    def test_play_swallows_pwm_failures(self, feedback_factory):
        fb = feedback_factory()
        # Force freq() to throw on every call.
        fb._pwm.freq.side_effect = RuntimeError("simulated")
        # success() must not raise.
        fb.success()


class TestUpdateFeedbackFinish:
    def test_finish_zeros_duty(self, feedback_factory):
        fb = feedback_factory()
        fb._pwm.duty_u16.reset_mock()
        fb.finish()
        duty_calls = [c.args[0] for c in fb._pwm.duty_u16.call_args_list if c.args]
        assert duty_calls[-1] == 0

    def test_finish_with_no_buzzer(self, feedback_factory):
        fb = feedback_factory(buzzer_pin=None)
        fb.finish()  # no raise


class TestBuildFromConfig:
    def _cfg(self, **overrides):
        cfg = {
            "pins": {
                "activity_led": 4,
                "sd_led": 5,
                "reminder_led": 8,
                "warning_led": 6,
                "error_led": 7,
                "buzzer": 14,
            },
            "status_leds": {"walk_order": ["activity", "sd", "reminder", "warning", "error"]},
            "updater_feedback": {
                "enabled": True,
                "tick_freq_hz": 1500,
                "tick_duration_ms": 0,
                "step_delay_ms": 0,
                "success_pattern": [(1047, 1, 0)],
                "fail_pattern": [(400, 1, 0)],
            },
        }
        cfg["updater_feedback"].update(overrides)
        return cfg

    def test_builds_when_enabled(self):
        from lib.updater_feedback import UpdateFeedback, build_from_config

        fb = build_from_config(self._cfg())
        assert isinstance(fb, UpdateFeedback)
        assert len(fb._leds) == 5

    def test_returns_none_when_disabled(self):
        from lib.updater_feedback import build_from_config

        assert build_from_config(self._cfg(enabled=False)) is None

    def test_returns_none_for_non_dict(self):
        from lib.updater_feedback import build_from_config

        assert build_from_config(None) is None
        assert build_from_config("nope") is None

    def test_walks_only_known_roles(self):
        from lib.updater_feedback import build_from_config

        cfg = self._cfg()
        cfg["status_leds"]["walk_order"] = ["activity", "bogus", "error"]
        fb = build_from_config(cfg)
        assert fb is not None
        assert len(fb._leds) == 2  # bogus role is filtered

    def test_missing_pins_section_still_builds(self):
        from lib.updater_feedback import build_from_config

        cfg = self._cfg()
        cfg.pop("pins")
        fb = build_from_config(cfg)
        # No pins → no LEDs and no buzzer, but instance constructed.
        assert fb is not None
        assert fb._leds == []
        assert fb._pwm is None
