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
            "sht31",
            "temp_humidity_logger",
            "fan_1",
            "fan_2",
            "growlight",
            "heater",
            "co2_logger",
            "soil_logger",
            "Service_reminder",
            "buffer_manager",
            "event_logger",
            "output_pins",
            "display",
            "system",
            "updater",
            "updater_feedback",
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

        original = config.DEVICE_CONFIG["pins"].get("buzzer")
        del config.DEVICE_CONFIG["pins"]["buzzer"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pins"]["buzzer"] = original

    def test_reserved_relays_parked_high(self):
        """Reserved relay GPIOs are parked HIGH (off) so they don't float."""
        from config import DEVICE_CONFIG

        for key in (
            "relay_reserved_1",
            "relay_reserved_2",
            "relay_reserved_3",
            "relay_reserved_4",
        ):
            assert key in DEVICE_CONFIG["output_pins"], f"{key} missing from output_pins"
            assert DEVICE_CONFIG["output_pins"][key] is True, (
                f"{key} must be True (HIGH = relay off) to keep input from floating"
            )

    def test_missing_reserved_relay_output_raises(self):
        """Removing a reserved relay output_pins entry raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["output_pins"].pop("relay_reserved_1")
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["output_pins"]["relay_reserved_1"] = original

    def test_negative_th_interval_raises(self):
        """Negative temp_humidity_logger.interval_s raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["temp_humidity_logger"]["interval_s"]
        config.DEVICE_CONFIG["temp_humidity_logger"]["interval_s"] = -1
        try:
            with pytest.raises(ValueError):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["temp_humidity_logger"]["interval_s"] = original

    def test_invalid_sht31_address_raises(self):
        """sht31.i2c_address outside {0x44, 0x45} raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["sht31"]["i2c_address"]
        config.DEVICE_CONFIG["sht31"]["i2c_address"] = 0x50
        try:
            with pytest.raises(ValueError, match="sht31.i2c_address"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["sht31"]["i2c_address"] = original

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

    def test_updater_relative_path_raises(self):
        """updater.update_dir must be an absolute path."""
        import config

        original = config.DEVICE_CONFIG["updater"]["update_dir"]
        config.DEVICE_CONFIG["updater"]["update_dir"] = "sd/update"
        try:
            with pytest.raises(ValueError, match="updater.update_dir"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["update_dir"] = original

    def test_updater_zero_retries_raises(self):
        """updater.max_retries < 1 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["updater"]["max_retries"]
        config.DEVICE_CONFIG["updater"]["max_retries"] = 0
        try:
            with pytest.raises(ValueError, match="updater.max_retries"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["max_retries"] = original

    def test_updater_empty_allowed_paths_raises(self):
        """updater.allowed_paths must be a non-empty list."""
        import config

        original = config.DEVICE_CONFIG["updater"]["allowed_paths"]
        config.DEVICE_CONFIG["updater"]["allowed_paths"] = []
        try:
            with pytest.raises(ValueError, match="updater.allowed_paths"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["allowed_paths"] = original

    def test_updater_feedback_non_bool_enabled_raises(self):
        """updater_feedback.enabled must be a bool."""
        import config

        original = config.DEVICE_CONFIG["updater_feedback"]["enabled"]
        config.DEVICE_CONFIG["updater_feedback"]["enabled"] = "yes"
        try:
            with pytest.raises(ValueError, match="updater_feedback.enabled"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater_feedback"]["enabled"] = original

    def test_updater_feedback_zero_tick_freq_raises(self):
        """updater_feedback.tick_freq_hz <= 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["updater_feedback"]["tick_freq_hz"]
        config.DEVICE_CONFIG["updater_feedback"]["tick_freq_hz"] = 0
        try:
            with pytest.raises(ValueError, match="updater_feedback.tick_freq_hz"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater_feedback"]["tick_freq_hz"] = original

    def test_updater_feedback_empty_success_pattern_raises(self):
        """updater_feedback.success_pattern must be non-empty."""
        import config

        original = config.DEVICE_CONFIG["updater_feedback"]["success_pattern"]
        config.DEVICE_CONFIG["updater_feedback"]["success_pattern"] = []
        try:
            with pytest.raises(ValueError, match="updater_feedback.success_pattern"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater_feedback"]["success_pattern"] = original

    def test_updater_feedback_malformed_fail_pattern_raises(self):
        """updater_feedback.fail_pattern entries must be (freq, dur, pause) triples."""
        import config

        original = config.DEVICE_CONFIG["updater_feedback"]["fail_pattern"]
        config.DEVICE_CONFIG["updater_feedback"]["fail_pattern"] = [(400, 200)]
        try:
            with pytest.raises(ValueError, match="updater_feedback.fail_pattern"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater_feedback"]["fail_pattern"] = original

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
        """temp_humidity_logger.retry_delay_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["temp_humidity_logger"]["retry_delay_s"]
        config.DEVICE_CONFIG["temp_humidity_logger"]["retry_delay_s"] = 0
        try:
            with pytest.raises(ValueError, match="retry_delay_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["temp_humidity_logger"]["retry_delay_s"] = original

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

    def test_heater_zero_poll_interval_raises(self):
        """heater.poll_interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["heater"]["poll_interval_s"]
        config.DEVICE_CONFIG["heater"]["poll_interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="heater.poll_interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["heater"]["poll_interval_s"] = original

    def test_heater_negative_hysteresis_raises(self):
        """heater.temp_hysteresis < 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["heater"]["temp_hysteresis"]
        config.DEVICE_CONFIG["heater"]["temp_hysteresis"] = -0.5
        try:
            with pytest.raises(ValueError, match="heater.temp_hysteresis"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["heater"]["temp_hysteresis"] = original

    def test_heater_day_below_night_raises(self):
        """heater.day_min_temp < night_min_temp raises ValueError."""
        import config

        orig_day = config.DEVICE_CONFIG["heater"]["day_min_temp"]
        orig_night = config.DEVICE_CONFIG["heater"]["night_min_temp"]
        config.DEVICE_CONFIG["heater"]["day_min_temp"] = 10.0
        config.DEVICE_CONFIG["heater"]["night_min_temp"] = 15.0
        try:
            with pytest.raises(ValueError, match="day_min_temp"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["heater"]["day_min_temp"] = orig_day
            config.DEVICE_CONFIG["heater"]["night_min_temp"] = orig_night

    def test_status_leds_walk_order_default_valid(self):
        """Default DEVICE_CONFIG (with the shipped walk_order) validates."""
        import config

        assert config.validate_config() is True
        assert config.DEVICE_CONFIG["status_leds"]["walk_order"] == [
            "activity",
            "sd",
            "reminder",
            "warning",
            "error",
        ]

    def test_status_leds_walk_order_empty_raises(self):
        """status_leds.walk_order = [] raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["status_leds"]["walk_order"]
        config.DEVICE_CONFIG["status_leds"]["walk_order"] = []
        try:
            with pytest.raises(ValueError, match="walk_order"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["status_leds"]["walk_order"] = original

    def test_status_leds_walk_order_unknown_role_raises(self):
        """status_leds.walk_order with an unknown role raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["status_leds"]["walk_order"]
        config.DEVICE_CONFIG["status_leds"]["walk_order"] = ["activity", "purple"]
        try:
            with pytest.raises(ValueError, match="walk_order"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["status_leds"]["walk_order"] = original

    def test_status_leds_walk_order_duplicate_raises(self):
        """status_leds.walk_order with duplicate roles raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["status_leds"]["walk_order"]
        config.DEVICE_CONFIG["status_leds"]["walk_order"] = ["activity", "activity"]
        try:
            with pytest.raises(ValueError, match="walk_order"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["status_leds"]["walk_order"] = original

    def test_heater_missing_key_raises(self):
        """Missing heater.day_min_temp raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["heater"]["day_min_temp"]
        del config.DEVICE_CONFIG["heater"]["day_min_temp"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["heater"]["day_min_temp"] = original

    def test_co2_logger_zero_interval_raises(self):
        """co2_logger.interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["co2_logger"]["interval_s"]
        config.DEVICE_CONFIG["co2_logger"]["interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="co2_logger.interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["co2_logger"]["interval_s"] = original

    def test_co2_logger_hysteresis_inverted_raises(self):
        """co2_logger.override_ppm_on <= override_ppm_off raises ValueError."""
        import config

        orig_on = config.DEVICE_CONFIG["co2_logger"]["override_ppm_on"]
        orig_off = config.DEVICE_CONFIG["co2_logger"]["override_ppm_off"]
        config.DEVICE_CONFIG["co2_logger"]["override_ppm_on"] = 500
        config.DEVICE_CONFIG["co2_logger"]["override_ppm_off"] = 600
        try:
            with pytest.raises(ValueError, match="override_ppm_on"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["co2_logger"]["override_ppm_on"] = orig_on
            config.DEVICE_CONFIG["co2_logger"]["override_ppm_off"] = orig_off

    def test_co2_logger_unknown_override_fan_raises(self):
        """co2_logger.override_fan not in {fan_1, fan_2} raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["co2_logger"]["override_fan"]
        config.DEVICE_CONFIG["co2_logger"]["override_fan"] = "fan_3"
        try:
            with pytest.raises(ValueError, match="override_fan"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["co2_logger"]["override_fan"] = original

    def test_co2_logger_missing_key_raises(self):
        """Missing co2_logger.interval_s raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["co2_logger"]["interval_s"]
        del config.DEVICE_CONFIG["co2_logger"]["interval_s"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["co2_logger"]["interval_s"] = original

    def test_soil_logger_zero_interval_raises(self):
        """soil_logger.interval_s = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["soil_logger"]["interval_s"]
        config.DEVICE_CONFIG["soil_logger"]["interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="soil_logger.interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["soil_logger"]["interval_s"] = original

    def test_soil_logger_dry_le_wet_raises(self):
        """soil_logger.adc_dry_raw <= adc_wet_raw raises ValueError."""
        import config

        orig_dry = config.DEVICE_CONFIG["soil_logger"]["adc_dry_raw"]
        orig_wet = config.DEVICE_CONFIG["soil_logger"]["adc_wet_raw"]
        config.DEVICE_CONFIG["soil_logger"]["adc_dry_raw"] = 300
        config.DEVICE_CONFIG["soil_logger"]["adc_wet_raw"] = 500
        try:
            with pytest.raises(ValueError, match="adc_dry_raw must be > adc_wet_raw"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["soil_logger"]["adc_dry_raw"] = orig_dry
            config.DEVICE_CONFIG["soil_logger"]["adc_wet_raw"] = orig_wet

    def test_soil_logger_dry_out_of_range_raises(self):
        """soil_logger.adc_dry_raw outside 0-1023 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["soil_logger"]["adc_dry_raw"]
        config.DEVICE_CONFIG["soil_logger"]["adc_dry_raw"] = 2000
        try:
            with pytest.raises(ValueError, match="adc_dry_raw"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["soil_logger"]["adc_dry_raw"] = original

    def test_soil_logger_warn_pct_out_of_range_raises(self):
        """soil_logger.warn_pct_below outside 0-100 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["soil_logger"]["warn_pct_below"]
        config.DEVICE_CONFIG["soil_logger"]["warn_pct_below"] = 150
        try:
            with pytest.raises(ValueError, match="warn_pct_below"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["soil_logger"]["warn_pct_below"] = original

    def test_soil_logger_missing_key_raises(self):
        """Missing soil_logger.interval_s raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["soil_logger"]["interval_s"]
        del config.DEVICE_CONFIG["soil_logger"]["interval_s"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["soil_logger"]["interval_s"] = original

    def test_growlight_dac_address_out_of_range_raises(self):
        """growlight.dac_i2c_address outside 7-bit I2C range raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["growlight"]["dac_i2c_address"]
        config.DEVICE_CONFIG["growlight"]["dac_i2c_address"] = 0x80
        try:
            with pytest.raises(ValueError, match="dac_i2c_address"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"]["dac_i2c_address"] = original

    def test_growlight_dac_address_non_int_raises(self):
        """growlight.dac_i2c_address non-int raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["growlight"]["dac_i2c_address"]
        config.DEVICE_CONFIG["growlight"]["dac_i2c_address"] = "0x60"
        try:
            with pytest.raises(ValueError, match="dac_i2c_address"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"]["dac_i2c_address"] = original

    def test_growlight_max_level_out_of_range_raises(self):
        """growlight.max_level_pct > 100 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["growlight"]["max_level_pct"]
        config.DEVICE_CONFIG["growlight"]["max_level_pct"] = 150
        try:
            with pytest.raises(ValueError, match="max_level_pct"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"]["max_level_pct"] = original

    def test_growlight_default_above_max_raises(self):
        """growlight.default_level_pct > max_level_pct raises ValueError."""
        import config

        orig_default = config.DEVICE_CONFIG["growlight"]["default_level_pct"]
        orig_max = config.DEVICE_CONFIG["growlight"]["max_level_pct"]
        config.DEVICE_CONFIG["growlight"]["max_level_pct"] = 50
        config.DEVICE_CONFIG["growlight"]["default_level_pct"] = 80
        try:
            with pytest.raises(ValueError, match="default_level_pct"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"]["default_level_pct"] = orig_default
            config.DEVICE_CONFIG["growlight"]["max_level_pct"] = orig_max

    def test_growlight_min_above_max_raises(self):
        """growlight.min_level_pct > max_level_pct raises ValueError."""
        import config

        orig_min = config.DEVICE_CONFIG["growlight"]["min_level_pct"]
        config.DEVICE_CONFIG["growlight"]["min_level_pct"] = 100
        try:
            with pytest.raises(ValueError, match="min_level_pct"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"]["min_level_pct"] = orig_min

    def test_growlight_mode_invalid_raises(self):
        """growlight.mode outside {'dimmed','relay_only'} raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["growlight"]["mode"]
        config.DEVICE_CONFIG["growlight"]["mode"] = "bogus"
        try:
            with pytest.raises(ValueError, match="growlight.mode"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"]["mode"] = original

    def test_growlight_mode_dimmed_valid(self):
        """growlight.mode='dimmed' passes validation."""
        import config

        original = config.DEVICE_CONFIG["growlight"]["mode"]
        config.DEVICE_CONFIG["growlight"]["mode"] = "dimmed"
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["growlight"]["mode"] = original

    def test_growlight_negative_ramp_raises(self):
        """growlight.ramp_duration_s < 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["growlight"]["ramp_duration_s"]
        config.DEVICE_CONFIG["growlight"]["ramp_duration_s"] = -1
        try:
            with pytest.raises(ValueError, match="ramp_duration_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["growlight"]["ramp_duration_s"] = original

    def test_display_negative_startup_banner_raises(self):
        """display.startup_banner_s < 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["display"]["startup_banner_s"]
        config.DEVICE_CONFIG["display"]["startup_banner_s"] = -1
        try:
            with pytest.raises(ValueError, match="startup_banner_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["display"]["startup_banner_s"] = original

    def test_display_non_numeric_vram_delay_raises(self):
        """display.vram_clear_delay_s with non-numeric value raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["display"]["vram_clear_delay_s"]
        config.DEVICE_CONFIG["display"]["vram_clear_delay_s"] = "fast"
        try:
            with pytest.raises(ValueError, match="vram_clear_delay_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["display"]["vram_clear_delay_s"] = original

    def test_display_zero_delays_valid(self):
        """display warmup delays of 0 are accepted (used in tests)."""
        import config

        originals = {k: config.DEVICE_CONFIG["display"][k] for k in
                     ("startup_banner_s", "vram_clear_delay_s", "invert_delay_s")}
        for k in originals:
            config.DEVICE_CONFIG["display"][k] = 0
        try:
            assert config.validate_config() is True
        finally:
            for k, v in originals.items():
                config.DEVICE_CONFIG["display"][k] = v

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

    def test_negative_button_debounce_raises(self):
        """system.button_debounce_ms < 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["button_debounce_ms"]
        config.DEVICE_CONFIG["system"]["button_debounce_ms"] = -1
        try:
            with pytest.raises(ValueError, match="button_debounce_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["button_debounce_ms"] = original

    def test_zero_long_press_ms_raises(self):
        """system.long_press_ms = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["long_press_ms"]
        config.DEVICE_CONFIG["system"]["long_press_ms"] = 0
        try:
            with pytest.raises(ValueError, match="long_press_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["long_press_ms"] = original

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

    def test_watchdog_timeout_too_small_raises(self):
        """system.watchdog_timeout_ms < 1000 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"]
        config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"] = 500
        try:
            with pytest.raises(ValueError, match="watchdog_timeout_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"] = original

    def test_watchdog_timeout_exceeds_hw_limit_raises(self):
        """system.watchdog_timeout_ms > 8388 raises ValueError (RP2040 limit)."""
        import config

        original = config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"]
        config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"] = 9000
        try:
            with pytest.raises(ValueError, match="watchdog_timeout_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"] = original

    def test_watchdog_feed_interval_zero_raises(self):
        """system.watchdog_feed_interval_ms = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"]
        config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"] = 0
        try:
            with pytest.raises(ValueError, match="watchdog_feed_interval_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"] = original

    def test_watchdog_feed_interval_exceeds_timeout_raises(self):
        """system.watchdog_feed_interval_ms >= watchdog_timeout_ms raises ValueError."""
        import config

        orig_feed = config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"]
        orig_timeout = config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"]
        config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"] = 5000
        config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"] = 5000
        try:
            with pytest.raises(ValueError, match="watchdog_feed_interval_ms must be < watchdog_timeout_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"] = orig_feed
            config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"] = orig_timeout

    def test_watchdog_valid_config(self):
        """Valid watchdog config passes validation."""
        import config

        orig_feed = config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"]
        orig_timeout = config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"]
        config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"] = 8000
        config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"] = 2000
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["system"]["watchdog_feed_interval_ms"] = orig_feed
            config.DEVICE_CONFIG["system"]["watchdog_timeout_ms"] = orig_timeout

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

    def test_debug_enabled_non_bool_raises(self):
        """event_logger.debug_enabled with non-bool raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["debug_enabled"]
        config.DEVICE_CONFIG["event_logger"]["debug_enabled"] = "yes"
        try:
            with pytest.raises(ValueError, match="debug_enabled"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["debug_enabled"] = original

    def test_debug_to_file_non_bool_raises(self):
        """event_logger.debug_to_file with non-bool raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["debug_to_file"]
        config.DEVICE_CONFIG["event_logger"]["debug_to_file"] = "yes"
        try:
            with pytest.raises(ValueError, match="debug_to_file"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["debug_to_file"] = original

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

    def test_debug_enabled_is_bool(self):
        """event_logger.debug_enabled is a boolean (True or False)."""
        from config import DEVICE_CONFIG

        assert isinstance(DEVICE_CONFIG["event_logger"]["debug_enabled"], bool)

    def test_debug_to_file_is_bool(self):
        """event_logger.debug_to_file is a boolean (True or False)."""
        from config import DEVICE_CONFIG

        assert isinstance(DEVICE_CONFIG["event_logger"]["debug_to_file"], bool)

    def test_missing_debug_enabled_raises(self):
        """Missing event_logger.debug_enabled raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["debug_enabled"]
        del config.DEVICE_CONFIG["event_logger"]["debug_enabled"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["debug_enabled"] = original

    def test_missing_debug_to_file_raises(self):
        """Missing event_logger.debug_to_file raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["debug_to_file"]
        del config.DEVICE_CONFIG["event_logger"]["debug_to_file"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["debug_to_file"] = original
