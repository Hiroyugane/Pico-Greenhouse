# Hardware Factory - Coordinated Device Initialization
# Dennis Hiro, 2024-06-08
#
# Factory for instantiating all hardware (RTC, SPI, SD, GPIO pins) once in main(),
# then providing them to modules via dependency injection.
#
# Solves:
# - Initialization order (SD mount before BufferManager before EventLogger)
# - Global state (no module-level hardware init; all in one place)
# - Testing (factory can inject mocks instead of real hardware)

import os
import time
import sys
import machine
from machine import Pin, SPI, I2C

from config import DEVICE_CONFIG
from lib import ds3231, sdcard
from lib.sd_integration import mount_sd, is_mounted

# Patchable flag: False when running on the Pico, True on host/CPython.
_IS_HOST = (sys.implementation.name != 'micropython')


class HardwareFactory:
    """
    Factory for creating and managing all hardware instances.
    
    Coordinates initialization order:
    1. RTC (I2C)
    2. SPI + SD Card (mount)
    3. GPIO pins (relay, LED, button)
    
    Provides graceful fallback if hardware unavailable.
    Returns hardware instances for dependency injection.
    
    Attributes:
        config (dict): Device configuration from config.py
        i2c1 (machine.I2C): Shared I2C1 bus (RTC + OLED display)
        rtc (ds3231.RTC): Real-time clock instance
        spi (machine.SPI): SPI bus for SD card
        sd (sdcard.SDCard): SD card driver
        sd_mounted (bool): Whether SD mount succeeded
        pins (dict): GPIO pin instances {name: Pin}
        errors (list): Errors encountered during initialization
    """
    
    def __init__(self, config=None):
        """
        Initialize hardware factory with configuration.
        
        Does not attempt hardware init here; call setup() to perform it.
        
        Args:
            config (dict, optional): Device configuration (default: DEVICE_CONFIG from config.py)
        """
        self.config = config or DEVICE_CONFIG
        self.i2c1 = None
        self.rtc = None
        self.spi = None
        self.sd = None
        self.sd_mounted = False
        self.pins = {}
        self.errors = []
    
    def setup(self) -> bool:
        """
        Perform all hardware initialization.
        
        Initializes in order:
        1. I2C1 bus (shared: RTC + OLED)
        2. RTC (via shared I2C1)
        3. SPI
        4. SD card mount
        5. GPIO pins (output: relays, LEDs; input: buttons)
        
        Prints status to console (fallback when logging not yet ready).
        Stores errors for later inspection via get_errors().
        
        Returns:
            bool: True if critical hardware initialized (RTC), False if RTC fails
        """
        print('[HardwareFactory] Starting initialization...')
        
        # Step 1: Initialize shared I2C bus
        self._init_i2c()
        
        # Step 2: Initialize RTC (critical for timestamps)
        if not self._init_rtc():
            print('[HardwareFactory] ERROR: RTC initialization failed')
            return False
        print('[HardwareFactory] RTC initialized')
        
        # Step 3: Initialize SPI + SD Card
        self._init_spi()
        self._init_sd()
        
        # Step 4: Initialize GPIO pins
        self._init_pins()
        
        print(f'[HardwareFactory] Setup complete. Errors: {len(self.errors)}')
        return True
    
    def _init_i2c(self) -> bool:
        """
        Initialize shared I2C1 bus for RTC and OLED display.
        
        Creates a single I2C instance on the configured port/pins
        that will be shared between the DS3231 RTC (0x68) and the
        SSD1306 OLED display (0x3C).
        
        Returns True on success, False on failure (non-fatal).
        """
        try:
            pins = self.config.get('pins', {})
            i2c_port = pins.get('rtc_i2c_port', 1)
            sda = pins.get('rtc_sda', 2)
            scl = pins.get('rtc_scl', 3)
            
            self.i2c1 = I2C(i2c_port, sda=Pin(sda), scl=Pin(scl), freq=100000)
            return True
        except Exception as e:
            self.errors.append(f'I2C1 init failed: {e}')
            return False
    
    def _init_rtc(self) -> bool:
        """
        Initialize RTC via shared I2C1 bus.
        
        Uses the pre-built self.i2c1 instance if available,
        otherwise falls back to letting the driver create its own.
        
        Returns True on success, False on failure.
        """
        try:
            pins = self.config.get('pins', {})
            
            if self.i2c1 is not None:
                self.rtc = ds3231.RTC(i2c=self.i2c1)
            else:
                i2c_port = pins.get('rtc_i2c_port', 0)
                sda = pins.get('rtc_sda', 0)
                scl = pins.get('rtc_scl', 1)
                self.rtc = ds3231.RTC(sda_pin=sda, scl_pin=scl, port=i2c_port)
            
            # Verify RTC is responding
            result = self.rtc.ReadTime(1)
            if isinstance(result, tuple) and len(result) >= 7:
                return True
            else:
                self.errors.append('RTC not responding to ReadTime()')
                return False
        except Exception as e:
            self.errors.append(f'RTC init failed: {e}')
            return False
    
    def _init_spi(self) -> bool:
        """
        Initialize SPI bus for SD card.
        
        Returns True on success, False on failure.
        """
        try:
            spi_config = self.config.get('spi', {})
            spi_id = spi_config.get('id', 1)
            baudrate = spi_config.get('baudrate', 40000000)
            sck = spi_config.get('sck', 10)
            mosi = spi_config.get('mosi', 11)
            miso = spi_config.get('miso', 12)
            
            self.spi = SPI(
                spi_id,
                baudrate=baudrate,
                sck=Pin(sck),
                mosi=Pin(mosi),
                miso=Pin(miso)
            )
            return True
        except Exception as e:
            self.errors.append(f'SPI init failed: {e}')
            return False
    
    def _init_sd(self) -> bool:
        """
        Initialize and mount SD card.
        
        Adds a power-up stabilization delay and retry logic for cold boot
        scenarios where the SD card may not be ready immediately.
        
        Returns True if mounted, False otherwise (non-fatal; system can run with fallback).
        """
        try:
            if _IS_HOST:
                # Simulate SD availability on host
                mount_point = self.config.get('spi', {}).get('mount_point', '/sd')
                try:
                    os.makedirs(mount_point, exist_ok=True)
                except Exception:
                    pass
                self.sd_mounted = True
                return True
            if not self.spi:
                self.errors.append('SPI not initialized; skipping SD init')
                return False
            
            spi_config = self.config.get('spi', {})
            cs = spi_config.get('cs', 13)
            mount_point = spi_config.get('mount_point', '/sd')
            
            # Allow the SD card to stabilize after power-on before
            # attempting SPI initialization (cold-boot timing).
            time.sleep_ms(250)
            
            # Retry mount up to 3 times for cards that need extra
            # power-up time on standalone (non-Thonny) boot.
            max_retries = 3
            for attempt in range(max_retries):
                ok, sd = mount_sd(self.spi, cs, mount_point)
                if ok:
                    self.sd = sd
                    self.sd_mounted = True
                    return True
                if attempt < max_retries - 1:
                    print(f'[HardwareFactory] SD mount attempt {attempt + 1} failed, retrying...')
                    time.sleep_ms(500)
            
            self.errors.append('SD card mount failed after retries (will use fallback buffering)')
            return False
        except Exception as e:
            self.errors.append(f'SD init failed: {e}')
            return False
    
    def _init_pins(self) -> bool:
        """
        Initialize all GPIO pins (relays, LEDs, buttons).
        
        Sets output pins to initial states from config.py output_pins section.
        Configures input pins (buttons) for interrupts.
        
        Returns True if all pins initialized (non-fatal if some fail).
        """
        try:
            pins_config = self.config.get('pins', {})
            output_pins_config = self.config.get('output_pins', {})
            
            # Output pins: relays, LEDs (initialize to state specified in config)
            for pin_name, initial_high in output_pins_config.items():
                if pin_name in pins_config:
                    pin_num = pins_config[pin_name]
                    try:
                        pin = Pin(pin_num, Pin.OUT)
                        pin.value(1 if initial_high else 0)
                        self.pins[pin_name] = pin
                    except Exception as e:
                        self.errors.append(f'Failed to init output pin {pin_name}: {e}')
            
            # Input pins: buttons (menu + reserved)
            for button_name in ('button_menu', 'button_reserved'):
                if button_name in pins_config:
                    try:
                        pin_num = pins_config[button_name]
                        button = Pin(pin_num, Pin.IN, Pin.PULL_UP)
                        self.pins[button_name] = button
                    except Exception as e:
                        self.errors.append(f'Failed to init button pin {button_name}: {e}')
            
            return True
        except Exception as e:
            self.errors.append(f'Pin initialization failed: {e}')
            return False
    
    def get_rtc(self):
        """Return RTC instance (or None if init failed)."""
        return self.rtc
    
    def get_pin(self, name: str):
        """
        Get GPIO pin by name.
        
        Args:
            name (str): Pin name from config (e.g., 'relay_fan_1', 'reminder_led')
        
        Returns:
            Pin: machine.Pin instance or None if not initialized
        """
        return self.pins.get(name)
    
    def get_all_pins(self) -> dict:
        """Return all initialized GPIO pins."""
        return self.pins.copy()
    
    def is_sd_mounted(self) -> bool:
        """Return whether SD card is currently mounted."""
        return self.sd_mounted

    def refresh_sd(self) -> bool:
        """
        Re-check SD availability and refresh SD/SPI instances if reinitialized.

        Returns True if SD is accessible after refresh, False otherwise.
        """
        try:
            result = is_mounted(self.sd, self.spi, return_instances=True)
            if isinstance(result, tuple) and len(result) == 3:
                ok, sd, spi = result
                self.sd = sd
                self.spi = spi
                self.sd_mounted = ok
                return ok

            self.sd_mounted = bool(result)
            return self.sd_mounted
        except Exception as e:
            self.errors.append(f'SD refresh failed: {e}')
            self.sd_mounted = False
            return False
    
    def get_errors(self) -> list:
        """Return list of initialization errors encountered."""
        return self.errors.copy()
    
    def print_status(self):
        """Print human-readable initialization status to console."""
        print('[HardwareFactory] Status Report:')
        print(f'  RTC: {"OK" if self.rtc else "FAILED"}')
        print(f'  SD: {"MOUNTED" if self.sd_mounted else "FAILED (using fallback)"}')
        print(f'  Pins initialized: {len(self.pins)}')
        if self.errors:
            print('  Errors:')
            for err in self.errors:
                print(f'    - {err}')
        else:
            print('  No errors')
