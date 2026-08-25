# Tests for main.py orchestration
# Covers startup, task spawning, error paths, health-check loop, watchdog

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from config import DEVICE_CONFIG
from tests.conftest import FAKE_LOCALTIME


@pytest.fixture(autouse=True)
def _stub_oled_display(monkeypatch):
    """Replace OLEDDisplay in main with a Mock so init warmup sleeps don't run."""
    import main as main_module

    monkeypatch.setattr(
        main_module,
        "OLEDDisplay",
        lambda *a, **kw: Mock(display_on=True),
    )


def _mock_create_task(coro):
    """Test helper: consume coroutine objects when asyncio.create_task is monkeypatched."""
    coro.close()
    return Mock()


def _capture_create_task(created_tasks):
    """Return a create_task stub that records and closes coroutines."""

    def _create_task(coro):
        created_tasks.append(coro)
        coro.close()
        return Mock()

    return _create_task


@pytest.mark.asyncio
class TestFeedWatchdog:
    """Tests for feed_watchdog() async task."""

    async def test_feed_watchdog_feeds_wdt(self, monkeypatch):
        """feed_watchdog() calls wdt.feed() each iteration."""
        import main as main_module

        mock_wdt = Mock()
        feed_count = 0

        async def limited_sleep_ms(ms):
            nonlocal feed_count
            feed_count += 1
            if feed_count >= 3:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep_ms)

        with pytest.raises(asyncio.CancelledError):
            await main_module.feed_watchdog(mock_wdt, 1000)

        assert mock_wdt.feed.call_count == 3

    async def test_feed_watchdog_cancelled_logs_warning(self, monkeypatch):
        """feed_watchdog() logs warning on CancelledError."""
        import main as main_module

        mock_wdt = Mock()
        mock_logger = Mock()

        async def raise_cancelled(ms):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep_ms", raise_cancelled)

        with pytest.raises(asyncio.CancelledError):
            await main_module.feed_watchdog(mock_wdt, 1000, logger=mock_logger)

        mock_logger.warning.assert_called_once()
        assert "cancelled" in str(mock_logger.warning.call_args).lower()

    async def test_feed_watchdog_error_continues(self, monkeypatch):
        """feed_watchdog() continues after unexpected exception (no logging to avoid blocking)."""
        import main as main_module

        mock_wdt = Mock()
        mock_wdt.feed.side_effect = [RuntimeError("WDT failure"), None, None]

        iteration = 0

        async def limited_sleep_ms(ms):
            nonlocal iteration
            iteration += 1
            if iteration >= 3:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep_ms)

        # Should continue despite error (no crash)
        with pytest.raises(asyncio.CancelledError):
            await main_module.feed_watchdog(mock_wdt, 1000)

        # Verify it attempted to feed 3 times (first failed, next two succeeded)
        assert mock_wdt.feed.call_count == 3

    async def test_feed_watchdog_no_logger(self, monkeypatch):
        """feed_watchdog() works without logger (no crash on error)."""
        import main as main_module

        mock_wdt = Mock()
        mock_wdt.feed.side_effect = RuntimeError("WDT failure")

        iteration = 0

        async def limited_sleep_ms(ms):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep_ms)

        # Should not crash even with error and no logger
        with pytest.raises(asyncio.CancelledError):
            await main_module.feed_watchdog(mock_wdt, 1000, logger=None)


