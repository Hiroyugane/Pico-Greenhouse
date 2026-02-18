# Tests for config.py
# Covers validate_config() with valid/invalid configurations


import pytest


class TestConfigStructure:
    """Tests for DEVICE_CONFIG structure."""

    def test_config_has_required_sections(self):
        """DEVICE_CONFIG has all required top-level sections."""
        from config import DEVICE_CONFIG

        required = [
            "pins",
            "spi",
            "files",
            "dht_logger",
            "fan_1",
            "fan_2",
            "growlight",
            "Service_reminder",
            "buffer_manager",
            "event_logger",
            "output_pins",
            "display",
            "system",
        ]
        for key in required:
            assert key in DEVICE_CONFIG, f"Missing section: {key}"

    def test_config_pin_numbers_are_ints(self):
        """All pin numbers should be integers."""
        from config import DEVICE_CONFIG

        for name, value in DEVICE_CONFIG["pins"].items():
            assert isinstance(value, int), f"Pin '{name}' is not int: {type(value)}"


class TestValidateConfig:
    """Tests for validate_config() function."""

    def test_validate_success(self):
        """Valid config passes validation."""
        from config import validate_config

        assert validate_config() is True

    def test_missing_section_raises(self):
        """Missing top-level section raises ValueError."""
        import config

        original = config.DEVICE_CONFIG.get("growlight")
        del config.DEVICE_CONFIG["growlight"]
        try:
            with pytest.raises(ValueError, match="Missing config section"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"] = original

    def test_missing_subkey_raises(self):
        """Missing sub-key raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["pins"].get("dht22")
        del config.DEVICE_CONFIG["pins"]["dht22"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pins"]["dht22"] = original

    def test_negative_dht_interval_raises(self):
        """Negative dht_logger.interval_s raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["dht_logger"]["interval_s"]
        config.DEVICE_CONFIG["dht_logger"]["interval_s"] = -1
        try:
            with pytest.raises(ValueError):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["dht_logger"]["interval_s"] = original

    def test_zero_fan_timing_raises(self):
        """fan_1.on_time_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["fan_1"]["on_time_s"]
        config.DEVICE_CONFIG["fan_1"]["on_time_s"] = 0
        try:
            with pytest.raises(ValueError):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fan_1"]["on_time_s"] = original

    def test_zero_fan2_interval_raises(self):
        """fan_2.interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["fan_2"]["interval_s"]
        config.DEVICE_CONFIG["fan_2"]["interval_s"] = 0
        try:
            with pytest.raises(ValueError):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fan_2"]["interval_s"] = original

    def test_zero_service_reminder_days_raises(self):
        """Service_reminder.days_interval = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["Service_reminder"]["days_interval"]
        config.DEVICE_CONFIG["Service_reminder"]["days_interval"] = 0
        try:
            with pytest.raises(ValueError):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["Service_reminder"]["days_interval"] = original

    def test_zero_buffer_entries_raises(self):
        """buffer_manager.max_buffer_entries = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["buffer_manager"]["max_buffer_entries"]
        config.DEVICE_CONFIG["buffer_manager"]["max_buffer_entries"] = 0
        try:
            with pytest.raises(ValueError):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["buffer_manager"]["max_buffer_entries"] = original

    def test_zero_max_size_raises(self):
        """event_logger.max_size = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["max_size"]
        config.DEVICE_CONFIG["event_logger"]["max_size"] = 0
        try:
            with pytest.raises(ValueError):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["max_size"] = original

    # --- New validation tests for externalized constants ---

    def test_zero_info_flush_threshold_raises(self):
        """event_logger.info_flush_threshold = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["info_flush_threshold"]
        config.DEVICE_CONFIG["event_logger"]["info_flush_threshold"] = 0
        try:
            with pytest.raises(ValueError, match="info_flush_threshold"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["info_flush_threshold"] = original

    def test_zero_warn_flush_threshold_raises(self):
        """event_logger.warn_flush_threshold = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["warn_flush_threshold"]
        config.DEVICE_CONFIG["event_logger"]["warn_flush_threshold"] = 0
        try:
            with pytest.raises(ValueError, match="warn_flush_threshold"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["warn_flush_threshold"] = original

    def test_zero_retry_delay_raises(self):
        """dht_logger.retry_delay_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["dht_logger"]["retry_delay_s"]
        config.DEVICE_CONFIG["dht_logger"]["retry_delay_s"] = 0
        try:
            with pytest.raises(ValueError, match="retry_delay_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["dht_logger"]["retry_delay_s"] = original

    def test_zero_fan1_poll_interval_raises(self):
        """fan_1.poll_interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["fan_1"]["poll_interval_s"]
        config.DEVICE_CONFIG["fan_1"]["poll_interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="poll_interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fan_1"]["poll_interval_s"] = original

    def test_zero_fan2_poll_interval_raises(self):
        """fan_2.poll_interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["fan_2"]["poll_interval_s"]
        config.DEVICE_CONFIG["fan_2"]["poll_interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="poll_interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fan_2"]["poll_interval_s"] = original

    def test_zero_growlight_poll_interval_raises(self):
        """growlight.poll_interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["growlight"]["poll_interval_s"]
        config.DEVICE_CONFIG["growlight"]["poll_interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="poll_interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"]["poll_interval_s"] = original

    def test_negative_blink_after_days_raises(self):
        """Service_reminder.blink_after_days = -1 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["Service_reminder"]["blink_after_days"]
        config.DEVICE_CONFIG["Service_reminder"]["blink_after_days"] = -1
        try:
            with pytest.raises(ValueError, match="blink_after_days"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["Service_reminder"]["blink_after_days"] = original

    def test_zero_monitor_interval_raises(self):
        """Service_reminder.monitor_interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["Service_reminder"]["monitor_interval_s"]
        config.DEVICE_CONFIG["Service_reminder"]["monitor_interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="monitor_interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["Service_reminder"]["monitor_interval_s"] = original

    def test_zero_i2c_freq_raises(self):
        """system.i2c_freq = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["i2c_freq"]
        config.DEVICE_CONFIG["system"]["i2c_freq"] = 0
        try:
            with pytest.raises(ValueError, match="i2c_freq"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["i2c_freq"] = original

    def test_zero_sd_mount_retries_raises(self):
        """system.sd_mount_retries = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["sd_mount_retries"]
        config.DEVICE_CONFIG["system"]["sd_mount_retries"] = 0
        try:
            with pytest.raises(ValueError, match="sd_mount_retries"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["sd_mount_retries"] = original

    def test_zero_rtc_sync_interval_raises(self):
        """system.rtc_sync_interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["rtc_sync_interval_s"]
        config.DEVICE_CONFIG["system"]["rtc_sync_interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="rtc_sync_interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["rtc_sync_interval_s"] = original

    def test_zero_button_poll_ms_raises(self):
        """system.button_poll_ms = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["button_poll_ms"]
        config.DEVICE_CONFIG["system"]["button_poll_ms"] = 0
        try:
            with pytest.raises(ValueError, match="button_poll_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["button_poll_ms"] = original

    def test_invalid_log_level_raises(self):
        """event_logger.log_level with invalid value raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["log_level"]
        config.DEVICE_CONFIG["event_logger"]["log_level"] = "TRACE"
        try:
            with pytest.raises(ValueError, match="log_level"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["log_level"] = original

    def test_debug_to_sd_non_bool_raises(self):
        """event_logger.debug_to_sd with non-bool raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["debug_to_sd"]
        config.DEVICE_CONFIG["event_logger"]["debug_to_sd"] = "yes"
        try:
            with pytest.raises(ValueError, match="debug_to_sd"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["debug_to_sd"] = original

    def test_zero_debug_flush_threshold_raises(self):
        """event_logger.debug_flush_threshold = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["debug_flush_threshold"]
        config.DEVICE_CONFIG["event_logger"]["debug_flush_threshold"] = 0
        try:
            with pytest.raises(ValueError, match="debug_flush_threshold"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["debug_flush_threshold"] = original

    def test_valid_debug_log_level(self):
        """event_logger.log_level='DEBUG' passes validation."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["log_level"]
        config.DEVICE_CONFIG["event_logger"]["log_level"] = "DEBUG"
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["event_logger"]["log_level"] = original
