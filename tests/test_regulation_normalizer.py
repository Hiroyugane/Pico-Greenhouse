# Tests for lib/regulation_normalizer.py
# Deviation mapping, time-of-day blend, and the RegulationNormalizer class.

from array import array


def _profile():
    """Small two-phase profile: night anchors sit below day anchors."""
    return {
        "day": {
            "temp": {"at_0": 14.0, "at_50": 24.0, "at_100": 34.0},
            "humidity": {"at_0": 40.0, "at_50": 60.0, "at_100": 90.0},
            "co2": {"at_0": 400.0, "at_50": 800.0, "at_100": 1600.0},
        },
        "night": {
            "temp": {"at_0": 10.0, "at_50": 18.0, "at_100": 26.0},
            "humidity": {"at_0": 40.0, "at_50": 60.0, "at_100": 90.0},
            "co2": {"at_0": 400.0, "at_50": 900.0, "at_100": 1600.0},
        },
    }


class TestDeviation:
    def test_anchor_points_map_exactly(self):
        from lib.regulation_normalizer import deviation

        assert deviation(14.0, 14.0, 24.0, 34.0) == 0.0
        assert deviation(24.0, 14.0, 24.0, 34.0) == 50.0
        assert deviation(34.0, 14.0, 24.0, 34.0) == 100.0

    def test_spec_example_29c_maps_to_75(self):
        from lib.regulation_normalizer import deviation

        assert deviation(29.0, 14.0, 24.0, 34.0) == 75.0

    def test_clamps_below_and_above(self):
        from lib.regulation_normalizer import deviation

        assert deviation(5.0, 14.0, 24.0, 34.0) == 0.0
        assert deviation(50.0, 14.0, 24.0, 34.0) == 100.0

    def test_asymmetric_spacing(self):
        from lib.regulation_normalizer import deviation

        # Loose low side (0..50 over 20 units), strict high side (50..100 over 5).
        # 4 units above at_50 with a 5-unit high span → 50 + 50*0.8 = 90.
        assert deviation(29.0, 5.0, 25.0, 30.0) == 90.0

    def test_monotonic_increasing(self):
        from lib.regulation_normalizer import deviation

        prev = -1.0
        for v in range(10, 40):
            d = deviation(float(v), 14.0, 24.0, 34.0)
            assert d >= prev
            prev = d


class TestSeverity:
    def test_severity_symmetric(self):
        from lib.regulation_normalizer import severity

        assert severity(50.0) == 0.0
        assert severity(75.0) == 25.0
        assert severity(25.0) == 25.0
        assert severity(0.0) == 50.0
        assert severity(100.0) == 50.0


class TestBlendFactor:
    def test_night_is_zero(self):
        from lib.regulation_normalizer import blend_factor

        # Window [420, 1140], transition 30.
        assert blend_factor(0, 420, 1140, 30) == 0.0
        assert blend_factor(419, 420, 1140, 30) == 0.0
        assert blend_factor(1140, 420, 1140, 30) == 0.0
        assert blend_factor(1300, 420, 1140, 30) == 0.0

    def test_midday_is_one(self):
        from lib.regulation_normalizer import blend_factor

        assert blend_factor(720, 420, 1140, 30) == 1.0

    def test_rising_edge_halfway(self):
        from lib.regulation_normalizer import blend_factor

        assert blend_factor(435, 420, 1140, 30) == 0.5

    def test_falling_edge_halfway(self):
        from lib.regulation_normalizer import blend_factor

        assert blend_factor(1125, 420, 1140, 30) == 0.5

    def test_zero_transition_is_step(self):
        from lib.regulation_normalizer import blend_factor

        assert blend_factor(420, 420, 1140, 0) == 1.0
        assert blend_factor(419, 420, 1140, 0) == 0.0


class TestRegulationNormalizer:
    def test_midday_uses_day_anchors(self):
        from lib.regulation_normalizer import RegulationNormalizer

        norm = RegulationNormalizer(_profile(), 420, 1140, 30, ("temp", "humidity", "co2"))
        out = array("f", [0.0, 0.0, 0.0])
        b = norm.update((29.0, 60.0, 800.0), 720, out)
        assert b == 1.0
        assert abs(out[0] - 75.0) < 1e-4  # day temp anchors
        assert abs(out[1] - 50.0) < 1e-4
        assert abs(out[2] - 50.0) < 1e-4

    def test_night_uses_night_anchors(self):
        from lib.regulation_normalizer import RegulationNormalizer

        norm = RegulationNormalizer(_profile(), 420, 1140, 30, ("temp", "humidity", "co2"))
        out = array("f", [0.0, 0.0, 0.0])
        b = norm.update((18.0, 60.0, 900.0), 0, out)
        assert b == 0.0
        assert abs(out[0] - 50.0) < 1e-4  # 18C is night ideal
        assert abs(out[2] - 50.0) < 1e-4  # 900ppm is night ideal

    def test_none_reading_is_neutral(self):
        from lib.regulation_normalizer import RegulationNormalizer

        norm = RegulationNormalizer(_profile(), 420, 1140, 30, ("temp", "humidity", "co2"))
        out = array("f", [0.0, 0.0, 0.0])
        norm.update((29.0, None, None), 720, out)
        assert out[1] == 50.0
        assert out[2] == 50.0

    def test_update_is_allocation_free_reuses_buffer(self):
        from lib.regulation_normalizer import RegulationNormalizer

        norm = RegulationNormalizer(_profile(), 420, 1140, 30, ("temp", "humidity", "co2"))
        out = array("f", [0.0, 0.0, 0.0])
        norm.update((29.0, 60.0, 800.0), 720, out)
        first = out[0]
        norm.update((14.0, 60.0, 800.0), 720, out)
        assert out[0] == 0.0
        assert first == 75.0
