# Tests for main.py orchestration
# Covers startup, task spawning, error paths, health-check loop

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

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