@pytest.mark.asyncio
class TestMainStartup:
    """Tests for main() startup sequence."""

    async def test_config_validation_failure_exits(self, monkeypatch):
        """If validate_config raises, main() returns early."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", Mock(side_effect=ValueError("bad config")))

        # Should return without crashing
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            await main_module.main()

    async def test_hardware_setup_failure_exits(self, monkeypatch):
        """If hardware.setup() returns False, main() returns early."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = False
        mock_hw.print_status = Mock()
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            await main_module.main()

        mock_hw.print_status.assert_called()

    async def test_spawns_tasks_and_runs_loop(self, monkeypatch):
        """main() creates async tasks and enters event loop."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))

        created_tasks = []
        monkeypatch.setattr(main_module.asyncio, "create_task", _capture_create_task(created_tasks))

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        assert len(created_tasks) > 0

    async def test_logs_firmware_and_app_version_once_per_boot(self, monkeypatch):
        """Boot writes one version line to system.log AND /boot.log.

        Why both: system.log is the searchable history, but a unit whose SD
        card has gone read-only still records its identity on internal flash —
        and that line is the only record of the outgoing firmware once a new
        .uf2 is flashed over it (plan section 3.1).
        """
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))

        boot_lines = []
        monkeypatch.setattr(main_module.boot_log, "log", boot_lines.append)
        monkeypatch.setattr(main_module.version, "describe", lambda: "fw=pg-fw-2026.07-a1b2c3d app=deadbee")

        monkeypatch.setattr(main_module.asyncio, "create_task", _capture_create_task([]))

        async def stop_immediately(duration):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_immediately)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_immediately)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        version_calls = [
            call for call in mock_logger.info.call_args_list if str(call.args[1:2]).startswith("('version | ")
        ]
        assert len(version_calls) == 1, "exactly one version line belongs in system.log per boot"
        assert version_calls[0].args[0] == "MAIN"
        assert "fw=pg-fw-2026.07-a1b2c3d" in version_calls[0].args[1]

        version_boot_lines = [line for line in boot_lines if line.startswith("[VERSION] ")]
        assert len(version_boot_lines) == 1
        assert "app=deadbee" in version_boot_lines[0]

    async def test_startup_drains_fallback_when_sd_mounted(self, monkeypatch):
        """main() drains the previous boot's fallback rows via migrate_fallback().

        Why: clear_fallback_startup() destroyed legitimate data buffered
        during the prior boot's SD outage. Boot-time migration preserves
        that data; if migration is bounded and the backlog is large, the
        boot calls migrate_fallback at most twice before handing off to
        the health-check loop.
        """
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        # Two non-empty drain passes, then a zero — caller should stop after the zero.
        mock_buffer.migrate_fallback = Mock(side_effect=[5, 0])
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # First pass migrated, second pass returned 0 → loop exits early.
        # Health-check loop later also calls migrate_fallback, so total >= 2.
        assert mock_buffer.migrate_fallback.call_count >= 2

    async def test_startup_skips_fallback_drain_when_sd_unmounted(self, monkeypatch):
        """When SD is not mounted at boot, migrate_fallback is not invoked.

        Why: migrate_fallback() short-circuits internally when primary is
        down, but we don't even reach BufferManager during the
        require_sd_startup degraded path. The startup drain block must
        guard on is_sd_mounted() to keep that path clean.
        """
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        # require_sd_startup defaults to True, so an unmounted SD enters
        # the failure-state countdown and main() returns without touching
        # BufferManager. We override the system block to skip the gate
        # so we can prove the drain block itself is guarded.
        from config import DEVICE_CONFIG

        orig = DEVICE_CONFIG["system"]["require_sd_startup"]
        DEVICE_CONFIG["system"]["require_sd_startup"] = False

        try:
            mock_hw = Mock()
            mock_hw.setup.return_value = True
            mock_hw.get_rtc.return_value = Mock()
            mock_hw.is_sd_mounted.return_value = False
            monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

            mock_buffer = Mock()
            mock_buffer.migrate_fallback = Mock(return_value=0)
            mock_buffer.get_metrics.return_value = {
                "buffer_entries": 0,
                "writes_to_fallback": 0,
                "fallback_migrations": 0,
                "writes_to_primary": 0,
                "write_failures": 0,
            }
            mock_buffer.is_primary_available.return_value = False
            mock_buffer._buffers = {}
            monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

            mock_logger = Mock()
            monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
            monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
            monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
            monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
            mock_buzzer = Mock()
            mock_buzzer.startup = AsyncMock()
            monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
            monkeypatch.setattr(
                main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True))
            )
            monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

            startup_drain_calls = []

            def track_drain(*args, **kwargs):
                startup_drain_calls.append((args, kwargs))
                return 0

            # Snapshot the call count before the health loop runs.
            async def first_sleep_records(duration):
                # Record drain calls up to this point (before health loop fires)
                startup_drain_calls.append(("HEALTH_LOOP_REACHED",))
                raise asyncio.CancelledError()

            mock_buffer.migrate_fallback = Mock(side_effect=track_drain)
            monkeypatch.setattr(main_module.asyncio, "sleep", first_sleep_records)
            monkeypatch.setattr(main_module.asyncio, "sleep_ms", first_sleep_records)

            with patch("time.localtime", return_value=FAKE_LOCALTIME):
                with pytest.raises(asyncio.CancelledError):
                    await main_module.main()

            # Drain must NOT have been called before the health loop kicked in.
            calls_before_health_loop = [c for c in startup_drain_calls if c != ("HEALTH_LOOP_REACHED",)]
            assert calls_before_health_loop == [], "migrate_fallback was called at boot despite SD unmounted"
        finally:
            DEVICE_CONFIG["system"]["require_sd_startup"] = orig


class TestDescribeResetCause:
    """Tests for the reset-cause logging helper."""

    def test_returns_pwron_label_for_pwron_code(self, monkeypatch):
        """Known reset codes map to their MicroPython constant name."""
        import main as main_module

        monkeypatch.setattr(main_module.machine, "reset_cause", lambda: main_module.machine.PWRON_RESET)
        assert main_module._describe_reset_cause() == "PWRON_RESET"

    def test_returns_wdt_label_for_wdt_code(self, monkeypatch):
        """WDT_RESET maps cleanly — this is the label we'll most want to see."""
        import main as main_module

        monkeypatch.setattr(main_module.machine, "reset_cause", lambda: main_module.machine.WDT_RESET)
        assert main_module._describe_reset_cause() == "WDT_RESET"

    def test_returns_code_for_unknown_value(self, monkeypatch):
        """Unknown integer codes fall through to a 'code=N' representation."""
        import main as main_module

        monkeypatch.setattr(main_module.machine, "reset_cause", lambda: 99)
        assert main_module._describe_reset_cause() == "code=99"

    def test_returns_unknown_when_reset_cause_raises(self, monkeypatch):
        """A throwing reset_cause() must not block boot diagnostics."""
        import main as main_module

        def boom():
            raise RuntimeError("port has no reset_cause")

        monkeypatch.setattr(main_module.machine, "reset_cause", boom)
        assert main_module._describe_reset_cause() == "unknown"


