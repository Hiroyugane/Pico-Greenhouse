import time

from machine import I2C, Pin

# Initialize I2C0 on GP0/GP1
i2c = I2C(0, scl=Pin(1), sda=Pin(0), freq=400000)

# Scan for devices
devices = i2c.scan()
print("I2C devices found:", [hex(d) for d in devices])

# If display found, try basic test
if 0x3C in devices:
    from lib.ssd1306 import SSD1306_I2C

    oled = SSD1306_I2C(128, 64, i2c, addr=0x3C)
    oled.fill(0)
    oled.show()
    time.sleep(0.2)
    oled.text("TEST", 50, 28, 1)
    oled.show()
    print("Test pattern sent")
