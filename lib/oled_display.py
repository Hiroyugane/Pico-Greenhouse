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
#   7: co2       – CO2 status placeholder

import time

import uasyncio as asyncio

try:
    _ticks_ms = time.ticks_ms  # MicroPython
except AttributeError:

    def _ticks_ms() -> int:  # CPython fallback
        return int(time.time() * 1000)


# ── Menu identifiers (ordered) ─────────────────────────────────────────────
MENUS = ("temp", "humidity", "service", "sd", "alerts", "system", "relays", "co2")


class OLEDDisplay:
    """
    Menu-driven OLED display controller for Pi Greenhouse.

    Renders system information on a 128×64 SSD1306 display.
    Menu cycling is driven by the short-press button callback registered
    in main.py. Long-press actions are context-sensitive per menu.

    Dependencies injected at construction:
    - i2c:              machine.I2C shared bus
    - time_provider:    RTCTimeProvider for current time
    - dht_logger:       DHTLogger for temperature/humidity stats
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

    Attributes:
        current_menu (int): index into MENUS tuple
        display_on (bool): whether the display is initialized and working
    """

    def __init__(
        self,
        i2c,
        time_provider,
        dht_logger,
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
    ):
        self._i2c = i2c
        self._time_provider = time_provider
        self._dht_logger = dht_logger
        self._buffer_manager = buffer_manager
        self._status_manager = status_manager
        self._reminder = reminder
        self._fans = fans or []
        self._growlight = growlight
        self._sd_remount_cb = sd_remount_cb
        self._start_time_ms = start_time_ms
        self._logger = logger
        self._width = width
        self._height = height
        self._i2c_address = i2c_address
        self._refresh_interval_s = refresh_interval_s
        self._stats_window_s = stats_window_s
        self._menu_timeout_s = menu_timeout_s

        self.current_menu: int = 0
        self.display_on: bool = False
        self._oled = None
        self._last_interaction_ms: int = _ticks_ms()

        self._init_display()

    # ── Initialization ────────────────────────────────────────────────────

    def _init_display(self) -> None:
        """Initialize SSD1306 driver. Non-fatal if display absent."""
        try:
            from lib.ssd1306 import SSD1306_I2C

            self._oled = SSD1306_I2C(
                self._width, self._height, self._i2c, addr=self._i2c_address
            )
            self.display_on = True
            if self._logger:
                self._logger.info(
                    "OLEDDisplay", f"SSD1306 initialized at 0x{self._i2c_address:02X}"
                )
            else:
                print(f"[OLEDDisplay] SSD1306 at 0x{self._i2c_address:02X}")
        except Exception as e:
            self.display_on = False
            if self._logger:
                self._logger.warning(
                    "OLEDDisplay", f"Display init failed (non-critical): {e}"
                )
            else:
                print(f"[OLEDDisplay] Init failed: {e}")

    # ── Public API ────────────────────────────────────────────────────────

    def next_menu(self) -> None:
        """Advance to next menu (wraps around). Called on short button press."""
        self.current_menu = (self.current_menu + 1) % len(MENUS)
        self._last_interaction_ms = _ticks_ms()
        if self._logger:
            self._logger.debug(
                "OLEDDisplay", "menu changed", menu=MENUS[self.current_menu]
            )

    def long_press_action(self) -> None:
        """
        Execute context-sensitive action for the current menu.

        Menu → action:
        - temp / humidity: clear reading history
        - service:         reset service reminder
        - sd:              trigger SD remount
        - others:          no-op
        """
        menu = MENUS[self.current_menu]
        self._last_interaction_ms = _ticks_ms()
        if menu in ("temp", "humidity"):
            if self._dht_logger:
                self._dht_logger.clear_history()
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
                self._logger.debug(
                    "OLEDDisplay", "Long press: no action for menu", menu=menu
                )

    def render(self) -> None:
        """Render the current menu to the display. No-op if display is off."""
        if not self.display_on or self._oled is None:
            return
        try:
            self._oled.fill(0)
            menu = MENUS[self.current_menu]
            getattr(self, f"_render_{menu}")()
            self._oled.show()
        except Exception as e:
            if self._logger:
                self._logger.warning("OLEDDisplay", f"Render error: {e}")

    async def refresh_loop(self) -> None:
        """
        Async task: periodically re-render the current menu.

        Also handles menu timeout: returns to menu 0 after
        menu_timeout_s seconds of no button presses.
        """
        while True:
            try:
                # Timeout: return to default menu after inactivity
                if self._menu_timeout_s > 0:
                    idle_ms = _ticks_ms() - self._last_interaction_ms
                    if (
                        idle_ms >= self._menu_timeout_s * 1000
                        and self.current_menu != 0
                    ):
                        self.current_menu = 0
                        if self._logger:
                            self._logger.debug(
                                "OLEDDisplay", "menu timeout → returned to temp"
                            )

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
        o = self._oled
        o.text(title, 0, 0, 1)
        o.hline(0, 9, self._width, 1)

    def _row(self, text: str, row: int) -> None:
        """Draw text on display row (0-based, each row = 10 px after header)."""
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
        stats = (
            self._dht_logger.get_stats(self._stats_window_s) if self._dht_logger else {}
        )
        self._header("TEMPERATURE")
        self._row(f"Now: {self._fmt_f(stats.get('temp_now'))}C", 0)
        self._row(f"Hi:  {self._fmt_f(stats.get('temp_hi'))}C", 1)
        self._row(f"Lo:  {self._fmt_f(stats.get('temp_lo'))}C", 2)
        self._row(f"Avg: {self._fmt_f(stats.get('temp_avg'))}C", 3)
        # Long-press hint at bottom
        self._oled.text("[HOLD]=clr", 68, 56, 1)

    def _render_humidity(self) -> None:
        stats = (
            self._dht_logger.get_stats(self._stats_window_s) if self._dht_logger else {}
        )
        self._header("HUMIDITY")
        self._row(f"Now: {self._fmt_f(stats.get('hum_now'))}%", 0)
        self._row(f"Hi:  {self._fmt_f(stats.get('hum_hi'))}%", 1)
        self._row(f"Lo:  {self._fmt_f(stats.get('hum_lo'))}%", 2)
        self._row(f"Avg: {self._fmt_f(stats.get('hum_avg'))}%", 3)
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
        time_str = now[11:16] if len(now) >= 16 else now  # HH:MM
        date_str = now[:10] if len(now) >= 10 else now  # YYYY-MM-DD
        metrics = self._buffer_manager.get_metrics() if self._buffer_manager else {}
        buffered = metrics.get("buffer_entries", 0)
        self._row(date_str, 0)
        self._row(time_str, 1)
        self._row(f"Up: {self._uptime_str()}", 2)
        self._row(f"Buf:{buffered}", 3)

    def _render_relays(self) -> None:
        self._header("RELAYS")
        row = 0
        for fan in self._fans:
            state = "ON " if fan.is_on() else "OFF"
            self._row(f"{fan.name[:7]}: {state}", row)
            row += 1
        if self._growlight:
            state = "ON " if self._growlight.is_on() else "OFF"
            self._row(f"Light: {state}", row)

    def _render_co2(self) -> None:
        self._header("CO2")
        self._row("Not active", 0)
        self._row("(future)", 1)