class _FakeTask:
    """Minimal task handle stand-in with a settable done() result."""

    def __init__(self, finished=False):
        self._finished = finished

    def done(self):
        return self._finished


class _OpaqueTask:
    """A handle with no done() — some MicroPython builds hand these back."""


class TestTaskLeakMetric:
    """The metrics `tasks` column reports a DELTA, not an absolute count.

    MicroPython's uasyncio has no all_tasks(), so the old hasattr() guard left
    the cell empty in all 10 327 rows of the 2026-08-07 field run. Tracking the
    handles main() spawns works on both runtimes, and a delta makes a healthy
    run read 0 while any drift shows up immediately.
    """

    @staticmethod
    def _seed(monkeypatch, tasks, baseline):
        import main as main_module

        monkeypatch.setattr(main_module, "_spawned_tasks", list(tasks))
        monkeypatch.setattr(main_module, "_task_baseline", baseline)
        return main_module

    def test_healthy_run_reports_zero(self, monkeypatch):
        m = self._seed(monkeypatch, [_FakeTask() for _ in range(9)], 9)
        assert m._get_runtime_load_snapshot()["task_count"] == 0

    def test_a_dead_task_reports_a_negative_delta(self, monkeypatch):
        tasks = [_FakeTask() for _ in range(9)]
        tasks[3] = _FakeTask(finished=True)
        m = self._seed(monkeypatch, tasks, 9)
        assert m._get_runtime_load_snapshot()["task_count"] == -1

    def test_an_extra_task_reports_a_positive_delta(self, monkeypatch):
        m = self._seed(monkeypatch, [_FakeTask() for _ in range(11)], 9)
        assert m._get_runtime_load_snapshot()["task_count"] == 2

    def test_handles_without_done_count_as_live(self, monkeypatch):
        """No done() on the runtime must read as "healthy", not as a phantom leak."""
        m = self._seed(monkeypatch, [_OpaqueTask() for _ in range(9)], 9)
        assert m._live_task_count() == 9
        assert m._get_runtime_load_snapshot()["task_count"] == 0

    def test_a_throwing_done_counts_as_live(self, monkeypatch):
        class _Angry:
            def done(self):
                raise RuntimeError("nope")

        m = self._seed(monkeypatch, [_Angry(), _FakeTask()], 2)
        assert m._live_task_count() == 2

    def test_track_task_returns_the_handle(self, monkeypatch):
        m = self._seed(monkeypatch, [], 0)
        handle = _FakeTask()
        assert m._track_task(handle) is handle
        assert m._live_task_count() == 1

    def test_snapshot_never_omits_the_key(self, monkeypatch):
        """Both metric sinks read this key; an absent one is what left the CSV blank."""
        m = self._seed(monkeypatch, [], 0)
        assert "task_count" in m._get_runtime_load_snapshot()


