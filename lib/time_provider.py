# Time Provider Abstraction
# Dennis Hiro, 2026-01-29

# Abstract TimeProvider interface and RTC-backed implementation.
# Normalizes multiple RTC output formats into consistent methods.
#
# Enables:
# - Dependency injection for testing (mock TimeProvider)
# - Centralized RTC access (all time queries go through one place)
# - Format consistency (no scattered rtc.ReadTime() calls with different modes)

# should not pass any exceptions, but return sensible defaults instead.

import time


class TimeProvider:
    """
    Abstract time provider interface.
    
    Implementations provide a consistent API for querying current time,
    independent of underlying RTC hardware or testing mocks.
    """
    
    def now_timestamp(self) -> str:
        """
        Return current time as ISO-8601 timestamp string.
        
        Returns:
            str: Timestamp in format 'YYYY-MM-DD HH:MM:SS'
        
        Example:
            '2026-01-29 14:35:42'
        """
        try:
            t = time.localtime()
            # localtime: (year, month, mday, hour, minute, second, weekday, yearday)
            return f'{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}'
        except Exception:
            return 'TIME_ERROR'
    
    def now_date_tuple(self) -> tuple:
        """
        Return current date as a tuple.
        
        Returns:
            tuple: (year, month, day) for date-based file rollover
        
        Example:
            (2026, 1, 29)
        """
        try:
            t = time.localtime()
            return (int(t[0]), int(t[1]), int(t[2]))
        except Exception:
            return (0, 0, 0)
    
    def get_seconds_since_midnight(self) -> int:
        """
        Return seconds elapsed since midnight (00:00:00).
        
        Used for time-of-day scheduling (fans, grow lights).
        
        Returns:
            int: Seconds [0, 86400)
        
        Example:
            At 14:35:42 returns: 14*3600 + 35*60 + 42 = 52542
        """
        try:
            t = time.localtime()
            return int(t[5]) + int(t[4]) * 60 + int(t[3]) * 3600
        except Exception:
            return 0
    
    def get_time_tuple(self) -> tuple:
        """
        Return raw time tuple (fallback for edge cases).
        
        Returns:
            tuple: (second, minute, hour, weekday, day, month, year)
                   Raw numeric format from RTC (no string conversion)
        
        Note:
            Prefer specific methods (now_timestamp, get_seconds_since_midnight)
            over this raw tuple for cleaner code.
        """
        try:
            t = time.localtime()
            # Return RTC-style tuple: (second, minute, hour, weekday, day, month, year)
            return (int(t[5]), int(t[4]), int(t[3]), int(t[6]), int(t[2]), int(t[1]), int(t[0]))
        except Exception:
            return (0, 0, 0, 0, 0, 0, 0)

    def sunrise_sunset(self, year: int, month: int, day: int) -> tuple:
        # Cologne ~50.94 N, 6.96 E
        # Fixpoints: astronomical / politically meaningful
        # Format: (day_of_year, sunrise_min, sunset_min)
        POINTS = [
            (355, 508, 986),   # 21 Dec – Winter solstice
            (79,  448, 1135),  # 20 Mar – Spring equinox
            (87,  418, 1215),  # DST start (last Sun Mar, typical)
            (172, 330, 1227),  # 21 Jun – Summer solstice
            (265, 427, 1186),  # 22 Sep – Autumn equinox
            (304, 456, 1100),  # DST end (last Sun Oct, typical)
            (365+355, 508, 986),  # Repeat for year wrap
        ]

        def day_of_year(year, month, day):
            mdays = [31,28,31,30,31,30,31,31,30,31,30,31]
            leap = (year%4==0 and (year%100!=0 or year%400==0))
            if leap: mdays[1] = 29
            return day + sum(mdays[:month-1])
        try:
            doy = day_of_year(year, month, day)
            if doy < POINTS[0][0]:
                prev_year = year - 1
                leap_prev = (prev_year % 4 == 0 and (prev_year % 100 != 0 or prev_year % 400 == 0))
                doy += 366 if leap_prev else 365  # Year wrap with leap year correction

            for i in range(len(POINTS)-1):
                d0, r0, s0 = POINTS[i]
                d1, r1, s1 = POINTS[i+1]
                if d0 <= doy <= d1:
                    t = (doy - d0) / (d1 - d0)
                    r = int(r0 + t * (r1 - r0))
                    s = int(s0 + t * (s1 - s0))
                    return (r//60, r%60), (s//60, s%60)
        except Exception:
            pass

        return ((0, 0), (0, 0)) # error fallback


class RTCTimeProvider(TimeProvider):
    """
    TimeProvider backed by ds3231.RTC hardware.
    
    Wraps lib.ds3231.RTC and normalizes its multiple output formats.
    Handles format conversions internally to provide clean API.
    """
    
    def __init__(self, rtc):
        """
        Wrap an existing ds3231.RTC instance.
        
        Args:
            rtc: lib.ds3231.RTC instance (already initialized with I2C pins)
        
        Example:
            rtc_hw = ds3231.RTC(sda_pin=0, scl_pin=1)
            time_provider = RTCTimeProvider(rtc_hw)
        """
        self.rtc = rtc
    
    def now_timestamp(self) -> str:
        """
        Return ISO-8601 timestamp using RTC.
        
        Uses ds3231.ReadTime('timestamp') which returns 'YYYY-MM-DD HH:MM:SS'.
        Falls back to formatting numeric tuple if 'timestamp' mode unavailable.
        
        Returns:
            str: Timestamp in format 'YYYY-MM-DD HH:MM:SS'
        
        Raises:
            Exception: If RTC communication fails (returns error string)
        """
        try:
            result = self.rtc.ReadTime('timestamp')
            if isinstance(result, str) and 'Error' not in result:
                return result
        except:
            pass
        
        # Fallback: format numeric tuple
        try:
            time_tuple = self.rtc.ReadTime(1)  # (sec, min, hour, wday, day, mon, year)
            if isinstance(time_tuple, tuple) and len(time_tuple) >= 7:
                sec, minute, hour, _, day, month, year = time_tuple[0], time_tuple[1], time_tuple[2], time_tuple[3], time_tuple[4], time_tuple[5], time_tuple[6]
                return f'{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{sec:02d}'
        except:
            pass
        
        return 'TIME_ERROR'
    
    def now_date_tuple(self) -> tuple:
        """
        Return date as (year, month, day) tuple.
        
        Extracted from numeric RTC ReadTime format.
        Used for date-based CSV file rollover.
        
        Returns:
            tuple: (year, month, day)
        
        Example:
            (2026, 1, 29)
        """
        try:
            time_tuple = self.rtc.ReadTime(1)  # (sec, min, hour, wday, day, mon, year)
            if isinstance(time_tuple, tuple) and len(time_tuple) >= 7:
                year = int(time_tuple[6])
                month = int(time_tuple[5])
                day = int(time_tuple[4])
                return (year, month, day)
        except:
            pass
        
        return (0, 0, 0)  # Error fallback
    
    def get_seconds_since_midnight(self) -> int:
        """
        Calculate seconds elapsed since midnight (00:00:00).
        
        Used for time-of-day scheduling.
        
        Returns:
            int: Seconds [0, 86400)
        
        Example:
            At 14:35:42 (2:35:42 PM) returns: 52542
        """
        try:
            time_tuple = self.rtc.ReadTime(1)  # (sec, min, hour, wday, day, mon, year)
            if isinstance(time_tuple, tuple) and len(time_tuple) >= 7:
                sec = int(time_tuple[0])
                minute = int(time_tuple[1])
                hour = int(time_tuple[2])
                return sec + minute * 60 + hour * 3600
        except:
            pass
        
        return 0  # Error fallback (midnight)
    
    def get_time_tuple(self) -> tuple:
        """
        Return raw time tuple from RTC.
        
        Returns numeric format: (second, minute, hour, weekday, day, month, year).
        Prefer specific methods (now_timestamp, get_seconds_since_midnight) for cleaner code.
        
        Returns:
            tuple: (sec, min, hour, wday, day, mon, year) or (0,0,0,0,0,0,0) on error
        """
        try:
            result = self.rtc.ReadTime(1)
            if isinstance(result, tuple):
                return result
        except:
            pass
        
        return (0, 0, 0, 0, 0, 0, 0)  # Error fallback
