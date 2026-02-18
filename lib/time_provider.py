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
            return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
        except Exception:
            return "TIME_ERROR"

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
            (1, 475, 1035),  # 1 Jan
            (20, 466, 1060),  # 20 Jan
            (34, 448, 1083),  # 4 Feb
            (50, 421, 1110),  # 19 Feb
            (79, 360, 1159),  # 20 Mar – Equinox
            (82, 353, 1164),  # DST start (min)
            (89, 397, 1236),  # DST start (max)
            (109, 351, 1271),  # 20 Apr
            (139, 294, 1324),  # 20 May
            (154, 276, 1345),  # 4 Jun
            (172, 271, 1356),  # 21 Jun – Solstice
            (185, 279, 1353),  # 5 Jul
            (200, 298, 1337),  # 19 Jul
            (214, 321, 1314),  # 3 Aug
            (231, 350, 1279),  # 18 Aug
            (267, 410, 1196),  # 22 Sep – Equinox
            (296, 456, 1135),  # DST end (min)
            (304, 409, 1061),  # DST end (max)
            (323, 439, 1035),  # 16 Nov
            (342, 463, 1025),  # 9 Dec
            (358, 474, 1029),  # 21 Dec – Solstice
            (365, 475, 1034),  # 31 Dec
        ]

        def day_of_year(year, month, day):
            days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
            if leap:
                days_per_month[1] = 29
            return day + sum(days_per_month[: month - 1])

        try:
            doy = day_of_year(year, month, day)
            if doy < POINTS[0][0]:
                prev_year = year - 1
                leap_prev = prev_year % 4 == 0 and (prev_year % 100 != 0 or prev_year % 400 == 0)
                doy += 366 if leap_prev else 365  # Year wrap with leap year correction

            for i in range(len(POINTS) - 1):
                d0, r0, s0 = POINTS[i]
                d1, r1, s1 = POINTS[i + 1]
                if d0 <= doy <= d1:
                    interpolation_factor = (doy - d0) / (d1 - d0)
                    r = int(r0 + interpolation_factor * (r1 - r0))
                    s = int(s0 + interpolation_factor * (s1 - s0))
                    sunrise = (r // 60, r % 60)
                    sunset = (s // 60, s % 60)
                    return (sunrise, sunset)
        except Exception as exc:
            # Log error while still returning a safe fallback value.
            # This keeps the provider from raising, but surfaces issues for debugging.
            print("TimeProvider.sunrise_sunset error:", exc)
            pass

        return ((0, 0), (0, 0))  # error fallback

    def export_sunrise_sunset_2026_csv(self, csv_path: str = "sunrise_sunset_2026.csv") -> None:
        """
        Generate a CSV with sunrise/sunset values for every day in 2026.

        Columns: date, sunrise_hhmm, sunset_hhmm, sunrise_minutes, sunset_minutes
        """
        provider = TimeProvider()
        year = 2026
        days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

        with open(csv_path, "w") as f:
            f.write("date,sunrise_hhmm,sunset_hhmm,sunrise_minutes,sunset_minutes\n")
            for month in range(1, 13):
                for day in range(1, days_per_month[month - 1] + 1):
                    (sr_h, sr_m), (ss_h, ss_m) = provider.sunrise_sunset(year, month, day)
                    sr_min = sr_h * 60 + sr_m
                    ss_min = ss_h * 60 + ss_m
                    sr_hhmm = f"{sr_h:02d}:{sr_m:02d}"
                    ss_hhmm = f"{ss_h:02d}:{ss_m:02d}"
                    date_str = f"{year:04d}-{month:02d}-{day:02d}"
                    f.write(f"{date_str},{sr_hhmm},{ss_hhmm},{sr_min},{ss_min}\n")


class RTCTimeProvider(TimeProvider):
    """
    TimeProvider backed by ds3231.RTC hardware.

    Wraps lib.ds3231.RTC and normalizes its multiple output formats.
    Handles format conversions internally to provide clean API.
    """

    def __init__(self, rtc, sync_interval_s: int = 3600, rtc_min_year: int = 2025, rtc_max_year: int = 2035):
        """
        Wrap an existing ds3231.RTC instance.

        Args:
            rtc: lib.ds3231.RTC instance (already initialized with I2C pins)
            sync_interval_s (int): RTC-to-Pico clock sync interval in seconds (default: 3600)
            rtc_min_year (int): Minimum valid RTC year (default: 2025)
            rtc_max_year (int): Maximum valid RTC year (default: 2035)

        Example:
            rtc_hw = ds3231.RTC(sda_pin=0, scl_pin=1)
            time_provider = RTCTimeProvider(rtc_hw)
        """
        self.rtc = rtc
        self._sync_interval_s = sync_interval_s
        self._last_sync_epoch = None
        self._time_valid = True
        self._rtc_min_year = rtc_min_year
        self._rtc_max_year = rtc_max_year
        self._sync_from_rtc(force=True)

    def _sync_from_rtc(self, force: bool = False) -> None:
        """Sync Pico time from RTC at startup and once per hour."""
        now = None
        try:
            now = time.time()
        except Exception:
            pass

        if not force and self._last_sync_epoch is not None and now is not None:
            try:
                if (now - self._last_sync_epoch) < self._sync_interval_s:
                    return
            except Exception:
                pass

        try:
            time_tuple = self.rtc.ReadTime(1)  # (sec, min, hour, wday, day, mon, year)
            if isinstance(time_tuple, tuple) and len(time_tuple) >= 7:
                sec, minute, hour, wday, day, month, year = (
                    int(time_tuple[0]),
                    int(time_tuple[1]),
                    int(time_tuple[2]),
                    int(time_tuple[3]),
                    int(time_tuple[4]),
                    int(time_tuple[5]),
                    int(time_tuple[6]),
                )
                # Validate year range to detect RTC battery loss / reset
                self._time_valid = self._rtc_min_year <= year <= self._rtc_max_year
                try:
                    import machine

                    machine.RTC().datetime((year, month, day, wday, hour, minute, sec, 0))
                except Exception:
                    pass
                try:
                    self._last_sync_epoch = time.time()
                except Exception:
                    self._last_sync_epoch = now
                return
        except Exception:
            pass

        if now is not None:
            self._last_sync_epoch = now

    @property
    def time_valid(self) -> bool:
        """Whether the RTC time is considered valid (year within expected range)."""
        return self._time_valid

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
        self._sync_from_rtc()
        try:
            t = time.localtime()
            return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
        except Exception:
            pass

        return "TIME_ERROR"

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
        self._sync_from_rtc()
        try:
            t = time.localtime()
            return (int(t[0]), int(t[1]), int(t[2]))
        except Exception:
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
        self._sync_from_rtc()
        try:
            t = time.localtime()
            return int(t[5]) + int(t[4]) * 60 + int(t[3]) * 3600
        except Exception:
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
        self._sync_from_rtc()
        try:
            t = time.localtime()
            return (int(t[5]), int(t[4]), int(t[3]), int(t[6]), int(t[2]), int(t[1]), int(t[0]))
        except Exception:
            pass

        return (0, 0, 0, 0, 0, 0, 0)  # Error fallback
