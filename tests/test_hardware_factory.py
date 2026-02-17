# Tests for lib/hardware_factory.py
# Covers setup, init methods, error handling, SD refresh

from unittest.mock import Mock, patch


class TestHardwareFactorySetup:
    """Tests for HardwareFactory.setup() orchestration."""

    def test_full_setup_success(self, monkeypatch):
        """All _init_* succeed → setup() returns True."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        monkeypatch.setattr(factory, '_init_rtc', lambda: True)
        monkeypatch.setattr(factory, '_init_spi', lambda: True)
        monkeypatch.setattr(factory, '_init_sd', lambda: True)
        assert factory.setup() is True

    def test_rtc_failure_returns_false(self, monkeypatch):
        """RTC failure → setup() returns False."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        monkeypatch.setattr(factory, '_init_rtc', lambda: False)
        assert factory.setup() is False

    def test_spi_failure_non_fatal(self, monkeypatch):
        """SPI failure is non-fatal; setup still returns True (RTC ok)."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        monkeypatch.setattr(factory, '_init_rtc', lambda: True)
        monkeypatch.setattr(factory, '_init_spi', lambda: False)
        monkeypatch.setattr(factory, '_init_sd', lambda: True)
        assert factory.setup() is True

    def test_sd_failure_non_fatal(self, monkeypatch):
        """SD mount failure is non-fatal; system continues with fallback."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        monkeypatch.setattr(factory, '_init_rtc', lambda: True)
        monkeypatch.setattr(factory, '_init_spi', lambda: True)
        monkeypatch.setattr(factory, '_init_sd', lambda: False)
        assert factory.setup() is True
        assert factory.sd_mounted is False


class TestHardwareFactoryRTC:
    """Tests for RTC initialization."""

    def test_init_rtc_success(self):
        """_init_rtc() returns True when RTC responds."""
        from lib.hardware_factory import HardwareFactory

        mock_rtc_class = Mock()
        mock_rtc_instance = Mock()
        mock_rtc_instance.ReadTime = Mock(return_value=(0, 0, 12, 3, 15, 2, 2026))
        mock_rtc_class.return_value = mock_rtc_instance

        factory = HardwareFactory()
        with patch('lib.hardware_factory.ds3231.RTC', mock_rtc_class):
            result = factory._init_rtc()
        assert result is True
        assert factory.rtc is mock_rtc_instance

    def test_init_rtc_failure(self):
        """_init_rtc() returns False when RTC raises."""
        from lib.hardware_factory import HardwareFactory

        mock_rtc_class = Mock(side_effect=OSError('I2C fail'))

        factory = HardwareFactory()
        with patch('lib.hardware_factory.ds3231.RTC', mock_rtc_class):
            result = factory._init_rtc()
        assert result is False
        assert len(factory.errors) > 0

    def test_init_rtc_invalid_response(self):
        """_init_rtc() returns False when ReadTime returns invalid data."""
        from lib.hardware_factory import HardwareFactory

        mock_rtc_class = Mock()
        mock_rtc_instance = Mock()
        mock_rtc_instance.ReadTime = Mock(return_value='Error: Not connected')
        mock_rtc_class.return_value = mock_rtc_instance

        factory = HardwareFactory()
        with patch('lib.hardware_factory.ds3231.RTC', mock_rtc_class):
            result = factory._init_rtc()
        assert result is False


class TestHardwareFactorySPI:
    """Tests for SPI initialization."""

    def test_init_spi_success(self):
        """_init_spi() returns True when SPI inits OK."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        result = factory._init_spi()
        assert result is True
        assert factory.spi is not None

    def test_init_spi_failure(self):
        """_init_spi() returns False when SPI raises."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        with patch('lib.hardware_factory.SPI', side_effect=OSError('SPI fail')):
            result = factory._init_spi()
        assert result is False
        assert len(factory.errors) > 0


