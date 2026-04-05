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
# 6. Create DHTLogger (temperature/humidity sensor)
# 7. Create relay controllers: FanController × 2, GrowlightController
# 8. Create LED/button handler and ServiceReminder task
# 9. Spawn all async tasks and run event loop
#
# All components use dependency injection; no global state after init.
#
# HOW TO RUN:
# 1. First time only: run rtc_set_time.py to sync RTC
# 2. Run this main.py via Thonny
# 3. Check /sd/dht_log_YYYY-MM-DD.csv for data

import gc
import os
import sys

if sys.implementation.name != "micropython":  # type: ignore[union-attr]
    host_shims_path = os.path.join(  # type: ignore
        os.path.dirname(os.path.abspath(__file__)),  # type: ignore
        "host_shims",  # type: ignore
    )  # type: ignore[attr-defined]
    sys.path.insert(0, host_shims_path)

import uasyncio as asyncio
from machine import WDT

from config import DEVICE_CONFIG, validate_config
from lib.buffer_manager import BufferManager
from lib.buzzer import BuzzerController
from lib.dht_logger import DHTLogger
from lib.event_logger import EventLogger
from lib.hardware_factory import HardwareFactory
from lib.led_button import LEDButtonHandler, ServiceReminder
from lib.oled_display import OLEDDisplay
from lib.relay import FanController, GrowlightController
from lib.status_manager import StatusManager
from lib.time_provider import RTCTimeProvider
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
    hardware = HardwareFactory(DEVICE_CONFIG, debug_callback=_dbg_cb)
    if not hardware.setup():
        print("[STARTUP ERROR] Critical hardware initialization failed (RTC)")
        hardware.print_status()
        return

    wdt.feed()  # Feed after hardware init
    hardware.print_status()

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

    wdt.feed()  # Feed before buffer/logger init

    # Step 4: Create BufferManager
    buffer_config = DEVICE_CONFIG.get("buffer_manager", {})
    buffer_manager = BufferManager(
        sd_mount_point=buffer_config.get("sd_mount_point", "/sd"),
        fallback_path=buffer_config.get("fallback_path", "/local/fallback.csv"),
        max_buffer_entries=buffer_config.get("max_buffer_entries", 200),
        max_fallback_size_kb=buffer_config.get("max_fallback_size_kb", 50),
        debug_callback=_dbg_cb,
    )
    # Step 4b: Create WriteQueueManager (async SD write batching)
    system_config = DEVICE_CONFIG.get("system", {})
    write_queue = WriteQueueManager(
        buffer_manager=buffer_manager,
        logger=None,  # Inject logger later after EventLogger created
        max_queue_size=system_config.get("write_queue_max_size", 500),
        drain_interval_ms=system_config.get("queue_drain_interval_ms", 100),
        batch_size=system_config.get("queue_batch_size", 5),
    )
    # Step 5: Create EventLogger
    logger = EventLogger(
        time_provider,
        buffer_manager,
        logfile=logger_config.get("logfile", "/sd/system.log"),
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

    logger.info("MAIN", "System startup")
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

    # Step 6: Create DHTLogger
    dht_config = DEVICE_CONFIG.get("dht_logger", {})
    files_config = DEVICE_CONFIG.get("files", {})
    try:
        dht_logger = DHTLogger(
            pin=DEVICE_CONFIG["pins"]["dht22"],
            time_provider=time_provider,
            buffer_manager=buffer_manager,
            logger=logger,
            interval=dht_config.get("interval_s", 30),
            filename=f"/sd/{files_config.get('dht_log_base', 'dht_log.csv')}",
            max_retries=dht_config.get("max_retries", 3),
            status_manager=status_manager,
            dht_warn_threshold=status_led_config.get("dht_warn_threshold", 3),
            dht_error_threshold=status_led_config.get("dht_error_threshold", 10),
            retry_delay_s=dht_config.get("retry_delay_s", 0.5),
            write_queue=write_queue,
        )
    except Exception as e:
        logger.error("MAIN", f"DHTLogger init failed: {e}")
        # Create a minimal DHTLogger without status manager to keep system running
        dht_logger = DHTLogger(
            pin=DEVICE_CONFIG["pins"]["dht22"],
            time_provider=time_provider,
            buffer_manager=buffer_manager,
            logger=logger,
            interval=dht_config.get("interval_s", 30),
            filename=f"/sd/{files_config.get('dht_log_base', 'dht_log.csv')}",
            max_retries=dht_config.get("max_retries", 3),
            retry_delay_s=dht_config.get("retry_delay_s", 0.5),
            write_queue=write_queue,
        )

    wdt.feed()  # Feed after DHTLogger init

    # Step 7: Create relay controllers with dependency injection
    fan_configs = [
        (DEVICE_CONFIG["pins"]["relay_fan_1"], DEVICE_CONFIG.get("fan_1", {}), "Fan_1"),
        (DEVICE_CONFIG["pins"]["relay_fan_2"], DEVICE_CONFIG.get("fan_2", {}), "Fan_2"),
    ]

    fans = []
    for pin, config, name in fan_configs:
        fan = FanController(
            pin=pin,
            time_provider=time_provider,
            dht_logger=dht_logger,
            logger=logger,
            interval_s=config.get("interval_s", 600),
            on_time_s=config.get("on_time_s", 20),
            max_temp=config.get("max_temp", 23.8),
            temp_hysteresis=config.get("temp_hysteresis", 0.5),
            poll_interval_s=config.get("poll_interval_s", 5),
            name=name,
        )
        fans.append(fan)
    logger.info("MAIN", "Fan controllers initialized")
    wdt.feed()  # Feed after fan controllers
    logger.debug(
        "MAIN",
        "Step 7a fans",
        fan_count=len(fans),
        fan_names=str([f.name for f in fans]),
    )

    # Step 7b: Create grow light controller
    light_config = DEVICE_CONFIG.get("growlight", {})
    growlight = GrowlightController(
        pin=DEVICE_CONFIG["pins"]["relay_growlight"],
        time_provider=time_provider,
        logger=logger,
        dawn_hour=light_config.get("dawn_hour", 7),
        dawn_minute=light_config.get("dawn_minute", 0),
        sunset_hour=light_config.get("sunset_hour", 19),
        sunset_minute=light_config.get("sunset_minute", 0),
        poll_interval_s=light_config.get("poll_interval_s", 60),
        name="Growlight",
    )
    logger.debug(
        "MAIN",
        "Step 7b growlight",
        dawn=f"{light_config.get('dawn_hour', 7):02d}:{light_config.get('dawn_minute', 0):02d}",
        sunset=f"{light_config.get('sunset_hour', 19):02d}:{light_config.get('sunset_minute', 0):02d}",
        poll_s=light_config.get("poll_interval_s", 60),
    )

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
        await status_manager.run_post(step_ms=post_step, reminder_led=led_handler.led)
        wdt.feed()  # Feed after POST
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

        try:
            oled = OLEDDisplay(
                i2c=hardware.get_i2c(),
                time_provider=time_provider,
                dht_logger=dht_logger,
                buffer_manager=buffer_manager,
                status_manager=status_manager,
                reminder=reminder,
                fans=fans,
                growlight=growlight,
                sd_remount_cb=_sd_remount_cb,
                start_time_ms=0,
                logger=logger,
                width=display_config.get("width", 128),
                height=display_config.get("height", 64),
                i2c_address=display_config.get("i2c_address", 0x3C),
                refresh_interval_s=display_config.get("refresh_interval_s", 5),
                stats_window_s=display_config.get("stats_window_s", 3600),
                menu_timeout_s=display_config.get("menu_timeout_s", 30),
                display_timeout_s=display_config.get("display_timeout_s", 120),
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
    asyncio.create_task(dht_logger.log_loop())
    logger.debug("MAIN", "task spawned", task="dht_logger.log_loop")
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
