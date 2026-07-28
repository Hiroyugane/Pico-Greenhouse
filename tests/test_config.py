# Tests for config.py
# Covers validate_config() with valid/invalid configurations


import copy

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
            "regulation",
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

        original = config.DEVICE_CONFIG.get("sht31")
        del config.DEVICE_CONFIG["sht31"]
        try:
            with pytest.raises(ValueError, match="Missing config section"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["sht31"] = original

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

    def test_updater_enforce_mpy_abi_defaults_on(self):
        """The ABI guard ships enabled — a mismatched .mpy payload must fail safe."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["updater"]["enforce_mpy_abi"] is True

    def test_updater_enforce_mpy_abi_non_bool_raises(self):
        """updater.enforce_mpy_abi must be a bool."""
        import config

        original = config.DEVICE_CONFIG["updater"]["enforce_mpy_abi"]
        config.DEVICE_CONFIG["updater"]["enforce_mpy_abi"] = "yes"
        try:
            with pytest.raises(ValueError, match="updater.enforce_mpy_abi"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["enforce_mpy_abi"] = original

    def test_updater_enforce_mpy_abi_may_be_disabled(self):
        """Turning the guard off is a valid operator override, not a config error."""
        import config

        original = config.DEVICE_CONFIG["updater"]["enforce_mpy_abi"]
        config.DEVICE_CONFIG["updater"]["enforce_mpy_abi"] = False
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["updater"]["enforce_mpy_abi"] = original

    def test_updater_prune_stale_defaults_on(self):
        """Flash stops being additive by default — a stale shadow negates the freeze."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["updater"]["prune_stale"] is True

    def test_updater_prune_stale_non_bool_raises(self):
        """updater.prune_stale must be a bool."""
        import config

        original = config.DEVICE_CONFIG["updater"]["prune_stale"]
        config.DEVICE_CONFIG["updater"]["prune_stale"] = "yes"
        try:
            with pytest.raises(ValueError, match="updater.prune_stale"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["updater"]["prune_stale"] = original

    def test_updater_prune_stale_may_be_disabled(self):
        """Keeping the pre-2026-07-28 additive behaviour is a valid operator choice."""
        import config

        original = config.DEVICE_CONFIG["updater"]["prune_stale"]
        config.DEVICE_CONFIG["updater"]["prune_stale"] = False
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["updater"]["prune_stale"] = original

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

    def test_pca9685_freq_is_the_sub_audible_trial_value(self):
        """pca9685.freq_hz stays at the 60 Hz noise trial, not back at 1000."""
        # 2026-07-28: dropped 1000 -> 60 to move the fan tone below the
        # whine band (chat-log 2026-07-28). Pinned so a revert is deliberate:
        # the pitch operators hear is exactly this number.
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["pca9685"]["freq_hz"] == 60

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

    def test_pca9685_invert_default_false(self):
        """pca9685.invert ships False — the reworked fan MOSFET stage does not invert.

        FAN.PP.1 moved the fan's black lead from pin 1 to pin 4, putting the
        AO3400A in the fan's ground return, so a commanded 0 % must reach the
        chip as 0 %. While this was still True the driver wrote the complement
        of every command: 0 % became FULL_ON and the fans ran flat out with no
        observable speed step.
        """
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["pca9685"]["invert"] is False

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
        """Only the case fan lives in the roster — the rest are engine actuators."""
        from config import DEVICE_CONFIG

        assert set(DEVICE_CONFIG["fans"]) == {"case"}

    def test_fans_default_enabled_set(self):
        """The case fan is enabled on PCA9685 ch3 (bench-confirmed map)."""
        from config import DEVICE_CONFIG

        case = DEVICE_CONFIG["fans"]["case"]
        assert case["enabled"] is True
        assert case["output"] == "pca9685"
        assert case["pca9685_ch"] == 3

    def test_fans_channels_disjoint_from_regulation(self):
        """Roster channels must not collide with regulation adapter channels."""
        from config import DEVICE_CONFIG

        roster = {c["pca9685_ch"] for c in DEVICE_CONFIG["fans"].values() if c["output"] == "pca9685"}
        regs = DEVICE_CONFIG["regulation"]["regulators"]
        reg_chans = {
            regs["heater_follower"]["adapter"]["pca9685_ch"],
            regs["exhaust"]["adapter"]["pca9685_ch"],
            regs["circulation"]["adapter"]["center_ch"],
            regs["circulation"]["adapter"]["wall_ch"],
        }
        assert not (roster & reg_chans)

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

        original = config.DEVICE_CONFIG["fans"]["case"].pop("mode")
        try:
            with pytest.raises(ValueError, match="fans.case.mode"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["mode"] = original

    def test_fans_bad_mode_raises(self):
        """Regulated policies are gone; anything but always_on is rejected."""
        import config

        original = config.DEVICE_CONFIG["fans"]["case"]["mode"]
        config.DEVICE_CONFIG["fans"]["case"]["mode"] = "thermostat_schedule"
        try:
            with pytest.raises(ValueError, match="fans.case.mode"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["mode"] = original

    def test_fans_bad_output_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"]["output"]
        config.DEVICE_CONFIG["fans"]["case"]["output"] = "magic"
        try:
            with pytest.raises(ValueError, match="fans.case.output"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["output"] = original

    def test_fans_enabled_non_bool_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"]["enabled"]
        config.DEVICE_CONFIG["fans"]["case"]["enabled"] = "yes"
        try:
            with pytest.raises(ValueError, match="fans.case.enabled"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["enabled"] = original

    @staticmethod
    def _aux_relay_fan(pin_key):
        """A minimal relay-backed always_on fan for validator branch tests."""
        return {
            "enabled": True,
            "mode": "always_on",
            "output": "relay",
            "relay_pin_key": pin_key,
            "duty_pct": 100,
            "refresh_interval_s": 300,
        }

    def test_fans_relay_pin_key_unknown_raises(self):
        """A relay-output fan referencing an unknown pin raises ValueError."""
        import config

        fans = config.DEVICE_CONFIG["fans"]
        fans["aux"] = self._aux_relay_fan("no_such_pin")
        try:
            with pytest.raises(ValueError, match="relay_pin_key"):
                config.validate_config()
        finally:
            del fans["aux"]

    def test_fans_relay_pin_key_collision_raises(self):
        """Two relay-backed fans cannot share the same pin."""
        import config

        fans = config.DEVICE_CONFIG["fans"]
        fans["aux1"] = self._aux_relay_fan("relay_reserved_1")
        fans["aux2"] = self._aux_relay_fan("relay_reserved_1")
        try:
            with pytest.raises(ValueError, match="is used by another fan"):
                config.validate_config()
        finally:
            del fans["aux1"]
            del fans["aux2"]

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

        fans = config.DEVICE_CONFIG["fans"]
        fans["aux"] = {
            "enabled": True,
            "mode": "always_on",
            "output": "pca9685",
            "pca9685_ch": fans["case"]["pca9685_ch"],
            "duty_pct": 100,
            "refresh_interval_s": 300,
        }
        try:
            with pytest.raises(ValueError, match="is used by another fan"):
                config.validate_config()
        finally:
            del fans["aux"]

    def test_fans_pca9685_missing_channel_raises(self):
        import config

        original = config.DEVICE_CONFIG["fans"]["case"].pop("pca9685_ch")
        try:
            with pytest.raises(ValueError, match="pca9685_ch"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["fans"]["case"]["pca9685_ch"] = original

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
        """mode='plant' passes validation with a matching plant profile."""
        import config

        original = config.DEVICE_CONFIG["mode"]
        orig_profile = config.DEVICE_CONFIG["regulation"]["profile"]
        config.DEVICE_CONFIG["mode"] = "plant"
        # The regulation profile category is tied to the top-level mode, so a
        # plant mode needs a plant profile selected.
        config.DEVICE_CONFIG["regulation"]["profile"] = "cannabis"
        try:
            assert config.validate_config() is True
        finally:
            config.DEVICE_CONFIG["mode"] = original
            config.DEVICE_CONFIG["regulation"]["profile"] = orig_profile

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

    def test_display_max_render_errors_default_valid(self):
        """display.max_render_errors defaults to a positive int and validates."""
        from config import DEVICE_CONFIG, validate_config

        assert DEVICE_CONFIG["display"]["max_render_errors"] == 5
        assert validate_config() is True

    def test_display_max_render_errors_zero_raises(self):
        """display.max_render_errors < 1 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["display"]["max_render_errors"]
        config.DEVICE_CONFIG["display"]["max_render_errors"] = 0
        try:
            with pytest.raises(ValueError, match="max_render_errors"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["display"]["max_render_errors"] = original

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

    def test_i2c_recovery_defaults_present_and_valid(self):
        """The shared-I2C resilience tunables default to sane values and validate."""
        from config import DEVICE_CONFIG, validate_config

        sys_cfg = DEVICE_CONFIG["system"]
        assert sys_cfg["i2c_freq"] == 100000  # dropped from 400k for pull-up margin
        assert sys_cfg["i2c_use_soft"] is True
        assert sys_cfg["i2c_timeout_us"] == 50000
        assert sys_cfg["i2c_recover_on_error"] is True
        assert sys_cfg["i2c_recover_clocks"] == 9
        assert validate_config() is True

    def test_i2c_use_soft_non_bool_raises(self):
        """system.i2c_use_soft must be a bool."""
        import config

        original = config.DEVICE_CONFIG["system"]["i2c_use_soft"]
        config.DEVICE_CONFIG["system"]["i2c_use_soft"] = "yes"
        try:
            with pytest.raises(ValueError, match="i2c_use_soft"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["i2c_use_soft"] = original

    def test_i2c_timeout_us_out_of_range_raises(self):
        """system.i2c_timeout_us below 1000 or above 1000000 raises."""
        import config

        original = config.DEVICE_CONFIG["system"]["i2c_timeout_us"]
        try:
            for bad in (500, 2_000_000):
                config.DEVICE_CONFIG["system"]["i2c_timeout_us"] = bad
                with pytest.raises(ValueError, match="i2c_timeout_us"):
                    config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["i2c_timeout_us"] = original

    def test_i2c_recover_clocks_out_of_range_raises(self):
        """system.i2c_recover_clocks outside 8..16 raises."""
        import config

        original = config.DEVICE_CONFIG["system"]["i2c_recover_clocks"]
        try:
            for bad in (7, 17):
                config.DEVICE_CONFIG["system"]["i2c_recover_clocks"] = bad
                with pytest.raises(ValueError, match="i2c_recover_clocks"):
                    config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["i2c_recover_clocks"] = original

    def test_missing_i2c_recover_key_raises(self):
        """A missing shared-I2C key raises (required-keys coverage)."""
        import config

        original = config.DEVICE_CONFIG["system"]["i2c_recover_on_error"]
        del config.DEVICE_CONFIG["system"]["i2c_recover_on_error"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["system"]["i2c_recover_on_error"] = original

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

    def test_log_retention_days_present_and_positive(self):
        """event_logger.log_retention_days is a positive int by default."""
        from config import DEVICE_CONFIG

        assert isinstance(DEVICE_CONFIG["event_logger"]["log_retention_days"], int)
        assert DEVICE_CONFIG["event_logger"]["log_retention_days"] > 0

    def test_zero_log_retention_days_raises(self):
        """event_logger.log_retention_days = 0 raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["log_retention_days"]
        config.DEVICE_CONFIG["event_logger"]["log_retention_days"] = 0
        try:
            with pytest.raises(ValueError, match="log_retention_days"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["log_retention_days"] = original

    def test_non_int_log_retention_days_raises(self):
        """event_logger.log_retention_days must be an int, not a float/str."""
        import config

        original = config.DEVICE_CONFIG["event_logger"]["log_retention_days"]
        config.DEVICE_CONFIG["event_logger"]["log_retention_days"] = 30.0
        try:
            with pytest.raises(ValueError, match="log_retention_days"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["event_logger"]["log_retention_days"] = original

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
    """Tests for the diagnostics.mem_trend_log / metrics_log toggles."""

    def test_mem_trend_log_is_bool(self):
        """diagnostics.mem_trend_log defaults to a boolean."""
        from config import DEVICE_CONFIG

        assert isinstance(DEVICE_CONFIG["diagnostics"]["mem_trend_log"], bool)

    def test_metrics_log_on_by_default(self):
        """diagnostics.metrics_log defaults to True since the firmware freeze
        reclaimed ~83 KB of heap (2026-07-27) — the post-freeze soak needs the CSV."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["diagnostics"]["metrics_log"] is True

    def test_metrics_log_non_bool_raises(self):
        """diagnostics.metrics_log with non-bool raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["diagnostics"]["metrics_log"]
        config.DEVICE_CONFIG["diagnostics"]["metrics_log"] = "yes"
        try:
            with pytest.raises(ValueError, match="metrics_log"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["diagnostics"]["metrics_log"] = original

    def test_missing_metrics_log_raises(self):
        """Missing diagnostics.metrics_log raises ValueError."""
        import config

        original = config.DEVICE_CONFIG["diagnostics"]["metrics_log"]
        del config.DEVICE_CONFIG["diagnostics"]["metrics_log"]
        try:
            with pytest.raises(ValueError, match="Missing config key"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["diagnostics"]["metrics_log"] = original

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


class TestRegulationConfig:
    """Tests for the DEVICE_CONFIG['regulation'] block and _validate_regulation()."""

    @staticmethod
    def _restore(snapshot):
        import config

        config.DEVICE_CONFIG["regulation"] = snapshot

    def test_regulation_section_present(self):
        """DEVICE_CONFIG has a regulation section."""
        from config import DEVICE_CONFIG

        assert "regulation" in DEVICE_CONFIG

    def test_regulation_default_valid(self):
        """The shipped regulation block validates clean."""
        import config

        assert config.validate_config() is True

    def test_regulation_missing_section_raises(self):
        """Removing the regulation section raises ValueError."""
        import config

        original = config.DEVICE_CONFIG.pop("regulation")
        try:
            with pytest.raises(ValueError, match="Missing config section: regulation"):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG["regulation"] = original

    def test_regulation_enabled_by_default(self):
        """Engine ships enabled — the wiring swap made it the only actuator owner."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["regulation"]["enabled"] is True

    def test_regulation_tick_zero_raises(self):
        """regulation.tick_s <= 0 raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["tick_s"] = 0
        try:
            with pytest.raises(ValueError, match="regulation.tick_s"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_band_edges_not_ascending_raises(self):
        """Non-ascending band_edges raise ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["band_edges"] = [5, 5, 20, 30, 40, 50]
        try:
            with pytest.raises(ValueError, match="band_edges"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_band_edges_too_few_raises(self):
        """Fewer than 4 band_edges raise ValueError (arbiter needs four thresholds)."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["band_edges"] = [40, 50]
        try:
            with pytest.raises(ValueError, match="at least 4"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_band_edges_not_ending_at_50_raises(self):
        """band_edges must end at 50."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["band_edges"] = [5, 10, 20, 30, 40, 45]
        try:
            with pytest.raises(ValueError, match="band_edges must end at 50"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_day_window_inverted_raises(self):
        """day_start_min >= day_end_min raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["day_start_min"] = 1200
        try:
            with pytest.raises(ValueError, match="day_start_min"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_profile_unknown_raises(self):
        """regulation.profile not in profiles raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["profile"] = "triffid"
        try:
            with pytest.raises(ValueError, match="not in profiles"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_profile_category_mismatch_raises(self):
        """Active profile category must match the top-level mode."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        # Top-level mode is 'mushroom'; selecting a plant profile must fail.
        config.DEVICE_CONFIG["regulation"]["profile"] = "cannabis"
        try:
            with pytest.raises(ValueError, match="category must match"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_anchors_not_ascending_raises(self):
        """Profile anchors must be strictly ascending."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["profiles"]["cubensis"]["day"]["temp"]["at_50"] = 40.0
        try:
            with pytest.raises(ValueError, match="strictly ascending"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_regulators_wrong_set_raises(self):
        """Dropping a regulator (set mismatch) raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        del config.DEVICE_CONFIG["regulation"]["regulators"]["cooler"]
        try:
            with pytest.raises(ValueError, match="regulators must be exactly"):
                config.validate_config()
        finally:
            self._restore(snap)

    @pytest.mark.parametrize("param,lo,hi,_default", __import__("config")._SURFACE_PARAMS)
    def test_regulation_surface_param_out_of_range_raises(self, param, lo, hi, _default):
        """Every surface param is range-checked by the shared schema loop."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["regulators"]["heater"]["surface"][param] = hi + 1.0
        try:
            with pytest.raises(ValueError, match="regulation.regulators.heater.surface"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_surface_out_min_ge_out_max_raises(self):
        """A surface with out_min >= out_max raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        surf = config.DEVICE_CONFIG["regulation"]["regulators"]["heater"]["surface"]
        surf["out_min"] = 50.0
        surf["out_max"] = 50.0
        try:
            with pytest.raises(ValueError, match="out_min must be < out_max"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_relay_hysteresis_inverted_raises(self):
        """A relay adapter with on_above <= off_below raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        adapter = config.DEVICE_CONFIG["regulation"]["regulators"]["cooler"]["adapter"]
        adapter["on_above"] = 30.0
        adapter["off_below"] = 40.0
        try:
            with pytest.raises(ValueError, match="on_above must be > off_below"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_pwm_channel_out_of_range_raises(self):
        """A pwm adapter channel outside 0-15 raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["regulators"]["exhaust"]["adapter"]["pca9685_ch"] = 16
        try:
            with pytest.raises(ValueError, match="pca9685_ch"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_adapter_pin_key_unknown_raises(self):
        """A relay adapter referencing an unknown pin raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["regulators"]["cooler"]["adapter"]["pin_key"] = "no_such_pin"
        try:
            with pytest.raises(ValueError, match="pin_key"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_growlight_dac_max_pct_out_of_range_raises(self):
        """growlight adapter dac_max_pct outside 0-100 raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["regulators"]["growlight"]["adapter"]["dac_max_pct"] = 150
        try:
            with pytest.raises(ValueError, match="dac_max_pct"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_growlight_dac_max_pct_default_is_xs1500_ceiling(self):
        """Shipped dac_max_pct stays at the ViparSpectra XS1500 safe ceiling."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["regulation"]["regulators"]["growlight"]["adapter"]["dac_max_pct"] == 91

    def test_regulation_conflict_unknown_regulator_raises(self):
        """A conflict rule forcing an unknown regulator raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["conflicts"][0]["force"] = {"nonexistent": 0.0}
        try:
            with pytest.raises(ValueError, match="unknown regulator"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_conflict_unknown_dimension_raises(self):
        """A conflict when-term with an unknown dimension raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["conflicts"][0]["when"] = [["pressure", "above", 30]]
        try:
            with pytest.raises(ValueError, match="dimension"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_latch_release_ticks_zero_raises(self):
        """latch.release_ticks < 1 raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["latch"]["release_ticks"] = 0
        try:
            with pytest.raises(ValueError, match="release_ticks"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_latch_enter_ticks_zero_raises(self):
        """latch.enter_ticks < 1 raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["latch"]["enter_ticks"] = 0
        try:
            with pytest.raises(ValueError, match="enter_ticks"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_latch_enter_ticks_default_debounces(self):
        """The shipped latch waits for a sustained condition, not one bad read."""
        from config import DEVICE_CONFIG

        assert DEVICE_CONFIG["regulation"]["latch"]["enter_ticks"] >= 2

    def test_regulation_escalation_low_side_off_by_default(self):
        """Being far BELOW ideal is the startup case, never an emergency.

        Regression guard for 2026-07-21: with the low side escalating, a tent
        brought up from ambient latched the safe-state vector on the first tick
        and could never recover (the humidifier was forced off).
        """
        from config import DEVICE_CONFIG

        esc = DEVICE_CONFIG["regulation"]["escalation"]
        assert esc["temp"]["low"] is False
        assert esc["humidity"]["low"] is False
        assert esc["co2"] == {"high": False, "low": False}
        assert esc["temp"]["high"] is True
        assert esc["humidity"]["high"] is True

    def test_regulation_escalation_missing_dimension_raises(self):
        """escalation must cover exactly the regulation dimensions."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        del config.DEVICE_CONFIG["regulation"]["escalation"]["co2"]
        try:
            with pytest.raises(ValueError, match="escalation"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_escalation_non_bool_side_raises(self):
        """escalation.<dim>.<side> must be a bool."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["escalation"]["temp"]["high"] = 1
        try:
            with pytest.raises(ValueError, match="escalation.temp.high"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_safe_state_accepts_none(self):
        """None = 'free': the forced vector leaves that regulator organic."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["regulators"]["exhaust"]["safe_state"] = None
        try:
            assert config.validate_config() is True
        finally:
            self._restore(snap)

    def test_regulation_safe_state_out_of_range_raises(self):
        """A non-None safe_state outside 0-100 still raises."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["regulators"]["exhaust"]["safe_state"] = 120.0
        try:
            with pytest.raises(ValueError, match="safe_state"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_safe_state_missing_raises(self):
        """Omitting safe_state entirely is still an error (None must be explicit)."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        del config.DEVICE_CONFIG["regulation"]["regulators"]["exhaust"]["safe_state"]
        try:
            with pytest.raises(ValueError, match="safe_state"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_cooler_free_in_forced_vectors(self):
        """The cooler is the corrective actuator for the only escalating side."""
        from config import DEVICE_CONFIG

        cooler = DEVICE_CONFIG["regulation"]["regulators"]["cooler"]
        assert cooler["emergency_value"] is None
        assert cooler["safe_state"] is None

    def test_regulation_circulation_takes_the_co2_term(self):
        """Venting alone leaves dead zones — the circulation pair ramps with CO2 too."""
        from config import DEVICE_CONFIG

        circ = DEVICE_CONFIG["regulation"]["regulators"]["circulation"]
        assert circ["co2_gain"] > 0.0
        assert 0.0 <= circ["co2_break"] <= 100.0
        # Stirring the tent helps regardless of what the outside air is like.
        assert circ["external"] is False

    def test_regulation_co2_term_can_clear_its_own_floor(self):
        """Every CO2 term must be able to out-command the floor that follows it.

        Regression guard for a bug class this repo has now hit twice: a
        threshold set in one pipeline stage nullified by a guard in a later one.
        The additive term is bounded by co2_gain * (100 - co2_break); if that
        ceiling sits at or below the regulator's floor, the arbiter forces the
        command up to the floor and CO2 changes nothing anywhere in the
        profile's range (docs/notes/chat-log.md 2026-07-22). Gain, break and
        floor are one calibration — this asserts they were re-derived together.
        """
        from config import DEVICE_CONFIG

        for name, rcfg in DEVICE_CONFIG["regulation"]["regulators"].items():
            if "co2_gain" not in rcfg:
                continue
            ceiling = rcfg["co2_gain"] * (100.0 - rcfg["co2_break"])
            assert ceiling > rcfg["floor"], "{}: CO2 term tops out at {} under a floor of {}".format(
                name, ceiling, rcfg["floor"]
            )

    def test_regulation_co2_term_partial_block_raises(self):
        """A CO2 gain without its break/external siblings raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        del config.DEVICE_CONFIG["regulation"]["regulators"]["circulation"]["co2_break"]
        try:
            with pytest.raises(ValueError, match="CO2 term needs all of"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_co2_term_on_non_surface_regulator_raises(self):
        """The term is added to a surface output, so a tod regulator cannot take it."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        light = config.DEVICE_CONFIG["regulation"]["regulators"]["growlight"]
        light.update({"co2_gain": 1.0, "co2_break": 50.0, "external": False})
        try:
            with pytest.raises(ValueError, match="requires driven='surface'"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_exhaust_without_co2_term_raises(self):
        """The exhaust is the primary CO2 actuator — losing the term is a regression."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        for key in ("co2_gain", "co2_break", "external"):
            del config.DEVICE_CONFIG["regulation"]["regulators"]["exhaust"][key]
        try:
            with pytest.raises(ValueError, match="must carry the CO2 term keys"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_co2_break_out_of_range_raises(self):
        """co2_break outside 0-100 raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["regulators"]["circulation"]["co2_break"] = 140.0
        try:
            with pytest.raises(ValueError, match="co2_break"):
                config.validate_config()
        finally:
            self._restore(snap)

    def test_regulation_cubensis_co2_is_fruiting_grade(self):
        """Fruiting needs continuous FAE — the IDEAL stays well under colonization levels."""
        from config import DEVICE_CONFIG

        prof = DEVICE_CONFIG["regulation"]["profiles"]["cubensis"]
        for phase in ("day", "night"):
            co2 = prof[phase]["co2"]
            assert co2["at_50"] <= 600.0

    def test_regulation_mushroom_co2_envelope_covers_indoor_air(self):
        """Mushroom CO2 anchors span the real indoor range without saturating.

        Regression (2026-07-21): the 400/1200 envelope reported ordinary room
        air — 500 ppm on a good day, 1300 on a bad one, ~420 outdoors — as
        maximum deviation in one direction or the other, pinning global
        severity at the top band for a condition the room cannot leave.
        """
        from config import DEVICE_CONFIG
        from lib.regulation_normalizer import deviation

        profiles = DEVICE_CONFIG["regulation"]["profiles"]
        for name, prof in profiles.items():
            if prof["category"] != "mushroom":
                continue
            for phase in ("day", "night"):
                co2 = prof[phase]["co2"]
                ctx = "{}.{}".format(name, phase)
                # Full severity belongs at genuinely stale air, not room air.
                assert co2["at_100"] == 2000.0, ctx
                # Fresh air is never a fault for a fruiting body.
                assert co2["at_0"] == 0.0, ctx
                for ppm in (400.0, 500.0, 1300.0):
                    sev = abs(deviation(ppm, **co2) - 50.0)
                    assert sev < 30.0, "{} at {} ppm: severity {}".format(ctx, ppm, sev)

    def test_regulation_external_min_factor_out_of_range_raises(self):
        """external_sensor.min_factor outside 0-1 raises ValueError."""
        import config

        snap = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        config.DEVICE_CONFIG["regulation"]["external_sensor"]["min_factor"] = 1.5
        try:
            with pytest.raises(ValueError, match="min_factor"):
                config.validate_config()
        finally:
            self._restore(snap)
