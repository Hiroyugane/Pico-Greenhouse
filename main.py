# Pi Pico DHT22 Library
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0

# Pi Pico CSV Library
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0

# HOW TO RUN: First, check all connections on pi:
#
# SPI SD-Card Reader 
# 	MISO → GP12 (Pin 16)
# 	MOSI → GP11 (Pin 15)
# 	SCK → GP10 (Pin 14)
# 	CS → GP13 (Pin 17)
# 	VCC → 3.3 V (oder 5 V, je nach SD-Modul!)
# 	GND → GND
# DHT22:
# 	DATA → GP15 (Pin 21)
# 	VCC → 3.3 V
# 	GND → GND
# DS3231 (RTC-Modul)
# 	SDA → GP0 (Pin 1)
# 	SCL → GP1 (Pin 2)
# 	VCC → 3.3 V
# 	GND → GND
#
# Then: Run thonny, run current script "rtc_set_time.py".
# Afterwards, run current script "main.py".
# unplug and check if data is written on sd-card with current timestamp

import uasyncio as asyncio
import dht
import machine
import time
import os
import lib.ds3231 as ds3231
from machine import Pin, SPI
from lib import sdcard


# Initialize RTC
rtc = ds3231.RTC(sda_pin=0, scl_pin=1)

# Initialize SD Card with error handling
spi=SPI(1,baudrate=40000000,sck=Pin(10),mosi=Pin(11),miso=Pin(12))
sd=sdcard.SDCard(spi,Pin(13))
try:
    os.mount(sd,'/sd')
    sd_mounted = True
    print('[STARTUP] SD card mounted successfully')
except OSError as e:
    sd_mounted = False
    # Blink LED 3 times to indicate SD card error
    led = machine.Pin(25, machine.Pin.OUT)
    for _ in range(3):
        led.on()
        time.sleep(0.3)
        led.off()
        time.sleep(0.3)
    print(f'[STARTUP ERROR] Failed to mount SD card: {e}')
    print('[STARTUP ERROR] Please insert SD card and restart the device.')


class EventLogger:
    """
    Centralized event logging system for Pi Greenhouse.
    
    Logs system events to both console (stdout) and SD card file with timestamps.
    Supports three severity levels: info, warning, error.
    Implements buffered writes for efficiency and automatic log rotation.
    
    Attributes:
        logfile (str): Path to system log file on SD card
        max_size (int): Maximum log file size before rotation (bytes)
        buffer (list): In-memory buffer for log entries (flushed periodically)
        flush_count (int): Counter of successful flush operations
    """
    def __init__(self, logfile='/sd/system.log', max_size=50000):
        """
        Initialize event logger with SD card file.
        
        Args:
            logfile (str): Path to log file (default: '/sd/system.log')
            max_size (int): Max file size before rotation in bytes (default: 50000)
        """
        self.logfile = logfile
        self.max_size = max_size
        self.buffer = []
        self.flush_count = 0
        
        try:
            # Initialize log file with header if new
            if not self._file_exists():
                with open(self.logfile, 'w') as f:
                    f.write('=== Pi Greenhouse System Log ===\n')
            print(f'[EventLogger] Initialized: {self.logfile}')
        except OSError as e:
            print(f'[EventLogger] WARNING: Could not initialize logfile: {e}')
    
    def _file_exists(self):
        try:
            with open(self.logfile, 'r'):
                return True
        except OSError:
            return False
    
    def _get_timestamp(self):
        """
        Get formatted timestamp from RTC module.
        
        Returns:
            str: Formatted timestamp 'DD.MM.YYYY HH:MM:SS' or 'TIME_ERROR' if RTC fails
        """
        try:
            time_tuple = rtc.ReadTime(1)  # (sec, min, hour, wday, day, mon, year)
            return f'{time_tuple[5]:02d}.{time_tuple[4]:02d}.{time_tuple[6]} {time_tuple[2]:02d}:{time_tuple[1]:02d}:{time_tuple[0]:02d}'
        except:
            return 'TIME_ERROR'
    
    def info(self, module, message):
        """
        Log informational message (severity: low).
        
        Args:
            module (str): Module/component name generating the log
            message (str): Log message content
        """
        timestamp = self._get_timestamp()
        log_entry = f'[{timestamp}] [INFO] [{module}] {message}\n'
        print(log_entry.rstrip())
        self.buffer.append(log_entry)
        if len(self.buffer) >= 5:
            self.flush()
    
    def warning(self, module, message):
        """Log warning message"""
        timestamp = self._get_timestamp()
        log_entry = f'[{timestamp}] [WARN] [{module}] {message}\n'
        print(log_entry.rstrip())
        self.buffer.append(log_entry)
        if len(self.buffer) >= 3:
            self.flush()
    
    def error(self, module, message):
        """Log error message"""
        timestamp = self._get_timestamp()
        log_entry = f'[{timestamp}] [ERR] [{module}] {message}\n'
        print(log_entry.rstrip())
        self.buffer.append(log_entry)
        self.flush()  # Flush errors immediately for persistence
    
    def flush(self):
        """Write all buffered log entries to SD card file."""
        if not self.buffer:
            return
        try:
            with open(self.logfile, 'a') as f:
                for entry in self.buffer:
                    f.write(entry)
            self.flush_count += 1
        except OSError as e:
            print(f'[EventLogger] ERROR writing to logfile: {e}')
        finally:
            self.buffer = []
    
    def check_size(self):
        """
        Check log file size and rotate if exceeds max_size.
        
        Renames current log to backup and creates new log file.
        Called periodically to prevent excessive disk usage.
        """
        try:
            stat = os.stat(self.logfile)
            if stat[6] > self.max_size:
                backup = self.logfile.replace('.log', '_backup.log')
                os.rename(self.logfile, backup)
                with open(self.logfile, 'w') as f:
                    f.write('=== Pi Greenhouse System Log (rotated) ===\n')
                self.info('EventLogger', f'Log rotated. Backup: {backup}')
        except OSError:
            pass


