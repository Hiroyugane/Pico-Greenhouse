# Tests for lib/i2c_guard.py — the RecoverableI2C bus guard.
#
# The guard bounds and recovers a stuck shared I2C bus (the 2026-07-19
# ETIMEDOUT bootloop fix). These tests drive its inner bus by patching the
# module-level SoftI2C/I2C/Pin names that _build() references.

from unittest.mock import MagicMock

import pytest


def _guard(monkeypatch, inner_factory, **kwargs):
    """Construct a RecoverableI2C whose inner SoftI2C comes from inner_factory."""
    import lib.i2c_guard as g

    monkeypatch.setattr(g, "SoftI2C", inner_factory)
    from lib.i2c_guard import RecoverableI2C

    params = dict(sda=2, scl=3, freq=100000, use_soft=True, timeout_us=50000)
    params.update(kwargs)
    return RecoverableI2C(**params)


class TestPassthrough:
    def test_writeto_success_delegates(self, monkeypatch):
        inner = MagicMock()
        guard = _guard(monkeypatch, MagicMock(return_value=inner))
        guard.writeto(0x3C, b"hi")
        inner.writeto.assert_called_once_with(0x3C, b"hi")
        assert guard.recoveries == 0

    def test_readfrom_delegates(self, monkeypatch):
        inner = MagicMock()
        inner.readfrom.return_value = b"\x00" * 6
        guard = _guard(monkeypatch, MagicMock(return_value=inner))
        assert guard.readfrom(0x44, 6) == b"\x00" * 6

    def test_writeto_mem_delegates(self, monkeypatch):
        inner = MagicMock()
        guard = _guard(monkeypatch, MagicMock(return_value=inner))
        guard.writeto_mem(0x40, 0x06, b"\xff")
        inner.writeto_mem.assert_called_once_with(0x40, 0x06, b"\xff")

    def test_readfrom_mem_delegates(self, monkeypatch):
        inner = MagicMock()
        inner.readfrom_mem.return_value = b"\x01\x02"
        guard = _guard(monkeypatch, MagicMock(return_value=inner))
        assert guard.readfrom_mem(0x68, 0x00, 2) == b"\x01\x02"

    def test_writevto_delegates(self, monkeypatch):
        inner = MagicMock()
        guard = _guard(monkeypatch, MagicMock(return_value=inner))
        guard.writevto(0x3C, [b"\x40", b"data"])
        inner.writevto.assert_called_once_with(0x3C, [b"\x40", b"data"])

    def test_scan_delegates(self, monkeypatch):
        inner = MagicMock()
        inner.scan.return_value = [0x3C, 0x68]
        guard = _guard(monkeypatch, MagicMock(return_value=inner))
        assert guard.scan() == [0x3C, 0x68]


class TestRecovery:
    def test_oserror_triggers_recover_and_retry(self, monkeypatch):
        bad = MagicMock()
        bad.writeto.side_effect = OSError(110, "ETIMEDOUT")
        good = MagicMock()
        # first build -> bad; recover()'s rebuild -> good
        guard = _guard(monkeypatch, MagicMock(side_effect=[bad, good]))
        guard.writeto(0x3C, b"x")
        assert guard.recoveries == 1
        good.writeto.assert_called_once_with(0x3C, b"x")

    def test_persistent_oserror_reraises(self, monkeypatch):
        bad = MagicMock()
        bad.writeto.side_effect = OSError(110)
        bad2 = MagicMock()
        bad2.writeto.side_effect = OSError(110)
        guard = _guard(monkeypatch, MagicMock(side_effect=[bad, bad2]))
        with pytest.raises(OSError):
            guard.writeto(0x3C, b"x")
        assert guard.recoveries == 1

    def test_readfrom_mem_recovers(self, monkeypatch):
        bad = MagicMock()
        bad.readfrom_mem.side_effect = OSError(110)
        good = MagicMock()
        good.readfrom_mem.return_value = b"\xab"
        guard = _guard(monkeypatch, MagicMock(side_effect=[bad, good]))
        assert guard.readfrom_mem(0x68, 0x00, 1) == b"\xab"
        assert guard.recoveries == 1

    def test_recover_disabled_reraises_immediately(self, monkeypatch):
        bad = MagicMock()
        bad.writeto.side_effect = OSError(110)
        guard = _guard(monkeypatch, MagicMock(return_value=bad), recover_on_error=False)
        with pytest.raises(OSError):
            guard.writeto(0x3C, b"x")
        assert guard.recoveries == 0

    def test_recover_swallows_gpio_errors(self, monkeypatch):
        import lib.i2c_guard as g

        inner = MagicMock()
        monkeypatch.setattr(g, "SoftI2C", MagicMock(return_value=inner))
        from lib.i2c_guard import RecoverableI2C

        guard = RecoverableI2C(sda=2, scl=3)  # built with the working Pin mock
        # Now make every Pin(...) call blow up; recover() must not propagate.
        monkeypatch.setattr(g, "Pin", MagicMock(side_effect=RuntimeError("no gpio")))
        assert guard.recover() is False


class TestBuild:
    def test_use_soft_false_builds_hardware_i2c(self, monkeypatch):
        import lib.i2c_guard as g

        hw = MagicMock()
        factory = MagicMock(return_value=hw)
        monkeypatch.setattr(g, "I2C", factory)
        from lib.i2c_guard import RecoverableI2C

        guard = RecoverableI2C(sda=2, scl=3, port=0, use_soft=False)
        assert guard._i2c is hw
        factory.assert_called_once()

    def test_soft_unavailable_falls_back_to_hardware(self, monkeypatch):
        import lib.i2c_guard as g

        monkeypatch.setattr(g, "SoftI2C", None)
        hw = MagicMock()
        monkeypatch.setattr(g, "I2C", MagicMock(return_value=hw))
        from lib.i2c_guard import RecoverableI2C

        guard = RecoverableI2C(sda=2, scl=3, use_soft=True)
        assert guard._use_soft is False
        assert guard._i2c is hw
