# Tests for lib/time_provider.py
# Covers TimeProvider (base) and RTCTimeProvider (RTC-backed)

from unittest.mock import Mock, patch

from tests.conftest import FAKE_LOCALTIME


class TestBaseTimeProvider:
    """Tests for the base TimeProvider (no RTC dependency)."""

    def test_now_timestamp_format(self, base_time_provider):
        """now_timestamp() returns 'YYYY-MM-DD HH:MM:SS' format."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            ts = base_time_provider.now_timestamp()
        assert ts == '2026-01-29 14:23:45'

    def test_now_date_tuple(self, base_time_provider):
        """now_date_tuple() returns (year, month, day)."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            date = base_time_provider.now_date_tuple()
        assert date == (2026, 1, 29)

    def test_get_seconds_since_midnight(self, base_time_provider):
        """get_seconds_since_midnight() for 14:23:45 = 51825."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            seconds = base_time_provider.get_seconds_since_midnight()
        assert seconds == 14 * 3600 + 23 * 60 + 45

    def test_get_time_tuple(self, base_time_provider):
        """get_time_tuple() returns RTC-style (sec, min, hour, wday, day, mon, year)."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            tup = base_time_provider.get_time_tuple()
        assert tup == (45, 23, 14, 3, 29, 1, 2026)

    def test_now_timestamp_exception_returns_TIME_ERROR(self):
        """When time.localtime raises, return 'TIME_ERROR'."""
        from lib.time_provider import TimeProvider
        tp = TimeProvider()
        with patch('time.localtime', side_effect=OSError('clock fail')):
            assert tp.now_timestamp() == 'TIME_ERROR'

    def test_now_date_tuple_exception_returns_zeros(self):
        """When time.localtime raises, return (0, 0, 0)."""
        from lib.time_provider import TimeProvider
        tp = TimeProvider()
        with patch('time.localtime', side_effect=OSError('clock fail')):
            assert tp.now_date_tuple() == (0, 0, 0)

    def test_get_seconds_since_midnight_exception_returns_zero(self):
        """When time.localtime raises, return 0."""
        from lib.time_provider import TimeProvider
        tp = TimeProvider()
        with patch('time.localtime', side_effect=OSError('clock fail')):
            assert tp.get_seconds_since_midnight() == 0

    def test_get_time_tuple_exception_returns_zeros(self):
        """When time.localtime raises, return all-zero tuple."""
        from lib.time_provider import TimeProvider
        tp = TimeProvider()
        with patch('time.localtime', side_effect=OSError('clock fail')):
            assert tp.get_time_tuple() == (0, 0, 0, 0, 0, 0, 0)


class TestRTCTimeProvider:
    """Tests for RTCTimeProvider backed by ds3231.RTC."""

    def test_now_timestamp(self, time_provider):
        """RTCTimeProvider.now_timestamp() returns ISO format."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            ts = time_provider.now_timestamp()
        assert '2026-01-29' in ts
        assert '14:23:45' in ts

    def test_now_date_tuple(self, time_provider):
        """RTCTimeProvider.now_date_tuple() returns (year, month, day)."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            date = time_provider.now_date_tuple()
        assert date == (2026, 1, 29)

    def test_get_seconds_since_midnight(self, time_provider):
        """RTCTimeProvider.get_seconds_since_midnight() correct calculation."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            seconds = time_provider.get_seconds_since_midnight()
        assert seconds == 14 * 3600 + 23 * 60 + 45

    def test_get_time_tuple(self, time_provider):
        """RTCTimeProvider.get_time_tuple() returns raw 7-tuple."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            tup = time_provider.get_time_tuple()
        assert isinstance(tup, tuple)
        assert len(tup) == 7
        assert tup[0] == 45  # seconds

    def test_sync_from_rtc_forced(self, mock_rtc):
        """_sync_from_rtc(force=True) calls ReadTime and machine.RTC().datetime()."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            from lib.time_provider import RTCTimeProvider
            provider = RTCTimeProvider(mock_rtc)
        mock_rtc.ReadTime.assert_called()

    def test_sync_from_rtc_skips_when_recent(self, mock_rtc):
        """_sync_from_rtc() does not call ReadTime again if synced recently."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            from lib.time_provider import RTCTimeProvider
            provider = RTCTimeProvider(mock_rtc)
            initial_call_count = mock_rtc.ReadTime.call_count
            # Subsequent calls within sync interval should not re-read
            provider._sync_from_rtc(force=False)
        assert mock_rtc.ReadTime.call_count == initial_call_count

    def test_sync_from_rtc_failure_graceful(self):
        """If RTC ReadTime raises, sync handles gracefully."""
        rtc = Mock()
        rtc.ReadTime = Mock(side_effect=OSError('I2C fail'))
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            from lib.time_provider import RTCTimeProvider
            # Should not raise — graceful handling
            provider = RTCTimeProvider(rtc)
            ts = provider.now_timestamp()
        assert isinstance(ts, str)

    def test_now_timestamp_falls_back_to_TIME_ERROR(self, mock_rtc):
        """If both RTC and localtime fail, return 'TIME_ERROR'."""
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            from lib.time_provider import RTCTimeProvider
            provider = RTCTimeProvider(mock_rtc)

        with patch('time.localtime', side_effect=OSError('fail')):
            with patch('time.time', side_effect=OSError('fail')):
                ts = provider.now_timestamp()
        assert ts == 'TIME_ERROR'


