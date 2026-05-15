# Tests for lib/sensor_paths.py

import pytest


def test_daily_csv_path_basic():
    from lib.sensor_paths import daily_csv_path

    assert (
        daily_csv_path("/sd/sensors", "co2", 2026, 5, 15)
        == "/sd/sensors/co2/2026/co2_2026-05-15.csv"
    )


def test_daily_csv_path_strips_trailing_slash():
    from lib.sensor_paths import daily_csv_path

    assert (
        daily_csv_path("/sd/sensors/", "th", 2026, 1, 1)
        == "/sd/sensors/th/2026/th_2026-01-01.csv"
    )


def test_daily_csv_path_pads_month_and_day():
    from lib.sensor_paths import daily_csv_path

    assert (
        daily_csv_path("/sd/sensors", "soil", 2026, 3, 7)
        == "/sd/sensors/soil/2026/soil_2026-03-07.csv"
    )


@pytest.mark.parametrize(
    "kwargs,match",
    [
        (dict(sensor_root="", sensor_type="co2", year=2026, month=5, day=15), "sensor_root"),
        (dict(sensor_root="/sd/sensors", sensor_type="", year=2026, month=5, day=15), "sensor_type"),
        (dict(sensor_root="/sd/sensors", sensor_type="co2", year=2026, month=0, day=15), "month"),
        (dict(sensor_root="/sd/sensors", sensor_type="co2", year=2026, month=13, day=15), "month"),
        (dict(sensor_root="/sd/sensors", sensor_type="co2", year=2026, month=5, day=0), "day"),
        (dict(sensor_root="/sd/sensors", sensor_type="co2", year=2026, month=5, day=32), "day"),
    ],
)
def test_daily_csv_path_validates_inputs(kwargs, match):
    from lib.sensor_paths import daily_csv_path

    with pytest.raises(ValueError, match=match):
        daily_csv_path(**kwargs)
