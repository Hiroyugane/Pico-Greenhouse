# Pi Greenhouse - Main Orchestrator (Refactored)
# Dennis Hiro, 2024-06-08 - 2026-01-29
# Ver: InDev2.0 (Modular Architecture with Dependency Injection)
#
# Clean entry point for Pi Greenhouse automation system.
#
# Initialization sequence:
# 1. Validate configuration (config.py)
# 2. Initialize hardware via factory pattern (RTC, SPI, SD, GPIO)
# 3. Create providers: TimeProvider (wraps RTC)
# 4. Create centralized BufferManager (SD + fallback)
# 5. Create EventLogger (system event tracking)
# 6. Create TempHumidityLogger (SHT31 on shared I2C0)
# 7. Create relay controllers: FanController × 2, GrowlightController
# 8. Create LED/button handler and ServiceReminder task
# 9. Spawn all async tasks and run event loop
#
# All components use dependency injection; no global state after init.
#
# HOW TO RUN:
# 1. First time only: run rtc_set_time.py to sync RTC
# 2. Run this main.py via Thonny
# 3. Check /sd/sensors/th/YYYY/th_YYYY-MM-DD.csv for data

import gc
import os
import sys
import time

if sys.implementation.name != "micropython":  # type: ignore[union-attr]
    host_shims_path = os.path.join(  # type: ignore
        os.path.dirname(os.path.abspath(__file__)),  # type: ignore
        "host_shims",  # type: ignore
    )  # type: ignore[attr-defined]
    sys.path.insert(0, host_shims_path)

import machine
import uasyncio as asyncio
from machine import ADC, UART, WDT, Pin


def _describe_reset_cause() -> str:
    """Return a human-readable label for ``machine.reset_cause()``.

    Mapping is best-effort: MicroPython's rp2 port exposes named constants
    (PWRON_RESET, WDT_RESET, BROWNOUT_RESET, …) but other ports may add
    extras. Unknown codes fall through to the raw integer. Errors here
    never block boot — the caller treats this as best-effort diagnostics.
    """
    try:
        code = machine.reset_cause()
    except Exception:
        return "unknown"

    name_map = {}
    for name in (
        "PWRON_RESET",
        "HARD_RESET",
        "WDT_RESET",
        "DEEPSLEEP_RESET",
        "SOFT_RESET",
        "BROWNOUT_RESET",
    ):
        value = getattr(machine, name, None)
        if isinstance(value, int):
            name_map[value] = name
    label = name_map.get(code, f"code={code}")
    return label

from config import DEVICE_CONFIG, validate_config
from lib import boot_log
from lib.buffer_manager import BufferManager
from lib.buzzer import BuzzerController
from lib.co2_logger import CO2Logger
from lib.event_logger import EventLogger
from lib.fan_controllers import AlwaysOnFanController, HeaterFollowerFanController
from lib.fan_output import Pca9685FanOutput, RelayFanOutput
from lib.hardware_factory import HardwareFactory
from lib.heater import HeaterController
from lib.led_button import LEDButtonHandler, ServiceReminder
from lib.mcp4725 import MCP4725
from lib.oled_display import OLEDDisplay
from lib.relay import FanController, GrowlightController, RelayController
from lib.sht31 import SHT31
from lib.soil_logger import SoilLogger
from lib.status_manager import StatusManager
from lib.temp_humidity_logger import TempHumidityLogger
from lib.time_provider import RTCTimeProvider
from lib.updater import run_pending_update
from lib.write_queue_manager import WriteQueueManager


async def feed_watchdog(wdt, interval_ms, logger=None):
    """
    Async task that periodically feeds the watchdog timer.

    If the uasyncio scheduler freezes, this task stops running and the
    watchdog will reset the Pico after the configured timeout.

    Args:
        wdt: WDT instance to feed
        interval_ms: Feed interval in milliseconds (must be < watchdog timeout)
        logger: Optional EventLogger for debug output
    """
    while True:
        try:
            wdt.feed()
            await asyncio.sleep_ms(interval_ms)
        except asyncio.CancelledError:
            if logger:
                logger.warning("Watchdog", "Feed task cancelled")
            raise
        except Exception:
            # Don't log here - logging can block and cause watchdog timeout
            await asyncio.sleep_ms(1000)


# Module-level WDT reference for feeding during long operations
_wdt = None


def feed_wdt():
    """Feed the watchdog timer during long synchronous operations."""
    global _wdt
    if _wdt is not None:
        _wdt.feed()


def _enter_sd_failure_state(status_manager, wdt, countdown_s):
    """Hold sd_led + error_led ON for countdown_s, feeding WDT, then reset.

    Invoked when ``system.require_sd_startup`` is True and the cold-boot
    mount path could not bring the card up. The countdown is visible to
    the operator (LEDs lit + console line) so the failure cause is
    obvious before the Pico cycles. Cold-boot SD failures are often
    transient — bad connector seating, brown-out, slow card — so a
    bounded reset loop tends to recover without intervention.

    On MicroPython this never returns (calls ``machine.reset()``). On
    host/CPython it returns after the wait so tests can assert state.
    """
    status_manager.set_sd_status(False)
    status_manager.set_error("sd_required", True)
    print(f"[STARTUP ERROR] SD card required but not mounted. Resetting in {countdown_s}s...")

    step_s = 0.5
    elapsed = 0.0
    while elapsed < countdown_s:
        if wdt is not None:
            try:
                wdt.feed()
            except Exception:
                pass
        time.sleep(step_s)
        elapsed += step_s

    if sys.implementation.name == "micropython":  # type: ignore[union-attr]
        import machine

        machine.reset()


