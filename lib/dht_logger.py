# DHT Logger - Temperature/Humidity Logging with DI
# Dennis Hiro, 2026-01-29
#
# Refactored from original main.py.
# Uses dependency injection for TimeProvider, BufferManager, EventLogger.
# Decoupled from global state; supports hot-swap SD and date-based file rollover.

import dht
import machine
import uasyncio as asyncio
from lib.led_button import LED


class DHTLogger:
    """
    DHT22 temperature/humidity sensor logger with SD hot-swap and date-based rollover.
    
    Reads DHT22 sensor and logs timestamped CSV entries.
    All storage resilience delegated to BufferManager:
    - Writes to primary (SD) when available
    - Falls back to fallback file when SD unavailable
    - Buffers in-memory when both unavailable
    - Auto-migrates fallback entries when SD reconnects
    
    Automatically rolls over CSV file at midnight.
    
    Dependencies injected:
    - time_provider: For timestamps and date-based rollover
    - buffer_manager: For all write operations (handles resilience)
    - logger: For event logging
    
    Attributes:
        dht_sensor: DHT22 sensor instance
        interval: Logging interval in seconds
        filename_base: CSV filename base
        time_provider: TimeProvider instance
        buffer_manager: BufferManager instance
        logger: EventLogger instance
        current_date: Current date (year, month, day) for rollover detection
        last_temperature: Cached temperature for thermostat queries
        last_humidity: Cached humidity reading
        read_failures: Count of sensor read failures
        write_failures: Count of failed writes
    """
    
    def __init__(self, pin, time_provider, buffer_manager, logger, 
                 interval=60, filename='dht_log.csv', max_retries=3):
        """
        Initialize DHTLogger with dependency injection.
        
        Args:
            pin (int): GPIO pin for DHT22 data line
            time_provider: TimeProvider instance
            buffer_manager: BufferManager instance
            logger: EventLogger instance
            interval (int): Logging interval in seconds (default: 60)
            filename (str): CSV filename (default: 'dht_log.csv')
            max_retries (int): Sensor read retries (default: 3)
        """
        self.dht_sensor = dht.DHT22(machine.Pin(pin))
        self.interval = interval
        self.filename_base = filename if filename.startswith('/sd/') else f'/sd/{filename}'
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.logger = logger
        self.max_retries = max_retries
        
        # State
        self.last_temperature = None
        self.last_humidity = None
        self.read_failures = 0
        self.write_failures = 0
        self.current_date = None
        
        # Initialize filename with current date
        self._update_filename_for_date()
        
        # Create CSV file if needed
        try:
            if not self._file_exists():
                self._create_file()
            logger.info('DHTLogger', f'Initialized: {self.filename}')
        except Exception as e:
            logger.error('DHTLogger', f'Init error: {e}')
    
    def _update_filename_for_date(self) -> None:
        """
        Update log filename based on current RTC date.
        
        Format: dht_log_YYYY-MM-DD.csv (auto date-based rollover).
        """
        try:
            date_tuple = self.time_provider.now_date_tuple()
            year, month, day = date_tuple[0], date_tuple[1], date_tuple[2]
            self.current_date = (year, month, day)
            
            base = self.filename_base.replace('.csv', '')
            self.filename = f'{base}_{year:04d}-{month:02d}-{day:02d}.csv'
        except Exception as e:
            self.logger.error('DHTLogger', f'Error updating filename: {e}')
            self.filename = self.filename_base
    
    def _file_exists(self) -> bool:
        """Check if CSV file exists on primary storage."""
        try:
            with open(self.filename, 'r'):
                return True
        except:
            return False
    
    def _create_file(self) -> None:
        """
        Create CSV file with header on primary storage.
        
        Header: 'Timestamp,Temperature,Humidity'
        """
        try:
            self.buffer_manager.write(self.filename.lstrip('/sd/'), 'Timestamp,Temperature,Humidity\n')
            self.logger.info('DHTLogger', f'Created CSV file: {self.filename}')
        except Exception as e:
            self.logger.error('DHTLogger', f'Failed to create file: {e}')
            raise
    
    def read_sensor(self):
        """
        Read temperature and humidity from DHT22.
        
        Implements retry logic with 0.5s delay between attempts.
        Validates readings are in range: -40°C to 80°C, 0% to 100%.
        
        Returns:
            tuple: (temperature, humidity) or (None, None) on failure
        """
        for attempt in range(self.max_retries):
            try:
                self.dht_sensor.measure()
                temp = self.dht_sensor.temperature()
                hum = self.dht_sensor.humidity()
                
                if -40 <= temp <= 80 and 0 <= hum <= 100:
                    return temp, hum
                else:
                    self.logger.warning('DHTLogger', f'Reading out of range: {temp}°C, {hum}%')
            except Exception as e:
                self.logger.warning('DHTLogger', f'Read attempt {attempt + 1}/{self.max_retries} failed: {e}')
                if attempt < self.max_retries - 1:
                    import time # importing time here to avoid global import in async context - useful?
                    time.sleep(0.5)
        
        self.read_failures += 1
        return None, None
    
    def _check_date_changed(self) -> bool:
        """
        Check if date has changed; update filename if so.
        
        Returns True if date changed and file was switched, False otherwise.
        """
        try:
            date_tuple = self.time_provider.now_date_tuple()
            current_date = (date_tuple[0], date_tuple[1], date_tuple[2])
            
            if current_date != self.current_date:
                old_filename = self.filename
                self._update_filename_for_date()
                
                if not self._file_exists():
                    self._create_file()
                
                self.logger.info('DHTLogger', f'Date changed - switched from {old_filename} to {self.filename}')
                return True
            
            return False
        except Exception as e:
            self.logger.error('DHTLogger', f'Error during date check: {e}')
            return False
    
    async def log_loop(self) -> None:
        """
        Main async coroutine for continuous sensor logging.
        
        Reads sensor periodically, logs to CSV via BufferManager.
        BufferManager handles all storage resilience:
        - Writes to primary (SD) when available
        - Falls back to fallback file when SD unavailable
        - Buffers in-memory when both unavailable
        - Auto-migrates fallback entries when SD reconnects
        - Auto-flushes in-memory buffer when SD reconnects
        
        Handles date-based file rollover at midnight.
        
        LED feedback patterns (via lib/led_button.py LED class):
        - 1 pulse (0.1s): Reading started
        - 2 pulses (0.1s): Read successful, data logged
        - 3 pulses (0.15s): Sensor read failed
        """
        led = LED(25)
        
        while True:
            try:
                # Check for date rollover
                self._check_date_changed()
                
                # LED: Single pulse = reading started
                await led.blink_pattern_async([100, 100])
                
                # Read sensor
                temp, hum = self.read_sensor()
                
                if temp is not None and hum is not None:
                    # LED: Double pulse = read successful
                    await led.blink_pattern_async([100, 100, 100, 100])
                    
                    # Cache for thermostat queries
                    self.last_temperature = temp
                    self.last_humidity = hum
                    
                    timestamp = self.time_provider.now_timestamp()
                    relpath = self.filename.lstrip('/sd/')
                    row = f'{timestamp},{temp:.1f},{hum:.1f}\n'
                    
                    # Write to storage via BufferManager
                    # BufferManager handles: primary → fallback → in-memory buffer
                    try:
                        self.buffer_manager.write(relpath, row)
                    except Exception as e:
                        self.logger.error('DHTLogger', f'Failed to write: {e}')
                        self.write_failures += 1
                else:
                    # LED: Triple pulse = sensor read failed
                    await led.blink_pattern_async([150, 150, 150, 150, 150, 150])
                    self.logger.warning('DHTLogger', f'Sensor read failed (total: {self.read_failures})')
                
                self.logger.check_size()
                await asyncio.sleep(self.interval)
                
            except asyncio.CancelledError:
                self.logger.warning('DHTLogger', 'Log loop cancelled')
                raise
            except Exception as e:
                self.logger.error('DHTLogger', f'Unexpected error: {e}')
                await led.blink_pattern_async([500, 500, 500, 500, 500, 500])
                await asyncio.sleep(1)
