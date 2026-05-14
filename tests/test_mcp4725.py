# Tests for lib/mcp4725.py
# Covers MCP4725 12-bit DAC fast-write protocol (2-byte write to I2C address).

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_i2c():
    bus = MagicMock()
    bus.writeto = MagicMock(return_value=2)
    return bus


class TestMCP4725FastWrite:
    def test_init_stores_address(self, mock_i2c):
        from lib.mcp4725 import MCP4725

        dac = MCP4725(mock_i2c, address=0x60)
        assert dac.address == 0x60

    def test_default_address_is_0x60(self, mock_i2c):
        from lib.mcp4725 import MCP4725

        dac = MCP4725(mock_i2c)
        assert dac.address == 0x60

    def test_write_zero(self, mock_i2c):
        """write(0) sends [0x00, 0x00]."""
        from lib.mcp4725 import MCP4725

        dac = MCP4725(mock_i2c, address=0x60)
        dac.write(0)
        mock_i2c.writeto.assert_called_once()
        addr, data = mock_i2c.writeto.call_args.args
        assert addr == 0x60
        assert bytes(data) == bytes([0x00, 0x00])

    def test_write_full_scale(self, mock_i2c):
        """write(0xFFF) sends [0x0F, 0xFF] (12-bit max packed into 16 bits)."""
        from lib.mcp4725 import MCP4725

        dac = MCP4725(mock_i2c, address=0x60)
        dac.write(0xFFF)
        addr, data = mock_i2c.writeto.call_args.args
        assert addr == 0x60
        assert bytes(data) == bytes([0x0F, 0xFF])

    def test_write_midscale(self, mock_i2c):
        """write(0x800) sends [0x08, 0x00]."""
        from lib.mcp4725 import MCP4725

        dac = MCP4725(mock_i2c, address=0x60)
        dac.write(0x800)
        _, data = mock_i2c.writeto.call_args.args
        assert bytes(data) == bytes([0x08, 0x00])

    def test_write_clamps_negative_to_zero(self, mock_i2c):
        from lib.mcp4725 import MCP4725

        dac = MCP4725(mock_i2c)
        dac.write(-100)
        _, data = mock_i2c.writeto.call_args.args
        assert bytes(data) == bytes([0x00, 0x00])

    def test_write_clamps_overflow_to_12bit(self, mock_i2c):
        """Values > 0xFFF are masked to 12 bits."""
        from lib.mcp4725 import MCP4725

        dac = MCP4725(mock_i2c)
        dac.write(0x1234)  # masked to 0x234
        _, data = mock_i2c.writeto.call_args.args
        assert bytes(data) == bytes([0x02, 0x34])

    def test_write_returns_true_on_ack(self, mock_i2c):
        """write() returns True when the I2C bus confirms 2 bytes sent."""
        from lib.mcp4725 import MCP4725

        mock_i2c.writeto.return_value = 2
        dac = MCP4725(mock_i2c)
        assert dac.write(0x100) is True

    def test_write_returns_false_on_partial(self, mock_i2c):
        from lib.mcp4725 import MCP4725

        mock_i2c.writeto.return_value = 1
        dac = MCP4725(mock_i2c)
        assert dac.write(0x100) is False

    def test_writeto_address_changes_with_constructor_arg(self, mock_i2c):
        """Constructing with 0x61 (A0=VCC) routes writes there."""
        from lib.mcp4725 import MCP4725

        dac = MCP4725(mock_i2c, address=0x61)
        dac.write(0x123)
        addr, _ = mock_i2c.writeto.call_args.args
        assert addr == 0x61