def _get_runtime_load_snapshot() -> dict:
    """Collect lightweight runtime load indicators for diagnostics."""
    snapshot = {}

    # MicroPython memory telemetry (primary signal for resource pressure).
    if hasattr(gc, "mem_free") and hasattr(gc, "mem_alloc"):
        try:
            mem_free = int(gc.mem_free())
            mem_alloc = int(gc.mem_alloc())
            mem_total = mem_free + mem_alloc
            snapshot["mem_free_b"] = mem_free
            snapshot["mem_alloc_b"] = mem_alloc
            snapshot["mem_total_b"] = mem_total
            if mem_total > 0:
                snapshot["mem_used_pct"] = round((mem_alloc * 100.0) / mem_total, 1)
        except Exception:
            # Telemetry is best-effort; never fail the control loop.
            pass

    # Useful in host simulation to correlate with accidental task fan-out.
    try:
        if hasattr(asyncio, "all_tasks"):
            snapshot["task_count"] = len(asyncio.all_tasks())
    except Exception:
        pass

    return snapshot


async def main():
    """
    Main async entry point for Pi Greenhouse system.

    Orchestrates initialization and spawns all concurrent tasks.
    All long-running operations (logging, relay cycling, scheduling) run as async tasks.
    """
    print("[STARTUP] Initializing Pi Greenhouse system...")

    # Step 1: Validate configuration
    try:
        validate_config()
        print("[STARTUP] Configuration validated")
    except ValueError as e:
        print(f"[STARTUP ERROR] Config validation failed: {e}")
        return

    device_mode = DEVICE_CONFIG["mode"]
    is_plant_mode = device_mode == "plant"
    print(f"[STARTUP] Operating mode: {device_mode}")

    # Configure boot_log so HardwareFactory tees its SD diagnostics into
    # /boot.log (or the configured path). Each boot truncates this file
    # on first write, so reading it after a reset shows the most recent
    # boot's diagnostics only — perfect for the require_sd_startup
    # reset-loop case where the operator never sees USB serial.
    _sys_cfg = DEVICE_CONFIG.get("system", {})
    boot_log.configure(
        path=_sys_cfg.get("boot_log_path", "/boot.log"),
        max_bytes=int(_sys_cfg.get("boot_log_max_kb", 10)) * 1024,
    )

    # Step 1b: Initialize watchdog timer (early, before any other hardware)
    # If the system freezes during init or runtime, the watchdog will reset it.
    global _wdt
    system_config = DEVICE_CONFIG.get("system", {})
    wdt_timeout_ms = system_config.get("watchdog_timeout_ms", 8000)
    wdt_feed_interval_ms = system_config.get("watchdog_feed_interval_ms", 2000)
    wdt = WDT(timeout=wdt_timeout_ms)
    _wdt = wdt  # Store for feed_wdt() helper
    print(f"[STARTUP] Watchdog enabled: timeout={wdt_timeout_ms}ms, feed_interval={wdt_feed_interval_ms}ms")

    # Step 2: Initialize hardware
    # Create debug callback for pre-logger modules (only active when DEBUG)
    logger_config = DEVICE_CONFIG.get("event_logger", {})
    _dbg_cb = None
    if logger_config.get("log_level", "INFO") == "DEBUG":
        _dbg_cb = lambda msg: print(f"[DEBUG] {msg}")  # noqa: E731

    wdt.feed()  # Feed before hardware init
    hardware = HardwareFactory(DEVICE_CONFIG, debug_callback=_dbg_cb, wdt=wdt)
    if not hardware.setup():
        print("[STARTUP ERROR] Critical hardware initialization failed (RTC)")
        hardware.print_status()
        return

    wdt.feed()  # Feed after hardware init
    hardware.print_status()

    # Step 2b: SD-payload software update (see lib/updater.py).
    # Runs BEFORE EventLogger so logging code can be safely replaced
    # along with the rest. If a pending update is applied, this call
    # ends in machine.reset() and does not return; the new code boots
    # from a clean import state.
    wdt.feed()
    try:
        run_pending_update(DEVICE_CONFIG, hardware, wdt)
    except Exception as e:
        # Updater failures must never block normal boot. The updater
        # logs its own diagnostics to /sd/logs/updates.log; live code is
        # left in whatever state the apply loop reached.
        print(f"[STARTUP] Updater raised (non-fatal): {e}")
    wdt.feed()

    # Step 3: Create TimeProvider (wraps RTC)
    rtc = hardware.get_rtc()
    time_provider = RTCTimeProvider(
        rtc,
        sync_interval_s=system_config.get("rtc_sync_interval_s", 3600),
        rtc_min_year=system_config.get("rtc_min_year", 2025),
        rtc_max_year=system_config.get("rtc_max_year", 2035),
        debug_callback=_dbg_cb,
    )
    print(f"[STARTUP] TimeProvider created (valid={time_provider.time_valid})")

    # Step 3b: Create StatusManager (owns activity/SD/warning/error/heartbeat LEDs)
    status_led_config = DEVICE_CONFIG.get("status_leds", {})
    status_manager = StatusManager(
        activity_pin=DEVICE_CONFIG["pins"]["activity_led"],
        sd_pin=DEVICE_CONFIG["pins"]["sd_led"],
        warning_pin=DEVICE_CONFIG["pins"]["warning_led"],
        error_pin=DEVICE_CONFIG["pins"]["error_led"],
        heartbeat_pin=DEVICE_CONFIG["pins"]["onboard_led"],
        activity_blink_ms=status_led_config.get("activity_blink_ms", 50),
    )

    # Check RTC validity (year out of range → warning)
    if not time_provider.time_valid:
        status_manager.set_warning("rtc_invalid", True)
        print("[STARTUP] WARNING: RTC time appears invalid (battery loss?)")

    # Reflect initial SD state
    status_manager.set_sd_status(hardware.is_sd_mounted())

    # Fail hard if SD is required and the boot mount path could not bring
    # it up. Light sd_led + error_led, hold for the configured countdown
    # (visible to the operator), then machine.reset(). The next boot will
    # try again — cold-boot SD failures are often transient. Skipped when
    # require_sd_startup=False so headless/test runs can proceed on
    # fallback storage.
    if not hardware.is_sd_mounted() and system_config.get("require_sd_startup", True):
        _enter_sd_failure_state(
            status_manager,
            wdt,
            countdown_s=system_config.get("sd_fail_reset_s", 10),
        )
        return  # host path: end main() after countdown

    wdt.feed()  # Feed before buffer/logger init

    # Step 4: Create BufferManager
    buffer_config = DEVICE_CONFIG.get("buffer_manager", {})
    buffer_manager = BufferManager(
        sd_mount_point=buffer_config.get("sd_mount_point", "/sd"),
        fallback_path=buffer_config.get("fallback_path", "/local/fallback.csv"),
        max_buffer_entries=buffer_config.get("max_buffer_entries", 200),
        max_fallback_size_kb=buffer_config.get("max_fallback_size_kb", 50),
        debug_callback=_dbg_cb,
        migrate_batch_max=system_config.get("fallback_migrate_batch_max", 20),
        wdt_feed=feed_wdt,
    )
    # Drain any fallback rows that accumulated during the previous boot's
    # SD outage instead of wiping them. Migration is bounded by
    # fallback_migrate_batch_max, so a backlog drains across the first few
    # health-check cycles even when the queue is large. SD must be mounted
    # for migration to succeed; on a degraded boot the rows stay parked.
    # Bounded loop: at most two batches at boot so init time stays
    # predictable. The health loop picks up any leftovers.
    if hardware.is_sd_mounted():
        for _ in range(2):
            try:
                migrated = int(buffer_manager.migrate_fallback() or 0)
            except Exception:
                break
            if migrated <= 0:
                break
            print(f"[STARTUP] Drained {migrated} fallback row(s) from previous boot")
    # Step 4b: Create WriteQueueManager (async SD write batching)
    system_config = DEVICE_CONFIG.get("system", {})
    write_queue = WriteQueueManager(
        buffer_manager=buffer_manager,
        logger=None,  # Inject logger later after EventLogger created
        max_queue_size=system_config.get("write_queue_max_size", 500),
        drain_interval_ms=system_config.get("queue_drain_interval_ms", 100),
        batch_size=system_config.get("queue_batch_size", 5),
        wdt_feed=feed_wdt,
    )
    # Step 5: Create EventLogger
    logger = EventLogger(
        time_provider,
        buffer_manager,
        logfile=logger_config.get("logfile", "/sd/logs/system.log"),
        max_size=logger_config.get("max_size", 50000),
        debug_max_size=logger_config.get("debug_max_size", 25000),
        status_manager=status_manager,
        info_flush_threshold=logger_config.get("info_flush_threshold", 5),
        warn_flush_threshold=logger_config.get("warn_flush_threshold", 3),
        debug_flush_threshold=logger_config.get("debug_flush_threshold", 10),
        log_level=logger_config.get("log_level", "INFO"),
        debug_enabled=logger_config.get("debug_enabled", False),
        debug_to_file=logger_config.get("debug_to_file", False),
        write_queue=write_queue,
    )

    # Update write_queue with logger reference (now available)
    write_queue.set_logger(logger)

    wdt.feed()  # Feed after logger init

    reset_label = _describe_reset_cause()
    logger.info("MAIN", f"System startup (reset_cause={reset_label})")
    log_lvl = logger_config.get("log_level", "INFO")
    dbg_on = logger_config.get("debug_enabled", False)
    logger.debug("MAIN", f"log_level={log_lvl}, debug_enabled={dbg_on}")

    # Wire logger into StatusManager, BufferManager, TimeProvider, and HardwareFactory
    status_manager.set_logger(logger)
    buffer_manager.set_logger(logger)
    time_provider.set_logger(logger)
    hardware.set_logger(logger)

    logger.debug(
        "MAIN",
        "Step 3-5 complete",
        rtc_valid=time_provider.time_valid,
        sd_mounted=hardware.is_sd_mounted(),
        debug_enabled=logger_config.get("debug_enabled", False),
        debug_to_file=logger_config.get("debug_to_file", False),
    )

    # Step 6: Create SHT31 sensor and TempHumidityLogger
    th_config = DEVICE_CONFIG.get("temp_humidity_logger", {})
    sht31_config = DEVICE_CONFIG.get("sht31", {})
    sht31 = SHT31(
        i2c=hardware.get_i2c(),
        address=sht31_config.get("i2c_address", 0x44),
    )
    try:
        th_logger = TempHumidityLogger(
            sensor=sht31,
            time_provider=time_provider,
            buffer_manager=buffer_manager,
            logger=logger,
            interval=th_config.get("interval_s", 30),
            sensor_root=DEVICE_CONFIG["paths"]["sensor_root"],
            sensor_type=th_config.get("sensor_type", "th"),
            max_retries=th_config.get("max_retries", 3),
            status_manager=status_manager,
            th_warn_threshold=status_led_config.get("th_warn_threshold", 3),
            th_error_threshold=status_led_config.get("th_error_threshold", 10),
            retry_delay_s=th_config.get("retry_delay_s", 0.5),
            write_queue=write_queue,
        )
    except Exception as e:
        logger.error("MAIN", f"TempHumidityLogger init failed: {e}")
        # Create a minimal logger without status manager to keep system running
        th_logger = TempHumidityLogger(
            sensor=sht31,
            time_provider=time_provider,
            buffer_manager=buffer_manager,
            logger=logger,
            interval=th_config.get("interval_s", 30),
            sensor_root=DEVICE_CONFIG["paths"]["sensor_root"],
            sensor_type=th_config.get("sensor_type", "th"),
            max_retries=th_config.get("max_retries", 3),
            retry_delay_s=th_config.get("retry_delay_s", 0.5),
            write_queue=write_queue,
        )

    wdt.feed()  # Feed after TempHumidityLogger init

    # Step 6b: Create heater controller (active-HIGH MOSFET, day/night
    # thermostat). Constructed before the fan loop so heater_follower
    # fans can take a reference to it.
    light_config = DEVICE_CONFIG.get("growlight", {})
    heater_config = DEVICE_CONFIG.get("heater", {})
    dawn_h = light_config.get("dawn_hour", 7)
    dawn_m = light_config.get("dawn_minute", 0)
    sunset_h = light_config.get("sunset_hour", 19)
    sunset_m = light_config.get("sunset_minute", 0)
    day_offset_min = heater_config.get("day_offset_min", 0)
    night_offset_min = heater_config.get("night_offset_min", 0)
    day_total_min = dawn_h * 60 + dawn_m + day_offset_min
    night_total_min = sunset_h * 60 + sunset_m + night_offset_min
    heater = HeaterController(
        pin=DEVICE_CONFIG["pins"]["heater_mosfet"],
        time_provider=time_provider,
        th_logger=th_logger,
        logger=logger,
        day_min_temp=heater_config.get("day_min_temp", 22.0),
        night_min_temp=heater_config.get("night_min_temp", 16.0),
        temp_hysteresis=heater_config.get("temp_hysteresis", 0.5),
        day_start_hour=(day_total_min // 60) % 24,
        day_start_minute=day_total_min % 60,
        night_start_hour=(night_total_min // 60) % 24,
        night_start_minute=night_total_min % 60,
        max_stale_reads=heater_config.get("max_stale_reads", 3),
        poll_interval_s=heater_config.get("poll_interval_s", 30),
        name="Heater",
    )
    logger.info("MAIN", "Heater controller initialized")

    # Step 7: Create fan controllers from the role-keyed fans dict.
    # Iterates DEVICE_CONFIG["fans"], skips entries with enabled=False,
    # and dispatches output (relay vs pca9685) and policy (mode) per
    # entry. pca9685 entries are skipped with a warning when the chip
    # is not present (current PCB until next-rev hardware lands).
    fans = []
    pca9685 = hardware.get_pca9685()
    for role, fan_cfg in DEVICE_CONFIG.get("fans", {}).items():
        if not fan_cfg.get("enabled", False):
            logger.debug("MAIN", "fan disabled in config; skipping", role=role)
            continue

        output_type = fan_cfg["output"]
        fan_output = None
        if output_type == "relay":
            pin = DEVICE_CONFIG["pins"][fan_cfg["relay_pin_key"]]
            relay = RelayController(pin=pin, invert=True, name=role, logger=logger)
            fan_output = RelayFanOutput(relay)
        elif output_type == "pca9685":
            if pca9685 is None:
                logger.warning(
                    "MAIN",
                    f"Fan {role!r} uses pca9685 but driver unavailable; skipping",
                )
                continue
            fan_output = Pca9685FanOutput(
                pca9685,
                channel=fan_cfg["pca9685_ch"],
                name=role,
                default_duty_pct=fan_cfg.get("default_duty_pct", 100),
            )

        mode = fan_cfg["mode"]
        if mode == "thermostat_schedule":
            fan = FanController(
                output=fan_output,
                time_provider=time_provider,
                th_logger=th_logger,
                logger=logger,
                interval_s=fan_cfg["interval_s"],
                on_time_s=fan_cfg["on_time_s"],
                max_temp=fan_cfg["max_temp"],
                temp_hysteresis=fan_cfg["temp_hysteresis"],
                poll_interval_s=fan_cfg["poll_interval_s"],
                name=role,
            )
            fans.append(fan)
        elif mode == "always_on":
            fan = AlwaysOnFanController(
                output=fan_output,
                logger=logger,
                duty_pct=fan_cfg["duty_pct"],
                refresh_interval_s=fan_cfg["refresh_interval_s"],
                name=role,
            )
            fans.append(fan)
        elif mode == "heater_follower":
            fan = HeaterFollowerFanController(
                output=fan_output,
                heater=heater,
                logger=logger,
                duty_pct=fan_cfg["duty_pct"],
                post_run_s=fan_cfg["post_run_s"],
                poll_interval_s=fan_cfg["poll_interval_s"],
                name=role,
            )
            fans.append(fan)
        else:
            logger.warning(
                "MAIN",
                f"Fan {role!r} mode={mode!r} has no policy class; skipping",
            )

    logger.info("MAIN", "Fan controllers initialized")
    wdt.feed()  # Feed after fan controllers
    logger.debug(
        "MAIN",
        "Step 7a fans",
        fan_count=len(fans),
        fan_names=str([f.name for f in fans]),
    )

    # Step 7b: Create grow light controller (relay master + MCP4725 dimming).
    # Plant mode runs the MCP4725 dimming path; mushroom mode runs the basic
    # relay-only path. growlight.mode in DEVICE_CONFIG is no longer consulted.
    grow_dac = None
    if is_plant_mode:
        try:
            grow_dac = MCP4725(
                i2c=hardware.get_i2c(),
                address=light_config.get("dac_i2c_address", 0x60),
            )
            logger.info("MAIN", f"MCP4725 grow-light DAC at 0x{light_config.get('dac_i2c_address', 0x60):02X}")
        except Exception as e:
            logger.warning("MAIN", f"MCP4725 init failed (falling back to relay-only growlight): {e}")
    else:
        logger.info("MAIN", "mushroom mode — growlight runs relay-only, MCP4725 init skipped")
    growlight = GrowlightController(
        pin=DEVICE_CONFIG["pins"]["relay_growlight"],
        time_provider=time_provider,
        logger=logger,
        dawn_hour=light_config.get("dawn_hour", 7),
        dawn_minute=light_config.get("dawn_minute", 0),
        sunset_hour=light_config.get("sunset_hour", 19),
        sunset_minute=light_config.get("sunset_minute", 0),
        poll_interval_s=light_config.get("poll_interval_s", 60),
        dac=grow_dac,
        default_level_pct=light_config.get("default_level_pct", 80),
        max_level_pct=light_config.get("max_level_pct", 91),
        min_level_pct=light_config.get("min_level_pct", 0),
        name="Growlight",
    )
    logger.debug(
        "MAIN",
        "Step 7b growlight",
        dawn=f"{light_config.get('dawn_hour', 7):02d}:{light_config.get('dawn_minute', 0):02d}",
        sunset=f"{light_config.get('sunset_hour', 19):02d}:{light_config.get('sunset_minute', 0):02d}",
        poll_s=light_config.get("poll_interval_s", 60),
    )

    # Step 7b3: Create CO2 logger (UART0 SenseAir-style sensor) and wire its
    # override flag into the configured fan so high-ppm triggers ventilation.
    co2_config = DEVICE_CONFIG.get("co2_logger", {})
    co2_logger_obj = None
    try:
        co2_uart = UART(
            DEVICE_CONFIG["pins"]["co2_uart_id"],
            baudrate=DEVICE_CONFIG["pins"]["co2_baudrate"],
            tx=Pin(DEVICE_CONFIG["pins"]["co2_uart_tx"]),
            rx=Pin(DEVICE_CONFIG["pins"]["co2_uart_rx"]),
        )
        co2_logger_obj = CO2Logger(
            uart=co2_uart,
            time_provider=time_provider,
            buffer_manager=buffer_manager,
            logger=logger,
            interval_s=co2_config.get("interval_s", 30),
            warmup_s=co2_config.get("warmup_s", 30),
            max_retries=co2_config.get("max_retries", 3),
            override_ppm_on=co2_config.get("override_ppm_on", 1000),
            override_ppm_off=co2_config.get("override_ppm_off", 800),
            sensor_root=DEVICE_CONFIG["paths"]["sensor_root"],
            sensor_type=co2_config.get("sensor_type", "co2"),
            write_queue=write_queue,
            status_manager=status_manager,
        )
        # Attach the override hook to the fan whose role matches override_fan.
        override_role = co2_config.get("override_fan", "exhaust")
        target_fan = next((f for f in fans if f.name == override_role), None)
        if target_fan is not None:
            target_fan.external_override = co2_logger_obj.is_override_active
            logger.info(
                "MAIN",
                f"CO2 override wired to {target_fan.name} (>{co2_config.get('override_ppm_on', 1000)} ppm)",
            )
        else:
            logger.warning(
                "MAIN",
                f"CO2 override_fan {override_role!r} not found in enabled fans",
            )
    except Exception as e:
        logger.warning("MAIN", f"CO2Logger init failed (non-critical): {e}")
        co2_logger_obj = None

    # Step 7b4: Create SoilLogger (GP28 ADC2 single-probe).
    # Plant mode only — mushroom mode skips construction entirely.
    # Calibration constants live in config; use prototypes via the
    # `print_raw()` REPL helper in lib/soil_logger.py to retune them
    # per sensor + soil pot. Warning LED flips when % < warn_pct_below.
    soil_config = DEVICE_CONFIG.get("soil_logger", {})
    soil_logger_obj = None
    if is_plant_mode:
        try:
            soil_adc = ADC(Pin(DEVICE_CONFIG["pins"]["adc_input"]))
            soil_logger_obj = SoilLogger(
                adc=soil_adc,
                time_provider=time_provider,
                buffer_manager=buffer_manager,
                logger=logger,
                interval_s=soil_config.get("interval_s", 60),
                adc_dry_raw=soil_config.get("adc_dry_raw", 850),
                adc_wet_raw=soil_config.get("adc_wet_raw", 350),
                warn_pct_below=soil_config.get("warn_pct_below", 20),
                sensor_root=DEVICE_CONFIG["paths"]["sensor_root"],
                sensor_type=soil_config.get("sensor_type", "soil"),
                write_queue=write_queue,
                status_manager=status_manager,
            )
            logger.info(
                "MAIN",
                f"SoilLogger on GP{DEVICE_CONFIG['pins']['adc_input']} "
                f"(dry={soil_config.get('adc_dry_raw', 850)}, "
                f"wet={soil_config.get('adc_wet_raw', 350)}, "
                f"warn<{soil_config.get('warn_pct_below', 20)}%)",
            )
        except Exception as e:
            logger.warning("MAIN", f"SoilLogger init failed (non-critical): {e}")
            soil_logger_obj = None
    else:
        logger.info("MAIN", "mushroom mode — SoilLogger not constructed")

    wdt.feed()  # Feed before buzzer (startup melody takes time)

    # Step 7c: Create buzzer controller
    buzzer_config = DEVICE_CONFIG.get("buzzer", {})
    buzzer = None
    if buzzer_config.get("enabled", True):
        try:
            buzzer = BuzzerController(
                pin=DEVICE_CONFIG["pins"]["buzzer"],
                logger=logger,
                enabled=True,
                default_freq=buzzer_config.get("default_freq", 1000),
                default_duty_pct=buzzer_config.get("default_duty_pct", 50),
                patterns={
                    k: v
                    for k, v in buzzer_config.items()
                    if isinstance(v, list) and k.endswith(("_melody", "_pattern"))
                },
            )
            await buzzer.startup()
            wdt.feed()  # Feed after buzzer startup melody
            logger.debug(
                "MAIN",
                f"Buzzer GP{DEVICE_CONFIG['pins']['buzzer']}: patterns={list(buzzer.patterns.keys())}",
            )
            logger.info("MAIN", "Buzzer initialized")
            status_manager.set_buzzer(buzzer)
        except Exception as e:
            logger.warning("MAIN", f"Buzzer init failed (non-critical): {e}")
            buzzer = None

    # Step 8: Create LED/button handler and Service reminder
    #
    # Single menu button (GP9): short press = cycle display menu,
    # long press (>=3s) = context action (e.g. reset service reminder).
    led_handler = LEDButtonHandler(
        led_pin=DEVICE_CONFIG["pins"]["reminder_led"],
        button_pin=DEVICE_CONFIG["pins"]["button_menu"],
        debounce_ms=DEVICE_CONFIG.get("system", {}).get("button_debounce_ms", 200),
        long_press_ms=DEVICE_CONFIG.get("system", {}).get("long_press_ms", 3000),
        logger=logger,
    )

    # Run POST (visual LED walk) if enabled
    if status_led_config.get("post_enabled", True):
        post_step = status_led_config.get("post_step_ms", 150)
        walk_order = status_led_config.get("walk_order")
        await status_manager.run_post(
            step_ms=post_step,
            reminder_led=led_handler.led,
            walk_order=walk_order,
        )
        wdt.feed()  # Feed after POST
        # POST drives every owned LED OFF at the end. Re-assert real state
        # so a degraded condition raised earlier (currently only SD) isn't
        # silently masked by the visual walk.
        status_manager.set_sd_status(hardware.is_sd_mounted())
        print("[STARTUP] POST complete — all status LEDs verified")

    Service_config = DEVICE_CONFIG.get("Service_reminder", {})
    reminder = ServiceReminder(
        time_provider=time_provider,
        led_handler=led_handler,
        days_interval=Service_config.get("days_interval", 7),
        blink_pattern_ms=Service_config.get("blink_pattern_ms", [200, 200, 200, 800]),
        blink_after_days=Service_config.get("blink_after_days", 3),
        storage_path=Service_config.get("storage_path", "/service_reminder.txt"),
        monitor_interval_s=Service_config.get("monitor_interval_s", 3600),
        auto_register_button=False,
        logger=logger,
    )

    wdt.feed()  # Feed before OLED init (I2C scan + initial render can be slow)

    # Step 8b: Create OLED display controller
    display_config = DEVICE_CONFIG.get("display", {})
    oled = None
    if display_config.get("enabled", True):

        def _sd_remount_cb():
            """Callback for OLED long-press SD remount action."""
            if hardware.refresh_sd():
                logger.info("MAIN", "SD remounted via OLED long-press")
                status_manager.set_sd_status(True)
            else:
                logger.warning("MAIN", "SD remount failed via OLED long-press")

        debug_cfg = display_config.get("debug", {})

        def _debug_blink_cb():
            """Schedule a brief reminder-LED pattern after a debug action completes."""
            try:
                asyncio.create_task(
                    led_handler.blink_pattern_async(debug_cfg.get("feedback_blink_ms", [80, 80, 80, 80]))
                )
            except Exception as exc:
                logger.warning("MAIN", f"Debug feedback blink scheduling failed: {exc}")

        try:
            oled = OLEDDisplay(
                i2c=hardware.get_i2c(),
                time_provider=time_provider,
                th_logger=th_logger,
                buffer_manager=buffer_manager,
                status_manager=status_manager,
                reminder=reminder,
                fans=fans,
                growlight=growlight,
                sd_remount_cb=_sd_remount_cb,
                start_time_ms=0,
                logger=logger,
                co2_logger=co2_logger_obj,
                soil_logger=soil_logger_obj,
                heater=heater,
                feedback_blink_cb=_debug_blink_cb if debug_cfg.get("enabled", True) else None,
                event_log_path=logger_config.get("logfile", "/sd/logs/system.log"),
                width=display_config.get("width", 128),
                height=display_config.get("height", 64),
                i2c_address=display_config.get("i2c_address", 0x3C),
                refresh_interval_s=display_config.get("refresh_interval_s", 5),
                stats_window_s=display_config.get("stats_window_s", 3600),
                menu_timeout_s=display_config.get("menu_timeout_s", 30),
                display_timeout_s=display_config.get("display_timeout_s", 120),
                startup_banner_s=display_config.get("startup_banner_s", 2.0),
                vram_clear_delay_s=display_config.get("vram_clear_delay_s", 0.05),
                invert_delay_s=display_config.get("invert_delay_s", 0.1),
                debug_confirm_timeout_s=debug_cfg.get("confirm_timeout_s", 8),
                debug_status_show_ms=debug_cfg.get("status_show_ms", 3000),
                debug_test_heater_s=debug_cfg.get("test_heater_s", 5),
                debug_test_growlight_pulse_s=debug_cfg.get("test_growlight_pulse_s", 2),
                debug_test_growlight_dim_levels_pct=debug_cfg.get(
                    "test_growlight_dim_levels_pct", [0, 25, 50, 75, 100, 0]
                ),
                debug_test_growlight_dim_step_s=debug_cfg.get("test_growlight_dim_step_s", 1),
                debug_test_relay_pulse_s=debug_cfg.get("test_relay_pulse_s", 1),
            )
            wdt.feed()  # Feed after OLED init
            logger.info("MAIN", f"OLED display initialized (on={oled.display_on})")
        except Exception as e:
            logger.warning("MAIN", f"OLED display init failed (non-critical): {e}")
            oled = None

    # Register button callbacks:
    # - Short press: cycle OLED display menu
    # - Long press: context action delegated to OLEDDisplay (or fallback: reset service reminder)
    def _on_short_press():
        if oled is not None:
            oled.next_menu()

    def _on_long_press():
        if oled is not None:
            oled.long_press_action()
        else:
            reminder.reset()

    led_handler.register_callbacks(
        short_press=_on_short_press,
        long_press=_on_long_press,
    )

    # Step 9: Spawn all async tasks
    logger.info("MAIN", "Spawning async tasks...")

    # Spawn watchdog feed task first (highest priority for system stability)
    asyncio.create_task(feed_watchdog(wdt, wdt_feed_interval_ms, logger))
    logger.debug("MAIN", "task spawned", task="feed_watchdog")

    # Spawn write queue drain task (async SD write batching)
    # Drain task is resilient and catches all exceptions internally (never dies)
    asyncio.create_task(write_queue.start_drain_task())
    logger.debug("MAIN", "task spawned", task="write_queue.start_drain_task")

    # Spawn fallback pruning task (async file maintenance, decoupled from drain)
    # Periodically trims fallback file when it exceeds max size limit
    asyncio.create_task(buffer_manager.start_fallback_prune_task(check_interval=10))
    logger.debug("MAIN", "task spawned", task="buffer_manager.start_fallback_prune_task")

    # Spawn fan cycle tasks
    for fan in fans:
        asyncio.create_task(fan.start_cycle())
        logger.debug("MAIN", "task spawned", task=f"{fan.name}.start_cycle")

    # Spawn other async tasks
    asyncio.create_task(growlight.start_scheduler())
    logger.debug("MAIN", "task spawned", task="growlight.start_scheduler")
    asyncio.create_task(heater.start_cycle())
    logger.debug("MAIN", "task spawned", task="heater.start_cycle")
    asyncio.create_task(th_logger.log_loop())
    logger.debug("MAIN", "task spawned", task="th_logger.log_loop")
    if co2_logger_obj is not None:
        asyncio.create_task(co2_logger_obj.log_loop())
        logger.debug("MAIN", "task spawned", task="co2_logger.log_loop")
    if soil_logger_obj is not None:
        asyncio.create_task(soil_logger_obj.log_loop())
        logger.debug("MAIN", "task spawned", task="soil_logger.log_loop")
    asyncio.create_task(reminder.monitor())
    logger.debug("MAIN", "task spawned", task="reminder.monitor")
    asyncio.create_task(
        led_handler.poll_button(
            interval_ms=system_config.get("button_poll_ms", 50),
        )
    )
    logger.debug("MAIN", "task spawned", task="led_handler.poll_button")

    if oled is not None:
        asyncio.create_task(oled.refresh_loop())
        logger.debug("MAIN", "task spawned", task="oled.refresh_loop")

    logger.info("MAIN", "All tasks spawned. System running.")

    # Main event loop with adaptive health-check interval:
    # - Normal: 60 s (configurable via system.health_check_interval_s)
    # - SD recovery: 10 s (configurable via system.sd_recovery_interval_s)
    normal_interval = system_config.get("health_check_interval_s", 60)
    recovery_interval = system_config.get("sd_recovery_interval_s", 10)
    health_interval = normal_interval

    logger.debug("MAIN", f"health_check={normal_interval}s, sd_recovery={recovery_interval}s")

    while True:
        await asyncio.sleep(health_interval)

        # Feed watchdog at start of health check (redundant with async task, but ensures feed during heavy I/O)
        wdt.feed()

        # Heartbeat: toggle on-board LED to prove loop is alive
        status_manager.heartbeat_tick()

        # Keep system.log bounded even when debug_to_file is enabled.
        try:
            logger.check_size()
        except Exception as e:
            logger.warning("MAIN", f"Log rotation check failed: {e}")

        # System memory check
        gc.collect()
        if hasattr(gc, "mem_alloc") and hasattr(gc, "mem_free"):
            mem_alloc = gc.mem_alloc()
            mem_free = gc.mem_free()
            used_pct = (mem_alloc / (mem_alloc + mem_free)) * 100 if (mem_alloc + mem_free) > 0 else 0
        else:
            # CPython gc does not expose mem_alloc/mem_free; keep health loop running.
            used_pct = 0

        warn_pct = status_led_config.get("mem_warning_pct", 80)
        error_pct = status_led_config.get("mem_error_pct", 90)

        if used_pct >= error_pct:
            status_manager.set_error("mem_error", True)
            status_manager.clear_warning("mem_warn")
        elif used_pct >= warn_pct:
            status_manager.set_warning("mem_warn", True)
            status_manager.clear_error("mem_error")
        else:
            status_manager.clear_warning("mem_warn")
            status_manager.clear_error("mem_error")

        # Periodic health checks
        metrics = buffer_manager.get_metrics()
        buffered = metrics["buffer_entries"]

        logger.debug(
            "MAIN",
            "health check",
            health_interval=health_interval,
            sd_primary_writes=metrics["writes_to_primary"],
            sd_fallback_writes=metrics["writes_to_fallback"],
            migrations=metrics["fallback_migrations"],
            failures=metrics["write_failures"],
            buffered=buffered,
            mem_used_pct=f"{used_pct:.1f}%",
        )

        load_snapshot = _get_runtime_load_snapshot()
        if load_snapshot:
            logger.debug("MAIN", "runtime load", **load_snapshot)

        # Hot-swap recovery: attempt SD refresh when primary is
        # reported down OR when the in-memory buffer is growing.
        # The second condition catches the case where is_primary_available()
        # returns True (cached VFS metadata) but real writes are failing.
        # refresh_sd() performs a block-level readblocks check and is
        # cheap when the card is actually present.
        primary_avail = buffer_manager.is_primary_available()
        sd_needs_check = not primary_avail or buffered > 0
        logger.debug(
            "MAIN",
            "SD check decision",
            sd_needs_check=sd_needs_check,
            primary_available=primary_avail if not sd_needs_check else "skipped",
            buffered=buffered,
        )
        if sd_needs_check:
            logger.debug(
                "MAIN",
                f"SD needs check: primary_avail={primary_avail}, buffered={buffered}",
            )
            if hardware.refresh_sd():
                logger.info("MAIN", "SD card re-mounted after hot-swap")
                logger.debug("MAIN", "SD recovery success", prev_interval=health_interval)
                status_manager.set_sd_status(True)
                # Clear any stale logged_error that was SD-related
                status_manager.clear_error("logged_error")
                # Flush in-memory buffer now that primary is back
                if buffered > 0:
                    buffer_manager.flush()
                    logger.info("MAIN", f"Flushed {buffered} buffered entries to SD")
                health_interval = normal_interval
            else:
                logger.warning("MAIN", "SD card not accessible, retrying soon")
                status_manager.set_sd_status(False)
                status_manager.set_warning("fallback_active", True)
                health_interval = recovery_interval
        else:
            status_manager.set_sd_status(True)
            status_manager.clear_warning("fallback_active")
            health_interval = normal_interval

        # Log buffer warning AFTER the SD check so the reader sees
        # the recovery attempt first, then the remaining state.
        new_buffered = sum(len(v) for v in buffer_manager._buffers.values())
        if new_buffered > 0:
            logger.warning("MAIN", f"Buffer has {new_buffered} entries (SD may be unavailable)")
            status_manager.set_warning("buffer_backlog", True)
        else:
            status_manager.clear_warning("buffer_backlog")

        # Attempt to migrate fallback entries if primary became available
        if metrics["writes_to_fallback"] > metrics["fallback_migrations"]:
            logger.debug(
                "MAIN",
                "migration check",
                writes_fallback=metrics["writes_to_fallback"],
                migrations=metrics["fallback_migrations"],
            )
            migrated = buffer_manager.migrate_fallback()
            if migrated > 0:
                logger.info("MAIN", f"Migrated {migrated} fallback entries to primary SD")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[SHUTDOWN] Keyboard interrupt")
    except Exception as e:
        print(f"[SHUTDOWN] Fatal error: {e}")
        import traceback

        traceback.print_exc()
