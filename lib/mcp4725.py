# MCP4725 12-bit DAC driver
#
# Vendored from wayoda/micropython-mcp4725 (The Unlicense / public domain).
# Adapted for Pi Greenhouse:
#   - Default address 0x60 to match the PCB strap (A0 = GND); the schematic
#     wires the MCP4725 to the shared I2C0 bus alongside the DS3231 RTC
#     (0x68) and SSD1306 OLED (0x3C). The driver accepts any 7-bit address
#     so a board reworked to A0 = VCC (0x61) only needs a config change.
#   - write() returns True/False so the caller can detect a bus failure
#     without an exception in the schedule loop.

# Power-down modes (host -> bit pattern). 'Off' is the only one we use;
# the others tristate the output through different impedances.
POWER_DOWN_MODE = {"Off": 0, "1k": 1, "100k": 2, "500k": 3}


class MCP4725:
    """12-bit DAC controlled by a single 2-byte write (fast-mode).

    write(value) clamps value to the 12-bit range and emits the high
    nibble + low byte on I2C. The MCP4725 latches the new output before
    the I2C STOP returns, so the call is effectively synchronous.
    """

    def __init__(self, i2c, address: int = 0x60):
        self.i2c = i2c
        self.address = address
        self._buf = bytearray(2)

    def write(self, value: int) -> bool:
        """Push a 12-bit value (0..4095) to the DAC. Returns True on ACK."""
        if value < 0:
            value = 0
        value = value & 0xFFF
        self._buf[0] = (value >> 8) & 0xFF
        self._buf[1] = value & 0xFF
        return self.i2c.writeto(self.address, self._buf) == 2
