# I2C0 bus scanner — run via Thonny on the Pico.
#
# Reports every responding I2C address on the shared bus. Used to
# confirm the MCP4725 grow-light DAC address (A0=GND → 0x60,
# A0=VCC → 0x61) before wiring the dimming driver. Should also list
# the DS3231 RTC (0x68) and SSD1306 OLED (0x3C) for context.
#
# Phase 0 of docs/notes/2026-05-14-pcb-codebase-gap-plan.md.

machine = __import__("machine")
time = __import__("time")

I2C_ID = 0
I2C_SDA = 0
I2C_SCL = 1
I2C_FREQ = 400000

KNOWN = {
    0x3C: "SSD1306 OLED",
    0x60: "MCP4725 DAC (A0=GND)",
    0x61: "MCP4725 DAC (A0=VCC)",
    0x68: "DS3231 RTC",
}


def main():
    i2c = machine.I2C(
        I2C_ID,
        sda=machine.Pin(I2C_SDA),
        scl=machine.Pin(I2C_SCL),
        freq=I2C_FREQ,
    )
    print("[i2c_scan] I2C0 init: sda=GP{}, scl=GP{}, freq={}".format(I2C_SDA, I2C_SCL, I2C_FREQ))
    time.sleep_ms(50)

    addrs = i2c.scan()
    print("[i2c_scan] {} device(s) responded".format(len(addrs)))
    for addr in addrs:
        label = KNOWN.get(addr, "unknown")
        print("  0x{:02X}  {}".format(addr, label))

    mcp = [a for a in addrs if a in (0x60, 0x61)]
    if not mcp:
        print("[i2c_scan] WARN: no MCP4725 detected (expected 0x60 or 0x61)")
    elif len(mcp) > 1:
        print("[i2c_scan] WARN: multiple MCP4725 candidates: {}".format([hex(a) for a in mcp]))
    else:
        print("[i2c_scan] MCP4725 confirmed at 0x{:02X} — set growlight.dac_i2c_address".format(mcp[0]))


if __name__ == "__main__":
    main()
