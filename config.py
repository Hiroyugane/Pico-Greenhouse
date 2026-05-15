# Pi Greenhouse Configuration
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0
#
# Central configuration for all hardware pins, intervals, file paths, and thresholds.
# Modify values here to tune device behavior without editing module code.

DEVICE_CONFIG = {
    # Hardware Pins
    #
    # Pico GPIO layout — matches PCB schematic SCH_Pico-Greenhouse-PCB_2026-05-14
    # (docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json):
    #
    #   GP0-GP1:   I2C0 bus (shared: RTC + OLED + MCP4725 grow-light DAC +
    #              I2C_CON1/2/3 breakouts). Pulled up to 3V3 via R1/R2.
    #   GP2:       GP2_CON header (general-purpose breakout, future use)
    #   GP3:       Heater MOSFET gate (via R6 → IRLZ44N gate, active HIGH)
    #   GP4:       Activity LED   (LED_CON)
    #   GP5:       SD-problem LED (LED_CON)
    #   GP6:       Warning LED    (LED_CON)
    #   GP7:       Error LED      (LED_CON)
    #   GP8:       Service / reminder LED (LED_CON)
    #   GP9:       Menu button (MEN_BTN, short=cycle, long=action)
    #   GP10-GP13: SPI1 (SD card via SD_CON). MOSI uses R10, MISO uses R8
    #              as series resistors between Pico and SD_CON.
    #   GP14:      Passive buzzer (BUZ_CON, with R3 pulldown to GND)
    #   GP15:      Free (formerly DHT22 data on T/H_CON pin 4; SHT31 now
    #              shares the I2C0 bus, GP15 is available for future use)
    #   GP16:      UART0 TX → CO2 sensor (via R9 to CO2_CON pin 4)
    #   GP17:      UART0 RX ← CO2 sensor (via R11 from CO2_CON pin 3)
    #   GP18:      Relay 1 — fan 1     (REL_CON pin 2)
    #   GP19:      Relay 2 — fan 2     (REL_CON pin 3)
    #   GP20:      Relay 3 — growlight (REL_CON pin 4)
    #   GP21-GP22: Reserved relays (REL_CON pins 5-6, future use)
    #   GP25:      On-board LED (heartbeat)
    #   GP26-GP27: Reserved relays (REL_CON pins 7-8, future use)
    #   GP28:      ADC input (ADC_CON pin 4; ADC_VREF on Pico pin 35)
    #
    # RES_BTN on the PCB is wired to the Pico's 3V3_EN line (hardware reset),
    # not a GPIO; "button_reserved" below points at the GP2 breakout for any
    # future software-side button.
    "pins": {
        # I2C0 — shared bus (RTC, OLED, MCP4725 grow-light DAC, I2C breakouts)
        "rtc_i2c_port": 0,
        "rtc_sda": 0,  # GP0 (I2C0 SDA)
        "rtc_scl": 1,  # GP1 (I2C0 SCL)
        # General-purpose breakout header (GP2_CON, future use)
        "gp2_breakout": 2,  # GP2 — exposed for future use
        "button_reserved": 2,  # Reserved (mapped onto GP2_CON; RES_BTN is now a hw reset, not a GPIO)
        # Heater control (GP3 → R6 → HE_MOSFET gate)
        "heater_mosfet": 3,  # GP3 — heater MOSFET gate (active HIGH)
        # Status LEDs (LED_CON wiring per new PCB; roles by GPIO)
        "activity_led": 4,  # GP4 — Activity LED (brief blink on I/O actions)
        "sd_led": 5,  # GP5 — SD-problem LED (solid = SD missing/failed)
        "warning_led": 6,  # GP6 — Warning LED (solid = degraded condition)
        "error_led": 7,  # GP7 — Error LED (solid = fault needs attention)
        "reminder_led": 8,  # GP8 — Service-reminder LED (blinks when due)
        # Menu button
        "button_menu": 9,  # GP9 — Menu button (short=cycle menu, long≥3s=action)
        # Buzzer (BUZ_CON, pulled to GND via R3)
        "buzzer": 14,  # GP14 — Passive buzzer (PWM output)
        # CO2 sensor (UART0 with series resistors R9/R11)
        "co2_uart_id": 0,  # UART0
        "co2_uart_tx": 16,  # GP16 — UART0 TX → CO2_CON pin 4 (via R9)
        "co2_uart_rx": 17,  # GP17 — UART0 RX ← CO2_CON pin 3 (via R11)
        "co2_baudrate": 9600,
        # Relays (REL_CON pins 2-8 → 7 GPIO control lines)
        "relay_fan_1": 18,  # GP18 — Fan relay 1 (REL_CON pin 2)
        "relay_fan_2": 19,  # GP19 — Fan relay 2 (REL_CON pin 3)
        "relay_growlight": 20,  # GP20 — Grow light relay (REL_CON pin 4)
        "relay_reserved_1": 21,  # GP21 — Reserved relay (REL_CON pin 5)
        "relay_reserved_2": 22,  # GP22 — Reserved relay (REL_CON pin 6)
        "relay_reserved_3": 26,  # GP26 — Reserved relay (REL_CON pin 7)
        "relay_reserved_4": 27,  # GP27 — Reserved relay (REL_CON pin 8)
        # Analog input (ADC_CON pin 4; ADC_VREF on Pico pin 35)
        "adc_input": 28,  # GP28 — ADC input (ADC_CON pin 4)
        # On-board LED
        "onboard_led": 25,  # GP25 — Pico on-board LED (heartbeat)
    },
    # SPI Configuration (SD Card via SD_CON; MOSI/MISO use series resistors R10/R8)
    "spi": {
        "id": 1,
        "baudrate": 40000000,
        "sck": 10,  # GP10 → SD_CON.SCK
        "mosi": 11,  # GP11 → R10 → SD_CON.MOSI
        "miso": 12,  # GP12 → R8 → SD_CON.MISO
        "cs": 13,  # GP13 → SD_CON.CS
        "mount_point": "/sd",
    },
    # File Paths
    "files": {
        "th_log_base": "th_log",  # Will become th_log_YYYY-MM-DD.csv
        "system_log": "/sd/system.log",
        "fallback_path": "/local/fallback.csv",  # Fallback when SD unavailable
    },
    # SHT31-D temperature/humidity sensor (shared I2C0 bus, alongside RTC,
    # OLED and MCP4725 DAC). ADDR pin tied to GND = 0x44; tied to VCC = 0x45.
    "sht31": {
        "i2c_address": 0x44,
    },
    # Temperature/Humidity Logger Configuration
    "temp_humidity_logger": {
        "interval_s": 30,  # Log interval in seconds
        "max_retries": 3,  # Sensor read retries
        "max_buffer_size": 200,  # Max in-memory readings
        "retry_delay_s": 0.5,  # Delay between sensor read retries (seconds)
    },
    # Fan Control - Fan 1 (Time-based + Thermostat)
    "fan_1": {
        "interval_s": 600,  # Cycle interval (10 minutes)
        "on_time_s": 20,  # Time ON per cycle
        "max_temp": 23.8,  # Temperature threshold (°C)
        "temp_hysteresis": 0.5,  # Hysteresis for thermostat (°C)
        "poll_interval_s": 5,  # Schedule/thermostat check interval (seconds)
    },
    # Fan Control - Fan 2 (Time-based + Thermostat)
    "fan_2": {
        "interval_s": 500,  # Cycle interval
        "on_time_s": 20,  # Time ON per cycle
        "max_temp": 27.0,  # Temperature threshold (°C)
        "temp_hysteresis": 0.5,  # Hysteresis for thermostat (°C)
        "poll_interval_s": 5,  # Schedule/thermostat check interval (seconds)
    },
    # Heater Configuration (GP3 → R6 → IRLZ44N gate, ACTIVE HIGH)
    #
    # Day/night setpoints inherit the growlight schedule plus an optional
    # offset in minutes. day_start = growlight.dawn + day_offset_min;
    # night_start = growlight.sunset + night_offset_min. With both offsets
    # at 0 the heater follows the lamp 1:1.
    "heater": {
        "day_min_temp": 22.0,  # Setpoint while day window is active (°C)
        "night_min_temp": 16.0,  # Setpoint while night window is active (°C)
        "temp_hysteresis": 0.5,  # Drop below setpoint before re-firing (°C)
        "day_offset_min": 0,  # Minutes after growlight dawn for day window start
        "night_offset_min": 0,  # Minutes after growlight sunset for night window start
        "max_stale_reads": 3,  # Tolerate N consecutive DHT failures before failing OFF
        "poll_interval_s": 30,  # Thermostat check cadence (seconds)
    },
    # Soil Moisture Logger Configuration (GP28 / ADC2, single-probe)
    #
    # Raw ADC range on the RP2040 is 0-65535 (read_u16) but the plan
    # speaks in the conventional 0-1023 10-bit space. SoilLogger scales
    # the read_u16 result down internally; the calibration constants are
    # specified in 0-1023 space because that's what the REPL helper
    # (print_raw) prints. Calibrate against actual sensor + soil pot:
    # adc_dry_raw = raw value with probe in air / bone-dry soil,
    # adc_wet_raw = raw value with probe in saturated soil. Wet must be
    # < dry (lower raw = more conductive = more water).
    "soil_logger": {
        "interval_s": 60,  # Log cadence (seconds) — soil moves slowly
        "adc_dry_raw": 850,  # Raw 10-bit reading for 0% moisture (in-air)
        "adc_wet_raw": 350,  # Raw 10-bit reading for 100% moisture (saturated)
        "warn_pct_below": 20,  # Trigger warning LED when soil < this %
        "filename_base": "soil_log",  # Becomes /sd/soil_log_YYYY-MM-DD.csv
    },
    # CO2 Sensor Logger Configuration (SenseAir S8 / equivalent on UART0)
    #
    # Poll/response framing matches the prototype in tests/co2log.py:
    # 7-byte request 0xFE 0x44 0x00 0x08 0x02 0x9F 0x25 → 7-byte reply
    # whose bytes 3-4 (0-indexed) encode ppm as high*256 + low.
    # The override_fan key chooses which FanController gets force-on
    # when ppm crosses override_ppm_on, until ppm drops below
    # override_ppm_off. fan_2 has the higher max_temp by default so it
    # is the bigger ventilator and the natural CO2 vent target.
    "co2_logger": {
        "interval_s": 30,  # Poll cadence (seconds)
        "warmup_s": 30,  # Sensor warm-up window where read failures don't escalate
        "max_retries": 3,  # UART read retries per poll
        "override_ppm_on": 1000,  # Trip threshold (ppm)
        "override_ppm_off": 800,  # Release threshold (ppm), must be < on
        "override_fan": "fan_2",  # Which fan key to force-on (fan_1 or fan_2)
        "filename_base": "co2_log",  # Becomes /sd/co2_log_YYYY-MM-DD.csv
    },
    # Grow Light Configuration
    "growlight": {
        # "relay_only": drive GP20 relay as plain on/off, skip MCP4725 init.
        # "dimmed":     init MCP4725 DAC for ViparSpectra XS1500 dimming over
        #               the relay master-switch. Falls back to relay-only at
        #               runtime if DAC init throws (logged as warning).
        "mode": "relay_only",
        "dawn_hour": 7,  # Light ON at 7:00 AM
        "dawn_minute": 0,
        "sunset_hour": 19,  # Light OFF at 19:00 (10 PM)
        "sunset_minute": 0,
        "poll_interval_s": 60,  # Schedule check interval (seconds)
        # MCP4725 dimming DAC on shared I2C0. Only consulted when mode="dimmed".
        # Tentative default 0x60 (A0=GND); confirm with prototypes/i2c_scan.py —
        # A0=VCC is 0x61.
        "dac_i2c_address": 0x60,
        # Dimming layer over the master-switch relay. Relay handles
        # ON/OFF; DAC sets brightness via op-amp buffer to GL_CON.
        "default_level_pct": 80,  # Brightness when no override active
        "max_level_pct": 91,  # ViparSpectra XS1500 safe ceiling — never exceed
        "min_level_pct": 0,  # Below this snaps to 0 (relay off)
        "ramp_duration_s": 300,  # Linear fade duration on dawn/sunset edges
    },
    # Service Reminder Configuration
    "Service_reminder": {
        "days_interval": 7,  # Remind every 7 days
        "blink_pattern_ms": [
            200,
            200,
            200,
            800,
        ],  # ON 200ms, OFF 200ms, ON 200ms, OFF 800ms
        "blink_after_days": 3,  # Days overdue before LED switches from solid to blink
        "storage_path": "/service_reminder.txt",  # Persistence file for last-serviced timestamp
        "monitor_interval_s": 3600,  # Re-check interval when not due (seconds)
    },
    # Status LED Manager Configuration
    # Design: solid = problem, blink = activity, dark = all good
    #
    # walk_order — physical left-to-right order of the LED row on the PCB
    # (LED_CON). The POST walk lights LEDs in this sequence so the
    # visual sweep moves smoothly across the row instead of jumping
    # between GPIOs in pin-number order. Valid role names:
    #   "activity" (green, GP4), "sd" (blue, GP5),
    #   "reminder" (white, GP8), "warning" (yellow, GP6),
    #   "error" (red, GP7).
    # Heartbeat (GP25 on-board) is always appended after the row.
    "status_leds": {
        "activity_blink_ms": 50,  # Activity LED pulse duration (ms)
        "heartbeat_interval_ms": 2000,  # GP25 toggle period (ms)
        "th_warn_threshold": 3,  # Consecutive T/H read failures → warning
        "th_error_threshold": 10,  # Consecutive T/H read failures → error
        "rtc_min_year": 2025,  # Year below this → RTC invalid warning
        "rtc_max_year": 2035,  # Year above this → RTC invalid warning
        "post_enabled": True,  # Run LED power-on self-test at startup
        "post_step_ms": 150,  # Duration each LED stays on during POST walk (ms)
        "walk_order": ["activity", "sd", "reminder", "warning", "error"],
        "mem_warning_pct": 80,  # RAM usage % above this → warning LED
        "mem_error_pct": 90,  # RAM usage % above this → error LED
    },
    # Buffer Manager Configuration
    "buffer_manager": {
        "sd_mount_point": "/sd",
        "fallback_path": "/local/fallback.csv",
        "max_buffer_entries": 150,  # Ring buffer cap (reduced from 200 to reduce RAM usage)
        "max_fallback_size_kb": 50,  # Emergency fallback file size limit (KB); when exceeded, oldest entries are pruned
    },
    # Event Logger Configuration
    "event_logger": {
        "logfile": "/sd/system.log",
        "max_size": 1000000,  # Max log file size (bytes) before rotation
        "info_flush_threshold": 5,  # Flush after N info-level entries buffered
        "warn_flush_threshold": 1,  # Flush after N warning-level entries (1=immediate, like ERROR)
        "log_level": "INFO",  # Minimum severity: DEBUG, INFO, WARN, ERR
        "debug_enabled": False,  # Enable DEBUG messages to console (zero-cost when disabled)
        "debug_to_file": False,  # Also write DEBUG entries to SD log (caution: fills card)
        "debug_flush_threshold": 10,  # Flush after N debug entries buffered (when debug_to_file=True)
        "debug_max_size": 1000000,  # Rotation threshold when debug_to_file=True (lower: debug spam fills log faster)
    },
    # Buzzer Configuration (passive buzzer via PWM)
    "buzzer": {
        "enabled": True,  # Master enable/disable
        "default_freq": 1000,  # Default tone frequency (Hz)
        "default_duty_pct": 50,  # Default duty cycle (% of u16 range)
        "startup_melody": [
            (1047, 100, 50),  # C6, 100ms, 50ms pause
            (1319, 100, 50),  # E6
            (1568, 200, 0),  # G6
        ],
        "error_pattern": [
            (400, 200, 100),  # Low tone, 200ms, 100ms pause
            (400, 200, 100),
            (400, 400, 0),  # Longer final beep
        ],
        "alert_pattern": [
            (2000, 150, 100),  # High tone
            (2000, 150, 100),
            (2000, 150, 0),
        ],
        "reminder_pattern": [
            (880, 100, 200),  # A5
            (880, 100, 0),
        ],
    },
    # OLED Display Configuration (SSD1306 on shared I2C1 bus)
    "display": {
        "type": "SSD1306",
        "width": 128,
        "height": 64,
        "i2c_address": 0x3C,  # SSD1306 default (RTC is 0x68; no conflict)
        "enabled": True,  # Master enable/disable (False = skip display init)
        "refresh_interval_s": 5,  # How often to re-render the current menu
        "stats_window_s": 3600,  # Look-back window for temp/hum hi/lo/avg stats
        "max_history": 120,  # Max readings to keep for stats (120 × 30 s ≈ 1 h)
        "menu_timeout_s": 30,  # Return to default menu after this many seconds of inactivity
        "display_timeout_s": 120,  # Turn off display after this many seconds of inactivity (extends OLED lifetime)
        "startup_banner_s": 2.0,  # How long to show the "Pi Greenhouse / Ready!" banner at init
        "vram_clear_delay_s": 0.05,  # Per-step delay during the triple-clear sequence at init
        "invert_delay_s": 0.1,  # Delay after invert/revert and final clear at init
    },
    # Output Pin Initial States
    "output_pins": {
        "relay_fan_1": True,  # HIGH = off (relay module inverted logic)
        "relay_fan_2": True,  # HIGH = off (relay module inverted logic)
        "relay_growlight": True,  # HIGH = off (relay module inverted logic)
        "activity_led": False,  # LOW = off (active high LED)
        "reminder_led": False,  # LOW = off (active high LED)
        "sd_led": False,  # LOW = off (active high LED)
        "warning_led": False,  # LOW = off (active high LED)
        "error_led": False,  # LOW = off (active high LED)
        "onboard_led": False,  # LOW = off (active high LED)
    },
    # System Configuration
    "system": {
        "require_sd_startup": False,  # If True, system won't start without SD; if False, runs with buffering only # noqa: E501
        "button_debounce_ms": 60,  # Debounce delay for button presses
        "long_press_ms": 3000,  # Long-press threshold for menu action button
        "health_check_interval_s": 60,  # Normal health-check loop interval
        "sd_recovery_interval_s": 10,  # Fast retry interval when SD is unavailable
        "i2c_freq": 400000,  # I2C bus frequency in Hz (100 kHz standard, 400 kHz fast)
        "sd_power_up_ms": 250,  # SD card power-up stabilization delay (ms)
        "sd_mount_retries": 3,  # Number of SD mount attempts at cold boot
        "sd_retry_delay_ms": 500,  # Delay between SD mount retries (ms)
        "rtc_sync_interval_s": 3600,  # RTC-to-Pico clock sync interval (seconds)
        "button_poll_ms": 50,  # Button ISR flag polling interval (ms)
        "watchdog_timeout_ms": 8000,  # Watchdog timeout (ms); RP2040 max is ~8388ms
        "watchdog_feed_interval_ms": 2000,  # Feed watchdog every N ms (must be < timeout)
        # Write Queue Configuration (async SD write batching)
        "write_queue_max_size": 500,  # Max queue entries before overflow to fallback
        "queue_drain_interval_ms": 100,  # Milliseconds between drain cycles
        "queue_batch_size": 5,  # Max writes per drain cycle
        "sd_recovery_max_consecutive_failures": 5,  # Max failures before giving up in recovery attempt
    },
    # Software Updater Configuration (SD-payload self-update; see lib/updater.py)
    #
    # Operator drops a payload tree under update_dir on the SD card:
    #   <update_dir>/manifest.json           — {version, files: [{path, sha256, bytes}, ...]}
    #   <update_dir>/main.py                 — replaces /main.py
    #   <update_dir>/config.py               — replaces /config.py
    #   <update_dir>/lib/<file>.py           — replaces /lib/<file>.py
    #
    # On boot, main.py calls run_pending_update() BEFORE EventLogger init.
    # The updater verifies every file (SHA-256) before writing any, retries
    # per-file writes up to max_retries on failure, renames update_dir →
    # applied_dir/<version>/ on success, appends to log_path, then calls
    # machine.reset(). Set enabled=False to skip the boot-time check entirely.
    "updater": {
        "enabled": True,
        "update_dir": "/sd/update",
        "applied_dir": "/sd/applied",
        "log_path": "/sd/updates.log",
        "max_retries": 3,  # Per-file write retry count on apply failure
        "retry_delay_ms": 200,  # Delay between write retries (ms)
        "allowed_paths": ["main.py", "config.py", "config.mpy", "lib/"],  # Whitelist; anything outside fails verify
    },
}


