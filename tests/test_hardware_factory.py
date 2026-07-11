# Tests for lib/hardware_factory.py
# Covers setup, init methods, error handling, SD refresh

from unittest.mock import Mock, patch


class TestHardwareFactorySetup:
    """Tests for HardwareFactory.setup() orchestration."""

    def test_full_setup_success(self, monkeypatch):
        """All _init_* succeed → setup() returns True."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setattr(factory, "_init_rtc", lambda: True)
        monkeypatch.setattr(factory, "_init_spi", lambda: True)
        monkeypatch.setattr(factory, "_init_sd", lambda: True)
        assert factory.setup() is True

    def test_rtc_failure_returns_false(self, monkeypatch):
        """RTC failure → setup() returns False."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setattr(factory, "_init_rtc", lambda: False)
        assert factory.setup() is False

    def test_spi_failure_non_fatal(self, monkeypatch):
        """SPI failure is non-fatal; setup still returns True (RTC ok)."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setattr(factory, "_init_rtc", lambda: True)
        monkeypatch.setattr(factory, "_init_spi", lambda: False)
        monkeypatch.setattr(factory, "_init_sd", lambda: True)
        assert factory.setup() is True

    def test_sd_failure_non_fatal(self, monkeypatch):
        """SD mount failure is non-fatal; system continues with fallback."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setattr(factory, "_init_rtc", lambda: True)
        monkeypatch.setattr(factory, "_init_spi", lambda: True)
        monkeypatch.setattr(factory, "_init_sd", lambda: False)
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
        with patch("lib.hardware_factory.ds3231.RTC", mock_rtc_class):
            result = factory._init_rtc()
        assert result is True
        assert factory.rtc is mock_rtc_instance

    def test_init_rtc_failure(self):
        """_init_rtc() returns False when RTC raises."""
        from lib.hardware_factory import HardwareFactory

        mock_rtc_class = Mock(side_effect=OSError("I2C fail"))

        factory = HardwareFactory()
        with patch("lib.hardware_factory.ds3231.RTC", mock_rtc_class):
            result = factory._init_rtc()
        assert result is False
        assert len(factory.errors) > 0

    def test_init_rtc_invalid_response(self):
        """_init_rtc() returns False when ReadTime returns invalid data."""
        from lib.hardware_factory import HardwareFactory

        mock_rtc_class = Mock()
        mock_rtc_instance = Mock()
        mock_rtc_instance.ReadTime = Mock(return_value="Error: Not connected")
        mock_rtc_class.return_value = mock_rtc_instance

        factory = HardwareFactory()
        with patch("lib.hardware_factory.ds3231.RTC", mock_rtc_class):
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
        with patch("lib.hardware_factory.SPI", side_effect=OSError("SPI fail")):
            result = factory._init_spi()
        assert result is False
        assert len(factory.errors) > 0