class TestSunriseSunset:
    """Tests for sunrise_sunset() interpolation table."""

    def test_sunrise_sunset_bounds(self, time_provider):
        """Sunrise/sunset should return sensible hours/minutes."""
        (sr_h, sr_m), (ss_h, ss_m) = time_provider.sunrise_sunset(2026, 1, 29)
        assert 0 <= sr_h <= 23
        assert 0 <= sr_m <= 59
        assert 0 <= ss_h <= 23
        assert 0 <= ss_m <= 59

    def test_sunrise_sunset_jan1(self, base_time_provider):
        """Jan 1 — boundary at start of POINTS table."""
        (sr_h, sr_m), (ss_h, ss_m) = base_time_provider.sunrise_sunset(2026, 1, 1)
        # Jan 1 sunrise ~ 07:55 (475 min), sunset ~ 17:15 (1035 min) for Cologne
        assert 7 <= sr_h <= 8
        assert 16 <= ss_h <= 18

    def test_sunrise_sunset_june_solstice(self, base_time_provider):
        """June 21 — summer solstice, earliest sunrise / latest sunset."""
        (sr_h, sr_m), (ss_h, ss_m) = base_time_provider.sunrise_sunset(2026, 6, 21)
        # Sunrise around 04:31, sunset around 22:36 for Cologne (DST)
        assert 4 <= sr_h <= 5
        assert 22 <= ss_h <= 23

    def test_sunrise_sunset_dec31(self, base_time_provider):
        """Dec 31 — boundary at end of POINTS table."""
        (sr_h, sr_m), (ss_h, ss_m) = base_time_provider.sunrise_sunset(2026, 12, 31)
        assert 7 <= sr_h <= 8
        assert 16 <= ss_h <= 18

    def test_sunrise_sunset_leap_year(self, base_time_provider):
        """Leap year Feb 29 should not crash."""
        (sr_h, sr_m), (ss_h, ss_m) = base_time_provider.sunrise_sunset(2028, 2, 29)
        assert sr_h > 0 or sr_m > 0  # Not fallback (0,0)

    def test_sunrise_sunset_error_returns_fallback(self, base_time_provider):
        """Error in sunrise_sunset returns ((0,0),(0,0)) fallback."""
        # Pass None as year to trigger TypeError in day_of_year
        result = base_time_provider.sunrise_sunset(None, 1, 1)
        assert result == ((0, 0), (0, 0))

    def test_sunrise_sunset_equinox(self, base_time_provider):
        """March 20 equinox — sunrise and sunset roughly equal."""
        (sr_h, sr_m), (ss_h, ss_m) = base_time_provider.sunrise_sunset(2026, 3, 20)
        sr_minutes = sr_h * 60 + sr_m
        ss_minutes = ss_h * 60 + ss_m
        daylight = ss_minutes - sr_minutes
        # Equinox: roughly 12h daylight (720 min), allow generous range due to DST
        assert 600 <= daylight <= 840


class TestExportCSV:
    """Tests for export_sunrise_sunset_2026_csv utility."""

    def test_export_creates_csv_file(self, base_time_provider, tmp_path):
        """export_sunrise_sunset_2026_csv writes a properly formatted CSV."""
        csv_path = str(tmp_path / 'sunrise_sunset.csv')
        base_time_provider.export_sunrise_sunset_2026_csv(csv_path)

        content = (tmp_path / 'sunrise_sunset.csv').read_text()
        lines = content.strip().split('\n')
        assert lines[0] == 'date,sunrise_hhmm,sunset_hhmm,sunrise_minutes,sunset_minutes'
        assert len(lines) == 366  # header + 365 days
        # Spot-check Jan 1
        assert lines[1].startswith('2026-01-01,')


class TestRTCTimeProviderErrorFallbacks:
    """Tests for RTCTimeProvider error/fallback paths."""

    def test_rtc_now_timestamp_localtime_error(self, mock_rtc):
        """When localtime raises after sync, returns TIME_ERROR."""
        from lib.time_provider import RTCTimeProvider
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            provider = RTCTimeProvider(mock_rtc)
        # After creating, break localtime
        with patch('time.localtime', side_effect=OSError):
            assert provider.now_timestamp() == 'TIME_ERROR'

    def test_rtc_now_date_tuple_error(self, mock_rtc):
        """When localtime raises after sync, returns (0,0,0)."""
        from lib.time_provider import RTCTimeProvider
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            provider = RTCTimeProvider(mock_rtc)
        with patch('time.localtime', side_effect=OSError):
            assert provider.now_date_tuple() == (0, 0, 0)

    def test_rtc_get_seconds_since_midnight_error(self, mock_rtc):
        """Error fallback returns 0."""
        from lib.time_provider import RTCTimeProvider
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            provider = RTCTimeProvider(mock_rtc)
        with patch('time.localtime', side_effect=OSError):
            assert provider.get_seconds_since_midnight() == 0

    def test_rtc_get_time_tuple_error(self, mock_rtc):
        """Error fallback returns all zeros."""
        from lib.time_provider import RTCTimeProvider
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            provider = RTCTimeProvider(mock_rtc)
        with patch('time.localtime', side_effect=OSError):
            assert provider.get_time_tuple() == (0, 0, 0, 0, 0, 0, 0)
