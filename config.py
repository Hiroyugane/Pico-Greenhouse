# Pi Greenhouse Configuration
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0
#
# Central configuration for all hardware pins, intervals, file paths, and thresholds.
# Modify values here to tune device behavior without editing module code.

DEVICE_CONFIG = {
    # Hardware Pins
    #
    # Pico GPIO layout (active header pins only):
    #   GP0-GP1:   CO2 sensor UART0 (TX/RX)
    #   GP2-GP3:   I2C1 bus (RTC + OLED display, shared)
    #   GP4:       Activity LED (brief blink on I/O actions)
    #   GP5:       Service-reminder LED (blinks when due)
    #   GP6:       SD-problem LED (solid = SD missing/failed)
    #   GP7:       Warning LED (solid = degraded condition)
    #   GP8:       Error LED (solid = fault needs attention)
    #   GP9:       Menu button (short=cycle, long=action)
    #   GP10-GP13: SPI1 (SD card)
    #   GP14:      Reserved button (future use)
    #   GP15:      DHT22 data
    #   GP16-GP18: Relay outputs (fans + growlight)
    #   GP19:      Reserved (future relay)
    #   GP20:      Passive buzzer (PWM)
    #   GP21-GP22: Reserved (future relays / PWM fan)
    #   GP25:      On-board LED (heartbeat)
    #   GP26-GP28: Reserved ADC (analog sensors)
    "pins": {
        "dht22": 15,  # DHT22 data pin
        "onboard_led": 25,  # Pico on-board LED (heartbeat)
        "activity_led": 4,  # Activity LED (brief blink on I/O actions)
        "reminder_led": 5,  # Service-reminder LED (blinks when due)
        "sd_led": 6,  # SD-problem LED (solid = SD missing/failed)
        "warning_led": 7,  # Warning LED (solid = degraded condition)
        "error_led": 8,  # Error LED (solid = fault needs attention)
        "button_menu": 9,  # Menu button (short=cycle menu, long≥3s=action)
        "button_reserved": 14,  # Reserved button (future use)
        "rtc_i2c_port": 0,  # I2C1 peripheral (shared: RTC + OLED)
        "rtc_sda": 0,  # I2C1 SDA
        "rtc_scl": 1,  # I2C1 SCL
        "relay_fan_1": 16,  # Fan relay 1 (primary cycle)
        "relay_fan_2": 18,  # Fan relay 2 (secondary cycle)
        "relay_growlight": 17,  # Grow light relay
        "co2_uart_id": 1,  # CO2 sensor UART peripheral
        "co2_uart_tx": 2,  # CO2 sensor UART TX (GP0)
        "co2_uart_rx": 3,  # CO2 sensor UART RX (GP1)
        "co2_baudrate": 9600,  # CO2 sensor UART baudrate
        "buzzer": 20,  # Passive buzzer (PWM output)
    },
    # SPI Configuration (SD Card)
    "spi": {
        "id": 1,
        "baudrate": 40000000,
        "sck": 10,
        "mosi": 11,
        "miso": 12,
        "cs": 13,
        "mount_point": "/sd",
    },
    # File Paths
    "files": {
        "dht_log_base": "dht_log",  # Will become dht_log_YYYY-MM-DD.csv
        "system_log": "/sd/system.log",
        "fallback_path": "/local/fallback.csv",  # Fallback when SD unavailable
    },
    # DHT Logger Configuration
    "dht_logger": {
        "interval_s": 30,  # Log interval in seconds
        "max_retries": 3,  # Sensor read retries
        "max_buffer_size": 200,  # Max in-memory readings
    },
    # Fan Control - Fan 1 (Time-based + Thermostat)
    "fan_1": {
        "interval_s": 600,  # Cycle interval (10 minutes)
        "on_time_s": 20,  # Time ON per cycle
        "max_temp": 23.8,  # Temperature threshold (°C)
        "temp_hysteresis": 0.5,  # Hysteresis for thermostat (°C)
    },
    # Fan Control - Fan 2 (Time-based + Thermostat)
    "fan_2": {
        "interval_s": 500,  # Cycle interval
        "on_time_s": 20,  # Time ON per cycle
        "max_temp": 27.0,  # Temperature threshold (°C)
        "temp_hysteresis": 0.5,  # Hysteresis for thermostat (°C)
    },
    # Grow Light Configuration
    "growlight": {
        "dawn_hour": 7,  # Light ON at 7:00 AM
        "dawn_minute": 0,
        "sunset_hour": 19,  # Light OFF at 19:00 (10 PM)
        "sunset_minute": 0,
    },
    # Service Reminder Configuration
    "Service_reminder": {
        "days_interval": 7,  # Remind every 7 days
        "blink_pattern_ms": [200, 200, 200, 800],  # ON 200ms, OFF 200ms, ON 200ms, OFF 800ms
    },
    # Status LED Manager Configuration
    # Design: solid = problem, blink = activity, dark = all good
    "status_leds": {
        "activity_blink_ms": 50,  # Activity LED pulse duration (ms)
        "heartbeat_interval_ms": 2000,  # GP25 toggle period (ms)
        "dht_warn_threshold": 3,  # Consecutive DHT failures → warning
        "dht_error_threshold": 10,  # Consecutive DHT failures → error
        "rtc_min_year": 2025,  # Year below this → RTC invalid warning
        "rtc_max_year": 2035,  # Year above this → RTC invalid warning
        "post_enabled": True,  # Run LED power-on self-test at startup
        "post_step_ms": 150,  # Duration each LED stays on during POST walk (ms)
    },
    # Buffer Manager Configuration
    "buffer_manager": {
        "sd_mount_point": "/sd",
        "fallback_path": "/local/fallback.csv",
        "max_buffer_entries": 200,  # Reduced from 1000 to limit RAM on Pico (264KB)
    },
    # Event Logger Configuration
    "event_logger": {
        "logfile": "/sd/system.log",
        "max_size": 50000,  # Max log file size (bytes) before rotation
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
        "button_debounce_ms": 200,  # Debounce delay for button presses
        "long_press_ms": 3000,  # Long-press threshold for menu action button
        "health_check_interval_s": 60,  # Normal health-check loop interval
        "sd_recovery_interval_s": 10,  # Fast retry interval when SD is unavailable
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
            "dht22",
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
            "co2_uart_id",
            "co2_uart_tx",
            "co2_uart_rx",
            "co2_baudrate",
            "buzzer",
        ],
        "spi": ["id", "baudrate", "sck", "mosi", "miso", "cs", "mount_point"],
        "files": ["dht_log_base", "system_log", "fallback_path"],
        "dht_logger": ["interval_s", "max_retries", "max_buffer_size"],
        "fan_1": ["interval_s", "on_time_s", "max_temp", "temp_hysteresis"],
        "fan_2": ["interval_s", "on_time_s", "max_temp", "temp_hysteresis"],
        "growlight": ["dawn_hour", "dawn_minute", "sunset_hour", "sunset_minute"],
        "Service_reminder": ["days_interval", "blink_pattern_ms"],
        "buzzer": ["enabled", "default_freq", "default_duty_pct"],
        "buffer_manager": ["sd_mount_point", "fallback_path", "max_buffer_entries"],
        "event_logger": ["logfile", "max_size"],
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
            "dht_warn_threshold",
            "dht_error_threshold",
            "rtc_min_year",
            "rtc_max_year",
        ],
        "display": ["type", "width", "height", "i2c_address"],
        "system": [
            "require_sd_startup",
            "button_debounce_ms",
            "long_press_ms",
            "health_check_interval_s",
            "sd_recovery_interval_s",
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
    if DEVICE_CONFIG["dht_logger"]["interval_s"] <= 0:
        raise ValueError("dht_logger.interval_s must be > 0")

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

    if DEVICE_CONFIG["event_logger"]["max_size"] <= 0:
        raise ValueError("event_logger.max_size must be > 0")

    return True
