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
            "sd_detect",
            "files",
            "paths",
            "sht31",
            "temp_humidity_logger",
            "fans",
            "growlight",
            "heater",
            "pca9685",
            "co2_logger",
            "soil_logger",
            "Service_reminder",
            "buffer_manager",
            "event_logger",
            "diagnostics",
            "memory",
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

    def test_paths_section_present_and_under_sd(self):
        """All paths.* live under the SPI mount point."""
        from config import DEVICE_CONFIG

        sd_mount = DEVICE_CONFIG["spi"]["mount_point"]
        for key in (
            "sensor_root",
            "logs_dir",
            "ota_pending_dir",
            "ota_applied_dir",
            "diagnostics_dir",
        ):
            value = DEVICE_CONFIG["paths"][key]
            assert value.startswith(sd_mount), f"paths.{key}={value!r} not under {sd_mount}"

    def test_paths_relative_value_raises(self):
        """A non-absolute paths.* entry is rejected."""
        import config

        original = config.DEVICE_CONFIG["paths"]["sensor_root"]
        config.DEVICE_CONFIG["paths"]["sensor_root"] = "sensors"
        try:
            with pytest.raises(ValueError, match="paths.sensor_root"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["paths"]["sensor_root"] = original

    def test_paths_outside_sd_mount_raises(self):
        """A paths.* entry outside the SPI mount point is rejected."""
        import config

        original = config.DEVICE_CONFIG["paths"]["logs_dir"]
        config.DEVICE_CONFIG["paths"]["logs_dir"] = "/local/logs"
        try:
            with pytest.raises(ValueError, match="paths.logs_dir"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["paths"]["logs_dir"] = original

    def test_require_sd_startup_defaults_true(self):
        """Default config requires SD at startup so failures fail hard."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["system"]["require_sd_startup"] is True

    def test_require_sd_startup_non_bool_raises(self):
        """system.require_sd_startup must be a bool."""
        import config

        original = config.DEVICE_CONFIG["system"]["require_sd_startup"]
        config.DEVICE_CONFIG["system"]["require_sd_startup"] = "yes"
        try:
            with pytest.raises(ValueError, match="system.require_sd_startup"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["require_sd_startup"] = original

    def test_sd_fail_reset_s_zero_raises(self):
        """system.sd_fail_reset_s must be >= 1."""
        import config

        original = config.DEVICE_CONFIG["system"]["sd_fail_reset_s"]
        config.DEVICE_CONFIG["system"]["sd_fail_reset_s"] = 0
        try:
            with pytest.raises(ValueError, match="system.sd_fail_reset_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["sd_fail_reset_s"] = original

    def test_sd_fail_reset_s_missing_raises(self):
        """Removing system.sd_fail_reset_s raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"].pop("sd_fail_reset_s")
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["sd_fail_reset_s"] = original

    def test_boot_log_path_relative_raises(self):
        """system.boot_log_path must be absolute."""
        import config

        original = config.DEVICE_CONFIG["system"]["boot_log_path"]
        config.DEVICE_CONFIG["system"]["boot_log_path"] = "boot.log"
        try:
            with pytest.raises(ValueError, match="system.boot_log_path"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["boot_log_path"] = original

    def test_boot_log_max_kb_zero_raises(self):
        """system.boot_log_max_kb must be >= 1."""
        import config

        original = config.DEVICE_CONFIG["system"]["boot_log_max_kb"]
        config.DEVICE_CONFIG["system"]["boot_log_max_kb"] = 0
        try:
            with pytest.raises(ValueError, match="system.boot_log_max_kb"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["boot_log_max_kb"] = original

    def test_boot_log_keys_present_by_default(self):
        """Default config includes boot_log_path and boot_log_max_kb."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["system"]["boot_log_path"] == "/boot.log"
        assert DEVICE_CONFIG["system"]["boot_log_max_kb"] >= 1

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

    def test_updater_verify_max_retries_negative_raises(self):
        """updater.verify_max_retries < 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["updater"]["verify_max_retries"]
        config.DEVICE_CONFIG["updater"]["verify_max_retries"] = -1
        try:
            with pytest.raises(ValueError, match="updater.verify_max_retries"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["verify_max_retries"] = original

    def test_updater_verify_retry_delay_ms_negative_raises(self):
        """updater.verify_retry_delay_ms < 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["updater"]["verify_retry_delay_ms"]
        config.DEVICE_CONFIG["updater"]["verify_retry_delay_ms"] = -10
        try:
            with pytest.raises(ValueError, match="updater.verify_retry_delay_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["verify_retry_delay_ms"] = original

    def test_updater_verify_max_retries_zero_allowed(self):
        """Zero verify_max_retries disables retries (no error)."""
        import config

        original = config.DEVICE_CONFIG["updater"]["verify_max_retries"]
        config.DEVICE_CONFIG["updater"]["verify_max_retries"] = 0
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["updater"]["verify_max_retries"] = original

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

    def test_updater_legacy_update_dirs_non_list_raises(self):
        """updater.legacy_update_dirs must be a list."""
        import config

        original = config.DEVICE_CONFIG["updater"]["legacy_update_dirs"]
        config.DEVICE_CONFIG["updater"]["legacy_update_dirs"] = "/sd/update"
        try:
            with pytest.raises(ValueError, match="updater.legacy_update_dirs"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["legacy_update_dirs"] = original

    def test_updater_legacy_update_dirs_relative_entry_raises(self):
        """updater.legacy_update_dirs entries must be absolute paths."""
        import config

        original = config.DEVICE_CONFIG["updater"]["legacy_update_dirs"]
        config.DEVICE_CONFIG["updater"]["legacy_update_dirs"] = ["sd/update"]
        try:
            with pytest.raises(ValueError, match="updater.legacy_update_dirs"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["legacy_update_dirs"] = original

    def test_updater_legacy_update_dirs_empty_list_allowed(self):
        """Empty legacy_update_dirs list disables the fallback (no error)."""
        import config

        original = config.DEVICE_CONFIG["updater"]["legacy_update_dirs"]
        config.DEVICE_CONFIG["updater"]["legacy_update_dirs"] = []
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["updater"]["legacy_update_dirs"] = original

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

    def test_updater_feedback_noop_pattern_present_and_validated(self):
        """updater_feedback.noop_pattern must exist and be a non-empty list of triples."""
        import config

        assert "noop_pattern" in config.DEVICE_CONFIG["updater_feedback"]
        original = config.DEVICE_CONFIG["updater_feedback"]["noop_pattern"]
        config.DEVICE_CONFIG["updater_feedback"]["noop_pattern"] = []
        try:
            with pytest.raises(ValueError, match="updater_feedback.noop_pattern"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater_feedback"]["noop_pattern"] = original

    def test_display_debug_section_present(self):
        """display.debug must exist with all expected tunables."""
        from config import DEVICE_CONFIG

        dbg = DEVICE_CONFIG["display"]["debug"]
        for key in (
            "enabled",
            "confirm_timeout_s",
            "status_show_ms",
            "feedback_blink_ms",
            "test_heater_s",
            "test_growlight_pulse_s",
            "test_growlight_dim_levels_pct",
            "test_growlight_dim_step_s",
            "test_relay_pulse_s",
        ):
            assert key in dbg, f"display.debug missing {key}"

    def test_display_debug_missing_key_raises(self):
        """Removing a display.debug key raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["display"]["debug"].pop("test_heater_s")
        try:
            with pytest.raises(ValueError, match="display.debug.test_heater_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["display"]["debug"]["test_heater_s"] = original

    def test_display_debug_non_bool_enabled_raises(self):
        """display.debug.enabled must be a bool."""
        import config

        original = config.DEVICE_CONFIG["display"]["debug"]["enabled"]
        config.DEVICE_CONFIG["display"]["debug"]["enabled"] = "yes"
        try:
            with pytest.raises(ValueError, match="display.debug.enabled"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["display"]["debug"]["enabled"] = original

    def test_display_debug_zero_heater_duration_raises(self):
        """display.debug.test_heater_s must be > 0."""
        import config

        original = config.DEVICE_CONFIG["display"]["debug"]["test_heater_s"]
        config.DEVICE_CONFIG["display"]["debug"]["test_heater_s"] = 0
        try:
            with pytest.raises(ValueError, match="display.debug.test_heater_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["display"]["debug"]["test_heater_s"] = original

    def test_display_debug_invalid_dim_level_raises(self):
        """display.debug.test_growlight_dim_levels_pct entries must be 0-100."""
        import config

        original = config.DEVICE_CONFIG["display"]["debug"]["test_growlight_dim_levels_pct"]
        config.DEVICE_CONFIG["display"]["debug"]["test_growlight_dim_levels_pct"] = [0, 110]
        try:
            with pytest.raises(ValueError, match="display.debug.test_growlight_dim_levels_pct"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["display"]["debug"]["test_growlight_dim_levels_pct"] = original

    def test_display_debug_feedback_blink_empty_raises(self):
        """display.debug.feedback_blink_ms must be a non-empty list."""
        import config

        original = config.DEVICE_CONFIG["display"]["debug"]["feedback_blink_ms"]
        config.DEVICE_CONFIG["display"]["debug"]["feedback_blink_ms"] = []
        try:
            with pytest.raises(ValueError, match="display.debug.feedback_blink_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["display"]["debug"]["feedback_blink_ms"] = original

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

    def test_sd_fault_blink_ms_default_valid(self):
        """status_leds.sd_fault_blink_ms ships as a positive int and validates."""
        from config import DEVICE_CONFIG, validate_config

        assert DEVICE_CONFIG["status_leds"]["sd_fault_blink_ms"] == 500
        assert validate_config() is True

    def test_sd_fault_blink_ms_zero_raises(self):
        """status_leds.sd_fault_blink_ms <= 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["status_leds"]["sd_fault_blink_ms"]
        config.DEVICE_CONFIG["status_leds"]["sd_fault_blink_ms"] = 0
        try:
            with pytest.raises(ValueError, match="sd_fault_blink_ms"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["status_leds"]["sd_fault_blink_ms"] = original

    def test_sd_fault_blink_ms_missing_raises(self):
        """Removing status_leds.sd_fault_blink_ms raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["status_leds"].pop("sd_fault_blink_ms")
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["status_leds"]["sd_fault_blink_ms"] = original

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

    def test_pca9685_enabled_default_true(self):
        """pca9685 ships enabled now that the chip is on the next-rev PCB."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["pca9685"]["enabled"] is True

    def test_pca9685_enabled_non_bool_raises(self):
        """pca9685.enabled must be a bool."""
        import config

        original = config.DEVICE_CONFIG["pca9685"]["enabled"]
        config.DEVICE_CONFIG["pca9685"]["enabled"] = "yes"
        try:
            with pytest.raises(ValueError, match="pca9685.enabled"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pca9685"]["enabled"] = original

    def test_pca9685_address_out_of_range_raises(self):
        """pca9685.i2c_address outside 7-bit range raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["pca9685"]["i2c_address"]
        config.DEVICE_CONFIG["pca9685"]["i2c_address"] = 0x80
        try:
            with pytest.raises(ValueError, match="pca9685.i2c_address"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pca9685"]["i2c_address"] = original

    def test_pca9685_freq_too_low_raises(self):
        """pca9685.freq_hz below 24 Hz raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["pca9685"]["freq_hz"]
        config.DEVICE_CONFIG["pca9685"]["freq_hz"] = 10
        try:
            with pytest.raises(ValueError, match="pca9685.freq_hz"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pca9685"]["freq_hz"] = original

    def test_pca9685_freq_too_high_raises(self):
        """pca9685.freq_hz above 1526 Hz raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["pca9685"]["freq_hz"]
        config.DEVICE_CONFIG["pca9685"]["freq_hz"] = 2000
        try:
            with pytest.raises(ValueError, match="pca9685.freq_hz"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pca9685"]["freq_hz"] = original

    def test_pca9685_missing_key_raises(self):
        """Missing pca9685.enabled raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["pca9685"].pop("enabled")
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pca9685"]["enabled"] = original

    def test_pca9685_invert_default_true(self):
        """pca9685.invert ships True — the next-rev fan MOSFET stage inverts."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["pca9685"]["invert"] is True

    def test_pca9685_invert_non_bool_raises(self):
        """pca9685.invert must be a bool."""
        import config

        original = config.DEVICE_CONFIG["pca9685"]["invert"]
        config.DEVICE_CONFIG["pca9685"]["invert"] = 1
        try:
            with pytest.raises(ValueError, match="pca9685.invert"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pca9685"]["invert"] = original

    # --- fans dict validation ---

    def test_fans_default_roster(self):
        """Default config has the five planned fan roles."""
        from config import DEVICE_CONFIG

        for role in (
            "exhaust",
            "growroom_walls",
            "growroom_center",
            "heater_distribution",
            "case",
        ):
            assert role in DEVICE_CONFIG["fans"]

    def test_fans_default_enabled_set(self):
        """All five fan roles run from PCA9685 channels on the next-rev board."""
        from config import DEVICE_CONFIG

        enabled = {r for r, c in DEVICE_CONFIG["fans"].items() if c["enabled"]}
        assert enabled == {
            "exhaust",
            "growroom_walls",
            "growroom_center",
            "heater_distribution",
            "case",
        }

    def test_fans_all_pca9685_on_distinct_channels(self):
        """Every fan drives a distinct PCA9685 channel ch0–ch4 (relays freed)."""
        from config import DEVICE_CONFIG

        chans = []
        for role, cfg in DEVICE_CONFIG["fans"].items():
            assert cfg["output"] == "pca9685", f"{role} not on pca9685"
            chans.append(cfg["pca9685_ch"])
        assert sorted(chans) == [0, 1, 2, 3, 4]

    def test_fans_empty_dict_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]
        config.DEVICE_CONFIG["fans"] = {}
        try:
            with pytest.raises(ValueError, match="fans must be a non-empty dict"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"] = original

    def test_fans_missing_section_raises(self):
        import config

        original = config.DEVICE_CONFIG.pop("fans")
        try:
            with pytest.raises(ValueError, match="fans"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"] = original

    def test_fans_missing_mode_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["exhaust"].pop("mode")
        try:
            with pytest.raises(ValueError, match="fans.exhaust.mode"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["exhaust"]["mode"] = original

    def test_fans_bad_mode_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["exhaust"]["mode"]
        config.DEVICE_CONFIG["fans"]["exhaust"]["mode"] = "wishful"
        try:
            with pytest.raises(ValueError, match="fans.exhaust.mode"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["exhaust"]["mode"] = original

    def test_fans_bad_output_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["exhaust"]["output"]
        config.DEVICE_CONFIG["fans"]["exhaust"]["output"] = "magic"
        try:
            with pytest.raises(ValueError, match="fans.exhaust.output"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["exhaust"]["output"] = original

    def test_fans_enabled_non_bool_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["exhaust"]["enabled"]
        config.DEVICE_CONFIG["fans"]["exhaust"]["enabled"] = "yes"
        try:
            with pytest.raises(ValueError, match="fans.exhaust.enabled"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["exhaust"]["enabled"] = original

    def test_fans_relay_pin_key_unknown_raises(self):
        """A relay-output fan referencing an unknown pin raises ValueError."""
        import config

        # The roster is all-PCA9685 now; flip one fan to relay output to
        # exercise the relay_pin_key validation branch.
        fans = config.DEVICE_CONFIG["fans"]
        orig_exhaust = dict(fans["exhaust"])
        fans["exhaust"].pop("pca9685_ch", None)
        fans["exhaust"]["output"] = "relay"
        fans["exhaust"]["relay_pin_key"] = "no_such_pin"
        try:
            with pytest.raises(ValueError, match="relay_pin_key"):
                config.validate_config()
        finally:
            fans["exhaust"] = orig_exhaust

    def test_fans_relay_pin_key_collision_raises(self):
        """Two relay-backed fans cannot share the same pin."""
        import config

        fans = config.DEVICE_CONFIG["fans"]
        orig_exhaust = dict(fans["exhaust"])
        orig_walls = dict(fans["growroom_walls"])
        for role in ("exhaust", "growroom_walls"):
            fans[role].pop("pca9685_ch", None)
            fans[role]["output"] = "relay"
            fans[role]["relay_pin_key"] = "relay_fan_1"
        try:
            with pytest.raises(ValueError, match="is used by another fan"):
                config.validate_config()
        finally:
            fans["exhaust"] = orig_exhaust
            fans["growroom_walls"] = orig_walls

    def test_fans_pca9685_channel_out_of_range_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"]["pca9685_ch"]
        config.DEVICE_CONFIG["fans"]["case"]["pca9685_ch"] = 16
        try:
            with pytest.raises(ValueError, match="pca9685_ch"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["pca9685_ch"] = original

    def test_fans_pca9685_channel_collision_raises(self):
        """Two pca9685-backed fans cannot share the same channel."""
        import config

        original = config.DEVICE_CONFIG["fans"]["case"]["pca9685_ch"]
        config.DEVICE_CONFIG["fans"]["case"]["pca9685_ch"] = config.DEVICE_CONFIG["fans"]["growroom_center"][
            "pca9685_ch"
        ]
        try:
            with pytest.raises(ValueError, match="is used by another fan"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["pca9685_ch"] = original

    def test_fans_pca9685_missing_channel_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"].pop("pca9685_ch")
        try:
            with pytest.raises(ValueError, match="pca9685_ch"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["pca9685_ch"] = original

    def test_fans_thermostat_missing_interval_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["exhaust"].pop("interval_s")
        try:
            with pytest.raises(ValueError, match="interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["exhaust"]["interval_s"] = original

    def test_fans_thermostat_zero_interval_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["exhaust"]["interval_s"]
        config.DEVICE_CONFIG["fans"]["exhaust"]["interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["exhaust"]["interval_s"] = original

    def test_fans_thermostat_negative_hysteresis_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["exhaust"]["temp_hysteresis"]
        config.DEVICE_CONFIG["fans"]["exhaust"]["temp_hysteresis"] = -1
        try:
            with pytest.raises(ValueError, match="temp_hysteresis"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["exhaust"]["temp_hysteresis"] = original

    def test_fans_thermostat_duty_out_of_range_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["exhaust"]["default_duty_pct"]
        config.DEVICE_CONFIG["fans"]["exhaust"]["default_duty_pct"] = 150
        try:
            with pytest.raises(ValueError, match="default_duty_pct"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["exhaust"]["default_duty_pct"] = original

    def test_fans_always_on_missing_duty_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"].pop("duty_pct")
        try:
            with pytest.raises(ValueError, match="duty_pct"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["duty_pct"] = original

    def test_fans_always_on_missing_refresh_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"].pop("refresh_interval_s")
        try:
            with pytest.raises(ValueError, match="refresh_interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["refresh_interval_s"] = original

    def test_fans_always_on_zero_refresh_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"]["refresh_interval_s"]
        config.DEVICE_CONFIG["fans"]["case"]["refresh_interval_s"] = 0
        try:
            with pytest.raises(ValueError, match="refresh_interval_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["refresh_interval_s"] = original

    def test_fans_always_on_duty_out_of_range_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"]["duty_pct"]
        config.DEVICE_CONFIG["fans"]["case"]["duty_pct"] = -5
        try:
            with pytest.raises(ValueError, match="duty_pct"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["duty_pct"] = original

    def test_fans_heater_follower_missing_post_run_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["heater_distribution"].pop("post_run_s")
        try:
            with pytest.raises(ValueError, match="post_run_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["heater_distribution"]["post_run_s"] = original

    def test_fans_heater_follower_negative_post_run_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["heater_distribution"]["post_run_s"]
        config.DEVICE_CONFIG["fans"]["heater_distribution"]["post_run_s"] = -1
        try:
            with pytest.raises(ValueError, match="post_run_s"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["heater_distribution"]["post_run_s"] = original

    def test_co2_override_fan_default_is_exhaust(self):
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["co2_logger"]["override_fan"] == "exhaust"

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
        """co2_logger.override_fan not in fans dict raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["co2_logger"]["override_fan"]
        config.DEVICE_CONFIG["co2_logger"]["override_fan"] = "nonexistent_fan"
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

    def test_sd_detect_pin_present_and_int(self):
        """pins.sd_detect ships as GP15 and is an int (Adafruit 4682 DET)."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["pins"]["sd_detect"] == 15
        assert isinstance(DEVICE_CONFIG["pins"]["sd_detect"], int)

    def test_sd_detect_block_defaults_valid(self):
        """Default sd_detect block (enabled, present_when_low, pull=up) validates."""
        from config import DEVICE_CONFIG, validate_config

        assert DEVICE_CONFIG["sd_detect"]["enabled"] is True
        assert DEVICE_CONFIG["sd_detect"]["present_when_low"] is False
        assert DEVICE_CONFIG["sd_detect"]["pull"] == "up"
        assert validate_config() is True

    def test_sd_detect_missing_pin_raises(self):
        """Removing pins.sd_detect raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["pins"].pop("sd_detect")
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["pins"]["sd_detect"] = original

    def test_sd_detect_enabled_non_bool_raises(self):
        """sd_detect.enabled must be a bool."""
        import config

        original = config.DEVICE_CONFIG["sd_detect"]["enabled"]
        config.DEVICE_CONFIG["sd_detect"]["enabled"] = "yes"
        try:
            with pytest.raises(ValueError, match="sd_detect.enabled"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["sd_detect"]["enabled"] = original

    def test_sd_detect_present_when_low_non_bool_raises(self):
        """sd_detect.present_when_low must be a bool."""
        import config

        original = config.DEVICE_CONFIG["sd_detect"]["present_when_low"]
        config.DEVICE_CONFIG["sd_detect"]["present_when_low"] = 0
        try:
            with pytest.raises(ValueError, match="sd_detect.present_when_low"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["sd_detect"]["present_when_low"] = original

    def test_sd_detect_bad_pull_raises(self):
        """sd_detect.pull outside {up, down, none} raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["sd_detect"]["pull"]
        config.DEVICE_CONFIG["sd_detect"]["pull"] = "sideways"
        try:
            with pytest.raises(ValueError, match="sd_detect.pull"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["sd_detect"]["pull"] = original

    def test_sd_detect_pull_none_valid(self):
        """sd_detect.pull='none' (external pull on the board) validates."""
        import config

        original = config.DEVICE_CONFIG["sd_detect"]["pull"]
        config.DEVICE_CONFIG["sd_detect"]["pull"] = "none"
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["sd_detect"]["pull"] = original

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

    def test_mode_invalid_raises(self):
        """Top-level mode outside {'plant','mushroom'} raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["mode"]
        config.DEVICE_CONFIG["mode"] = "bogus"
        try:
            with pytest.raises(ValueError, match="mode must be"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["mode"] = original

    def test_mode_missing_raises(self):
        """Top-level mode missing raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["mode"]
        del config.DEVICE_CONFIG["mode"]
        try:
            with pytest.raises(ValueError, match="Missing config key: mode"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["mode"] = original

    def test_mode_plant_valid(self):
        """mode='plant' passes validation."""
        import config

        original = config.DEVICE_CONFIG["mode"]
        config.DEVICE_CONFIG["mode"] = "plant"
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["mode"] = original

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

        originals = {
            k: config.DEVICE_CONFIG["display"][k] for k in ("startup_banner_s", "vram_clear_delay_s", "invert_delay_s")
        }
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

    def test_fallback_migrate_batch_max_zero_raises(self):
        """system.fallback_migrate_batch_max <= 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["system"]["fallback_migrate_batch_max"]
        config.DEVICE_CONFIG["system"]["fallback_migrate_batch_max"] = 0
        try:
            with pytest.raises(ValueError, match="fallback_migrate_batch_max"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["fallback_migrate_batch_max"] = original

    def test_fallback_migrate_batch_max_default_valid(self):
        """The shipped fallback_migrate_batch_max default validates clean."""
        import config

        assert config.DEVICE_CONFIG["system"]["fallback_migrate_batch_max"] > 0
        assert config.validate_config() is True

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


class TestDiagnosticsConfig:
    """Tests for the diagnostics.mem_trend_log toggle."""

    def test_mem_trend_log_is_bool(self):
        """diagnostics.mem_trend_log defaults to a boolean."""
        from config import DEVICE_CONFIG

        assert isinstance(DEVICE_CONFIG["diagnostics"]["mem_trend_log"], bool)

    def test_mem_trend_log_non_bool_raises(self):
        """diagnostics.mem_trend_log with non-bool raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["diagnostics"]["mem_trend_log"]
        config.DEVICE_CONFIG["diagnostics"]["mem_trend_log"] = "yes"
        try:
            with pytest.raises(ValueError, match="mem_trend_log"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["diagnostics"]["mem_trend_log"] = original

    def test_missing_mem_trend_log_raises(self):
        """Missing diagnostics.mem_trend_log raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["diagnostics"]["mem_trend_log"]
        del config.DEVICE_CONFIG["diagnostics"]["mem_trend_log"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["diagnostics"]["mem_trend_log"] = original


class TestMemoryConfig:
    """Tests for the memory.gc_threshold_b tuning key."""

    def test_gc_threshold_is_valid_int(self):
        """memory.gc_threshold_b is a positive int or -1 (disabled)."""
        from config import DEVICE_CONFIG

        v = DEVICE_CONFIG["memory"]["gc_threshold_b"]
        assert isinstance(v, int)
        assert v > 0 or v == -1

    def test_gc_threshold_disabled_sentinel_passes(self):
        """memory.gc_threshold_b = -1 (disabled) passes validation."""
        import config

        original = config.DEVICE_CONFIG["memory"]["gc_threshold_b"]
        config.DEVICE_CONFIG["memory"]["gc_threshold_b"] = -1
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["memory"]["gc_threshold_b"] = original

    def test_gc_threshold_zero_raises(self):
        """memory.gc_threshold_b = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["memory"]["gc_threshold_b"]
        config.DEVICE_CONFIG["memory"]["gc_threshold_b"] = 0
        try:
            with pytest.raises(ValueError, match="gc_threshold_b"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["memory"]["gc_threshold_b"] = original

    def test_gc_threshold_non_int_raises(self):
        """memory.gc_threshold_b with non-int raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["memory"]["gc_threshold_b"]
        config.DEVICE_CONFIG["memory"]["gc_threshold_b"] = "24000"
        try:
            with pytest.raises(ValueError, match="gc_threshold_b"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["memory"]["gc_threshold_b"] = original

    def test_missing_gc_threshold_raises(self):
        """Missing memory.gc_threshold_b raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["memory"]["gc_threshold_b"]
        del config.DEVICE_CONFIG["memory"]["gc_threshold_b"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["memory"]["gc_threshold_b"] = original
