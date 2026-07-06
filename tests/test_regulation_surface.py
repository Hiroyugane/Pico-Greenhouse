# Tests for lib/regulation_surface.py
# 2D hinge surface math, param ordering, clamps, monotonicity.


def _freeze(**over):
    """Freeze a surface built from config neutral defaults + overrides."""
    import config
    from lib.regulation_surface import freeze_surface

    return freeze_surface(config._surface(**over))


class TestParamOrder:
    def test_param_names_match_config(self):
        """Surface PARAM_NAMES must equal config._SURFACE_PARAM_NAMES (no drift)."""
        import config
        from lib.regulation_surface import NUM_PARAMS, PARAM_NAMES

        assert PARAM_NAMES == config._SURFACE_PARAM_NAMES
        assert NUM_PARAMS == len(config._SURFACE_PARAM_NAMES)

    def test_freeze_puts_values_in_order(self):
        import config
        from lib.regulation_surface import P_GAIN, freeze_surface

        frozen = freeze_surface(config._surface(gain=-2.0))
        assert frozen[P_GAIN] == -2.0


class TestNeutralSurface:
    def test_neutral_surface_is_zero_everywhere(self):
        """All-default surface (gain 0) clamps to out_min=0 → command 0."""
        from lib.regulation_surface import evaluate

        p = _freeze()
        for x in (0.0, 25.0, 50.0, 75.0, 100.0):
            for y in (0.0, 50.0, 100.0):
                assert evaluate(p, x, y) == 0.0


class TestLinearSurfaces:
    def test_heater_cold_full_ideal_zero(self):
        """gain=-2 (heater): cold x=0 → 100, ideal x=50 → 0, hot x=100 → 0."""
        from lib.regulation_surface import evaluate

        p = _freeze(gain=-2.0)
        assert abs(evaluate(p, 0.0, 50.0) - 100.0) < 1e-3
        assert abs(evaluate(p, 50.0, 50.0) - 0.0) < 1e-3
        assert abs(evaluate(p, 100.0, 50.0) - 0.0) < 1e-3

    def test_cooler_hot_full(self):
        """gain=2 (cooler): hot x=100 → 100, ideal → 0."""
        from lib.regulation_surface import evaluate

        p = _freeze(gain=2.0)
        assert abs(evaluate(p, 100.0, 50.0) - 100.0) < 1e-3
        assert abs(evaluate(p, 50.0, 50.0) - 0.0) < 1e-3

    def test_monotonic_along_x(self):
        from lib.regulation_surface import evaluate

        p = _freeze(gain=2.0)
        prev = -1.0
        for xi in range(50, 101):
            v = evaluate(p, float(xi), 50.0)
            assert v >= prev - 1e-6
            prev = v


class TestClampAndRescale:
    def test_output_clamped_to_0_100(self):
        """Steep gain saturates but never exceeds the rescaled range."""
        from lib.regulation_surface import evaluate

        p = _freeze(gain=10.0)
        for x in (0.0, 50.0, 100.0):
            v = evaluate(p, x, 50.0)
            assert 0.0 <= v <= 100.0

    def test_rescale_compresses_range(self):
        """out_min=0,out_max=50 rescales a raw-50 result to command 100."""
        from lib.regulation_surface import evaluate

        # gain=2 at x=75 → lin = 2*25 = 50; clamp to [0,50] → 50; rescale → 100.
        p = _freeze(gain=2.0, out_min=0.0, out_max=50.0)
        assert abs(evaluate(p, 75.0, 50.0) - 100.0) < 1e-3


class TestHinges:
    def test_high_hinge_adds_above_breakpoint(self):
        """A positive x-high hinge kinks the surface upward past its breakpoint."""
        from lib.regulation_surface import evaluate

        # Flat base (gain 0) + hinge slope 2 beyond x=70.
        p = _freeze(hx_hi1=2.0, bx_hi1=70.0)
        assert evaluate(p, 60.0, 50.0) == 0.0  # below breakpoint, still 0
        # At x=90: lin = 2*(90-70) = 40 → command 40.
        assert abs(evaluate(p, 90.0, 50.0) - 40.0) < 1e-3

    def test_low_hinge_adds_below_breakpoint(self):
        from lib.regulation_surface import evaluate

        p = _freeze(hx_lo1=2.0, bx_lo1=30.0)
        assert evaluate(p, 40.0, 50.0) == 0.0
        # At x=10: lin = 2*(30-10) = 40 → command 40.
        assert abs(evaluate(p, 10.0, 50.0) - 40.0) < 1e-3
