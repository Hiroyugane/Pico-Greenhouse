# OLED Display Controller - Menu-driven SSD1306 display
# Dennis Hiro, 2026-03-02
#
# Manages a 128×64 SSD1306 OLED display on the shared I2C bus.
# Renders a set of menu pages, cycles on short button press,
# and executes context-sensitive actions on long button press.
#
# Menu order:
#   0: temp      – temperature stats (now / hi / lo / avg)
#   1: humidity  – humidity stats (now / hi / lo / avg)
#   2: service   – service reminder status
#   3: sd        – SD card space and mount status
#   4: alerts    – active warnings and errors
#   5: system    – current time, uptime, buffer entries
#   6: relays    – fan and growlight relay states
#   7: reg       – regulation engine band/latch, deviations, commanded vector
#   8: co2       – CO2 ppm + override status
#   9: soil      – soil moisture % + raw value
#  10: debug     – debug-actions entry; long-press opens a sub-menu where
#                  short-press cycles actions (wipe logs, cycle relays,
#                  heater 5 s, growlight pulse, growlight dim sweep) and
#                  long-press executes the highlighted action (destructive
#                  actions require a second long-press to confirm).

import gc
import os
import time

import uasyncio as asyncio

try:
    _ticks_ms = time.ticks_ms  # MicroPython
except AttributeError:

    def _ticks_ms() -> int:  # CPython fallback
        return int(time.time() * 1000)


try:
    from lib.build_info import VERSION as _BUILD_VERSION
except ImportError:
    try:
        from build_info import VERSION as _BUILD_VERSION  # on-device sys.path
    except ImportError:
        _BUILD_VERSION = "dev"


# ── Menu identifiers (ordered) ─────────────────────────────────────────────
MENUS = ("temp", "humidity", "service", "sd", "alerts", "system", "relays", "reg", "co2", "soil", "debug")

# Highest row index _row() can still draw on a 64 px panel (y = 12 + row*10).
_MAX_ROW = 4


