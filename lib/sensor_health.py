# Sensor health state machine — edge-triggered reporting + poll backoff.
# Dennis Hiro, 2026-08-25
#
# Every sensor logger used to report a failed read at WARN level, once per
# read, forever. The 2026-07-31..08-07 field run turned that into 20 533 CO2
# warning lines — 100 % of every warning the system emitted — from ONE dead
# sensor, which alone drove 3-4 log rotations a day and buried every other
# warning in the file. The failure was real; the repetition carried no
# information after the first line.
#
# This class holds the state a logger needs to report failures on EDGES:
#
#   healthy  --(warn_after_failures consecutive misses)-->  unreachable
#   unreachable --(any successful read)-->  healthy
#
# The caller logs DEBUG for the first few misses (blips are noise), exactly
# one WARN on the transition into unreachable, nothing while unreachable
# (unless a heartbeat is configured), and exactly one INFO on recovery. The
# durable operator-visible channel is the StatusManager warning, not the log.
#
# While unreachable the effective poll interval doubles from backoff_start_s
# up to backoff_max_s — there is no point asking a dead sensor every 30 s.
# ANY success snaps the interval straight back to normal.
#
# No RTC access: timing comes from the caller (``now_s``) or from an injected
# time source, defaulting to a wrap-safe monotonic built on time.ticks_ms().
# The per-poll path allocates nothing but small ints — no dicts, no f-strings;
# those only appear in the caller's transition messages.

import time

try:
    _ticks_ms = time.ticks_ms  # MicroPython
except AttributeError:

    def _ticks_ms() -> int:  # CPython fallback
        return int(time.time() * 1000)


try:
    _ticks_diff = time.ticks_diff  # MicroPython (wrap-safe)
except AttributeError:

    def _ticks_diff(a, b):  # CPython fallback
        return a - b


HEALTHY = "healthy"
DEGRADED = "degraded"
UNREACHABLE = "unreachable"


class MonotonicSeconds:
    """Wrap-safe seconds counter built on ``time.ticks_ms()``.

    ``ticks_ms`` wraps (roughly every 12 days on the RP2040), so absolute
    tick values cannot be compared directly. Accumulating ``ticks_diff``
    between calls keeps a monotonic total for as long as the object is
    called more often than one wrap period — which every poll loop is.
    """

    def __init__(self):
        self._last = _ticks_ms()
        self._acc_ms = 0

    def __call__(self):
        now = _ticks_ms()
        self._acc_ms += _ticks_diff(now, self._last)
        self._last = now
        return self._acc_ms / 1000.0


class SensorHealth:
    """Failure-state machine and poll-backoff schedule for one sensor.

    Attributes:
        state: ``healthy`` | ``degraded`` | ``unreachable``
        consecutive_failures: misses since the last success
        total_failures: misses since construction (never reset)
        last_outage_s: length of the most recent unreachable spell, in seconds
    """

    def __init__(
        self,
        normal_interval_s,
        warn_after_failures: int = 3,
        backoff_start_s: int = 60,
        backoff_max_s: int = 300,
        unreachable_heartbeat_s: int = 0,
        time_source=None,
    ):
        """
        Args:
            normal_interval_s: poll interval while the sensor answers.
            warn_after_failures: consecutive misses before "unreachable" (>= 1).
            backoff_start_s: first backed-off poll interval.
            backoff_max_s: ceiling for the doubling backoff.
            unreachable_heartbeat_s: reminder cadence while unreachable;
                0 (the default) means stay silent.
            time_source: callable returning monotonic seconds. Defaults to
                :class:`MonotonicSeconds`. Injected in tests.
        """
        self.normal_interval_s = normal_interval_s
        self.warn_after_failures = warn_after_failures if warn_after_failures >= 1 else 1
        self.backoff_start_s = backoff_start_s
        self.backoff_max_s = backoff_max_s if backoff_max_s >= backoff_start_s else backoff_start_s
        self.unreachable_heartbeat_s = unreachable_heartbeat_s
        self._now = time_source if time_source is not None else MonotonicSeconds()

        self.state = HEALTHY
        self.consecutive_failures = 0
        self.total_failures = 0
        self.last_outage_s = 0

        self._interval_s = normal_interval_s
        self._last_poll_s = None
        self._unreachable_since_s = None
        self._last_heartbeat_s = None

    # ------------------------------------------------------------------ state

    def record_success(self) -> bool:
        """Register a good reading.

        Returns:
            bool: True exactly once per outage — on the read that ends an
            ``unreachable`` spell. The caller turns that into one INFO line
            and clears the StatusManager warning.
        """
        recovered = self.state == UNREACHABLE
        if recovered:
            self.last_outage_s = int(self._now() - self._unreachable_since_s)
        self.state = HEALTHY
        self.consecutive_failures = 0
        self._interval_s = self.normal_interval_s
        self._unreachable_since_s = None
        self._last_heartbeat_s = None
        return recovered

    def record_failure(self) -> bool:
        """Register a missed reading.

        Returns:
            bool: True exactly once per outage — on the failure that crosses
            ``warn_after_failures``. The caller turns that into one WARN line
            and raises the StatusManager warning. Every later failure in the
            same outage returns False, which is the whole point of the class.
        """
        self.consecutive_failures += 1
        self.total_failures += 1

        if self.state == UNREACHABLE:
            # Already reported. Keep stepping the backoff ladder so a sensor
            # that stays dead is polled ever more cheaply.
            self._interval_s = self._next_backoff_s()
            return False

        if self.consecutive_failures >= self.warn_after_failures:
            self.state = UNREACHABLE
            now = self._now()
            self._unreachable_since_s = now
            self._last_heartbeat_s = now
            self._interval_s = self.backoff_start_s
            return True

        self.state = DEGRADED
        return False

    def _next_backoff_s(self):
        doubled = self._interval_s * 2
        return doubled if doubled < self.backoff_max_s else self.backoff_max_s

    def is_unreachable(self) -> bool:
        return self.state == UNREACHABLE

    # ------------------------------------------------------------------ timing

    def interval_s(self):
        """Current effective poll interval (normal, or the backed-off one)."""
        return self._interval_s

    def poll_due(self, now_s=None) -> bool:
        """Whether the sensor may be read now, honouring the backoff.

        Records the polled instant when it returns True, so a caller whose
        loop spins faster than the interval (e.g. the error path's 1 s retry
        sleep) cannot hammer a sensor that is already known to be dead.
        A backwards jump in ``now_s`` is treated as due rather than as a
        deadline that will never arrive.
        """
        if now_s is None:
            now_s = self._now()
        last = self._last_poll_s
        if last is None or now_s < last or (now_s - last) >= self._interval_s:
            self._last_poll_s = now_s
            return True
        return False

    def heartbeat_due(self, now_s=None) -> bool:
        """Whether an "still unreachable" reminder is owed.

        Always False unless ``unreachable_heartbeat_s`` is configured and the
        sensor is currently unreachable. Records the heartbeat when it fires.
        """
        if not self.unreachable_heartbeat_s or self.state != UNREACHABLE:
            return False
        if now_s is None:
            now_s = self._now()
        last = self._last_heartbeat_s
        if last is None or now_s < last or (now_s - last) >= self.unreachable_heartbeat_s:
            self._last_heartbeat_s = now_s
            return True
        return False
