# Tests for lib/sensor_health.py
# Covers the healthy -> degraded -> unreachable state machine, the doubling
# poll backoff and its snap-back, and the exactly-once edge semantics that
# exist to stop one dead sensor from writing 20 533 identical WARN lines.


class FakeClock:
    """Injectable monotonic seconds source with a settable value."""

    def __init__(self, start=0.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now


def _health(clock=None, **kwargs):
    from lib.sensor_health import SensorHealth

    params = {
        "normal_interval_s": 30,
        "warn_after_failures": 3,
        "backoff_start_s": 60,
        "backoff_max_s": 300,
    }
    params.update(kwargs)
    return SensorHealth(time_source=clock, **params)


class TestStateTransitions:
    def test_starts_healthy(self):
        from lib.sensor_health import HEALTHY

        h = _health(FakeClock())
        assert h.state == HEALTHY
        assert h.is_unreachable() is False
        assert h.consecutive_failures == 0
        assert h.total_failures == 0

    def test_first_failures_are_degraded_not_unreachable(self):
        """Blips are noise: below the threshold the caller only logs DEBUG."""
        from lib.sensor_health import DEGRADED

        h = _health(FakeClock())
        assert h.record_failure() is False
        assert h.state == DEGRADED
        assert h.record_failure() is False
        assert h.state == DEGRADED
        assert h.is_unreachable() is False

    def test_threshold_failure_transitions_to_unreachable(self):
        from lib.sensor_health import UNREACHABLE

        h = _health(FakeClock())
        h.record_failure()
        h.record_failure()
        assert h.record_failure() is True
        assert h.state == UNREACHABLE
        assert h.is_unreachable() is True

    def test_transition_is_reported_exactly_once(self):
        """This is the whole point: 20 000 failures, one WARN."""
        h = _health(FakeClock())
        edges = [h.record_failure() for _ in range(200)]
        assert edges.count(True) == 1
        assert edges.index(True) == 2  # the third consecutive failure
        assert h.total_failures == 200

    def test_recovery_is_reported_exactly_once(self):
        h = _health(FakeClock())
        for _ in range(5):
            h.record_failure()
        assert h.record_success() is True
        assert h.record_success() is False
        assert h.record_success() is False

    def test_success_without_an_outage_is_not_a_recovery(self):
        h = _health(FakeClock())
        assert h.record_success() is False
        h.record_failure()  # degraded only, never reported
        assert h.record_success() is False

    def test_success_resets_consecutive_but_not_total(self):
        h = _health(FakeClock())
        h.record_failure()
        h.record_failure()
        h.record_success()
        assert h.consecutive_failures == 0
        assert h.total_failures == 2

    def test_second_outage_reports_again(self):
        """Edge-triggered, not once-per-boot: a flapping sensor still reports."""
        h = _health(FakeClock())
        for _ in range(3):
            h.record_failure()
        h.record_success()
        edges = [h.record_failure() for _ in range(3)]
        assert edges == [False, False, True]

    def test_outage_duration_is_measured(self):
        clock = FakeClock()
        h = _health(clock)
        for _ in range(3):
            h.record_failure()
        clock.advance(742)
        h.record_success()
        assert h.last_outage_s == 742

    def test_warn_after_one_failure_is_immediate(self):
        h = _health(FakeClock(), warn_after_failures=1)
        assert h.record_failure() is True

    def test_warn_after_zero_is_clamped_to_one(self):
        """A zero threshold would report unreachable before any read failed."""
        h = _health(FakeClock(), warn_after_failures=0)
        assert h.warn_after_failures == 1


class TestBackoffLadder:
    def test_healthy_interval_is_the_normal_one(self):
        h = _health(FakeClock())
        assert h.interval_s() == 30

    def test_degraded_still_polls_at_the_normal_interval(self):
        """Below the threshold nothing has been established yet — keep looking."""
        h = _health(FakeClock())
        h.record_failure()
        assert h.interval_s() == 30

    def test_ladder_doubles_from_start_and_caps(self):
        h = _health(FakeClock())
        h.record_failure()
        h.record_failure()
        h.record_failure()
        assert h.interval_s() == 60
        h.record_failure()
        assert h.interval_s() == 120
        h.record_failure()
        assert h.interval_s() == 240
        h.record_failure()
        assert h.interval_s() == 300
        h.record_failure()
        assert h.interval_s() == 300

    def test_any_success_snaps_back_to_normal(self):
        h = _health(FakeClock())
        for _ in range(8):
            h.record_failure()
        assert h.interval_s() == 300
        h.record_success()
        assert h.interval_s() == 30

    def test_max_below_start_is_clamped(self):
        h = _health(FakeClock(), backoff_start_s=60, backoff_max_s=10)
        assert h.backoff_max_s == 60
        for _ in range(5):
            h.record_failure()
        assert h.interval_s() == 60


class TestPollDue:
    def test_first_poll_is_always_due(self):
        h = _health(FakeClock())
        assert h.poll_due() is True

    def test_not_due_before_the_interval_elapses(self):
        clock = FakeClock()
        h = _health(clock)
        assert h.poll_due() is True
        clock.advance(29)
        assert h.poll_due() is False

    def test_due_once_the_interval_elapses(self):
        clock = FakeClock()
        h = _health(clock)
        h.poll_due()
        clock.advance(30)
        assert h.poll_due() is True

    def test_backoff_suppresses_polls_between_ladder_steps(self):
        clock = FakeClock()
        h = _health(clock)
        h.poll_due()
        for _ in range(3):
            h.record_failure()
        assert h.interval_s() == 60
        clock.advance(30)
        assert h.poll_due() is False
        clock.advance(30)
        assert h.poll_due() is True

    def test_explicit_now_s_overrides_the_time_source(self):
        h = _health(FakeClock())
        assert h.poll_due(now_s=1000) is True
        assert h.poll_due(now_s=1010) is False
        assert h.poll_due(now_s=1030) is True

    def test_backwards_time_is_treated_as_due(self):
        """A clock that jumps back must not create a deadline that never arrives."""
        h = _health(FakeClock())
        assert h.poll_due(now_s=1000) is True
        assert h.poll_due(now_s=5) is True


class TestHeartbeat:
    def test_silent_by_default(self):
        h = _health(FakeClock())
        for _ in range(5):
            h.record_failure()
        assert h.heartbeat_due() is False

    def test_never_due_while_healthy(self):
        h = _health(FakeClock(), unreachable_heartbeat_s=600)
        assert h.heartbeat_due() is False

    def test_due_after_the_configured_gap(self):
        clock = FakeClock()
        h = _health(clock, unreachable_heartbeat_s=600)
        for _ in range(3):
            h.record_failure()
        assert h.heartbeat_due() is False  # the transition WARN just fired
        clock.advance(599)
        assert h.heartbeat_due() is False
        clock.advance(1)
        assert h.heartbeat_due() is True
        assert h.heartbeat_due() is False  # consumed


class TestMonotonicSeconds:
    def test_advances_with_ticks(self, monkeypatch):
        import lib.sensor_health as sh

        fake_ms = [0]
        monkeypatch.setattr(sh, "_ticks_ms", lambda: fake_ms[0])
        clock = sh.MonotonicSeconds()
        assert clock() == 0.0
        fake_ms[0] = 4500
        assert clock() == 4.5

    def test_survives_a_ticks_wrap(self, monkeypatch):
        """ticks_ms wraps on MicroPython; ticks_diff keeps the total monotonic."""
        import lib.sensor_health as sh

        wrap = 1 << 30
        fake_ms = [wrap - 1000]
        monkeypatch.setattr(sh, "_ticks_ms", lambda: fake_ms[0])
        monkeypatch.setattr(sh, "_ticks_diff", lambda a, b: ((a - b + (wrap >> 1)) % wrap) - (wrap >> 1))
        clock = sh.MonotonicSeconds()
        clock()
        fake_ms[0] = 2000  # wrapped past zero
        assert clock() == 3.0