@pytest.mark.asyncio
class TestMainHealthCheck:
    """Tests for main loop health-check logic."""

    async def test_health_check_calls_log_rotation_check(self, monkeypatch):
        """Health loop should call EventLogger.check_size every cycle."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        mock_logger.check_size.assert_called()

    async def test_task_count_matches_in_both_metric_sinks(self, monkeypatch):
        """The mem-trend line and the metrics CSV must print the same figure.

        They used to disagree on how to spell "unknown": the log printed -1
        while the CSV cell was left empty for the very same missing value.
        """
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)
        monkeypatch.setitem(DEVICE_CONFIG["diagnostics"], "mem_trend_log", True)
        monkeypatch.setitem(DEVICE_CONFIG["diagnostics"], "metrics_log", True)

        fake_gc = Mock()
        fake_gc.mem_alloc = Mock(return_value=100_000)
        fake_gc.mem_free = Mock(return_value=150_000)
        fake_gc.collect = Mock()
        monkeypatch.setattr(main_module, "gc", fake_gc)

        rows = []
        mock_metrics = Mock()
        mock_metrics.write_row = Mock(side_effect=rows.append)
        monkeypatch.setattr(main_module, "MetricsLogger", lambda *a, **kw: mock_metrics)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        assert rows, "no metrics row was written"
        csv_tasks = rows[-1]["tasks"]
        assert csv_tasks is not None  # the field-run symptom: an empty cell
        trend_lines = [c.args[1] for c in mock_logger.info.call_args_list if "mem trend" in str(c.args[1])]
        assert trend_lines, "no mem-trend line was logged"
        assert f"tasks={csv_tasks} " in trend_lines[-1]

    async def test_health_check_warns_on_buffered_entries(self, monkeypatch):
        """When buffer has entries, main loop logs warning."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 5,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {"test.csv": ["a\n", "b\n", "c\n", "d\n", "e\n"]}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # Should have warned about buffered entries
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("Buffer" in c or "buffer" in c for c in warning_calls)

    async def test_sd_hot_swap_recovery(self, monkeypatch):
        """When primary unavailable, main loop attempts refresh_sd."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.refresh_sd.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = False
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        mock_hw.refresh_sd.assert_called()

    async def test_sd_hot_swap_recovery_on_buffer_growth(self, monkeypatch):
        """When primary reports available but buffer is growing, still attempt refresh_sd."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.refresh_sd.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 10,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        # Primary claims available but buffer is growing (ghost writes)
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {"test.csv": list(range(10))}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # refresh_sd should be called even though is_primary_available is True
        mock_hw.refresh_sd.assert_called()
        # flush should also be called after successful refresh
        mock_buffer.flush.assert_called()
        # Should log how many entries were flushed
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Flushed" in c and "10" in c for c in info_calls)

    async def test_no_card_detected_skips_refresh(self, monkeypatch):
        """When DET reports no card, refresh_sd is skipped and state is no_card."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        mock_hw.is_card_present.return_value = False  # slot empty
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # No card → no bus probe, and the tri-state reports no_card_inserted.
        mock_hw.refresh_sd.assert_not_called()
        mock_sm.set_sd_state.assert_any_call("no_card_inserted")

    async def test_card_reinsert_forces_remount(self, monkeypatch):
        """A DET absent→present edge forces refresh_sd even when idle/clean."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        # Seed read (before loop) = absent; first loop read = present → edge.
        mock_hw.is_card_present.side_effect = [False, True, True, True]
        mock_hw.refresh_sd.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        # Primary claims available and buffer is empty: only the reinsert
        # edge can trigger a refresh here.
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # The reinsert edge forced a remount despite idle/clean buffer state.
        mock_hw.refresh_sd.assert_called()
        mock_sm.set_sd_state.assert_any_call("mounted")

    async def test_fallback_migration_attempt(self, monkeypatch):
        """When fallback writes exceed migrations, attempt migration."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 3,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        mock_buffer.migrate_fallback.return_value = 3
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", limited_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", limited_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        mock_buffer.migrate_fallback.assert_called()

    async def test_adaptive_interval_uses_recovery_when_sd_down(self, monkeypatch):
        """When SD is unavailable, health loop switches to the fast recovery interval."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.refresh_sd.return_value = False  # SD stays down
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = False
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        sleep_durations = []

        async def tracking_sleep(duration):
            sleep_durations.append(duration)
            if len(sleep_durations) >= 3:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", tracking_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", tracking_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # First sleep uses normal interval (60), subsequent ones use recovery (10)
        assert sleep_durations[0] == 60
        assert sleep_durations[1] == 10

        # Should log SD unavailability warning
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("SD card not accessible" in c for c in warning_calls)

    async def test_adaptive_interval_restores_after_recovery(self, monkeypatch):
        """After SD recovery, health loop restores the normal interval."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        # First call: SD comes back
        mock_hw.refresh_sd.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        call_count = 0

        def get_metrics():
            nonlocal call_count
            call_count += 1
            # First iteration: primary down, buffer has entries
            if call_count == 1:
                return {
                    "buffer_entries": 5,
                    "writes_to_fallback": 0,
                    "fallback_migrations": 0,
                    "writes_to_primary": 0,
                    "write_failures": 0,
                }
            # After recovery: everything good
            return {
                "buffer_entries": 0,
                "writes_to_fallback": 0,
                "fallback_migrations": 0,
                "writes_to_primary": 0,
                "write_failures": 0,
            }

        mock_buffer = Mock()
        mock_buffer.get_metrics = get_metrics
        mock_buffer.is_primary_available.return_value = False
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        sleep_durations = []

        async def tracking_sleep(duration):
            sleep_durations.append(duration)
            if len(sleep_durations) >= 3:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", tracking_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", tracking_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # First sleep = normal (60), after recovery: still normal (60)
        assert sleep_durations[0] == 60
        assert sleep_durations[1] == 60


@pytest.mark.asyncio
class TestMainInitFailures:
    """Tests for main() init-failure resilience paths."""

    async def test_th_logger_init_failure_creates_fallback(self, monkeypatch):
        """When TempHumidityLogger init raises (with status_manager), falls back to minimal logger."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {"buffer_entries": 0, "writes_to_fallback": 0, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)

        # First call (with status_manager) raises; second call (without) succeeds
        call_count = 0

        def th_factory(*a, **kw):
            nonlocal call_count
            call_count += 1
            if "status_manager" in kw and kw["status_manager"] is not None:
                raise RuntimeError("sensor init boom")
            return Mock()

        monkeypatch.setattr(main_module, "TempHumidityLogger", th_factory)
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        async def stop_sleep(duration):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # TempHumidityLogger should have been called twice (first raises, second succeeds)
        assert call_count == 2
        # Error should have been logged
        mock_logger.error.assert_any_call("MAIN", "TempHumidityLogger init failed: sensor init boom")

    async def test_buzzer_init_failure_sets_none(self, monkeypatch):
        """When BuzzerController init raises, buzzer is None and warning is logged."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {"buffer_entries": 0, "writes_to_fallback": 0, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())

        # BuzzerController raises on init
        monkeypatch.setattr(
            main_module,
            "BuzzerController",
            Mock(side_effect=RuntimeError("PWM fail")),
        )

        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        async def stop_sleep(duration):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # Should have logged warning about buzzer failure
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("Buzzer init failed" in c for c in warning_calls)
        # set_buzzer should NOT have been called on status_manager
        mock_sm.set_buzzer.assert_not_called()

    async def test_rtc_invalid_sets_warning(self, monkeypatch):
        """When time_provider.time_valid is False, sets rtc_invalid warning."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {"buffer_entries": 0, "writes_to_fallback": 0, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)

        # Create a mock RTCTimeProvider with time_valid=False
        mock_tp = Mock()
        mock_tp.time_valid = False
        monkeypatch.setattr(main_module, "RTCTimeProvider", lambda *a, **kw: mock_tp)

        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        async def stop_sleep(duration):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        mock_sm.set_warning.assert_any_call("rtc_invalid", True)

    async def test_post_disabled_skips_run_post(self, monkeypatch):
        """When post_enabled=False in config, run_post is not called."""
        import main as main_module

        # Override config to disable POST
        custom_config = dict(DEVICE_CONFIG)
        custom_config["status_leds"] = dict(DEVICE_CONFIG.get("status_leds", {}))
        custom_config["status_leds"]["post_enabled"] = False
        monkeypatch.setattr(main_module, "DEVICE_CONFIG", custom_config)

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {"buffer_entries": 0, "writes_to_fallback": 0, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)

        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        async def stop_sleep(duration):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # run_post should NOT have been called
        mock_sm.run_post.assert_not_called()


