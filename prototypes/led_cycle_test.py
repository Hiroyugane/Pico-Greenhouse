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

import sys

# On CPython, ensure the project root and host_shims are on sys.path.
# MicroPython's `os` lacks `os.path`, and paths are already correct on-device.
if sys.implementation.name != "micropython":
    import os

    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
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
        # Use a dummy LED pin (GP25, also in the list) so the handler's
        # internal LED doesn't conflict with the cycling LEDs.
        self.handler = LEDButtonHandler(led_pin=25, button_pin=BUTTON_PIN, debounce_ms=200)
        self.current_index = -1  # No LED lit initially
        self.handler.register_button_callback(self.next_led)
        print("[LEDCycler] Ready — press button on GP9 to cycle LEDs")
        print(f"[LEDCycler] LEDs: {', '.join(LED_NAMES)}")

    def next_led(self):
        """Turn off current LED, advance index, turn on next LED."""
        # Turn off previous
        if 0 <= self.current_index < len(self.leds):
            self.leds[self.current_index].off()

        # Advance (wrap around)
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

    # Start the button polling task (dispatches callbacks outside ISR context)
    asyncio.create_task(cycler.handler.poll_button())

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
