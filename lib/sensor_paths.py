# Sensor file path helpers.
# Dennis Hiro, 2026-05-15
#
# Single source of truth for the SD card sensor layout. Loggers compose
# their daily CSV path through daily_csv_path() so adding a new sensor
# type only needs a constructor argument, not duplicated path code.
#
# Layout: <sensor_root>/<sensor_type>/<YYYY>/<sensor_type>_<YYYY-MM-DD>.csv


def daily_csv_path(sensor_root, sensor_type, year, month, day):
    """
    Build the canonical daily CSV path for a sensor type.

    Args:
        sensor_root (str): Absolute root for sensor data (e.g. ``/sd/sensors``).
        sensor_type (str): Short sensor identifier (e.g. ``th``, ``soil``, ``co2``).
        year (int):  4-digit year.
        month (int): Month 1-12.
        day (int):   Day 1-31.

    Returns:
        str: Absolute path of the form
            ``<sensor_root>/<sensor_type>/<YYYY>/<sensor_type>_<YYYY-MM-DD>.csv``.

    Raises:
        ValueError: If ``sensor_root`` or ``sensor_type`` is empty, or if
            month/day are outside 1-12 / 1-31.
    """
    if not sensor_root:
        raise ValueError("sensor_root must be non-empty")
    if not sensor_type:
        raise ValueError("sensor_type must be non-empty")
    if not (1 <= month <= 12):
        raise ValueError("month must be 1-12")
    if not (1 <= day <= 31):
        raise ValueError("day must be 1-31")

    root = sensor_root.rstrip("/")
    return "{root}/{type}/{year:04d}/{type}_{year:04d}-{month:02d}-{day:02d}.csv".format(
        root=root,
        type=sensor_type,
        year=year,
        month=month,
        day=day,
    )