# Global logger instance
logger = EventLogger()


class DHTLogger:
    """
    DHT22 temperature/humidity sensor data logger with SD card hot-swap support.
    
    Reads DHT22 sensor on specified GPIO pin with retry logic.
    Logs timestamped readings to CSV file on SD card.
    Implements in-memory buffering when SD card is unavailable.
    Provides LED feedback for operational status.
    
    Attributes:
        dht_sensor: DHT22 sensor object
        interval (int): Logging interval in seconds
        filename (str): CSV file path on SD card
        max_retries (int): Number of retry attempts on sensor read failure
        buffer (list): In-memory buffer for readings when SD unavailable
        max_buffer_size (int): Maximum readings to buffer (overflow protection)
        read_failures (int): Counter of failed sensor reads
        write_failures (int): Counter of failed file writes
        sd_disconnected_count (int): Counter of SD card unavailability events
    """
    
    def __init__(self, pin, interval=60, filename='dht_log.csv', max_retries=3, max_buffer_size=200):
        """
        Initialize DHT22 logger with hot-swap SD card support.
        
        Args:
            pin (int): GPIO pin number for DHT22 data line
            interval (int): Seconds between log entries (default: 60)
            filename (str): CSV filename on SD card (default: 'dht_log.csv')
            max_retries (int): Sensor read retry attempts (default: 3)
            max_buffer_size (int): Max readings to buffer in-memory (default: 200)
            
        Raises:
            OSError: If SD card file initialization fails
        """
        self.dht_sensor = dht.DHT22(machine.Pin(pin))
        self.interval = interval
        self.filename = filename if filename.startswith('/sd/') else f'/sd/{filename}'
        self.max_retries = max_retries
        self.max_buffer_size = max_buffer_size
        self.buffer = []  # In-memory buffer for SD-unavailable periods
        self.read_failures = 0
        self.write_failures = 0
        self.sd_disconnected_count = 0
        
        # Validate file operations at init time
        try:
            if not self.file_exists():
                self.create_file()
            logger.info('DHTLogger', f'Initialized: {self.filename} (buffer_size={max_buffer_size})')
        except OSError as e:
            logger.error('DHTLogger', f'Init error: {e}')
            raise
    
    def _is_sd_available(self):
        """
        Check if SD card is accessible without blocking.
        
        Performs actual file access operation to detect physical disconnection.
        Uses listdir() instead of just stat() to catch removed cards.
        
        Returns:
            bool: True if SD card is mounted and accessible, False otherwise
        """
        try:
            os.listdir('/sd')
            return True
        except OSError:
            return False
    
    def file_exists(self):
        """Check if CSV log file exists on SD card."""
        try:
            with open(self.filename, 'r'):
                return True
        except OSError:
            return False
    
    def create_file(self):
        """
        Create new CSV file with standard header.
        
        Header format: 'Timestamp,Temperature,Humidity\n'
        
        Raises:
            OSError: If file creation fails on SD card
        """
        try:
            with open(self.filename, 'w') as f:
                f.write('Timestamp,Temperature,Humidity\n')
            logger.info('DHTLogger', f'Created CSV file: {self.filename}')
        except OSError as e:
            logger.error('DHTLogger', f'Failed to create file: {e}')
            raise
    
    def read_sensor(self):
        """
        Read temperature and humidity from DHT22 sensor.
        
        Implements retry logic with 0.5s delay between attempts.
        Validates readings are within sensor operational range:
        - Temperature: -40°C to 80°C
        - Humidity: 0% to 100%
        
        Returns:
            tuple: (temperature_C, humidity_%) on success, (None, None) on failure
        """
        for attempt in range(self.max_retries):
            try:
                self.dht_sensor.measure()
                temp = self.dht_sensor.temperature()
                hum = self.dht_sensor.humidity()
                
                # Validate sensor readings are in reasonable range
                if -40 <= temp <= 80 and 0 <= hum <= 100:
                    return temp, hum
                else:
                    logger.warning('DHTLogger', f'Reading out of range: {temp}C, {hum}%')
            except OSError as e:
                logger.warning('DHTLogger', f'Read attempt {attempt + 1}/{self.max_retries} failed: {e}')
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)  # Brief delay before retry
        
        self.read_failures += 1
        return None, None
    
    def _add_to_buffer(self, timestamp, temp, hum):
        """
        Add reading to in-memory buffer when SD card unavailable.
        
        Implements overflow protection by removing oldest entry if buffer full.
        
        Args:
            timestamp (str): Timestamp string from RTC
            temp (float): Temperature reading in Celsius
            hum (float): Humidity reading in percentage
        """
        self.buffer.append((timestamp, temp, hum))
        
        if len(self.buffer) > self.max_buffer_size:
            removed = self.buffer.pop(0)
            logger.warning('DHTLogger', f'Buffer overflow: dropped oldest entry {removed[0]}')
    
    async def _flush_buffer(self):
        """
        Flush all buffered readings to SD card file.
        
        Called when SD card becomes available after disconnection.
        Writes all buffered entries in order, then clears buffer.
        Logs summary of flush operation.
        
        Returns:
            bool: True if flush successful, False if SD still unavailable
        """
        if not self.buffer:
            return True
        
        if not self._is_sd_available():
            return False
        
        buffered_count = len(self.buffer)
        
        try:
            with open(self.filename, 'a') as f:
                for timestamp, temp, hum in self.buffer:
                    f.write(f'{timestamp},{temp:.1f},{hum:.1f}\n')
            
            logger.info('DHTLogger', f'Buffer flushed: {buffered_count} entries written to SD')
            self.buffer = []
            return True
            
        except OSError as e:
            logger.error('DHTLogger', f'Failed to flush buffer: {e}')
            self.write_failures += 1
            return False
    
    async def log_data(self):
        """
        Main async coroutine for continuous sensor logging with SD hot-swap support.
        
        Runs in infinite loop with LED feedback:
        - 1 pulse: Reading started
        - 2 pulses: Read successful, data logged to CSV or buffered
        - 3 pulses (0.15s): Sensor read failed, skipping
        - 4 pulses (0.2s): SD card disconnected, buffering
        - 5 pulses (0.2s): Buffer flushed successfully
        
        SD Card Hot-Swap Behavior:
        - If SD unavailable: readings stored in in-memory buffer
        - If SD becomes available: automatic flush of buffered data
        - If buffer full: oldest entries discarded with warning
        
        Periodically checks log file size for rotation and SD card availability.
        """
        led = machine.Pin(25, machine.Pin.OUT)
        sd_was_available = True

        while True:
            try:
                # LED: Single pulse = reading started
                await self._led_pulse(led, count=1, duration=0.1)

                temp, hum = self.read_sensor()
                
                if temp is not None and hum is not None:
                    # LED: Double pulse = read successful
                    await self._led_pulse(led, count=2, duration=0.1)
                    
                    timestamp = rtc.ReadTime('timestamp')
                    
                    # Check SD availability
                    sd_available = self._is_sd_available()
                    
                    if sd_available:
                        # SD is accessible: write directly and flush any buffered data
                        if not sd_was_available and self.buffer:
                            # SD reconnected: flush buffer first
                            await self._flush_buffer()
                            await self._led_pulse(led, count=5, duration=0.2)
                        
                        try:
                            with open(self.filename, 'a') as f:
                                f.write(f'{timestamp},{temp:.1f},{hum:.1f}\n')
                            sd_was_available = True
                        except OSError as e:
                            logger.error('DHTLogger', f'Failed to write to file: {e}')
                            self.write_failures += 1
                            sd_was_available = False
                    else:
                        # SD disconnected: buffer the reading
                        if sd_was_available:
                            # First disconnection event
                            self.sd_disconnected_count += 1
                            logger.warning('DHTLogger', f'SD card disconnected (event #{self.sd_disconnected_count})')
                            sd_was_available = False
                        
                        self._add_to_buffer(timestamp, temp, hum)
                        await self._led_pulse(led, count=4, duration=0.2)
                        logger.info('DHTLogger', f'Buffered (SD unavailable): {timestamp}, {temp}C, {hum}% [buffer_size={len(self.buffer)}]')
                else:
                    # LED: Triple pulse = sensor read failed
                    await self._led_pulse(led, count=3, duration=0.15)
                    logger.warning('DHTLogger', f'Sensor read failed (total failures: {self.read_failures})')

            except Exception as e:
                logger.error('DHTLogger', f'Unexpected error: {e}')
                await self._led_pulse(led, count=3, duration=0.5)

            logger.check_size()
            await asyncio.sleep(self.interval)
    
    async def _led_pulse(self, led, count=1, duration=0.1):
        """
        Non-blocking LED pulse pattern (async-safe).
        
        Produces distinct patterns for different operational states.
        Each pulse is: ON for duration, OFF for duration.
        
        Args:
            led: GPIO Pin object for LED
            count (int): Number of pulses (default: 1)
            duration (float): ON/OFF time per pulse in seconds (default: 0.1)
        """
        for _ in range(count):
            led.on()
            await asyncio.sleep(duration)
            led.off()
            await asyncio.sleep(duration)


