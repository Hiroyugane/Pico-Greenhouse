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


def _cfg_surface(name):
    """Freeze the shipped config surface for a regulator by name."""
    import config
    from lib.regulation_surface import freeze_surface

    return freeze_surface(config.DEVICE_CONFIG["regulation"]["regulators"][name]["surface"])


class TestShippedCouplings:
    """Physics couplings baked into the default surfaces (operator-tunable)."""

    def test_humidifier_evaporative_cooling_at_ideal_rh(self):
        # x = RH dev (50 = ideal), y = temp dev. Hot air pulls humidifier on for
        # evaporative cooling even at ideal RH; cold air suppresses it.
        from lib.regulation_surface import evaluate

        p = _cfg_surface("humidifier")
        hot = evaluate(p, 50.0, 100.0)
        cold = evaluate(p, 50.0, 0.0)
        assert hot > 0.0
        assert cold == 0.0
        assert hot > cold

    def test_humidifier_suppressed_when_already_humid(self):
        # Humid (x>55) cancels the evaporative-cooling bias so it never adds
        # moisture to a humid room, even when hot.
        from lib.regulation_surface import evaluate

        p = _cfg_surface("humidifier")
        assert evaluate(p, 80.0, 100.0) == 0.0

    def test_humidifier_dry_is_hotter_wetter(self):
        from lib.regulation_surface import evaluate

        p = _cfg_surface("humidifier")
        assert evaluate(p, 20.0, 100.0) > evaluate(p, 20.0, 0.0)

    def test_exhaust_vents_on_humidity_alone(self):
        # Ideal temp, high humidity → exhaust still opens (dumps moisture).
        from lib.regulation_surface import evaluate

        p = _cfg_surface("exhaust")
        assert evaluate(p, 50.0, 100.0) > 0.0

    def test_cooler_amplified_by_humidity(self):
        # Mildly hot: humid air runs the cooler harder (condensation dehumidifies).
        from lib.regulation_surface import evaluate

        p = _cfg_surface("cooler")
        assert evaluate(p, 75.0, 100.0) > evaluate(p, 75.0, 0.0)

    def test_cooler_never_runs_when_cold(self):
        from lib.regulation_surface import evaluate

        p = _cfg_surface("cooler")
        assert evaluate(p, 30.0, 100.0) == 0.0  # cold + humid → still off

    def test_heater_amplified_by_humidity(self):
        # Cold: humid air warms a touch more (warming lowers relative humidity).
        from lib.regulation_surface import evaluate

        p = _cfg_surface("heater")
        assert evaluate(p, 25.0, 100.0) > evaluate(p, 25.0, 0.0)

    def test_heater_never_runs_when_hot(self):
        from lib.regulation_surface import evaluate

        p = _cfg_surface("heater")
        assert evaluate(p, 80.0, 100.0) == 0.0  # hot + humid → still off

    def test_circulation_is_a_bowl(self):
        # Zero at ideal, positive whenever either axis drifts either direction.
        from lib.regulation_surface import evaluate

        p = _cfg_surface("circulation")
        assert evaluate(p, 50.0, 50.0) == 0.0
        for x, y in ((100.0, 50.0), (0.0, 50.0), (50.0, 100.0), (50.0, 0.0), (0.0, 0.0), (100.0, 100.0)):
            assert evaluate(p, x, y) > 0.0

    def test_deadband_near_ideal(self):
        """Each regulator is silent inside its own deadband and speaks just outside it.

        The widths are read from config rather than written out here. The
        2026-07-22 retune narrowed every deadband — the old fixed deviations
        (55 for the exhaust, 45 for the cooler) are now well inside the active
        ramp — and a test that pins literals only records what the deadbands
        used to be. What must stay true is the shape: no output at ideal, output
        as soon as the breakpoint is passed.
        """
        import config

        from lib.regulation_surface import evaluate

        regs = config.DEVICE_CONFIG["regulation"]["regulators"]
        # (regulator, its first breakpoint, which side of ideal it responds on)
        for name, key, side in (("heater", "bx_lo1", -1.0), ("cooler", "bx_hi1", 1.0), ("exhaust", "bx_hi1", 1.0)):
            p = _cfg_surface(name)
            edge = regs[name]["surface"][key]
            inside = edge - side * 0.5
            outside = edge + side * 2.0
            assert evaluate(p, 50.0, 50.0) == 0.0, name  # dead at ideal
            assert evaluate(p, inside, inside) == 0.0, name
            assert evaluate(p, outside, outside) > 0.0, name


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
