# LED and Button Handler - Async-Safe Patterns
# Dennis Hiro, 2024-06-08
#
# Low-level LED/button abstraction with async-safe blink patterns.
# ServiceReminder task tracks days since last Service and signals LED until button press.

import time

import machine
import uasyncio as asyncio


def _ticks_ms() -> int:
    """Return monotonic milliseconds on MicroPython or host."""
    if hasattr(time, 'ticks_ms'):
        return time.ticks_ms()
    return int(time.time() * 1000)


class LED:
    """
    Simple LED abstraction for on/off/blink control.
    
    Attributes:
        pin: machine.Pin for LED
    """
    
    def __init__(self, pin: int):
        """
        Initialize LED.
        
        Args:
            pin (int): GPIO pin for LED
        """
        self.pin = machine.Pin(pin, machine.Pin.OUT)
        self.pin.off()
    
    def on(self) -> None:
        """Turn LED on."""
        self.pin.on()
    
    def off(self) -> None:
        """Turn LED off."""
        self.pin.off()
    
    def toggle(self) -> None:
        """Toggle LED."""
        if self.pin.value():
            self.pin.off()
        else:
            self.pin.on()
    
    async def blink_pattern_async(self, pattern_ms: list, repeats: int = 1) -> None:
        """
        Play a blink pattern (async, non-blocking).
        
        Pattern is a list of millisecond durations alternating ON/OFF.
        
        Args:
            pattern_ms (list): [on_ms, off_ms, on_ms, off_ms, ...] durations
            repeats (int): Number of times to repeat the pattern (default: 1)
        
        Example:
            >>> led = LED(25)
            >>> await led.blink_pattern_async([200, 200, 200, 800])  # SOS: dot-dot-dash
        """
        if repeats < 1:
            return

        for _ in range(repeats):
            for i, duration_ms in enumerate(pattern_ms):
                is_on_phase = (i % 2) == 0  # Even indices are ON
                
                if is_on_phase:
                    self.on()
                else:
                    self.off()
                
                await asyncio.sleep(duration_ms / 1000.0)
        
        # Ensure LED is OFF at end of pattern
        self.off()
    
    async def blink_continuous_async(self, on_ms: int, off_ms: int, stop_event=None) -> None:
        """
        Play a continuous blink pattern until stop_event is set.
        
        Args:
            on_ms (int): ON duration in milliseconds
            off_ms (int): OFF duration in milliseconds
            stop_event: Optional asyncio.Event to signal stop
        
        Example:
            >>> led = LED(24)
            >>> stop = asyncio.Event()
            >>> asyncio.create_task(led.blink_continuous_async(200, 200, stop))
            >>> await asyncio.sleep(5)
            >>> stop.set()
        """
        while True:
            self.on()
            await asyncio.sleep(on_ms / 1000.0)
            
            self.off()
            await asyncio.sleep(off_ms / 1000.0)
            
            if stop_event and stop_event.is_set():
                self.off()
                break


