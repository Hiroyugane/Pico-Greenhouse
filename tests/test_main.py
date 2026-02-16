# Tests for main.py orchestration
# Covers startup, task spawning, error paths, health-check loop

import asyncio
import pytest
from unittest.mock import Mock, patch, MagicMock
from tests.conftest import FAKE_LOCALTIME


class TestMainStartup:
    """Tests for main() startup sequence."""

    async def test_config_validation_failure_exits(self, monkeypatch):
        """If validate_config raises, main() returns early."""
        import main as main_module

        monkeypatch.setattr(main_module, 'validate_config',
                            Mock(side_effect=ValueError('bad config')))

        # Should return without crashing
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            await main_module.main()

    async def test_hardware_setup_failure_exits(self, monkeypatch):
        """If hardware.setup() returns False, main() returns early."""
        import main as main_module

        monkeypatch.setattr(main_module, 'validate_config', lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = False
        mock_hw.print_status = Mock()
        monkeypatch.setattr(main_module, 'HardwareFactory', lambda *a, **kw: mock_hw)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            await main_module.main()

        mock_hw.print_status.assert_called()

    async def test_spawns_tasks_and_runs_loop(self, monkeypatch):
        """main() creates async tasks and enters event loop."""
        import main as main_module

        monkeypatch.setattr(main_module, 'validate_config', lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.is_sd_mounted.return_value = True
        monkeypatch.setattr(main_module, 'HardwareFactory', lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            'buffer_entries': 0, 'writes_to_fallback': 0, 'fallback_migrations': 0
        }
        mock_buffer.is_primary_available.return_value = True
        monkeypatch.setattr(main_module, 'BufferManager', lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, 'EventLogger', lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, 'DHTLogger', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'FanController', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'GrowlightController', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'LEDButtonHandler', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'ServiceReminder', lambda *a, **kw: Mock())

        created_tasks = []
        monkeypatch.setattr(main_module.asyncio, 'create_task',
                            lambda t: created_tasks.append(t) or Mock())

        call_count = 0
        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, 'sleep', limited_sleep)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        assert len(created_tasks) > 0


class TestMainHealthCheck:
    """Tests for main loop health-check logic."""

    async def test_health_check_warns_on_buffered_entries(self, monkeypatch):
        """When buffer has entries, main loop logs warning."""
        import main as main_module

        monkeypatch.setattr(main_module, 'validate_config', lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        monkeypatch.setattr(main_module, 'HardwareFactory', lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            'buffer_entries': 5, 'writes_to_fallback': 0, 'fallback_migrations': 0
        }
        mock_buffer.is_primary_available.return_value = True
        monkeypatch.setattr(main_module, 'BufferManager', lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, 'EventLogger', lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, 'DHTLogger', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'FanController', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'GrowlightController', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'LEDButtonHandler', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'ServiceReminder', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module.asyncio, 'create_task', lambda t: Mock())

        call_count = 0
        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, 'sleep', limited_sleep)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        # Should have warned about buffered entries
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any('Buffer' in c or 'buffer' in c for c in warning_calls)

    async def test_sd_hot_swap_recovery(self, monkeypatch):
        """When primary unavailable, main loop attempts refresh_sd."""
        import main as main_module

        monkeypatch.setattr(main_module, 'validate_config', lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        mock_hw.refresh_sd.return_value = True
        monkeypatch.setattr(main_module, 'HardwareFactory', lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            'buffer_entries': 0, 'writes_to_fallback': 0, 'fallback_migrations': 0
        }
        mock_buffer.is_primary_available.return_value = False
        monkeypatch.setattr(main_module, 'BufferManager', lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, 'EventLogger', lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, 'DHTLogger', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'FanController', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'GrowlightController', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'LEDButtonHandler', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'ServiceReminder', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module.asyncio, 'create_task', lambda t: Mock())

        call_count = 0
        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, 'sleep', limited_sleep)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        mock_hw.refresh_sd.assert_called()

    async def test_fallback_migration_attempt(self, monkeypatch):
        """When fallback writes exceed migrations, attempt migration."""
        import main as main_module

        monkeypatch.setattr(main_module, 'validate_config', lambda: True)

        mock_hw = Mock()
        mock_hw.setup.return_value = True
        mock_hw.get_rtc.return_value = Mock()
        monkeypatch.setattr(main_module, 'HardwareFactory', lambda *a, **kw: mock_hw)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            'buffer_entries': 0, 'writes_to_fallback': 3, 'fallback_migrations': 0
        }
        mock_buffer.is_primary_available.return_value = True
        mock_buffer.migrate_fallback.return_value = 3
        monkeypatch.setattr(main_module, 'BufferManager', lambda *a, **kw: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, 'EventLogger', lambda *a, **kw: mock_logger)
        monkeypatch.setattr(main_module, 'DHTLogger', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'FanController', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'GrowlightController', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'LEDButtonHandler', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module, 'ServiceReminder', lambda *a, **kw: Mock())
        monkeypatch.setattr(main_module.asyncio, 'create_task', lambda t: Mock())

        call_count = 0
        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        monkeypatch.setattr(main_module.asyncio, 'sleep', limited_sleep)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with pytest.raises(asyncio.CancelledError):
                await main_module.main()

        mock_buffer.migrate_fallback.assert_called()