def validate_config():
    """
    Validate configuration dictionary at startup.

    Checks for required keys and reasonable value ranges.
    Raises ValueError with descriptive message if validation fails.

    Returns:
        bool: True if config is valid

    Raises:
        ValueError: If required keys are missing or values out of range
    """
    required_keys = {
        "pins": [
            "activity_led",
            "reminder_led",
            "sd_led",
            "warning_led",
            "error_led",
            "onboard_led",
            "button_menu",
            "button_reserved",
            "rtc_i2c_port",
            "rtc_sda",
            "rtc_scl",
            "relay_fan_1",
            "relay_fan_2",
            "relay_growlight",
            "relay_reserved_1",
            "relay_reserved_2",
            "relay_reserved_3",
            "relay_reserved_4",
            "co2_uart_id",
            "co2_uart_tx",
            "co2_uart_rx",
            "co2_baudrate",
            "buzzer",
            "heater_mosfet",
            "gp2_breakout",
            "adc_input",
        ],
        "spi": ["id", "baudrate", "sck", "mosi", "miso", "cs", "mount_point"],
        "files": ["th_log_base", "system_log", "fallback_path"],
        "sht31": ["i2c_address"],
        "temp_humidity_logger": ["interval_s", "max_retries", "max_buffer_size", "retry_delay_s"],
        "fan_1": [
            "interval_s",
            "on_time_s",
            "max_temp",
            "temp_hysteresis",
            "poll_interval_s",
        ],
        "fan_2": [
            "interval_s",
            "on_time_s",
            "max_temp",
            "temp_hysteresis",
            "poll_interval_s",
        ],
        "heater": [
            "day_min_temp",
            "night_min_temp",
            "temp_hysteresis",
            "day_offset_min",
            "night_offset_min",
            "max_stale_reads",
            "poll_interval_s",
        ],
        "co2_logger": [
            "interval_s",
            "warmup_s",
            "max_retries",
            "override_ppm_on",
            "override_ppm_off",
            "override_fan",
            "filename_base",
        ],
        "soil_logger": [
            "interval_s",
            "adc_dry_raw",
            "adc_wet_raw",
            "warn_pct_below",
            "filename_base",
        ],
        "growlight": [
            "mode",
            "dawn_hour",
            "dawn_minute",
            "sunset_hour",
            "sunset_minute",
            "poll_interval_s",
            "dac_i2c_address",
            "default_level_pct",
            "max_level_pct",
            "min_level_pct",
            "ramp_duration_s",
        ],
        "Service_reminder": [
            "days_interval",
            "blink_pattern_ms",
            "blink_after_days",
            "storage_path",
            "monitor_interval_s",
        ],
        "buzzer": ["enabled", "default_freq", "default_duty_pct"],
        "buffer_manager": ["sd_mount_point", "fallback_path", "max_buffer_entries", "max_fallback_size_kb"],
        "event_logger": [
            "logfile",
            "max_size",
            "debug_max_size",
            "info_flush_threshold",
            "warn_flush_threshold",
            "log_level",
            "debug_enabled",
            "debug_to_file",
            "debug_flush_threshold",
        ],
        "output_pins": [
            "relay_fan_1",
            "relay_fan_2",
            "relay_growlight",
            "activity_led",
            "reminder_led",
            "sd_led",
            "warning_led",
            "error_led",
            "onboard_led",
        ],
        "status_leds": [
            "activity_blink_ms",
            "heartbeat_interval_ms",
            "th_warn_threshold",
            "th_error_threshold",
            "rtc_min_year",
            "rtc_max_year",
            "walk_order",
            "mem_warning_pct",
            "mem_error_pct",
        ],
        "display": [
            "type",
            "width",
            "height",
            "i2c_address",
            "enabled",
            "refresh_interval_s",
            "stats_window_s",
            "max_history",
            "menu_timeout_s",
            "startup_banner_s",
            "vram_clear_delay_s",
            "invert_delay_s",
        ],
        "updater": [
            "enabled",
            "update_dir",
            "applied_dir",
            "log_path",
            "max_retries",
            "retry_delay_ms",
            "allowed_paths",
        ],
        "system": [
            "require_sd_startup",
            "button_debounce_ms",
            "long_press_ms",
            "health_check_interval_s",
            "sd_recovery_interval_s",
            "i2c_freq",
            "sd_power_up_ms",
            "sd_mount_retries",
            "sd_retry_delay_ms",
            "rtc_sync_interval_s",
            "button_poll_ms",
            "watchdog_timeout_ms",
            "watchdog_feed_interval_ms",
            "write_queue_max_size",
            "queue_drain_interval_ms",
            "queue_batch_size",
            "sd_recovery_max_consecutive_failures",
        ],
    }

    # Check all required sections and keys exist
    for section, keys in required_keys.items():
        if section not in DEVICE_CONFIG:
            raise ValueError(f"Missing config section: {section}")
        for key in keys:
            if key not in DEVICE_CONFIG[section]:
                raise ValueError(f"Missing config key: {section}.{key}")

    # Validate value ranges
    if DEVICE_CONFIG["temp_humidity_logger"]["interval_s"] <= 0:
        raise ValueError("temp_humidity_logger.interval_s must be > 0")

    sht31_addr = DEVICE_CONFIG["sht31"]["i2c_address"]
    if not isinstance(sht31_addr, int) or sht31_addr not in (0x44, 0x45):
        raise ValueError("sht31.i2c_address must be 0x44 or 0x45")

    if DEVICE_CONFIG["fan_1"]["on_time_s"] <= 0 or DEVICE_CONFIG["fan_1"]["interval_s"] <= 0:
        raise ValueError("fan_1 timing values must be > 0")

    if DEVICE_CONFIG["fan_2"]["on_time_s"] <= 0 or DEVICE_CONFIG["fan_2"]["interval_s"] <= 0:
        raise ValueError("fan_2 timing values must be > 0")

    if DEVICE_CONFIG["Service_reminder"]["days_interval"] <= 0:
        raise ValueError("Service_reminder.days_interval must be > 0")

    if DEVICE_CONFIG["buzzer"]["default_freq"] <= 0:
        raise ValueError("buzzer.default_freq must be > 0")

    if not (0 < DEVICE_CONFIG["buzzer"]["default_duty_pct"] <= 100):
        raise ValueError("buzzer.default_duty_pct must be 1–100")

    if DEVICE_CONFIG["buffer_manager"]["max_buffer_entries"] <= 0:
        raise ValueError("buffer_manager.max_buffer_entries must be > 0")

    if DEVICE_CONFIG["buffer_manager"]["max_fallback_size_kb"] < 10:
        raise ValueError("buffer_manager.max_fallback_size_kb must be >= 10 (KB)")

    if DEVICE_CONFIG["event_logger"]["max_size"] <= 0:
        raise ValueError("event_logger.max_size must be > 0")

    if DEVICE_CONFIG["event_logger"]["debug_max_size"] <= 0:
        raise ValueError("event_logger.debug_max_size must be > 0")

    if DEVICE_CONFIG["event_logger"]["info_flush_threshold"] < 1:
        raise ValueError("event_logger.info_flush_threshold must be >= 1")

    if DEVICE_CONFIG["event_logger"]["warn_flush_threshold"] < 1:
        raise ValueError("event_logger.warn_flush_threshold must be >= 1")

    if DEVICE_CONFIG["event_logger"]["log_level"] not in (
        "DEBUG",
        "INFO",
        "WARN",
        "ERR",
    ):
        raise ValueError("event_logger.log_level must be one of: DEBUG, INFO, WARN, ERR")

    if not isinstance(DEVICE_CONFIG["event_logger"]["debug_enabled"], bool):
        raise ValueError("event_logger.debug_enabled must be a bool")

    if not isinstance(DEVICE_CONFIG["event_logger"]["debug_to_file"], bool):
        raise ValueError("event_logger.debug_to_file must be a bool")

    if DEVICE_CONFIG["event_logger"]["debug_flush_threshold"] < 1:
        raise ValueError("event_logger.debug_flush_threshold must be >= 1")

    if DEVICE_CONFIG["temp_humidity_logger"]["retry_delay_s"] <= 0:
        raise ValueError("temp_humidity_logger.retry_delay_s must be > 0")

    for fan_key in ("fan_1", "fan_2"):
        if DEVICE_CONFIG[fan_key]["poll_interval_s"] <= 0:
            raise ValueError(f"{fan_key}.poll_interval_s must be > 0")

    if DEVICE_CONFIG["growlight"]["poll_interval_s"] <= 0:
        raise ValueError("growlight.poll_interval_s must be > 0")

    heater_cfg = DEVICE_CONFIG["heater"]
    if heater_cfg["temp_hysteresis"] < 0:
        raise ValueError("heater.temp_hysteresis must be >= 0")
    if heater_cfg["poll_interval_s"] <= 0:
        raise ValueError("heater.poll_interval_s must be > 0")
    if heater_cfg["max_stale_reads"] < 0:
        raise ValueError("heater.max_stale_reads must be >= 0")
    if heater_cfg["day_min_temp"] < heater_cfg["night_min_temp"]:
        raise ValueError("heater.day_min_temp must be >= night_min_temp")

    co2_cfg = DEVICE_CONFIG["co2_logger"]
    if co2_cfg["interval_s"] <= 0:
        raise ValueError("co2_logger.interval_s must be > 0")
    if co2_cfg["warmup_s"] < 0:
        raise ValueError("co2_logger.warmup_s must be >= 0")
    if co2_cfg["max_retries"] < 1:
        raise ValueError("co2_logger.max_retries must be >= 1")
    if co2_cfg["override_ppm_on"] <= co2_cfg["override_ppm_off"]:
        raise ValueError("co2_logger.override_ppm_on must be > override_ppm_off")
    if co2_cfg["override_ppm_off"] < 0:
        raise ValueError("co2_logger.override_ppm_off must be >= 0")
    if co2_cfg["override_fan"] not in ("fan_1", "fan_2"):
        raise ValueError("co2_logger.override_fan must be 'fan_1' or 'fan_2'")
    if not isinstance(co2_cfg["filename_base"], str) or not co2_cfg["filename_base"]:
        raise ValueError("co2_logger.filename_base must be a non-empty string")

    soil_cfg = DEVICE_CONFIG["soil_logger"]
    if soil_cfg["interval_s"] <= 0:
        raise ValueError("soil_logger.interval_s must be > 0")
    if not isinstance(soil_cfg["adc_dry_raw"], int) or not (0 <= soil_cfg["adc_dry_raw"] <= 1023):
        raise ValueError("soil_logger.adc_dry_raw must be an int 0-1023")
    if not isinstance(soil_cfg["adc_wet_raw"], int) or not (0 <= soil_cfg["adc_wet_raw"] <= 1023):
        raise ValueError("soil_logger.adc_wet_raw must be an int 0-1023")
    if soil_cfg["adc_dry_raw"] <= soil_cfg["adc_wet_raw"]:
        raise ValueError("soil_logger.adc_dry_raw must be > adc_wet_raw")
    if not (0 <= soil_cfg["warn_pct_below"] <= 100):
        raise ValueError("soil_logger.warn_pct_below must be 0-100")
    if not isinstance(soil_cfg["filename_base"], str) or not soil_cfg["filename_base"]:
        raise ValueError("soil_logger.filename_base must be a non-empty string")

    disp_cfg = DEVICE_CONFIG["display"]
    for delay_key in ("startup_banner_s", "vram_clear_delay_s", "invert_delay_s"):
        if not isinstance(disp_cfg[delay_key], (int, float)) or disp_cfg[delay_key] < 0:
            raise ValueError(f"display.{delay_key} must be a number >= 0")

    dac_addr = DEVICE_CONFIG["growlight"]["dac_i2c_address"]
    if not isinstance(dac_addr, int) or not (0x08 <= dac_addr <= 0x77):
        raise ValueError("growlight.dac_i2c_address must be a 7-bit I2C address (0x08-0x77)")

    gl_cfg = DEVICE_CONFIG["growlight"]
    if gl_cfg["mode"] not in ("dimmed", "relay_only"):
        raise ValueError("growlight.mode must be 'dimmed' or 'relay_only'")
    for key in ("default_level_pct", "max_level_pct", "min_level_pct"):
        v = gl_cfg[key]
        if not isinstance(v, (int, float)) or not (0 <= v <= 100):
            raise ValueError(f"growlight.{key} must be 0-100")
    if gl_cfg["min_level_pct"] > gl_cfg["max_level_pct"]:
        raise ValueError("growlight.min_level_pct must be <= max_level_pct")
    if gl_cfg["default_level_pct"] > gl_cfg["max_level_pct"]:
        raise ValueError("growlight.default_level_pct must be <= max_level_pct")
    if gl_cfg["ramp_duration_s"] < 0:
        raise ValueError("growlight.ramp_duration_s must be >= 0")

    if DEVICE_CONFIG["Service_reminder"]["blink_after_days"] < 0:
        raise ValueError("Service_reminder.blink_after_days must be >= 0")

    if DEVICE_CONFIG["Service_reminder"]["monitor_interval_s"] <= 0:
        raise ValueError("Service_reminder.monitor_interval_s must be > 0")

    sys_cfg = DEVICE_CONFIG["system"]
    if sys_cfg["i2c_freq"] <= 0:
        raise ValueError("system.i2c_freq must be > 0")

    if sys_cfg["button_debounce_ms"] < 0:
        raise ValueError("system.button_debounce_ms must be >= 0")

    if sys_cfg["long_press_ms"] <= 0:
        raise ValueError("system.long_press_ms must be > 0")

    if sys_cfg["sd_mount_retries"] < 1:
        raise ValueError("system.sd_mount_retries must be >= 1")

    if sys_cfg["rtc_sync_interval_s"] <= 0:
        raise ValueError("system.rtc_sync_interval_s must be > 0")

    if sys_cfg["button_poll_ms"] <= 0:
        raise ValueError("system.button_poll_ms must be > 0")

    if sys_cfg["watchdog_timeout_ms"] < 1000 or sys_cfg["watchdog_timeout_ms"] > 8388:
        raise ValueError("system.watchdog_timeout_ms must be 1000-8388 (RP2040 hardware limit)")

    if sys_cfg["watchdog_feed_interval_ms"] <= 0:
        raise ValueError("system.watchdog_feed_interval_ms must be > 0")

    if sys_cfg["watchdog_feed_interval_ms"] >= sys_cfg["watchdog_timeout_ms"]:
        raise ValueError("system.watchdog_feed_interval_ms must be < watchdog_timeout_ms")

    # Validate write queue configuration
    if DEVICE_CONFIG["system"]["write_queue_max_size"] <= 0:
        raise ValueError("system.write_queue_max_size must be > 0")

    if DEVICE_CONFIG["system"]["queue_drain_interval_ms"] <= 0:
        raise ValueError("system.queue_drain_interval_ms must be > 0")

    if DEVICE_CONFIG["system"]["queue_batch_size"] <= 0:
        raise ValueError("system.queue_batch_size must be > 0")

    if DEVICE_CONFIG["system"]["sd_recovery_max_consecutive_failures"] <= 0:
        raise ValueError("system.sd_recovery_max_consecutive_failures must be > 0")

    # Validate status_leds.walk_order: non-empty list of unique role names
    valid_walk_roles = ("activity", "sd", "reminder", "warning", "error")
    walk = DEVICE_CONFIG["status_leds"]["walk_order"]
    if not isinstance(walk, list) or not walk:
        raise ValueError("status_leds.walk_order must be a non-empty list")
    if len(set(walk)) != len(walk):
        raise ValueError("status_leds.walk_order entries must be unique")
    for role in walk:
        if role not in valid_walk_roles:
            raise ValueError(
                f"status_leds.walk_order entries must be one of {valid_walk_roles}"
            )

    # Validate updater configuration
    upd_cfg = DEVICE_CONFIG["updater"]
    if not isinstance(upd_cfg["enabled"], bool):
        raise ValueError("updater.enabled must be a bool")
    for path_key in ("update_dir", "applied_dir", "log_path"):
        v = upd_cfg[path_key]
        if not isinstance(v, str) or not v.startswith("/"):
            raise ValueError(f"updater.{path_key} must be an absolute path string")
    if not isinstance(upd_cfg["max_retries"], int) or upd_cfg["max_retries"] < 1:
        raise ValueError("updater.max_retries must be an int >= 1")
    if not isinstance(upd_cfg["retry_delay_ms"], int) or upd_cfg["retry_delay_ms"] < 0:
        raise ValueError("updater.retry_delay_ms must be an int >= 0")
    if not isinstance(upd_cfg["allowed_paths"], list) or not upd_cfg["allowed_paths"]:
        raise ValueError("updater.allowed_paths must be a non-empty list")
    for entry in upd_cfg["allowed_paths"]:
        if not isinstance(entry, str) or not entry:
            raise ValueError("updater.allowed_paths entries must be non-empty strings")

    return True
