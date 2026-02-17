# led_cycle_test.py
# Simple LED cycle test: press the menu button (GP9) to cycle through 6 status LEDs.
# Uses existing LED and LEDButtonHandler libraries.
#
# LEDs:
#   GP4  - DHT read (status)
#   GP5  - Service reminder
#   GP6  - SD card
#   GP7  - Fan
#   GP8  - Error
#   GP25 - On-board heartbeat
#
# Button: GP9 (short press = next LED)

import os
import sys

# Ensure the project root is on sys.path so `lib` and `host_shims` resolve
# regardless of which directory the script is launched from.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Host shim auto-detection
if sys.implementation.name != "micropython":
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "host_shims"))

import uasyncio as asyncio  # noqa: E402

from lib.led_button import LED, LEDButtonHandler  # noqa: E402

# Pin definitions from config
LED_PINS = [4, 5, 6, 7, 8, 25]
LED_NAMES = ["DHT (GP4)", "Reminder (GP5)", "SD (GP6)", "Fan (GP7)", "Error (GP8)", "Onboard (GP25)"]
BUTTON_PIN = 9


class LEDCycler:
    """Cycles through 6 status LEDs on each button press."""

    def __init__(self):
        self.leds = [LED(pin) for pin in LED_PINS]
        self.handler = LEDButtonHandler(led_pin=LED_PINS[0], button_pin=BUTTON_PIN)
        self.current_index = -1  # No LED lit initially
        self.handler.register_button_callback(self.next_led)
        print("[LEDCycler] Ready — press button on GP9 to cycle LEDs")
        print(f"[LEDCycler] LEDs: {', '.join(LED_NAMES)}")

    def next_led(self):
        """Turn off current LED, advance index, turn on next LED."""
        # Turn off previous
        if 0 <= self.current_index < len(self.leds):
            self.leds[self.current_index].off()

        # Advance (wrap around, or go back to -1 after last to turn all off)
        self.current_index += 1
        if self.current_index >= len(self.leds):
            self.current_index = 0

        # Turn on new LED
        self.leds[self.current_index].on()
        print(f"[LEDCycler] -> {LED_NAMES[self.current_index]}")

    def all_off(self):
        """Turn off all LEDs."""
        for led in self.leds:
            led.off()
        self.current_index = -1


async def main():
    cycler = LEDCycler()

    # Quick startup animation: walk all LEDs once
    print("[LEDCycler] Startup animation...")
    for i, led in enumerate(cycler.leds):
        led.on()
        print(f"  {LED_NAMES[i]}")
        await asyncio.sleep(0.3)
        led.off()
    print("[LEDCycler] Waiting for button presses (Ctrl+C to exit)")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        cycler.all_off()
        print("[LEDCycler] All LEDs off. Done.")


asyncio.run(main())