class LEDButtonHandler:
    """
    Handler for LED and multi-function button control.
    
    LED operations via LED class (non-blocking async blink patterns).
    Button: single GPIO with debounced interrupt, distinguishing
    short press (< long_press_ms) from long press (>= long_press_ms).
    
    Attributes:
        led: LED instance
        button_pin: machine.Pin for button
        debounce_ms: Debounce delay
        long_press_ms: Threshold for long-press detection
        short_press_callback: Registered short-press callback
        long_press_callback: Registered long-press callback
    """
    
    def __init__(self, led_pin: int, button_pin: int, debounce_ms: int = 50,
                 long_press_ms: int = 3000):
        """
        Initialize LED and multi-function button.
        
        Args:
            led_pin (int): GPIO pin for LED
            button_pin (int): GPIO pin for button
            debounce_ms (int): Debounce delay in milliseconds (default: 50)
            long_press_ms (int): Long-press threshold in ms (default: 3000)
        """
        self.led = LED(led_pin)
        self.button = machine.Pin(button_pin, machine.Pin.IN, machine.Pin.PULL_UP)
        self.debounce_ms = debounce_ms
        self.long_press_ms = long_press_ms
        self.short_press_callback = None
        self.long_press_callback = None
        # Legacy alias for backward compatibility
        self.button_callback = None
        self._last_press_time = 0
        self._press_start_time = 0
    
    def set_on(self) -> None:
        """Turn LED on."""
        self.led.on()
    
    def set_off(self) -> None:
        """Turn LED off."""
        self.led.off()
    
    def toggle(self) -> None:
        """Toggle LED."""
        self.led.toggle()
    
    def register_button_callback(self, callback) -> None:
        """
        Register callback to be invoked on debounced button press (legacy).
        
        For backward compatibility, this registers the callback as the
        short-press handler and sets up IRQ on FALLING edge only.
        
        Args:
            callback: Callable that takes no arguments
        """
        self.button_callback = callback
        self.short_press_callback = callback
        self.button.irq(trigger=machine.Pin.IRQ_FALLING, handler=self._button_isr)
    
    def register_callbacks(self, short_press=None, long_press=None) -> None:
        """
        Register short-press and/or long-press callbacks.
        
        Short press: button released before long_press_ms threshold.
        Long press: button held >= long_press_ms then released.
        
        Args:
            short_press: Callable for short press (no args)
            long_press: Callable for long press (no args)
        """
        self.short_press_callback = short_press
        self.long_press_callback = long_press
        # Also set legacy alias to short_press for backward compat
        self.button_callback = short_press
        self.button.irq(
            trigger=machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING,
            handler=self._button_dual_isr
        )
    
    def _button_isr(self, pin) -> None:
        """Interrupt handler with debouncing (legacy, FALLING only)."""
        current_time = _ticks_ms()
        
        if current_time - self._last_press_time > self.debounce_ms:
            self._last_press_time = current_time
            
            if self.button_callback:
                try:
                    self.button_callback()
                except Exception as e:
                    print(f'[LEDButtonHandler] Button callback error: {e}')
    
    def _button_dual_isr(self, pin) -> None:
        """
        Interrupt handler for both FALLING and RISING edges.
        
        FALLING = press start (record timestamp).
        RISING  = press end (compute duration, dispatch callback).
        """
        current_time = _ticks_ms()
        
        # Debounce guard
        if current_time - self._last_press_time < self.debounce_ms:
            return
        self._last_press_time = current_time
        
        # Button pressed (FALLING edge, pin reads 0 when pressed with PULL_UP)
        if pin.value() == 0:
            self._press_start_time = current_time
            return
        
        # Button released (RISING edge)
        if self._press_start_time == 0:
            return  # No matching press start
        
        duration = current_time - self._press_start_time
        self._press_start_time = 0
        
        try:
            if duration >= self.long_press_ms and self.long_press_callback:
                self.long_press_callback()
            elif self.short_press_callback:
                self.short_press_callback()
        except Exception as e:
            print(f'[LEDButtonHandler] Button callback error: {e}')
    
    async def blink_pattern_async(self, pattern_ms: list, repeats: int = 1) -> None:
        """
        Play a blink pattern via LED (async, non-blocking).
        
        Args:
            pattern_ms (list): [on_ms, off_ms, on_ms, off_ms, ...] durations
            repeats (int): Number of times to repeat the pattern (default: 1)
        """
        await self.led.blink_pattern_async(pattern_ms, repeats)
    
    async def blink_continuous_async(self, on_ms: int, off_ms: int, stop_event=None) -> None:
        """
        Play a continuous blink pattern via LED until stop_event is set.
        
        Args:
            on_ms (int): ON duration in milliseconds
            off_ms (int): OFF duration in milliseconds
            stop_event: Optional asyncio.Event to signal stop
        """
        await self.led.blink_continuous_async(on_ms, off_ms, stop_event)


