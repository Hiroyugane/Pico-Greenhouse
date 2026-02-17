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
