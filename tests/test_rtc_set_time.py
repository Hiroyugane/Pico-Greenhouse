# Tests for rtc_set_time.py
# Covers dec_to_bcd, get_weekday, and build_time_data

from rtc_set_time import build_time_data, dec_to_bcd, get_weekday


class TestDecToBcd:
    """Tests for BCD encoding helper."""

    def test_zero(self):
        assert dec_to_bcd(0) == 0x00

    def test_single_digit(self):
        assert dec_to_bcd(5) == 0x05

    def test_double_digit(self):
        assert dec_to_bcd(23) == 0x23

    def test_max_value(self):
        assert dec_to_bcd(99) == 0x99

    def test_boundary_ten(self):
        assert dec_to_bcd(10) == 0x10

    def test_boundary_nine(self):
        assert dec_to_bcd(9) == 0x09

    def test_round_trip_all(self):
        """Every value 0-99 should encode to valid BCD."""
        for val in range(100):
            bcd = dec_to_bcd(val)
            high = (bcd >> 4) & 0x0F
            low = bcd & 0x0F
            assert high < 10 and low < 10
            assert high * 10 + low == val


class TestGetWeekday:
    """Tests for Zeller's Congruence weekday calculation."""

    # Reference: 0=Sun, 1=Mon, …, 6=Sat

    def test_known_wednesday(self):
        """2026-01-29 is a Thursday (4)."""
        # Actually let me verify: Jan 29, 2026
        # Jan 1, 2026 is Thursday. 29-1=28 days later → Thursday+0 = Thursday
        assert get_weekday(2026, 1, 29) == 4  # Thursday

    def test_known_sunday(self):
        """2026-02-01 is a Sunday."""
        assert get_weekday(2026, 2, 1) == 0

    def test_known_saturday(self):
        """2026-01-31 is a Saturday."""
        assert get_weekday(2026, 1, 31) == 6

    def test_leap_year_feb_29(self):
        """2028-02-29 (leap year) returns correct day."""
        # 2028-02-29 is Tuesday
        assert get_weekday(2028, 2, 29) == 2

    def test_march_first_after_february(self):
        """Zeller handles month < 3 adjustment correctly (Jan/Feb)."""
        # 2026-01-01 is Thursday
        assert get_weekday(2026, 1, 1) == 4
        # 2026-02-01 is Sunday
        assert get_weekday(2026, 2, 1) == 0

    def test_year_2000_jan_1(self):
        """2000-01-01 was a Saturday."""
        assert get_weekday(2000, 1, 1) == 6

    def test_epoch_start(self):
        """1970-01-01 was a Thursday."""
        assert get_weekday(1970, 1, 1) == 4


class TestBuildTimeData:
    """Tests for build_time_data() BCD payload assembly."""

    def test_known_time(self):
        """Build payload for 2026-01-29 14:23:45."""
        # time.localtime-style tuple:
        # (year, month, day, hour, min, sec, wday, yday, dst)
        lt = (2026, 1, 29, 14, 23, 45, 3, 29, -1)
        result = build_time_data(lt)

        assert isinstance(result, bytes)
        assert len(result) == 7

        # Expected BCD: [sec, min, hour, weekday, day, month, year]
        assert result[0] == dec_to_bcd(45)   # seconds
        assert result[1] == dec_to_bcd(23)   # minutes
        assert result[2] == dec_to_bcd(14)   # hours
        # weekday is computed from the date, not from the tuple's wday field
        assert result[3] == dec_to_bcd(get_weekday(2026, 1, 29))
        assert result[4] == dec_to_bcd(29)   # day
        assert result[5] == dec_to_bcd(1)    # month
        assert result[6] == dec_to_bcd(26)   # year (2026-2000)

    def test_midnight_new_year(self):
        """Midnight 2026-01-01 00:00:00."""
        lt = (2026, 1, 1, 0, 0, 0, 3, 1, -1)
        result = build_time_data(lt)

        assert result[0] == 0x00  # sec
        assert result[1] == 0x00  # min
        assert result[2] == 0x00  # hour
        assert result[4] == 0x01  # day
        assert result[5] == 0x01  # month
        assert result[6] == 0x26  # year

    def test_end_of_day(self):
        """23:59:59 encodes correctly."""
        lt = (2026, 12, 31, 23, 59, 59, 2, 365, -1)
        result = build_time_data(lt)

        assert result[0] == dec_to_bcd(59)  # sec
        assert result[1] == dec_to_bcd(59)  # min
        assert result[2] == dec_to_bcd(23)  # hour
        assert result[4] == dec_to_bcd(31)  # day
        assert result[5] == dec_to_bcd(12)  # month
        assert result[6] == dec_to_bcd(26)  # year

    def test_year_2000(self):
        """Year 2000 encodes as BCD 0x00."""
        lt = (2000, 6, 15, 12, 30, 0, 3, 167, -1)
        result = build_time_data(lt)
        assert result[6] == 0x00  # year 2000 - 2000 = 0

    def test_february_in_non_leap_year(self):
        """February date works (month < 3 Zeller edge case)."""
        lt = (2026, 2, 14, 10, 0, 0, 5, 45, -1)
        result = build_time_data(lt)
        assert result[5] == dec_to_bcd(2)   # month
        assert result[4] == dec_to_bcd(14)  # day

    def test_payload_length_always_seven(self):
        """Payload is always exactly 7 bytes."""
        for month in range(1, 13):
            lt = (2026, month, 1, 0, 0, 0, 0, 1, -1)
            assert len(build_time_data(lt)) == 7