class ServiceReminder:
    """
    Service reminder task that signals LED after N days.
    
    Tracks days since last Service (stored in memory).
    Blinks LED with configurable pattern when reminder is due.
    Resets timer on button press (via LEDButtonHandler callback).
    
    State:
    - last_serviced_timestamp: Stored as string (persisted to config/file later if needed)
    - days_elapsed: Calculated from RTC
    - reminder_due: Whether LED should be blinking
    
    Attributes:
        time_provider: TimeProvider instance
        led_handler: LEDButtonHandler instance
        days_interval: Days between Service reminders
        blink_pattern_ms: LED blink pattern
        last_serviced_timestamp: ISO timestamp of last Service
        last_serviced_date: Date tuple (year, month, day) for elapsed days calc
    """
    
    def __init__(self, time_provider, led_handler, last_serviced_timestamp = None,
                 days_interval: int = 7, blink_pattern_ms = None,
                 storage_path: str = '/service_reminder.txt',
                 auto_register_button: bool = True):
        """
        Initialize Service reminder.
        
        Args:
            time_provider: TimeProvider instance
            led_handler: LEDButtonHandler instance
            last_serviced_timestamp (str, optional): ISO timestamp of last Service (default: now)
            days_interval (int): Days between reminders (default: 7)
            blink_pattern_ms (list, optional): Blink pattern (default: [5000, 2000])
            storage_path (str, optional): File path for persisted timestamp
            auto_register_button (bool): If True, auto-register reset() as the
                button callback via register_button_callback().  Set False when
                the caller wires callbacks externally (e.g. via register_callbacks
                for multi-function button support).  Default: True.
        
        Example:
            >>> reminder = ServiceReminder(time_provider, led_handler, days_interval=7)
            >>> asyncio.create_task(reminder.monitor())
        """
        self.time_provider = time_provider
        self.led_handler = led_handler
        self.days_interval = days_interval
        self.blink_pattern_ms = blink_pattern_ms or [5000, 2000]  # SOS
        
        self.storage_path = storage_path

        # Initialize last Service timestamp (prefer explicit, then persisted, then now)
        if last_serviced_timestamp:
            self.last_serviced_timestamp = last_serviced_timestamp
            self._save_last_serviced_timestamp(self.last_serviced_timestamp)
        else:
            loaded = self._load_last_serviced_timestamp()
            if loaded:
                self.last_serviced_timestamp = loaded
            else:
                self.last_serviced_timestamp = self.time_provider.now_timestamp()
                self._save_last_serviced_timestamp(self.last_serviced_timestamp)

        # Extract date for comparison
        parsed_date = self._parse_date_from_timestamp(self.last_serviced_timestamp)
        self.last_serviced_date = parsed_date if parsed_date else self.time_provider.now_date_tuple()
        
        # Register reset callback (unless caller wires it externally)
        if auto_register_button:
            self.led_handler.register_button_callback(self.reset)
        
        print(f'[ServiceReminder] Initialized: {self.days_interval} days, last_serviced={self.last_serviced_timestamp}')

    def _parse_date_from_timestamp(self, timestamp: str):
        """
        Parse date tuple (year, month, day) from 'YYYY-MM-DD HH:MM:SS' timestamp.
        """
        try:
            date_part = timestamp.split(' ')[0]
            year_str, month_str, day_str = date_part.split('-')
            return (int(year_str), int(month_str), int(day_str))
        except:
            return None

    def _load_last_serviced_timestamp(self):
        """
        Load last serviced timestamp from storage file.
        """
        if not self.storage_path:
            return None
        try:
            with open(self.storage_path, 'r') as f:
                value = f.read().strip()
                return value if value else None
        except:
            return None

    def _save_last_serviced_timestamp(self, timestamp: str) -> None:
        """
        Persist last serviced timestamp to storage file.
        """
        if not self.storage_path:
            return
        try:
            with open(self.storage_path, 'w') as f:
                f.write(timestamp)
        except Exception as e:
            print(f'[ServiceReminder] ERROR saving timestamp: {e}')
    
    def _days_since_Service(self) -> int:
        """
        Calculate days elapsed since last Service.
        
        Simple calculation based on date tuples (year, month, day).
        Note: This is approximate and doesn't account for month/year changes fully.
        For production, use datetime module or proper date math.
        
        Returns:
            int: Approximate days elapsed
        """
        try:
            current_date = self.time_provider.now_date_tuple()
            
            # Use epoch-based day calculation to handle year boundaries safely
            current_secs = time.mktime((current_date[0], current_date[1], current_date[2], 0, 0, 0, 0, 0))
            last_secs = time.mktime((self.last_serviced_date[0], self.last_serviced_date[1], self.last_serviced_date[2], 0, 0, 0, 0, 0))
            
            return int((current_secs - last_secs) / 86400)
        except:
            return 0
    
    def reset(self) -> None:
        """
        Reset Service reminder (called on button press).
        
        Updates last_serviced_timestamp to now.
        """
        try:
            self.last_serviced_timestamp = self.time_provider.now_timestamp()
            self.last_serviced_date = self.time_provider.now_date_tuple()
            self._save_last_serviced_timestamp(self.last_serviced_timestamp)
            
            self.led_handler.set_off()  # Stop blinking immediately
            
            print(f'[ServiceReminder] Reset: last_serviced={self.last_serviced_timestamp}')
        except Exception as e:
            print(f'[ServiceReminder] ERROR during reset: {e}')
    
    async def monitor(self) -> None:
        """
        Async loop that monitors days elapsed and signals LED.
        
        Checks every hour if reminder is due.
        When due, plays blink pattern repeatedly until button pressed.
        """
        reminder_due = False
        
        while True:
            try:
                days_elapsed = self._days_since_Service()
                is_due = days_elapsed >= self.days_interval
                
                # Detect transition from not-due to due
                if is_due and not reminder_due:
                    reminder_due = True
                    print(f'[ServiceReminder] REMINDER DUE: {days_elapsed} days elapsed')
                
                elif not is_due and reminder_due:
                    reminder_due = False
                    self.led_handler.set_off()
                    print('[ServiceReminder] Reminder cleared')
                
                # When reminder is due, play blink pattern repeatedly
                if reminder_due:
                    await self.led_handler.blink_pattern_async(self.blink_pattern_ms)
                    
                    # Re-check condition after completing pattern to avoid unnecessary repeats
                    days_elapsed = self._days_since_Service()
                    is_due = days_elapsed >= self.days_interval
                    if not is_due:
                        reminder_due = False
                        self.led_handler.set_off()
                        print('[ServiceReminder] Reminder cleared')
                        # After clearing, fall back to hourly checks
                        await asyncio.sleep(3600)
                    else:
                        await asyncio.sleep(0.5)  # Brief pause before next pattern
                else:
                    # Not due: check every hour
                    await asyncio.sleep(3600)
                
            except asyncio.CancelledError:
                self.led_handler.set_off()
                print('[ServiceReminder] Monitor cancelled')
                raise
            except Exception as e:
                print(f'[ServiceReminder] ERROR in monitor: {e}')
                await asyncio.sleep(60)