class OLEDDisplay:
    """
    Menu-driven OLED display controller for Pi Greenhouse.

    Renders system information on a 128×64 SSD1306 display.
    Menu cycling is driven by the short-press button callback registered
    in main.py. Long-press actions are context-sensitive per menu.

    Dependencies injected at construction:
    - i2c:              machine.I2C shared bus
    - time_provider:    RTCTimeProvider for current time
    - th_logger:       TempHumidityLogger for temperature/humidity stats
    - buffer_manager:   BufferManager for SD metrics
    - status_manager:   StatusManager for warnings/errors
    - reminder:         ServiceReminder for service status
    - fans:             list of FanController instances
    - growlight:        GrowlightController instance
    - sd_remount_cb:    callable() → triggers SD remount from outside
    - start_time_ms:    ticks_ms at system boot (for uptime calculation)
    - logger:           EventLogger (optional)
    - width, height:    display dimensions (default 128×64)
    - i2c_address:      SSD1306 I2C address (default 0x3C)
    - refresh_interval_s: how often to redraw (default 5 s)
    - stats_window_s:   stats look-back window (default 3600 s)
    - menu_timeout_s:   return to menu 0 after inactivity (default 30 s)
    - display_timeout_s: turn off display after inactivity (default 120 s, extends OLED lifetime)

    Attributes:
        current_menu (int): index into MENUS tuple
        display_on (bool): whether the display is initialized and working
    """

    def __init__(
        self,
        i2c,
        time_provider,
        th_logger,
        buffer_manager,
        status_manager,
        reminder,
        fans,
        growlight,
        sd_remount_cb=None,
        start_time_ms: int = 0,
        logger=None,
        width: int = 128,
        height: int = 64,
        i2c_address: int = 0x3C,
        refresh_interval_s: int = 5,
        stats_window_s: int = 3600,
        menu_timeout_s: int = 30,
        display_timeout_s: int = 120,
        startup_banner_s: float = 2.0,
        vram_clear_delay_s: float = 0.05,
        invert_delay_s: float = 0.1,
        max_render_errors: int = 5,
        co2_logger=None,
        soil_logger=None,
        heater=None,
        regulation=None,
        feedback_blink_cb=None,
        event_log_path=None,
        debug_confirm_timeout_s: float = 8.0,
        debug_status_show_ms: int = 3000,
        debug_test_heater_s: float = 5.0,
        debug_test_growlight_pulse_s: float = 2.0,
        debug_test_growlight_dim_levels_pct=None,
        debug_test_growlight_dim_step_s: float = 1.0,
        debug_test_relay_pulse_s: float = 1.0,
        relays=None,
    ):
        self._i2c = i2c
        self._time_provider = time_provider
        self._th_logger = th_logger
        self._buffer_manager = buffer_manager
        self._status_manager = status_manager
        self._reminder = reminder
        self._fans = fans or []
        # Wired mains relay channels as (label, gpio_number, switch|None);
        # switch is None for a channel that is wired but has no controller.
        self._relays = list(relays or [])
        self._growlight = growlight
        self._sd_remount_cb = sd_remount_cb
        self._start_time_ms = start_time_ms
        self._logger = logger
        self._co2_logger = co2_logger
        self._soil_logger = soil_logger
        self._heater = heater
        self._regulation = regulation
        self._feedback_blink_cb = feedback_blink_cb
        self._event_log_path = event_log_path
        self._width = width
        self._height = height
        self._i2c_address = i2c_address
        self._refresh_interval_s = refresh_interval_s
        self._stats_window_s = stats_window_s
        self._menu_timeout_s = menu_timeout_s
        self._display_timeout_s = display_timeout_s
        self._startup_banner_s = startup_banner_s
        self._vram_clear_delay_s = vram_clear_delay_s
        self._invert_delay_s = invert_delay_s
        # Runtime self-disable: after this many consecutive render (I2C)
        # failures, stop rendering so a dead/marginal display can't keep
        # hammering the shared bus or starve the watchdog (2026-07-19 guard).
        self._max_render_errors = max_render_errors
        self._render_error_count = 0

        # Debug sub-menu config + state
        self._debug_confirm_timeout_ms = int(debug_confirm_timeout_s * 1000)
        self._debug_status_show_ms = int(debug_status_show_ms)
        self._debug_test_heater_s = debug_test_heater_s
        self._debug_test_growlight_pulse_s = debug_test_growlight_pulse_s
        self._debug_test_growlight_dim_levels_pct = list(debug_test_growlight_dim_levels_pct or [0, 25, 50, 75, 100, 0])
        self._debug_test_growlight_dim_step_s = debug_test_growlight_dim_step_s
        self._debug_test_relay_pulse_s = debug_test_relay_pulse_s

        self._debug_mode: bool = False
        self._debug_action_idx: int = 0
        self._debug_confirm_pending: bool = False
        self._debug_confirm_ms: int = 0
        self._debug_running: bool = False
        self._debug_status: str = ""
        self._debug_status_until_ms: int = 0
        self._debug_actions = self._build_debug_actions()

        self.current_menu: int = 0
        self.display_on: bool = False
        self._display_active: bool = False  # Whether the display is powered on (separate from display_on)
        self._oled = None
        self._last_interaction_ms: int = _ticks_ms()
        self._last_activity_ms: int = _ticks_ms()  # Track activity for display timeout

        self._init_display()

    # ── Initialization ────────────────────────────────────────────────────

    def _init_display(self) -> None:
        """Initialize SSD1306 driver. Non-fatal if display absent."""
        try:
            from lib.ssd1306 import SSD1306_I2C

            self._oled = SSD1306_I2C(self._width, self._height, self._i2c, addr=self._i2c_address)

            # Aggressive clear sequence to remove garbage pixels
            for _ in range(3):  # Triple-clear to ensure VRAM is zeroed
                self._oled.fill(0)
                self._oled.show()
                if self._vram_clear_delay_s:
                    time.sleep(self._vram_clear_delay_s)

            # Force display refresh by inverting and reverting
            self._oled.invert(1)
            self._oled.show()
            if self._vram_clear_delay_s:
                time.sleep(self._vram_clear_delay_s)
            self._oled.invert(0)
            self._oled.show()
            if self._invert_delay_s:
                time.sleep(self._invert_delay_s)

            # Final clear
            self._oled.fill(0)
            self._oled.show()
            if self._invert_delay_s:
                time.sleep(self._invert_delay_s)

            # Display startup message
            self._oled.fill(0)
            self._oled.text("Pi Greenhouse", 8, 24, 1)
            self._oled.text("Ready!", 48, 36, 1)
            self._oled.show()
            if self._startup_banner_s:
                time.sleep(self._startup_banner_s)

            self.display_on = True
            if self._logger:
                self._logger.info("OLEDDisplay", f"SSD1306 initialized at 0x{self._i2c_address:02X}")
            else:
                print(f"[OLEDDisplay] SSD1306 at 0x{self._i2c_address:02X}")

            # Do initial menu render
            self._display_active = True  # Display starts powered on
            self.render()
            if self._logger:
                self._logger.debug("OLEDDisplay", "initial render complete")
        except Exception as e:
            self.display_on = False
            if self._logger:
                self._logger.warning("OLEDDisplay", f"Display init failed (non-critical): {e}")
            else:
                print(f"[OLEDDisplay] Init failed: {e}")

    # ── Public API ────────────────────────────────────────────────────────

    def next_menu(self) -> None:
        """Advance to next menu (wraps around). Called on short button press.

        Inside the debug sub-menu, short press cycles through debug actions
        instead of advancing the top-level menu. A short press also cancels
        any pending destructive-action confirmation.
        """
        self._last_interaction_ms = _ticks_ms()
        self._last_activity_ms = self._last_interaction_ms
        # Turn on display if it was off
        if not self._display_active:
            self._turn_on_display()

        if self._debug_mode:
            if self._debug_running:
                # Swallow input while an action is executing.
                self.render()
                return
            if self._debug_confirm_pending:
                self._debug_confirm_pending = False
                self._set_debug_status("cancelled")
                self.render()
                return
            if self._debug_actions:
                self._debug_action_idx = (self._debug_action_idx + 1) % len(self._debug_actions)
                if self._logger:
                    self._logger.debug(
                        "OLEDDisplay",
                        "debug action selected",
                        action=self._debug_actions[self._debug_action_idx]["id"],
                    )
            self.render()
            return

        self.current_menu = (self.current_menu + 1) % len(MENUS)
        if self._logger:
            self._logger.debug("OLEDDisplay", "menu changed", menu=MENUS[self.current_menu])
        self.render()

    def long_press_action(self) -> None:
        """
        Execute context-sensitive action for the current menu.

        Menu → action:
        - temp / humidity: clear reading history
        - service:         reset service reminder
        - sd:              trigger SD remount
        - debug (entry):   open the debug actions sub-menu
        - debug (sub):     execute highlighted action (destructive ones
                           require a second long-press to confirm)
        - others:          no-op
        """
        menu = MENUS[self.current_menu]
        self._last_interaction_ms = _ticks_ms()
        self._last_activity_ms = self._last_interaction_ms
        if not self._display_active:
            self._turn_on_display()

        if menu == "debug":
            self._handle_debug_long_press()
            return

        if menu in ("temp", "humidity"):
            if self._th_logger:
                self._th_logger.clear_history()
            if self._logger:
                self._logger.info("OLEDDisplay", "Long press: cleared temp/hum history")
        elif menu == "service":
            if self._reminder:
                self._reminder.reset()
            if self._logger:
                self._logger.info("OLEDDisplay", "Long press: service reminder reset")
        elif menu == "sd":
            if self._sd_remount_cb:
                self._sd_remount_cb()
            if self._logger:
                self._logger.info("OLEDDisplay", "Long press: SD remount requested")
        else:
            if self._logger:
                self._logger.debug("OLEDDisplay", "Long press: no action for menu", menu=menu)
        self.render()

    # ── Debug sub-menu ────────────────────────────────────────────────────

    def _build_debug_actions(self):
        """Construct the ordered list of available debug actions.

        Skips actions whose hardware dependency is missing so the operator
        never lands on a no-op (e.g. dim sweep when no DAC is wired).
        """
        actions = [
            {
                "id": "wipe_logs",
                "label": "Wipe logs",
                "destructive": True,
                "handler": self._action_wipe_logs,
            },
            {
                "id": "cycle_relays",
                "label": "Cycle relays",
                "destructive": False,
                "handler": self._action_cycle_relays,
            },
        ]
        if self._heater is not None:
            actions.append(
                {
                    "id": "test_heater",
                    "label": "Heater 5s",
                    "destructive": False,
                    "handler": self._action_test_heater,
                }
            )
        if self._growlight is not None:
            actions.append(
                {
                    "id": "test_growlight",
                    "label": "Light pulse",
                    "destructive": False,
                    "handler": self._action_test_growlight,
                }
            )
            if getattr(self._growlight, "dac", None) is not None:
                actions.append(
                    {
                        "id": "test_growlight_dim",
                        "label": "Dim sweep",
                        "destructive": False,
                        "handler": self._action_test_growlight_dim,
                    }
                )
        return actions

    def _set_debug_status(self, text: str) -> None:
        self._debug_status = text
        self._debug_status_until_ms = _ticks_ms() + self._debug_status_show_ms

    def _exit_debug_mode(self) -> None:
        """Leave the debug sub-menu and reset transient state."""
        self._debug_mode = False
        self._debug_confirm_pending = False
        self._debug_action_idx = 0

    def _handle_debug_long_press(self) -> None:
        if not self._debug_mode:
            self._debug_mode = True
            self._debug_action_idx = 0
            self._debug_confirm_pending = False
            self._debug_status = ""
            if self._logger:
                self._logger.info("OLEDDisplay", "Debug sub-menu entered")
            self.render()
            return

        if self._debug_running or not self._debug_actions:
            self.render()
            return

        action = self._debug_actions[self._debug_action_idx]
        if action["destructive"] and not self._debug_confirm_pending:
            self._debug_confirm_pending = True
            self._debug_confirm_ms = _ticks_ms()
            if self._logger:
                self._logger.info("OLEDDisplay", f"Debug confirm armed: {action['id']}")
            self.render()
            return

        self._debug_confirm_pending = False
        self._dispatch_debug_action(action)

    def _dispatch_debug_action(self, action) -> None:
        """Spawn the action's coroutine and render the running state."""
        self._debug_running = True
        if self._logger:
            self._logger.info("OLEDDisplay", f"Debug action running: {action['id']}")

        async def _runner():
            ok = True
            err = None
            try:
                await action["handler"]()
            except Exception as exc:
                ok = False
                err = str(exc)
                if self._logger:
                    self._logger.error("OLEDDisplay", f"Debug action {action['id']} failed: {exc}")
            finally:
                self._debug_running = False
                self._set_debug_status("done" if ok else f"FAIL {err}"[:16])
                if ok and self._feedback_blink_cb:
                    try:
                        self._feedback_blink_cb()
                    except Exception as exc:
                        if self._logger:
                            self._logger.warning("OLEDDisplay", f"Feedback blink failed: {exc}")
                self.render()

        try:
            asyncio.create_task(_runner())
        except Exception as exc:
            # Fall back to a synchronous status update so the UI doesn't appear stuck.
            self._debug_running = False
            self._set_debug_status(f"FAIL {exc}"[:16])
            if self._logger:
                self._logger.error("OLEDDisplay", f"Debug task spawn failed: {exc}")
        self.render()

    # ── Debug action implementations ──────────────────────────────────────

    async def _action_wipe_logs(self) -> None:
        """Drop in-memory buffers, the fallback CSV, and the event log file.

        Sensor CSVs on the SD card are *not* removed — they are scientific
        data, and the user can format the card if a full wipe is needed.
        """
        bm = self._buffer_manager
        if bm is not None:
            try:
                bm._buffers = {}
            except Exception:
                pass
            try:
                clear_fn = getattr(bm, "clear_fallback_startup", None)
                if callable(clear_fn):
                    clear_fn()
            except Exception:
                pass
        if self._event_log_path:
            try:
                os.remove(self._event_log_path)
            except Exception:
                pass
        await asyncio.sleep(0)

    async def _action_cycle_relays(self) -> None:
        """Pulse each wired relay channel ON for ``test_relay_pulse_s``.

        Relay channels only — the PWM fans are not relays and are excluded, so
        the audible click count matches the number of mains channels. The
        regulation engine reasserts its own command on the next tick, so the
        test is a visible click + brief activity, not a lasting change.
        """
        for _label, _pin, switch in self._relays:
            if switch is None:
                continue
            try:
                switch.turn_on()
                await asyncio.sleep(self._debug_test_relay_pulse_s)
            finally:
                try:
                    switch.turn_off()
                except Exception:
                    pass

    async def _action_test_heater(self) -> None:
        """Drive the heater gate HIGH for ``test_heater_s`` then LOW."""
        if self._heater is None:
            return
        try:
            self._heater.turn_on()
            await asyncio.sleep(self._debug_test_heater_s)
        finally:
            try:
                self._heater.turn_off()
            except Exception:
                pass

    async def _action_test_growlight(self) -> None:
        """Pulse the growlight relay (and DAC, when present) at default level."""
        if self._growlight is None:
            return
        try:
            self._growlight.turn_on()
            await asyncio.sleep(self._debug_test_growlight_pulse_s)
        finally:
            try:
                self._growlight.turn_off()
            except Exception:
                pass

    async def _action_test_growlight_dim(self) -> None:
        """Step through configured dim levels with a fixed dwell at each."""
        if self._growlight is None or getattr(self._growlight, "dac", None) is None:
            return
        set_level = getattr(self._growlight, "set_level", None)
        if not callable(set_level):
            return
        try:
            for level in self._debug_test_growlight_dim_levels_pct:
                set_level(level)
                await asyncio.sleep(self._debug_test_growlight_dim_step_s)
        finally:
            try:
                set_level(0)
            except Exception:
                pass

    def render(self) -> None:
        """Render the current menu to the display. No-op if display is off or inactive."""
        if not self.display_on or not self._display_active or self._oled is None:
            return
        try:
            self._oled.fill(0)
            menu = MENUS[self.current_menu]
            if self._logger:
                self._logger.debug("OLEDDisplay", f"rendering menu={menu}")
            getattr(self, f"_render_{menu}")()
            self._oled.show()
            self._render_error_count = 0  # a clean render clears the fault streak
        except Exception as e:
            if self._logger:
                self._logger.error("OLEDDisplay", f"Render error (menu={MENUS[self.current_menu]}): {e}")
            else:
                print(f"[OLEDDisplay] Render error: {e}")
            # A marginal/stuck shared I2C bus surfaces here as ETIMEDOUT. After
            # too many in a row, disable the display so refresh_loop no-ops and
            # never touches the bus again (no bus I/O on disable — it may be
            # wedged). The boot-time `enabled` flag is the hard off-switch.
            self._render_error_count += 1
            if self._max_render_errors and self._render_error_count >= self._max_render_errors:
                self.display_on = False
                if self._logger:
                    self._logger.warning(
                        "OLEDDisplay",
                        f"auto-disabled after {self._render_error_count} consecutive render errors",
                    )

    async def refresh_loop(self) -> None:
        """
        Async task: periodically re-render the current menu.

        Also handles menu timeout: returns to menu 0 after
        menu_timeout_s seconds of no button presses.

        Display timeout: turns off display after display_timeout_s
        seconds of no activity to extend OLED lifetime.
        """
        while True:
            try:
                # Timeout: return to default menu after inactivity
                if self._menu_timeout_s > 0:
                    idle_ms = _ticks_ms() - self._last_interaction_ms
                    if idle_ms >= self._menu_timeout_s * 1000 and (self.current_menu != 0 or self._debug_mode):
                        if self._debug_mode and not self._debug_running:
                            self._exit_debug_mode()
                        self.current_menu = 0
                        if self._logger:
                            self._logger.debug("OLEDDisplay", "menu timeout → returned to temp")

                # Confirm prompt auto-cancels after debug_confirm_timeout_s
                if (
                    self._debug_mode
                    and self._debug_confirm_pending
                    and self._debug_confirm_timeout_ms > 0
                    and _ticks_ms() - self._debug_confirm_ms >= self._debug_confirm_timeout_ms
                ):
                    self._debug_confirm_pending = False
                    self._set_debug_status("cancelled")

                # Display timeout: turn off display after inactivity
                if self._display_timeout_s > 0 and self._display_active:
                    activity_idle_ms = _ticks_ms() - self._last_activity_ms
                    if activity_idle_ms >= self._display_timeout_s * 1000:
                        if self._debug_mode and not self._debug_running:
                            self._exit_debug_mode()
                        self._turn_off_display()

                self.render()
                await asyncio.sleep(self._refresh_interval_s)

            except asyncio.CancelledError:
                self._clear_display()
                if self._logger:
                    self._logger.warning("OLEDDisplay", "Refresh loop cancelled")
                raise
            except Exception as e:
                if self._logger:
                    self._logger.error("OLEDDisplay", f"Refresh loop error: {e}")
                await asyncio.sleep(1)

    # ── Display Power Management ──────────────────────────────────────

    def _turn_off_display(self) -> None:
        """Turn off the physical display to extend OLED lifetime."""
        if not self._display_active or self._oled is None:
            return
        try:
            self._oled.fill(0)
            self._oled.show()
            self._display_active = False
            if self._logger:
                self._logger.debug("OLEDDisplay", f"Display turned off after {self._display_timeout_s}s inactivity")
        except Exception as e:
            if self._logger:
                self._logger.warning("OLEDDisplay", f"Error turning off display: {e}")

    def _turn_on_display(self) -> None:
        """Turn on the physical display from sleep."""
        if self._display_active or self._oled is None:
            return
        try:
            self._display_active = True
            self._last_activity_ms = _ticks_ms()  # Reset inactivity timer
            if self._logger:
                self._logger.debug("OLEDDisplay", "Display turned on by button press")
        except Exception as e:
            if self._logger:
                self._logger.warning("OLEDDisplay", f"Error turning on display: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _clear_display(self) -> None:
        """Clear the display (called on shutdown)."""
        if self._oled:
            try:
                self._oled.fill(0)
                self._oled.show()
            except Exception:
                pass

    def _header(self, title: str) -> None:
        """Draw a menu title with underline on the top row."""
        if not self._oled:
            return
        o = self._oled
        o.text(title, 0, 0, 1)
        o.hline(0, 9, self._width, 1)

    def _row(self, text: str, row: int) -> None:
        """Draw text on display row (0-based, each row = 10 px after header)."""
        if not self._oled:
            return
        y = 12 + row * 10
        if y + 8 <= self._height:
            self._oled.text(text[:16], 0, y, 1)

    @staticmethod
    def _fmt_f(val, decimals: int = 1) -> str:
        """Format a float or None as a string."""
        if val is None:
            return "--"
        fmt = f"{val:.{decimals}f}"
        return fmt

    def _uptime_str(self) -> str:
        """Return a human-readable uptime string (e.g. '3d 2h 15m')."""
        elapsed_ms = _ticks_ms() - self._start_time_ms
        total_s = elapsed_ms // 1000
        days = total_s // 86400
        hours = (total_s % 86400) // 3600
        mins = (total_s % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h {mins}m"
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m {total_s % 60}s"

    # ── Menu renderers ────────────────────────────────────────────────────

    def _render_temp(self) -> None:
        stats = self._th_logger.get_stats(self._stats_window_s) if self._th_logger else {}
        self._header("TEMPERATURE")
        self._row(f"Now: {self._fmt_f(stats.get('temp_now'))}C", 0)
        self._row(f"Hi:  {self._fmt_f(stats.get('temp_hi'))}C", 1)
        self._row(f"Lo:  {self._fmt_f(stats.get('temp_lo'))}C", 2)
        self._row(f"Avg: {self._fmt_f(stats.get('temp_avg'))}C", 3)
        # Long-press hint at bottom
        if self._oled:
            self._oled.text("[HOLD]=clr", 68, 56, 1)

    def _render_humidity(self) -> None:
        stats = self._th_logger.get_stats(self._stats_window_s) if self._th_logger else {}
        self._header("HUMIDITY")
        self._row(f"Now: {self._fmt_f(stats.get('hum_now'))}%", 0)
        self._row(f"Hi:  {self._fmt_f(stats.get('hum_hi'))}%", 1)
        self._row(f"Lo:  {self._fmt_f(stats.get('hum_lo'))}%", 2)
        self._row(f"Avg: {self._fmt_f(stats.get('hum_avg'))}%", 3)
        if self._oled:
            self._oled.text("[HOLD]=clr", 68, 56, 1)

    def _render_service(self) -> None:
        self._header("SERVICE")
        if self._reminder:
            s = self._reminder.get_status()
            elapsed = s.get("days_elapsed", 0)
            interval = s.get("days_interval", 7)
            is_due = s.get("is_due", False)
            last = s.get("last_serviced", "")[:10]  # date part only
            self._row(f"Last: {last}", 0)
            self._row(f"Days: {elapsed}/{interval}", 1)
            self._row("DUE!" if is_due else "OK", 2)
            if self._oled:
                self._oled.text("[HOLD]=rst", 68, 56, 1)
        else:
            self._row("No reminder", 0)

    def _render_sd(self) -> None:
        self._header("SD CARD")
        try:
            import os

            stat = os.statvfs("/sd")
            block_size = stat[0]
            total_blocks = stat[2]
            free_blocks = stat[3]
            total_mb = (total_blocks * block_size) // (1024 * 1024)
            free_mb = (free_blocks * block_size) // (1024 * 1024)
            used_mb = total_mb - free_mb
            mounted = self._status_manager._sd_healthy if self._status_manager else True
            self._row("Mounted" if mounted else "UNMOUNTED", 0)
            self._row(f"Used: {used_mb}MB", 1)
            self._row(f"Free: {free_mb}MB", 2)
            if self._oled:
                self._oled.text("[HOLD]=mnt", 68, 56, 1)
        except Exception:
            self._row("SD error", 0)

    def _render_alerts(self) -> None:
        self._header("ALERTS")
        if self._status_manager:
            status = self._status_manager.get_status()
            errors = status.get("errors", [])
            warnings = status.get("warnings", [])
            if not errors and not warnings:
                self._row("All OK", 0)
            else:
                row = 0
                for e in errors[:2]:
                    self._row(f"ERR:{e[:11]}", row)
                    row += 1
                for w in warnings[:2]:
                    self._row(f"WRN:{w[:11]}", row)
                    row += 1
        else:
            self._row("No data", 0)

    def _render_system(self) -> None:
        self._header("SYSTEM")
        now = self._time_provider.now_timestamp() if self._time_provider else "?"
        date_time_str = now[:16] if len(now) >= 16 else now  # "YYYY-MM-DD HH:MM"
        metrics = self._buffer_manager.get_metrics() if self._buffer_manager else {}
        buffered = metrics.get("buffer_entries", 0)

        # Memory calculation
        if hasattr(gc, "mem_alloc") and hasattr(gc, "mem_free"):
            mem_alloc = gc.mem_alloc()
            mem_free = gc.mem_free()
            used_pct = (mem_alloc / (mem_alloc + mem_free)) * 100 if (mem_alloc + mem_free) > 0 else 0
        else:
            used_pct = 0

        self._row(date_time_str, 0)
        self._row(f"Ver:{_BUILD_VERSION}", 1)
        self._row(f"Up: {self._uptime_str()}", 2)
        self._row(f"Buf:{buffered}", 3)
        self._row(f"RAM: {used_pct:.1f}%", 4)

    def _render_relays(self) -> None:
        """The wired 230 V relay channels, then PWM outputs marked as such.

        Only entries in ``relays`` are mains channels on REL_CON1. The fans are
        PCA9685 PWM outputs and are labelled "PWM" so they can never be read as
        a mains socket — before the 3.5-D migration the case fan sat on a relay
        pin, and this page kept listing it next to the real relays afterwards.
        """
        self._header("RELAYS")
        row = 0
        for label, pin, switch in self._relays:
            if row > _MAX_ROW:
                return
            state = "--" if switch is None else ("ON" if switch.is_on() else "OFF")
            self._row(f"{label} GP{pin}: {state}", row)
            row += 1
        for fan in self._fans:
            if row > _MAX_ROW:
                return
            duty = getattr(fan, "duty_pct", None)
            if fan.is_on() and duty is not None:
                state = f"{duty:.0f}%"
            else:
                state = "ON" if fan.is_on() else "OFF"
            self._row(f"{fan.name[:4]} PWM: {state}", row)
            row += 1

    def _render_reg(self) -> None:
        """Regulation engine state: band + latch, deviations, commanded vector."""
        self._header("REGULATION")
        if self._regulation is None:
            self._row("Not active", 0)
            return
        try:
            s = self._regulation.get_state()
        except Exception:
            self._row("State error", 0)
            return
        if s["latched"]:
            mode = "LATCHED"
        elif s["emergency"]:
            mode = "EMERG"
        else:
            mode = "ok"
        self._row(f"Band {s['band']} {mode}", 0)
        d = s["deviations"]
        self._row(f"T{d[0]:.0f} H{d[1]:.0f} C{d[2]:.0f}", 1)
        c = s["commanded"]
        self._row(f"He{c['heater']:.0f} Fo{c['heater_follower']:.0f} Cl{c['cooler']:.0f}", 2)
        self._row(f"Hu{c['humidifier']:.0f} Ex{c['exhaust']:.0f} Ci{c['circulation']:.0f}", 3)
        self._row(f"Gl{c['growlight']:.0f} b{s['blend']:.2f}", 4)

    def _render_co2(self) -> None:
        self._header("CO2")
        if self._co2_logger is None:
            self._row("Not wired", 0)
            return
        ppm = getattr(self._co2_logger, "last_ppm", None)
        if ppm is None:
            self._row("Warming up...", 0)
        else:
            self._row(f"PPM: {ppm}", 0)
        if getattr(self._co2_logger, "is_override_active", lambda: False)():
            self._row("Vent: ON", 1)
        else:
            self._row("Vent: off", 1)

    def _render_debug(self) -> None:
        self._header("DEBUG")
        if not self._debug_mode:
            self._row("Hold to enter", 0)
            self._row("debug menu.", 1)
            if self._oled:
                self._oled.text("[HOLD]=open", 56, 56, 1)
            return

        if not self._debug_actions:
            self._row("No actions", 0)
            return

        action = self._debug_actions[self._debug_action_idx]
        self._row(f"> {action['label']}", 0)
        self._row(f"{self._debug_action_idx + 1}/{len(self._debug_actions)}", 1)

        if self._debug_running:
            self._row("RUNNING...", 2)
        elif self._debug_confirm_pending:
            self._row("CONFIRM?", 2)
            self._row("TAP=cancel", 3)
        elif self._debug_status and _ticks_ms() < self._debug_status_until_ms:
            self._row(self._debug_status[:16], 2)

        if self._oled and not self._debug_running:
            hint = "[HOLD]=run" if not self._debug_confirm_pending else "[HOLD]=YES"
            self._oled.text(hint, 56, 56, 1)

    def _render_soil(self) -> None:
        self._header("SOIL")
        if self._soil_logger is None:
            self._row("Not wired", 0)
            return
        pct = getattr(self._soil_logger, "last_percent", None)
        raw = getattr(self._soil_logger, "last_raw", None)
        warn_below = getattr(self._soil_logger, "warn_pct_below", None)
        if pct is None:
            self._row("Reading...", 0)
        else:
            self._row(f"Moist: {pct}%", 0)
            self._row(f"Raw:   {raw}", 1)
            if warn_below is not None:
                self._row(f"Warn<{warn_below}%", 2)
            if pct < (warn_below or 0):
                self._row("LOW!", 3)