class TestEnterSDFailureState:
    """Tests for _enter_sd_failure_state(): boot-time hard-fail on SD missing."""

    def test_lights_sd_and_error_leds(self, monkeypatch):
        """SD failure path turns on sd_led (via set_sd_status(False)) and error_led."""
        import main as main_module

        sm = Mock()
        wdt = Mock()
        monkeypatch.setattr(main_module.time, "sleep", lambda _: None)

        main_module._enter_sd_failure_state(sm, wdt, countdown_s=1)

        sm.set_sd_status.assert_called_once_with(False)
        sm.set_error.assert_called_once_with("sd_required", True)

    def test_feeds_watchdog_during_countdown(self, monkeypatch):
        """Each 0.5s tick of the countdown must feed the watchdog."""
        import main as main_module

        sm = Mock()
        wdt = Mock()
        monkeypatch.setattr(main_module.time, "sleep", lambda _: None)

        main_module._enter_sd_failure_state(sm, wdt, countdown_s=2)

        # 2s / 0.5s step = 4 feeds
        assert wdt.feed.call_count == 4

    def test_tolerates_wdt_feed_failure(self, monkeypatch):
        """A raising WDT.feed() does not abort the countdown."""
        import main as main_module

        sm = Mock()
        wdt = Mock()
        wdt.feed.side_effect = RuntimeError("dead WDT")
        monkeypatch.setattr(main_module.time, "sleep", lambda _: None)

        main_module._enter_sd_failure_state(sm, wdt, countdown_s=1)

        sm.set_error.assert_called_once_with("sd_required", True)
        assert wdt.feed.call_count >= 1

    def test_tolerates_no_wdt(self, monkeypatch):
        """Passing wdt=None must not raise."""
        import main as main_module

        sm = Mock()
        monkeypatch.setattr(main_module.time, "sleep", lambda _: None)

        main_module._enter_sd_failure_state(sm, None, countdown_s=1)

        sm.set_error.assert_called_once_with("sd_required", True)