class TestHardwareFactorySD:
    """Tests for SD card initialization."""

    def test_init_sd_host_mode(self, tmp_path):
        """On host (non-micropython), SD init creates directory."""
        from lib.hardware_factory import HardwareFactory

        config = {
            "pins": {},
            "spi": {"mount_point": str(tmp_path / "sd")},
            "output_pins": {},
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

        with patch.object(hf_mod, "_IS_HOST", False):
            result = factory._init_sd()

        assert result is False
        assert any("SPI not initialized" in e for e in factory.errors)

    def test_init_sd_device_mount_succeeds_first_try(self):
        """Device path: mount_sd succeeds on first attempt."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.spi = Mock()

        with patch.object(hf_mod, "_IS_HOST", False):
            with patch("lib.hardware_factory.mount_sd", return_value=(True, Mock())) as mount_mock:
                with patch("time.sleep_ms"):
                    result = factory._init_sd()

        assert result is True
        assert factory.sd_mounted is True
        assert mount_mock.call_count == 1  # type: ignore

    def test_init_sd_device_retries_on_failure(self):
        """Device path: mount_sd fails twice then succeeds on 3rd attempt."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.spi = Mock()

        mock_sd = Mock()
        with patch.object(hf_mod, "_IS_HOST", False):
            with patch(
                "lib.hardware_factory.mount_sd", side_effect=[(False, None), (False, None), (True, mock_sd)]
            ) as mount_mock:  # type: ignore
                with patch("time.sleep_ms"):
                    result = factory._init_sd()
                assert mount_mock.call_count == 3  # type: ignore

        assert result is True
        assert factory.sd_mounted is True

    def test_init_sd_reinits_spi_between_retries(self):
        """Each failed mount attempt must deinit + reinit SPI before the next try."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        first_spi = Mock()
        factory.spi = first_spi

        reinit_count = {"n": 0}
        original_reinit = factory._reinit_spi

        def _spy_reinit():
            reinit_count["n"] += 1
            # Hand back a fresh Mock to simulate a real SPI() return.
            factory.spi = Mock()
            # Don't actually call SPI() inside _init_spi — keep the test pure.
            return None

        with patch.object(hf_mod, "_IS_HOST", False):
            with patch.object(factory, "_reinit_spi", side_effect=_spy_reinit):
                with patch(
                    "lib.hardware_factory.mount_sd",
                    side_effect=[(False, None), (False, None), (True, Mock())],
                ):
                    with patch("time.sleep_ms"):
                        result = factory._init_sd()

        assert result is True
        # Two retries → two SPI reinits before the successful third attempt.
        assert reinit_count["n"] == 2
        # Last reinit replaced the original SPI instance.
        assert factory.spi is not first_spi
        # Silence "unused" warning on the original helper reference.
        assert callable(original_reinit)

    def test_reinit_spi_deinits_old_bus(self):
        """_reinit_spi() calls deinit() on the existing bus before creating a new one."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        old_spi = Mock()
        old_spi.deinit = Mock()
        factory.spi = old_spi

        with patch.object(factory, "_init_spi", return_value=True) as init_mock:
            factory._reinit_spi()

        old_spi.deinit.assert_called_once()
        init_mock.assert_called_once()

    def test_reinit_spi_tolerates_deinit_failure(self):
        """_reinit_spi() swallows deinit errors and still reinits."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        bad_spi = Mock()
        bad_spi.deinit = Mock(side_effect=OSError("bus gone"))
        factory.spi = bad_spi

        with patch.object(factory, "_init_spi", return_value=True) as init_mock:
            factory._reinit_spi()  # must not raise

        init_mock.assert_called_once()

    def test_init_sd_device_all_retries_fail(self):
        """Device path: 3 mount_sd attempts fail AND is_mounted fallback fails → returns False."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.spi = Mock()

        with patch.object(hf_mod, "_IS_HOST", False):
            with patch("lib.hardware_factory.mount_sd", return_value=(False, None)):
                with patch("lib.hardware_factory.is_mounted", return_value=(False, None, None)):
                    with patch("time.sleep_ms"):
                        result = factory._init_sd()

        assert result is False
        assert any("SD card mount failed after retries" in e for e in factory.errors)

    def test_init_sd_is_mounted_fallback_succeeds(self):
        """Device path: mount_sd fails 3× but is_mounted fallback succeeds → True."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.spi = Mock()

        mock_sd = Mock()
        mock_spi = Mock()
        with patch.object(hf_mod, "_IS_HOST", False):
            with patch("lib.hardware_factory.mount_sd", return_value=(False, None)) as mount_mock:
                with patch(
                    "lib.hardware_factory.is_mounted",
                    return_value=(True, mock_sd, mock_spi),
                ) as is_mounted_mock:
                    with patch("time.sleep_ms"):
                        result = factory._init_sd()

        assert result is True
        assert factory.sd_mounted is True
        assert factory.sd is mock_sd
        assert mount_mock.call_count == 3  # type: ignore[attr-defined]
        is_mounted_mock.assert_called_once()  # type: ignore[attr-defined]

    def test_init_sd_feeds_wdt_when_provided(self):
        """Each attempt + retry pause feeds the injected WDT so a slow card doesn't trip it."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory

        wdt = Mock()
        factory = HardwareFactory(wdt=wdt)
        factory.spi = Mock()

        with patch.object(hf_mod, "_IS_HOST", False):
            with patch("lib.hardware_factory.mount_sd", side_effect=[(False, None), (True, Mock())]):
                with patch("time.sleep_ms"):
                    result = factory._init_sd()

        assert result is True
        # At minimum: one feed after power-up, one between retries.
        assert wdt.feed.call_count >= 2

    def test_init_sd_wdt_feed_failure_is_swallowed(self):
        """A raising WDT.feed() inside _init_sd does not abort the mount loop."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory

        wdt = Mock()
        wdt.feed.side_effect = RuntimeError("dead wdt")
        factory = HardwareFactory(wdt=wdt)
        factory.spi = Mock()

        with patch.object(hf_mod, "_IS_HOST", False):
            with patch("lib.hardware_factory.mount_sd", return_value=(True, Mock())):
                with patch("time.sleep_ms"):
                    result = factory._init_sd()

        assert result is True

    def test_init_sd_writes_diagnostics_to_boot_log(self, tmp_path, monkeypatch):
        """SD mount progress lines land in /boot.log (or configured path)."""
        import lib.hardware_factory as hf_mod
        from lib import boot_log
        from lib.hardware_factory import HardwareFactory

        boot_log._reset_for_test()
        log_file = tmp_path / "boot.log"
        monkeypatch.setattr(boot_log, "_path", str(log_file))
        monkeypatch.setattr(boot_log, "_max_bytes", 4096)

        factory = HardwareFactory()
        factory.spi = Mock()

        with patch.object(hf_mod, "_IS_HOST", False):
            with patch("lib.hardware_factory.mount_sd", return_value=(False, None)):
                with patch("lib.hardware_factory.is_mounted", return_value=(False, None, None)):
                    with patch("time.sleep_ms"):
                        factory._init_sd()

        boot_log._reset_for_test()
        contents = log_file.read_text()
        assert "SD mount attempt 1/3" in contents
        assert "All mount_sd attempts failed; trying is_mounted fallback" in contents

    def test_init_sd_device_exception(self):
        """Device path: exception during SD init → returns False."""
        import lib.hardware_factory as hf_mod
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.spi = Mock()

        with patch.object(hf_mod, "_IS_HOST", False):
            with patch("lib.hardware_factory.mount_sd", side_effect=OSError("hw fault")):
                with patch("time.sleep_ms"):
                    result = factory._init_sd()

        assert result is False
        assert any("SD init failed" in e for e in factory.errors)


class TestHardwareFactoryPins:
    """Tests for GPIO pin initialization."""

    def test_init_pins_creates_entries(self, monkeypatch):
        """_init_pins() creates Pin entries for output_pins config."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory._init_pins()
        assert isinstance(factory.pins, dict)
        # Should have created pins for relay_cooler, relay_humidifier, etc.
        assert len(factory.pins) > 0

    def test_init_pins_button_with_pullup(self):
        """Button pin is created with Pin.IN and PULL_UP."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory._init_pins()
        assert "button_menu" in factory.pins


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
        assert factory.get_pin("nonexistent") is None

    def test_get_all_pins_returns_copy(self, monkeypatch):
        """get_all_pins() returns a copy of pins dict."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setattr(factory, "_init_rtc", lambda: True)
        monkeypatch.setattr(factory, "_init_spi", lambda: True)
        monkeypatch.setattr(factory, "_init_sd", lambda: True)
        factory.setup()
        pins = factory.get_all_pins()
        assert isinstance(pins, dict)
        # Modifying returned dict shouldn't affect factory
        pins["test"] = "value"
        assert "test" not in factory.pins

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
        factory.errors.append("test error")
        errors = factory.get_errors()
        assert "test error" in errors

    def test_print_status(self, capsys, monkeypatch):
        """print_status() outputs status report."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setattr(factory, "_init_rtc", lambda: True)
        monkeypatch.setattr(factory, "_init_spi", lambda: True)
        monkeypatch.setattr(factory, "_init_sd", lambda: True)
        factory.setup()
        factory.print_status()
        captured = capsys.readouterr()
        assert "Status Report" in captured.out


class TestHardwareFactoryRefresh:
    """Tests for SD refresh/hot-swap."""

    def test_refresh_sd_success(self, monkeypatch):
        """refresh_sd() returns True when SD is accessible."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        mock_sd = Mock()
        mock_spi = Mock()

        with patch("lib.hardware_factory.is_mounted", return_value=(True, mock_sd, mock_spi)):
            result = factory.refresh_sd()
        assert result is True
        assert factory.sd_mounted is True

    def test_refresh_sd_failure(self, monkeypatch):
        """refresh_sd() returns False on exception."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()

        with patch("lib.hardware_factory.is_mounted", side_effect=OSError("fail")):
            result = factory.refresh_sd()
        assert result is False
        assert factory.sd_mounted is False


class TestHardwareFactoryI2C:
    """Tests for I2C bus initialization."""

    def test_init_i2c_failure_logs_error(self):
        """_init_i2c() returns False and records error when I2C raises."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()

        with patch("lib.hardware_factory.I2C", side_effect=OSError("I2C bus fail")):
            result = factory._init_i2c()
        assert result is False
        assert factory.i2c1 is None
        assert any("I2C1 init failed" in e for e in factory.errors)

    def test_init_i2c_success(self):
        """_init_i2c() returns True and stores i2c1 instance."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        mock_i2c = Mock()

        with patch("lib.hardware_factory.I2C", return_value=mock_i2c):
            result = factory._init_i2c()
        assert result is True
        assert factory.i2c1 is mock_i2c

    def test_init_rtc_without_i2c_uses_fallback(self):
        """When i2c1 is None, _init_rtc() creates RTC with sda/scl/port fallback."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.i2c1 = None  # I2C init failed

        mock_rtc_instance = Mock()
        mock_rtc_instance.ReadTime = Mock(return_value=(0, 0, 12, 3, 15, 2, 2026))

        with patch("lib.hardware_factory.ds3231.RTC", return_value=mock_rtc_instance) as mock_rtc_cls:
            result = factory._init_rtc()
        assert result is True
        # Should have been called with sda_pin, scl_pin, port (fallback path)
        call_kwargs = mock_rtc_cls.call_args
        assert "sda_pin" in str(call_kwargs) or "scl_pin" in str(call_kwargs)


class TestHardwareFactorySDDetect:
    """Tests for the SD card-detect (DET) input."""

    def test_is_card_present_true_when_no_det_pin(self):
        """No DET pin initialized → assume a card is present (poll-only fallback)."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        assert factory.is_card_present() is True

    def test_init_sd_detect_disabled_skips(self, monkeypatch):
        """sd_detect.enabled=False leaves the pin None and records no error."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setitem(factory.config, "sd_detect", {"enabled": False, "present_when_low": True, "pull": "up"})
        assert factory._init_sd_detect() is False
        assert factory._sd_detect_pin is None
        assert factory.is_card_present() is True
        assert factory.errors == []

    def test_init_sd_detect_enabled_creates_pin(self, monkeypatch):
        """sd_detect.enabled=True creates the DET input pin."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setitem(factory.config, "sd_detect", {"enabled": True, "present_when_low": True, "pull": "up"})
        assert factory._init_sd_detect() is True
        assert factory._sd_detect_pin is not None

    def test_is_card_present_active_low(self, monkeypatch):
        """present_when_low=True: LOW means a card is seated, HIGH means empty."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setitem(factory.config, "sd_detect", {"enabled": True, "present_when_low": True, "pull": "up"})
        factory._init_sd_detect()
        factory._sd_detect_pin._current_value = 0
        assert factory.is_card_present() is True
        factory._sd_detect_pin._current_value = 1
        assert factory.is_card_present() is False

    def test_is_card_present_active_high(self, monkeypatch):
        """present_when_low=False inverts the polarity."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setitem(factory.config, "sd_detect", {"enabled": True, "present_when_low": False, "pull": "down"})
        factory._init_sd_detect()
        factory._sd_detect_pin._current_value = 1
        assert factory.is_card_present() is True
        factory._sd_detect_pin._current_value = 0
        assert factory.is_card_present() is False

    def test_init_sd_detect_missing_pin_records_error(self, monkeypatch):
        """Enabled but pins.sd_detect missing records an error and stays None."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setitem(factory.config, "sd_detect", {"enabled": True, "present_when_low": True, "pull": "up"})
        pins_no_det = dict(factory.config.get("pins", {}))
        pins_no_det.pop("sd_detect", None)
        monkeypatch.setitem(factory.config, "pins", pins_no_det)
        assert factory._init_sd_detect() is False
        assert factory._sd_detect_pin is None
        assert any("sd_detect" in e for e in factory.errors)

    def test_is_card_present_tolerates_read_failure(self, monkeypatch):
        """A raising pin.value() falls back to reporting the card present."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setitem(factory.config, "sd_detect", {"enabled": True, "present_when_low": True, "pull": "up"})
        factory._init_sd_detect()
        factory._sd_detect_pin.value = Mock(side_effect=OSError("pin gone"))
        assert factory.is_card_present() is True


class TestHardwareFactoryPCA9685:
    """Tests for PCA9685 PWM driver initialization."""

    def test_init_pca9685_disabled_skips_and_returns_false(self, monkeypatch):
        """When pca9685.enabled=False, init is skipped and pca9685 stays None."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.i2c1 = Mock()
        monkeypatch.setitem(factory.config, "pca9685", {"enabled": False, "i2c_address": 0x40, "freq_hz": 1000})
        assert factory._init_pca9685() is False
        assert factory.pca9685 is None
        assert factory.errors == []

    def test_init_pca9685_no_i2c_records_error(self, monkeypatch):
        """Enabled but i2c1 missing: error logged, pca9685 stays None."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.i2c1 = None
        monkeypatch.setitem(factory.config, "pca9685", {"enabled": True, "i2c_address": 0x40, "freq_hz": 1000})
        assert factory._init_pca9685() is False
        assert factory.pca9685 is None
        assert any("I2C bus not initialized" in e for e in factory.errors)

    def test_init_pca9685_success(self, monkeypatch):
        """Enabled + I2C present: PCA9685 instance is stored and returned."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.i2c1 = Mock()
        monkeypatch.setitem(factory.config, "pca9685", {"enabled": True, "i2c_address": 0x40, "freq_hz": 1000})
        mock_pca_instance = Mock()
        with patch("lib.pca9685.PCA9685", return_value=mock_pca_instance):
            ok = factory._init_pca9685()
        assert ok is True
        assert factory.pca9685 is mock_pca_instance
        assert factory.get_pca9685() is mock_pca_instance

    def test_init_pca9685_failure_records_error(self, monkeypatch):
        """Driver constructor raising: error recorded, pca9685 stays None."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        factory.i2c1 = Mock()
        monkeypatch.setitem(factory.config, "pca9685", {"enabled": True, "i2c_address": 0x40, "freq_hz": 1000})
        with patch("lib.pca9685.PCA9685", side_effect=OSError("no chip")):
            ok = factory._init_pca9685()
        assert ok is False
        assert factory.pca9685 is None
        assert any("PCA9685 init failed" in e for e in factory.errors)

    def test_get_pca9685_default_none(self):
        """Fresh factory before setup: get_pca9685() returns None."""
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        assert factory.get_pca9685() is None