async def fan_control(pin_no, on_time=20, period=1800):
    """
    Async coroutine for automatic fan control via relay.
    
    Implements cyclic relay control with configurable duty cycle.
    - Validates timing parameters (on_time > 0, period > 0, on_time <= period)
    - Logs cycle start/stop events with cycle counter
    - Handles relay GPIO failures gracefully with error recovery
    - Supports clean shutdown via CancelledError
    
    Relay logic (inverted GPIO):
    - relay.value(0) = LOW → Relais EIN (relay ON, fan running)
    - relay.value(1) = HIGH → Relais AUS (relay OFF, fan stopped)
    
    Args:
        pin_no (int): GPIO pin number for relay control (default: 16)
        on_time (int): Fan ON duration in seconds (default: 20)
        period (int): Total cycle duration in seconds (default: 1800 = 30min)
        
    Example:
        # Fan runs 20 seconds, off 10 seconds, repeats 30s cycle
        asyncio.create_task(fan_control(pin_no=16, on_time=20, period=30))
    """
    # Validate parameters
    if on_time <= 0 or period <= 0:
        logger.error('FanControl', f'Invalid timing: on_time={on_time}s, period={period}s')
        return
    if on_time > period:
        logger.warning('FanControl', f'on_time ({on_time}s) > period ({period}s), clamping')
        on_time = period
    
    off_time = period - on_time
    cycle_count = 0
    
    try:
        relay = Pin(pin_no, Pin.OUT)
        relay.value(1)
        logger.info('FanControl', f'Initialized: pin={pin_no}, on={on_time}s, period={period}s')
    except Exception as e:
        logger.error('FanControl', f'Failed to initialize relay on pin {pin_no}: {e}')
        return
    
    while True:
        try:
            cycle_count += 1
            
            try:
                relay.value(0)
                logger.info('FanControl', f'Cycle {cycle_count}: Relay ON ({on_time}s)')
            except Exception as e:
                logger.error('FanControl', f'Cycle {cycle_count}: Failed to turn ON: {e}')
                await asyncio.sleep(1)
                continue
            
            await asyncio.sleep(on_time)
            
            try:
                relay.value(1)
                logger.info('FanControl', f'Cycle {cycle_count}: Relay OFF ({off_time}s)')
            except Exception as e:
                logger.error('FanControl', f'Cycle {cycle_count}: Failed to turn OFF: {e}')
                await asyncio.sleep(1)
                continue
            
            await asyncio.sleep(off_time)
            
        except asyncio.CancelledError:
            logger.warning('FanControl', f'Cancelled at cycle {cycle_count}')
            relay.value(1)
            raise
        except Exception as e:
            logger.error('FanControl', f'Cycle {cycle_count}: Unexpected error: {e}')
            await asyncio.sleep(1)


