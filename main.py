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

import os
import sys

if sys.implementation.name != 'micropython':
    host_shims_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'host_shims')
    sys.path.insert(0, host_shims_path)

import uasyncio as asyncio
from config import DEVICE_CONFIG, validate_config
from lib.hardware_factory import HardwareFactory
from lib.time_provider import RTCTimeProvider
from lib.buffer_manager import BufferManager
from lib.event_logger import EventLogger
from lib.dht_logger import DHTLogger
from lib.relay import FanController, GrowlightController
from lib.led_button import LEDButtonHandler, ServiceReminder


async def main():
    """
    Main async entry point for Pi Greenhouse system.
    
    Orchestrates initialization and spawns all concurrent tasks.
    All long-running operations (logging, relay cycling, scheduling) run as async tasks.
    """
    print('[STARTUP] Initializing Pi Greenhouse system...')
    
    # Step 1: Validate configuration
    try:
        validate_config()
        print('[STARTUP] Configuration validated')
    except ValueError as e:
        print(f'[STARTUP ERROR] Config validation failed: {e}')
        return
    
    # Step 2: Initialize hardware
    hardware = HardwareFactory(DEVICE_CONFIG)
    if not hardware.setup():
        print('[STARTUP ERROR] Critical hardware initialization failed (RTC)')
        hardware.print_status()
        return
    
    hardware.print_status()
    
    # Step 3: Create TimeProvider (wraps RTC)
    rtc = hardware.get_rtc()
    time_provider = RTCTimeProvider(rtc)
    
    # Step 4: Create BufferManager
    buffer_config = DEVICE_CONFIG.get('buffer_manager', {})
    buffer_manager = BufferManager(
        sd_mount_point=buffer_config.get('sd_mount_point', '/sd'),
        fallback_path=buffer_config.get('fallback_path', '/local/fallback.csv'),
        max_buffer_entries=buffer_config.get('max_buffer_entries', 1000),
    )
    
    # Step 5: Create EventLogger
    logger_config = DEVICE_CONFIG.get('event_logger', {})
    logger = EventLogger(
        time_provider,
        buffer_manager,
        logfile=logger_config.get('logfile', '/sd/system.log'),
        max_size=logger_config.get('max_size', 50000),
    )
    
    logger.info('MAIN', 'System startup')
    
    # Step 6: Create DHTLogger
    dht_config = DEVICE_CONFIG.get('dht_logger', {})
    files_config = DEVICE_CONFIG.get('files', {})
    dht_logger = DHTLogger(
        pin=DEVICE_CONFIG['pins']['dht22'],
        time_provider=time_provider,
        buffer_manager=buffer_manager,
        logger=logger,
        interval=dht_config.get('interval_s', 60),
        filename=f'/sd/{files_config.get("dht_log_base", "dht_log.csv")}',
        max_retries=dht_config.get('max_retries', 3),
    )
    
    # Step 7: Create relay controllers with dependency injection
    fan_configs = [
        (DEVICE_CONFIG['pins']['relay_fan_1'], DEVICE_CONFIG.get('fan_1', {}), 'Fan_1'),
        (DEVICE_CONFIG['pins']['relay_fan_2'], DEVICE_CONFIG.get('fan_2', {}), 'Fan_2'),
    ]
    
    fans = []
    for pin, config, name in fan_configs:
        fan = FanController(
            pin=pin,
            time_provider=time_provider,
            dht_logger=dht_logger,
            logger=logger,
            interval_s=config.get('interval_s', 600),
            on_time_s=config.get('on_time_s', 20),
            max_temp=config.get('max_temp', 24.0),
            temp_hysteresis=config.get('temp_hysteresis', 1.0),
            name=name,
        )
        fans.append(fan)
    logger.info('MAIN', 'Fan controllers initialized')
    
    # Step 7b: Create grow light controller
    light_config = DEVICE_CONFIG.get('growlight', {})
    growlight = GrowlightController(
        pin=DEVICE_CONFIG['pins']['relay_growlight'],
        time_provider=time_provider,
        logger=logger,
        dawn_hour=light_config.get('dawn_hour', 6),
        dawn_minute=light_config.get('dawn_minute', 0),
        sunset_hour=light_config.get('sunset_hour', 22),
        sunset_minute=light_config.get('sunset_minute', 0),
        name='Growlight',
    )
    
    # Step 8: Create LED/button handler and Service reminder
    led_handler = LEDButtonHandler(
        led_pin=DEVICE_CONFIG['pins']['reminder_led'],
        button_pin=DEVICE_CONFIG['pins']['button_reminder'],
        debounce_ms=DEVICE_CONFIG.get('system', {}).get('button_debounce_ms', 50),
    )
    
    Service_config = DEVICE_CONFIG.get('Service_reminder', {})
    reminder = ServiceReminder(
        time_provider=time_provider,
        led_handler=led_handler,
        days_interval=Service_config.get('days_interval', 7),
        blink_pattern_ms=Service_config.get('blink_pattern_ms', [200, 200, 200, 800]),
    )
    
    # Step 9: Spawn all async tasks
    logger.info('MAIN', 'Spawning async tasks...')
    
    # Spawn fan cycle tasks
    for fan in fans:
        asyncio.create_task(fan.start_cycle())
    
    # Spawn other async tasks
    asyncio.create_task(growlight.start_scheduler())
    asyncio.create_task(dht_logger.log_loop())
    asyncio.create_task(reminder.monitor())
    
    logger.info('MAIN', 'All tasks spawned. System running.')
    
    # Main event loop (keep running)
    while True:
        await asyncio.sleep(60)
        
        # Periodic health checks
        metrics = buffer_manager.get_metrics()
        if metrics['buffer_entries'] > 0:
            logger.warning('MAIN', f'Buffer has {metrics["buffer_entries"]} entries (SD may be unavailable)')
        
        # Hot-swap recovery: if SD is not accessible, attempt remount
        # via HardwareFactory so the VFS mount is re-established after
        # a card removal + reinsertion cycle.
        if not buffer_manager.is_primary_available():
            if hardware.refresh_sd():
                logger.info('MAIN', 'SD card re-mounted after hot-swap')
        
        # Attempt to migrate fallback entries if primary became available
        if metrics['writes_to_fallback'] > metrics['fallback_migrations']:
            migrated = buffer_manager.migrate_fallback()
            if migrated > 0:
                logger.info('MAIN', f'Migrated {migrated} fallback entries to primary SD')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('[SHUTDOWN] Keyboard interrupt')
    except Exception as e:
        print(f'[SHUTDOWN] Fatal error: {e}')
        import traceback
        traceback.print_exc()
