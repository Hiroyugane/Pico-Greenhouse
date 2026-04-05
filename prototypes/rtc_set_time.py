import time


def dec_to_bcd(val):
    """Convert a decimal value (0-99) to BCD encoding."""
    return (val // 10) << 4 | (val % 10)


def get_weekday(year, month, day):
    """Return weekday (0=Sun … 6=Sat) using Zeller's Congruence."""
    if month < 3:
        month += 12
        year -= 1
    K = year % 100
    J = year // 100
    f = day + 13 * (month + 1) // 5 + K + K // 4 + J // 4 + 5 * J
    return (f % 7 + 6) % 7


def build_time_data(localtime_tuple):
    """Build the 7-byte BCD time payload for ds3231.SetTime().

    Parameters
    ----------
    localtime_tuple : tuple
        A ``time.localtime()``-style 9-tuple
        (year, month, day, hour, minute, second, weekday, yearday, dst).

    Returns
    -------
    bytes
        7-byte BCD payload: [sec, min, hour, wday, day, month, year].
    """
    year_full = localtime_tuple[0]
    month = localtime_tuple[1]
    day = localtime_tuple[2]
    hour = localtime_tuple[3]
    minute = localtime_tuple[4]
    second = localtime_tuple[5]
    weekday = get_weekday(year_full, month, day)
    year_short = year_full - 2000  # RTC expects 00-99

    return bytes(
        [
            dec_to_bcd(second),
            dec_to_bcd(minute),
            dec_to_bcd(hour),
            dec_to_bcd(weekday),
            dec_to_bcd(day),
            dec_to_bcd(month),
            dec_to_bcd(year_short),
        ]
    )


def main():  # pragma: no cover
    """Sync the ds3231 RTC to the system clock (run on-device via Thonny)."""
    import lib.ds3231 as ds3231
    from config import DEVICE_CONFIG

    pins = DEVICE_CONFIG["pins"]
    rtc = ds3231.RTC(
        sda_pin=pins["rtc_sda"],
        scl_pin=pins["rtc_scl"],
        port=pins["rtc_i2c_port"],
    )
    rtc_time = rtc.ReadTime("DIN-1355-1+time")  # type: ignore
    print("Alt:", rtc_time)

    current_time = time.localtime()
    time_data = build_time_data(current_time)
    rtc.SetTime(time_data)

    time.sleep(2)
    print("Neu:", rtc.ReadTime("DIN-1355-1+time"))  # type: ignore
    print("current Time:", time.localtime())
    print("Zeit erfolgreich auf RTC-Chip gesetzt.")


if __name__ == "__main__":  # pragma: no cover
    main()