class TestHardwareFactorySD:
    """Tests for SD card initialization."""

    def test_init_sd_host_mode(self, tmp_path):
        """On host (non-micropython), SD init creates directory."""
        from lib.hardware_factory import HardwareFactory
        config = {
            'pins': {}, 'spi': {'mount_point': str(tmp_path / 'sd')},
            'output_pins': {},
        }
        factory = HardwareFactory(config)
        result = factory._init_sd()
        assert result is True
        assert factory.sd_mounted is True

    def test_init_sd_no_spi_on_device(self):
        """_init_sd() returns False when SPI not initialized on device path."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        factory.spi = None

        with patch.object(hf_mod, '_IS_HOST', False):
            result = factory._init_sd()

        assert result is False
        assert any('SPI not initialized' in e for e in factory.errors)

    def test_init_sd_device_mount_succeeds_first_try(self):
        """Device path: mount_sd succeeds on first attempt."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        factory.spi = Mock()

        with patch.object(hf_mod, '_IS_HOST', False):
            with patch('lib.hardware_factory.mount_sd', return_value=(True, Mock())) as mount_mock:
                with patch('time.sleep_ms'):
                    result = factory._init_sd()

        assert result is True
        assert factory.sd_mounted is True
        assert mount_mock.call_count == 1 # type: ignore

    def test_init_sd_device_retries_on_failure(self):
        """Device path: mount_sd fails twice then succeeds on 3rd attempt."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        factory.spi = Mock()

        mock_sd = Mock()
        with patch.object(hf_mod, '_IS_HOST', False):
            with patch('lib.hardware_factory.mount_sd', side_effect=[
                (False, None), (False, None), (True, mock_sd)
            ]) as mount_mock:  # type: ignore
                with patch('time.sleep_ms'):
                    result = factory._init_sd()
                assert mount_mock.call_count == 3  # type: ignore

        assert result is True
        assert factory.sd_mounted is True

    def test_init_sd_device_all_retries_fail(self):
        """Device path: all 3 mount attempts fail → returns False."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        factory.spi = Mock()

        with patch.object(hf_mod, '_IS_HOST', False):
            with patch('lib.hardware_factory.mount_sd', return_value=(False, None)):
                with patch('time.sleep_ms'):
                    result = factory._init_sd()

        assert result is False
        assert any('SD card mount failed after retries' in e for e in factory.errors)

    def test_init_sd_device_exception(self):
        """Device path: exception during SD init → returns False."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        factory.spi = Mock()

        with patch.object(hf_mod, '_IS_HOST', False):
            with patch('lib.hardware_factory.mount_sd', side_effect=OSError('hw fault')):
                with patch('time.sleep_ms'):
                    result = factory._init_sd()

        assert result is False
        assert any('SD init failed' in e for e in factory.errors)


class TestHardwareFactoryPins:
    """Tests for GPIO pin initialization."""

    def test_init_pins_creates_entries(self, monkeypatch):
        """_init_pins() creates Pin entries for output_pins config."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        factory._init_pins()
        assert isinstance(factory.pins, dict)
        # Should have created pins for relay_fan_1, relay_fan_2, etc.
        assert len(factory.pins) > 0

    def test_init_pins_button_with_pullup(self):
        """Button pin is created with Pin.IN and PULL_UP."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        factory._init_pins()
        assert 'button_menu' in factory.pins


class TestHardwareFactoryAccessors:
    """Tests for get/accessor methods."""

    def test_get_rtc_returns_none_initially(self):
        """get_rtc() returns None before setup."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        assert factory.get_rtc() is None

    def test_get_pin_missing(self):
        """get_pin() returns None for non-existent pin."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        assert factory.get_pin('nonexistent') is None

    def test_get_all_pins_returns_copy(self, monkeypatch):
        """get_all_pins() returns a copy of pins dict."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        monkeypatch.setattr(factory, '_init_rtc', lambda: True)
        monkeypatch.setattr(factory, '_init_spi', lambda: True)
        monkeypatch.setattr(factory, '_init_sd', lambda: True)
        factory.setup()
        pins = factory.get_all_pins()
        assert isinstance(pins, dict)
        # Modifying returned dict shouldn't affect factory
        pins['test'] = 'value'
        assert 'test' not in factory.pins

    def test_is_sd_mounted_default_false(self):
        """is_sd_mounted() is False before setup."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        assert factory.is_sd_mounted() is False

    def test_get_errors_initially_empty(self):
        """get_errors() returns empty list before setup."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        assert factory.get_errors() == []

    def test_get_errors_after_failure(self):
        """get_errors() includes error messages after failures."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        factory.errors.append('test error')
        errors = factory.get_errors()
        assert 'test error' in errors

    def test_print_status(self, capsys, monkeypatch):
        """print_status() outputs status report."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        monkeypatch.setattr(factory, '_init_rtc', lambda: True)
        monkeypatch.setattr(factory, '_init_spi', lambda: True)
        monkeypatch.setattr(factory, '_init_sd', lambda: True)
        factory.setup()
        factory.print_status()
        captured = capsys.readouterr()
        assert 'Status Report' in captured.out


class TestHardwareFactoryRefresh:
    """Tests for SD refresh/hot-swap."""

    def test_refresh_sd_success(self, monkeypatch):
        """refresh_sd() returns True when SD is accessible."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()
        mock_sd = Mock()
        mock_spi = Mock()

        with patch('lib.hardware_factory.is_mounted', return_value=(True, mock_sd, mock_spi)):
            result = factory.refresh_sd()
        assert result is True
        assert factory.sd_mounted is True

    def test_refresh_sd_failure(self, monkeypatch):
        """refresh_sd() returns False on exception."""
        from lib.hardware_factory import HardwareFactory
        factory = HardwareFactory()

        with patch('lib.hardware_factory.is_mounted', side_effect=OSError('fail')):
            result = factory.refresh_sd()
        assert result is False
        assert factory.sd_mounted is False
