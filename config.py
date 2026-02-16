# Pi Greenhouse Configuration
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0
#
# Central configuration for all hardware pins, intervals, file paths, and thresholds.
# Modify values here to tune device behavior without editing module code.

DEVICE_CONFIG = {
    # Hardware Pins
    'pins': {
        'dht22': 15,                    # DHT22 data pin
        'status_led': 25,               # Status LED (feedback)
        'reminder_led': 24,             # Service reminder LED
        'button_reminder': 23,          # Button to reset Service reminder
        'rtc_i2c_port': 1,              # I2C peripheral (0 or 1)
        'rtc_sda': 2,                   # RTC I2C SDA
        'rtc_scl': 3,                   # RTC I2C SCL
        'relay_fan_1': 16,              # Fan relay 1 (primary cycle)
        'relay_fan_2': 18,              # Fan relay 2 (secondary cycle)
        'relay_growlight': 17,          # Grow light relay
        'co2_sda': 0,                   # CO2 sensor I2C SDA
        'co2_scl': 1,                   # CO2 sensor I2C SCL
        'co2_i2c_port': 0,              # CO2 sensor I2C port
    },
    
    # SPI Configuration (SD Card)
    'spi': {
        'id': 1,
        'baudrate': 40000000,
        'sck': 10,
        'mosi': 11,
        'miso': 12,
        'cs': 13,
        'mount_point': '/sd',
    },
    
    # File Paths
    'files': {
        'dht_log_base': 'dht_log',      # Will become dht_log_YYYY-MM-DD.csv
        'system_log': '/sd/system.log',
        'fallback_path': '/local/fallback.csv',  # Fallback when SD unavailable
    },
    
    # DHT Logger Configuration
    'dht_logger': {
        'interval_s': 30,               # Log interval in seconds
        'max_retries': 3,               # Sensor read retries
        'max_buffer_size': 200,         # Max in-memory readings
    },
    
    # Fan Control - Fan 1 (Time-based + Thermostat)
    'fan_1': {
        'interval_s': 600,              # Cycle interval (10 minutes)
        'on_time_s': 20,                # Time ON per cycle
        'max_temp': 23.8,               # Temperature threshold (°C)
        'temp_hysteresis': 0.5,         # Hysteresis for thermostat (°C)
    },
    
    # Fan Control - Fan 2 (Time-based + Thermostat)
    'fan_2': {
        'interval_s': 500,              # Cycle interval
        'on_time_s': 20,                # Time ON per cycle
        'max_temp': 27.0,               # Temperature threshold (°C)
        'temp_hysteresis': 0.5,         # Hysteresis for thermostat (°C)
    },
    
    # Grow Light Configuration
    'growlight': {
        'dawn_hour': 7,                 # Light ON at 7:00 AM
        'dawn_minute': 0,
        'sunset_hour': 19,              # Light OFF at 19:00 (10 PM)
        'sunset_minute': 0,
    },
    
    # Service Reminder Configuration
    'Service_reminder': {
        'days_interval': 7,             # Remind every 7 days
        'blink_pattern_ms': [2000, 2000, 2000, 2000],  # ON 200ms, OFF 200ms, ON 200ms, OFF 800ms (SOS pattern)
    },
    
    # Buffer Manager Configuration
    'buffer_manager': {
        'sd_mount_point': '/sd',
        'fallback_path': '/local/fallback.csv',
        'max_buffer_entries': 1000,
    },
    
    # Event Logger Configuration
    'event_logger': {
        'logfile': '/sd/system.log',
        'max_size': 50000,              # Max log file size (bytes) before rotation
    },
    
    # Output Pin Initial States
    'output_pins': {
        'relay_fan_1': True,            # HIGH = off (relay module inverted logic)
        'relay_fan_2': True,            # HIGH = off (relay module inverted logic)
        'relay_growlight': True,        # HIGH = off (relay module inverted logic)
        'status_led': False,            # LOW = off (active high LED)
        'reminder_led': False,          # LOW = off (active high LED)
    },
    
    # System Configuration
    'system': {
        'require_sd_startup': False,    # If True, system won't start without SD; if False, runs with buffering only
        'button_debounce_ms': 50,       # Debounce delay for button presses
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
        'pins': ['dht22', 'status_led', 'reminder_led', 'button_reminder', 
                 'rtc_i2c_port', 'rtc_sda', 'rtc_scl', 'relay_fan_1', 'relay_fan_2', 'relay_growlight'],
        'spi': ['id', 'baudrate', 'sck', 'mosi', 'miso', 'cs', 'mount_point'],
        'files': ['dht_log_base', 'system_log', 'fallback_path'],
        'dht_logger': ['interval_s', 'max_retries', 'max_buffer_size'],
        'fan_1': ['interval_s', 'on_time_s', 'max_temp', 'temp_hysteresis'],
        'fan_2': ['interval_s', 'on_time_s', 'max_temp', 'temp_hysteresis'],
        'growlight': ['dawn_hour', 'dawn_minute', 'sunset_hour', 'sunset_minute'],
        'Service_reminder': ['days_interval', 'blink_pattern_ms'],
        'buffer_manager': ['sd_mount_point', 'fallback_path', 'max_buffer_entries'],
        'event_logger': ['logfile', 'max_size'],
        'output_pins': ['relay_fan_1', 'relay_fan_2', 'relay_growlight', 'status_led', 'reminder_led'],
        'system': ['require_sd_startup', 'button_debounce_ms'],
    }
    
    # Check all required sections and keys exist
    for section, keys in required_keys.items():
        if section not in DEVICE_CONFIG:
            raise ValueError(f"Missing config section: {section}")
        for key in keys:
            if key not in DEVICE_CONFIG[section]:
                raise ValueError(f"Missing config key: {section}.{key}")
    
    # Validate value ranges
    if DEVICE_CONFIG['dht_logger']['interval_s'] <= 0:
        raise ValueError("dht_logger.interval_s must be > 0")
    
    if DEVICE_CONFIG['fan_1']['on_time_s'] <= 0 or DEVICE_CONFIG['fan_1']['interval_s'] <= 0:
        raise ValueError("fan_1 timing values must be > 0")
    
    if DEVICE_CONFIG['fan_2']['on_time_s'] <= 0 or DEVICE_CONFIG['fan_2']['interval_s'] <= 0:
        raise ValueError("fan_2 timing values must be > 0")
    
    if DEVICE_CONFIG['Service_reminder']['days_interval'] <= 0:
        raise ValueError("Service_reminder.days_interval must be > 0")
    
    if DEVICE_CONFIG['buffer_manager']['max_buffer_entries'] <= 0:
        raise ValueError("buffer_manager.max_buffer_entries must be > 0")
    
    if DEVICE_CONFIG['event_logger']['max_size'] <= 0:
        raise ValueError("event_logger.max_size must be > 0")
    
    return True