@pytest.mark.asyncio
class TestMainSDFailHard:
    """Tests for the require_sd_startup hard-fail path in main()."""

    async def test_sd_failure_with_required_triggers_fail_state(self, monkeypatch):
        """SD missing + require_sd_startup=True → _enter_sd_failure_state is called."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = False  # SD failed
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)

        fail_state_calls = []

        def _capture_fail_state(sm, wdt, countdown_s):
            fail_state_calls.append({"sm": sm, "wdt": wdt, "countdown_s": countdown_s})

        monkeypatch.setattr(main_module, "_enter_sd_failure_state", _capture_fail_state)
        monkeypatch.setitem(main_module.DEVICE_CONFIG["system"], "require_sd_startup", True)
        monkeypatch.setitem(main_module.DEVICE_CONFIG["system"], "sd_fail_reset_s", 7)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            await main_module.main()

        # Hard-fail path entered exactly once with config-driven countdown.
        assert len(fail_state_calls) == 1
        assert fail_state_calls[0]["countdown_s"] == 7
        assert fail_state_calls[0]["sm"] is mock_sm
        # Subsequent init (BufferManager, EventLogger, ...) must NOT have run.
        mock_sm.run_post.assert_not_called()

    async def test_sd_failure_without_required_continues_on_fallback(self, monkeypatch):
        """SD missing + require_sd_startup=False → boot proceeds (existing fallback path)."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = False
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = False
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)

        fail_state_calls = []
        monkeypatch.setattr(
            main_module,
            "_enter_sd_failure_state",
            lambda *a, **kw: fail_state_calls.append(a),
        )
        monkeypatch.setitem(main_module.DEVICE_CONFIG["system"], "require_sd_startup", False)
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        async def stop_sleep(_):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # Restore default so other tests see require_sd_startup=True again.
        monkeypatch.setitem(main_module.DEVICE_CONFIG["system"], "require_sd_startup", True)

        assert fail_state_calls == []
        mock_sm.run_post.assert_called_once()

    async def test_post_reasserts_sd_status_after_walk(self, monkeypatch):
        """After run_post() drives every LED off, set_sd_status is re-called with real state."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            "buffer_entries": 0,
            "writes_to_fallback": 0,
            "fallback_migrations": 0,
            "writes_to_primary": 0,
            "write_failures": 0,
        }
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "TempHumidityLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)
        monkeypatch.setattr(main_module.asyncio, "create_task", _mock_create_task)

        async def stop_sleep(_):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # set_sd_status is called at least twice: once before POST (initial
        # reflection) and once immediately after POST (re-assert).
        assert mock_sm.set_sd_status.call_count >= 2