async def growlight_control(pin_no, dawn_time=(6, 0), sunset_time=(22, 0)):
    """
    Async coroutine for time-based grow light control.
    
    Controls lighting relay based on dawn/sunset times from RTC.
    Provides automatic power-loss recovery (resumes correct state after reboot).
    Checks time every 60 seconds and updates state as needed.
    
    Relay logic (inverted GPIO):
    - light.value(0) = LOW → Relais EIN (relay ON, light ON)
    - light.value(1) = HIGH → Relais AUS (relay OFF, light OFF)
    
    Args:
        pin_no (int): GPIO pin number for grow light relay (default: 17)
        dawn_time (tuple): (hour, minute) when light turns ON (default: 6:00 AM)
        sunset_time (tuple): (hour, minute) when light turns OFF (default: 22:00 PM)
        
    Example:
        # Light ON 5:30 AM to 9:30 PM
        asyncio.create_task(growlight_control(pin_no=17, dawn_time=(5,30), sunset_time=(21,30)))
    """
    light = Pin(pin_no, Pin.OUT)
    light.value(1)
    logger.info('Growlight', f'Initialized: pin={pin_no}, dawn={dawn_time}, sunset={sunset_time}')
    
    last_state = None
    
    while True:
        try:
            # Get current time from RTC
            time_tuple = rtc.ReadTime(1)  # (second, minute, hour, weekday, day, month, year)
            current_hour = int(time_tuple[2])
            current_minute = int(time_tuple[1])
            current_time = (current_hour, current_minute)
            
            # Convert times to minutes for easier comparison
            dawn_h, dawn_m = dawn_time
            sunset_h, sunset_m = sunset_time
            current_minutes = current_hour * 60 + current_minute
            dawn_minutes = dawn_h * 60 + dawn_m
            sunset_minutes = sunset_h * 60 + sunset_m
            
            # Determine if light should be ON (between dawn and sunset)
            should_be_on = dawn_minutes <= current_minutes < sunset_minutes
            
            # Apply state change if needed (including power-loss recovery)
            if should_be_on != last_state:
                if should_be_on:
                    light.value(0)
                    logger.info('Growlight', f'ON at {current_time}')
                else:
                    light.value(1)
                    logger.info('Growlight', f'OFF at {current_time}')
                last_state = should_be_on
            
            await asyncio.sleep(60)  # Check every minute
            
        except Exception as e:
            logger.error('Growlight', f'Unexpected error: {e}')
            await asyncio.sleep(1)


async def main():
    """
    Main async entry point for Pi Greenhouse system.
    
    Initializes all concurrent tasks:
    - DHTLogger.log_data(): Temperature/humidity logging (every 30s)
    - fan_control(): Automatic fan relay cycling
    - growlight_control(): Time-based grow light control
    
    Maintains event loop with minimal sleep between iterations.
    All tasks run concurrently via uasyncio event loop.
    """
    if not sd_mounted:
        logger.error('Main', 'SD card not mounted. System cannot start.')
        logger.error('Main', 'Please insert SD card and restart the device.')
        return
    
    logger.info('Main', 'System startup')
    dht_logger = DHTLogger(pin=15, interval=30, filename='/sd/dht_log.csv')

    asyncio.create_task(dht_logger.log_data())
    asyncio.create_task(fan_control(pin_no=16, on_time=20, period=1800))
    asyncio.create_task(growlight_control(pin_no=17, dawn_time=(6, 0), sunset_time=(22, 0)))

    while True:
        await asyncio.sleep(1)


if __name__ == '__main__':
    asyncio.run(main())



