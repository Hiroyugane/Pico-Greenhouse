# Tests for main.py orchestration
# Covers startup, task spawning, error paths, health-check loop

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from config import DEVICE_CONFIG
from tests.conftest import FAKE_LOCALTIME


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
        mock_buffer.get_metrics.return_value = {"buffer_entries": 0, "writes_to_fallback": 0, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = True
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))

        created_tasks = []
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: created_tasks.append(t) or Mock())

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


@pytest.mark.asyncio
class TestMainHealthCheck:
    """Tests for main loop health-check logic."""

    async def test_health_check_warns_on_buffered_entries(self, monkeypatch):
        """When buffer has entries, main loop logs warning."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {"buffer_entries": 5, "writes_to_fallback": 0, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {"test.csv": ["a\n", "b\n", "c\n", "d\n", "e\n"]}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
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
        mock_buffer.get_metrics.return_value = {"buffer_entries": 0, "writes_to_fallback": 0, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = False
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
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
        mock_buffer.get_metrics.return_value = {"buffer_entries": 10, "writes_to_fallback": 0, "fallback_migrations": 0}
        # Primary claims available but buffer is growing (ghost writes)
        mock_buffer.is_primary_available.return_value = True
        mock_buffer._buffers = {"test.csv": list(range(10))}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
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

        # refresh_sd should be called even though is_primary_available is True
        mock_hw.refresh_sd.assert_called()
        # flush should also be called after successful refresh
        mock_buffer.flush.assert_called()
        # Should log how many entries were flushed
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Flushed" in c and "10" in c for c in info_calls)

    async def test_fallback_migration_attempt(self, monkeypatch):
        """When fallback writes exceed migrations, attempt migration."""
        import main as main_module

        monkeypatch.setattr(main_module, "validate_config", lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        monkeypatch.setattr(main_module, "HardwareFactory", lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {"buffer_entries": 0, "writes_to_fallback": 3, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = True
        mock_buffer.migrate_fallback.return_value = 3
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
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
        mock_buffer.get_metrics.return_value = {"buffer_entries": 0, "writes_to_fallback": 0, "fallback_migrations": 0}
        mock_buffer.is_primary_available.return_value = False
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

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
                return {"buffer_entries": 5, "writes_to_fallback": 0, "fallback_migrations": 0}
            # After recovery: everything good
            return {"buffer_entries": 0, "writes_to_fallback": 0, "fallback_migrations": 0}

        mock_buffer = Mock()
        mock_buffer.get_metrics = get_metrics
        mock_buffer.is_primary_available.return_value = False
        mock_buffer._buffers = {}
        monkeypatch.setattr(main_module, "BufferManager", lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, "EventLogger", lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

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

    async def test_dht_logger_init_failure_creates_fallback(self, monkeypatch):
        """When DHTLogger init raises (with status_manager), falls back to minimal DHTLogger."""
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

        def dht_factory(*a, **kw):
            nonlocal call_count
            call_count += 1
            if "status_manager" in kw and kw["status_manager"] is not None:
                raise RuntimeError("sensor init boom")
            return Mock()

        monkeypatch.setattr(main_module, "DHTLogger", dht_factory)
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: Mock(run_post=AsyncMock(return_value=True)))
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

        async def stop_sleep(duration):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # DHTLogger should have been called twice (first raises, second succeeds)
        assert call_count == 2
        # Error should have been logged
        mock_logger.error.assert_any_call("MAIN", "DHTLogger init failed: sensor init boom")

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
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
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
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

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
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
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
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

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
        monkeypatch.setattr(main_module, "DHTLogger", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "FanController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "GrowlightController", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "LEDButtonHandler", lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, "ServiceReminder", lambda *a, **kw: Mock())
        mock_buzzer = Mock()
        mock_buzzer.startup = AsyncMock()
        monkeypatch.setattr(main_module, "BuzzerController", lambda *a, **kw: mock_buzzer)

        mock_sm = Mock(run_post=AsyncMock(return_value=True))
        monkeypatch.setattr(main_module, "StatusManager", lambda *a, **kw: mock_sm)
        monkeypatch.setattr(main_module.asyncio, "create_task", lambda t: Mock())

        async def stop_sleep(duration):
            raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, "sleep", stop_sleep)
        monkeypatch.setattr(main_module.asyncio, "sleep_ms", stop_sleep)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # run_post should NOT have been called
        mock_sm.run_post.assert_not_called()
