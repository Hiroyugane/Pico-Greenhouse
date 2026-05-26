# Pi Greenhouse Configuration
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0
#
# Central configuration for all hardware pins, intervals, file paths, and thresholds.
# Modify values here to tune device behavior without editing module code.

DEVICE_CONFIG = {
    # Operating mode — single switch that picks which optional components
    # are constructed at boot.
    #
    #   "plant":    dimmable grow light (MCP4725 DAC over relay master) AND
    #               soil-moisture logger (GP28 ADC) are both enabled.
    #   "mushroom": basic relay-only grow light, soil sensor not constructed.
    #
    # Disabled components are skipped entirely in main.py (no task, no I/O),
    # so the only cost of being in the wrong mode is what's missing — not
    # idle objects holding RAM. Override growlight.mode below is ignored;
    # the top-level mode is the source of truth for grow-light wiring.
    "mode": "mushroom",
    # Hardware Pins
    #
    # Pico GPIO layout — matches PCB schematic SCH_Pico-Greenhouse-PCB_2026-05-14
    # (docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json):
    #
    #   GP0-GP1:   I2C0 bus (shared: RTC + OLED + MCP4725 grow-light DAC +
    #              I2C_CON1/2/3 breakouts). Pulled up to 3V3 via R1/R2.
    #   GP2:       GP2_CON header (general-purpose breakout, future use)
    #   GP3:       Heater MOSFET gate (via R6 → IRLZ44N gate, active HIGH)
    #   GP4:       Activity LED   (LED_CON)
    #   GP5:       SD-problem LED (LED_CON)
    #   GP6:       Warning LED    (LED_CON)
    #   GP7:       Error LED      (LED_CON)
    #   GP8:       Service / reminder LED (LED_CON)
    #   GP9:       Menu button (MEN_BTN, short=cycle, long=action)
    #   GP10-GP13: SPI1 (SD card via SD_CON). Both MOSI (R10) and MISO
    #              (R8 = 33 Ω) carry series damping resistors between
    #              Pico and SD_CON. R8 was initially suspected during
    #              the 2026-05-16/18 SD bit-error incident, but the
    #              root cause turned out to be VSYS starvation from the
    #              1N4002 input diodes (see chat-log 2026-05-19). R8
    #              stays on the next-rev PCB as a useful SPI signal
    #              damper at 10 MHz baud — see chat-log 2026-05-23
    #              "keep R8 = 33 Ω; fix the firmware comment instead".
    #   GP14:      Passive buzzer (BUZ_CON, with R3 pulldown to GND)
    #   GP15:      Free (formerly DHT22 data on T/H_CON pin 4; SHT31 now
    #              shares the I2C0 bus, GP15 is available for future use)
    #   GP16:      UART0 TX → CO2 sensor (via R9 to CO2_CON pin 4)
    #   GP17:      UART0 RX ← CO2 sensor (via R11 from CO2_CON pin 3)
    #   GP18:      Relay 1 — fan 1     (REL_CON pin 2)
    #   GP19:      Relay 2 — fan 2     (REL_CON pin 3)
    #   GP20:      Relay 3 — growlight (REL_CON pin 4)
    #   GP21-GP22: Reserved relays (REL_CON pins 5-6, future use)
    #   GP25:      On-board LED (heartbeat)
    #   GP26-GP27: Reserved relays (REL_CON pins 7-8, future use)
    #   GP28:      ADC input (ADC_CON pin 4; ADC_VREF on Pico pin 35)
    #
    # RES_BTN on the PCB is wired to the Pico's 3V3_EN line (hardware reset),
    # not a GPIO; "button_reserved" below points at the GP2 breakout for any
    # future software-side button.
    "pins": {
        # I2C0 — shared bus (RTC, OLED, MCP4725 grow-light DAC, I2C breakouts)
        "rtc_i2c_port": 0,
        "rtc_sda": 0,  # GP0 (I2C0 SDA)
        "rtc_scl": 1,  # GP1 (I2C0 SCL)
        # General-purpose breakout header (GP2_CON, future use)
        "gp2_breakout": 2,  # GP2 — exposed for future use
        "button_reserved": 2,  # Reserved (mapped onto GP2_CON; RES_BTN is now a hw reset, not a GPIO)
        # Heater control (GP3 → R6 → HE_MOSFET gate)
        "heater_mosfet": 3,  # GP3 — heater MOSFET gate (active HIGH)
        # Status LEDs (LED_CON wiring per new PCB; roles by GPIO)
        "activity_led": 4,  # GP4 — Activity LED (brief blink on I/O actions)
        "sd_led": 5,  # GP5 — SD-problem LED (solid = SD missing/failed)
        "warning_led": 6,  # GP6 — Warning LED (solid = degraded condition)
        "error_led": 7,  # GP7 — Error LED (solid = fault needs attention)
        "reminder_led": 8,  # GP8 — Service-reminder LED (blinks when due)
        # Menu button
        "button_menu": 9,  # GP9 — Menu button (short=cycle menu, long≥3s=action)
        # Buzzer (BUZ_CON, pulled to GND via R3)
        "buzzer": 14,  # GP14 — Passive buzzer (PWM output)
        # CO2 sensor (UART0 with series resistors R9/R11)
        "co2_uart_id": 0,  # UART0
        "co2_uart_tx": 16,  # GP16 — UART0 TX → CO2_CON pin 4 (via R9)
        "co2_uart_rx": 17,  # GP17 — UART0 RX ← CO2_CON pin 3 (via R11)
        "co2_baudrate": 9600,
        # Relays (REL_CON pins 2-8 → 7 GPIO control lines)
        "relay_fan_1": 18,  # GP18 — Fan relay 1 (REL_CON pin 2)
        "relay_fan_2": 19,  # GP19 — Fan relay 2 (REL_CON pin 3)
        "relay_growlight": 20,  # GP20 — Grow light relay (REL_CON pin 4)
        "relay_reserved_1": 21,  # GP21 — Reserved relay (REL_CON pin 5)
        "relay_reserved_2": 22,  # GP22 — Reserved relay (REL_CON pin 6)
        "relay_reserved_3": 26,  # GP26 — Reserved relay (REL_CON pin 7)
        "relay_reserved_4": 27,  # GP27 — Reserved relay (REL_CON pin 8)
        # Analog input (ADC_CON pin 4; ADC_VREF on Pico pin 35)
        # Queued for removal once the Adafruit STEMMA #4026 I²C soil
        # sensor swap ships — see docs/hardware/next-revision.md.
        "adc_input": 28,  # GP28 — ADC input (ADC_CON pin 4)
        # On-board LED
        "onboard_led": 25,  # GP25 — Pico on-board LED (heartbeat)
    },
    # SPI Configuration (SD Card via SD_CON; MOSI uses series resistor R10, MISO is direct)
    #
    # baudrate: a field run on 2026-05-16/18 produced 32× `SD status
    # changed: FAILED` over 42 h, traced to series resistor R8 on the
    # MISO line (GP12 ↔ SD_CON pin 3). R8 has since been removed and
    # MISO is now a direct trace. Baudrate kept at 10 MHz as a
    # precaution until the next bench run confirms 40 MHz is safe
    # without R8; bandwidth is not the bottleneck (CSV rows are ~30
    # bytes), so leaving headroom on the link is the conservative call.
    "spi": {
        "id": 1,
        "baudrate": 10000000,
        "sck": 10,  # GP10 → SD_CON.SCK
        "mosi": 11,  # GP11 → R10 → SD_CON.MOSI
        "miso": 12,  # GP12 → SD_CON.MISO (direct; R8 removed)
        "cs": 13,  # GP13 → SD_CON.CS
        "mount_point": "/sd",
    },
    # File Paths
    "files": {
        "system_log": "/sd/logs/system.log",
        "fallback_path": "/local/fallback.csv",  # Fallback when SD unavailable
    },
    # SD card directory layout. Sensor-first tree under sensor_root keeps
    # one folder per sensor type and one subfolder per year, so adding a
    # new sensor only needs a new key here — no logger code changes.
    # Final sensor file path: <sensor_root>/<type>/YYYY/<type>_YYYY-MM-DD.csv
    "paths": {
        "sensor_root": "/sd/sensors",
        "logs_dir": "/sd/logs",
        "ota_pending_dir": "/sd/ota/pending",
        "ota_applied_dir": "/sd/ota/applied",
        "diagnostics_dir": "/sd/diagnostics",
    },
    # SHT31-D temperature/humidity sensor (shared I2C0 bus, alongside RTC,
    # OLED and MCP4725 DAC). ADDR pin tied to GND = 0x44; tied to VCC = 0x45.
    "sht31": {
        "i2c_address": 0x44,
    },
    # Temperature/Humidity Logger Configuration
    "temp_humidity_logger": {
        "interval_s": 30,  # Log interval in seconds
        "max_retries": 3,  # Sensor read retries
        "max_buffer_size": 200,  # Max in-memory readings
        "retry_delay_s": 0.5,  # Delay between sensor read retries (seconds)
        "sensor_type": "th",  # Folder + filename prefix under paths.sensor_root
    },
    # Fan Roster (role-keyed, mode-dispatched).
    #
    # Each entry names a physical fan role. The controller class is picked
    # by `mode`; the drive backend by `output`. Current PCB has two relay
    # outputs (REL_CON pins 2 and 3, GP18/GP19) — those map to exhaust and
    # growroom_walls. The remaining three roles ship disabled and flip on
    # when the PCA9685 PCB lands; only main.py wiring changes (policy is
    # untouched).
    #
    # Modes:
    #   thermostat_schedule — time-of-day on-cycle + temperature override
    #                         (FanController). Needs interval_s, on_time_s,
    #                         max_temp, temp_hysteresis, poll_interval_s,
    #                         default_duty_pct.
    #   always_on           — constant duty (AlwaysOnFanController).
    #                         Needs duty_pct.
    #   heater_follower     — runs while heater.is_on() plus post_run_s
    #                         afterrun (HeaterFollowerFanController). Needs
    #                         post_run_s, duty_pct, poll_interval_s.
    #
    # Outputs:
    #   relay    — wraps a RelayController on the pin named by
    #              relay_pin_key (must reference DEVICE_CONFIG["pins"]).
    #   pca9685  — drives PCA9685 channel pca9685_ch (0..15). Disabled
    #              until pca9685.enabled flips True.
    "fans": {
        "exhaust": {
            "enabled": True,
            "mode": "thermostat_schedule",
            "output": "relay",
            "relay_pin_key": "relay_fan_1",
            "interval_s": 600,
            "on_time_s": 20,
            "max_temp": 23.8,
            "temp_hysteresis": 0.5,
            "poll_interval_s": 5,
            "default_duty_pct": 100,
        },
        "growroom_walls": {
            "enabled": True,
            "mode": "thermostat_schedule",
            "output": "relay",
            "relay_pin_key": "relay_fan_2",
            "interval_s": 500,
            "on_time_s": 20,
            "max_temp": 27.0,
            "temp_hysteresis": 0.5,
            "poll_interval_s": 5,
            "default_duty_pct": 100,
        },
        "growroom_center": {
            "enabled": False,
            "mode": "thermostat_schedule",
            "output": "pca9685",
            "pca9685_ch": 0,
            "interval_s": 500,
            "on_time_s": 20,
            "max_temp": 27.0,
            "temp_hysteresis": 0.5,
            "poll_interval_s": 5,
            "default_duty_pct": 80,
        },
        "heater_distribution": {
            "enabled": False,
            "mode": "heater_follower",
            "output": "pca9685",
            "pca9685_ch": 1,
            "post_run_s": 60,
            "duty_pct": 80,
            "poll_interval_s": 5,
        },
        "case": {
            "enabled": False,
            "mode": "always_on",
            "output": "pca9685",
            "pca9685_ch": 2,
            "duty_pct": 60,
            "refresh_interval_s": 300,
        },
    },
    # PCA9685 PWM driver (16-channel I2C, shared I2C0 bus).
    #
    # Used by the next hardware revision to drive IRLZ44N MOSFET gates for
    # variable-speed fan control (see lib/pca9685.py, lib/fan_output.py).
    # Disabled by default: until the new PCB lands the chip is absent and
    # HardwareFactory leaves get_pca9685() == None so fans fall back to
    # the existing relay path.
    #
    # i2c_address: A5..A0 strap pins on the PCA9685 select 0x40..0x7F;
    # 0x40 is the default with all straps tied LOW.
    # freq_hz: shared across all 16 channels per datasheet, 24..1526 Hz.
    "pca9685": {
        "enabled": False,
        "i2c_address": 0x40,
        "freq_hz": 1000,
    },
    # Heater Configuration (GP3 → R6 → IRLZ44N gate, ACTIVE HIGH)
    #
    # Day/night setpoints inherit the growlight schedule plus an optional
    # offset in minutes. day_start = growlight.dawn + day_offset_min;
    # night_start = growlight.sunset + night_offset_min. With both offsets
    # at 0 the heater follows the lamp 1:1.
    "heater": {
        "day_min_temp": 22.0,  # Setpoint while day window is active (°C)
        "night_min_temp": 16.0,  # Setpoint while night window is active (°C)
        "temp_hysteresis": 0.5,  # Drop below setpoint before re-firing (°C)
        "day_offset_min": 0,  # Minutes after growlight dawn for day window start
        "night_offset_min": 0,  # Minutes after growlight sunset for night window start
        "max_stale_reads": 3,  # Tolerate N consecutive DHT failures before failing OFF
        "poll_interval_s": 30,  # Thermostat check cadence (seconds)
    },
    # Soil Moisture Logger Configuration (GP28 / ADC2, single-probe)
    #
    # NOTE (2026-05-26): sensor swap queued — moving to the Adafruit
    # STEMMA #4026 (I²C, Seesaw ATSAMD10, address 0x36) on the next
    # PCB. See docs/hardware/next-revision.md "Soil moisture sensor
    # → Adafruit STEMMA #4026 (I²C, 0x36)" and the 2026-05-26
    # chat-log entry. When the firmware rewrite ships, the keys
    # below change shape: `adc_input` drops out of the pins dict;
    # `adc_dry_raw` / `adc_wet_raw` rename to `seesaw_dry_raw` /
    # `seesaw_wet_raw` with the wet/dry inequality reversed
    # (capacitive Seesaw: higher raw = wetter); new `i2c_address`
    # and `i2c_bus` keys land. validate_config() and
    # tests/test_config.py move in lockstep that turn. Until then
    # the analog-style keys stay so SoilLogger keeps booting.
    #
    # Raw ADC range on the RP2040 is 0-65535 (read_u16) but the plan
    # speaks in the conventional 0-1023 10-bit space. SoilLogger scales
    # the read_u16 result down internally; the calibration constants are
    # specified in 0-1023 space because that's what the REPL helper
    # (print_raw) prints. Calibrate against actual sensor + soil pot:
    # adc_dry_raw = raw value with probe in air / bone-dry soil,
    # adc_wet_raw = raw value with probe in saturated soil. Wet must be
    # < dry (lower raw = more conductive = more water).
    "soil_logger": {
        "interval_s": 60,  # Log cadence (seconds) — soil moves slowly
        "adc_dry_raw": 850,  # Raw 10-bit reading for 0% moisture (in-air)
        "adc_wet_raw": 350,  # Raw 10-bit reading for 100% moisture (saturated)
        "warn_pct_below": 20,  # Trigger warning LED when soil < this %
        "sensor_type": "soil",  # Folder + filename prefix under paths.sensor_root
    },
    # CO2 Sensor Logger Configuration (SenseAir S8 / equivalent on UART0)
    #
    # Poll/response framing matches the prototype in tests/co2log.py:
    # 7-byte request 0xFE 0x44 0x00 0x08 0x02 0x9F 0x25 → 7-byte reply
    # whose bytes 3-4 (0-indexed) encode ppm as high*256 + low.
    # The override_fan key names a role in DEVICE_CONFIG["fans"]; that
    # fan gets force-on when ppm crosses override_ppm_on, until ppm
    # drops below override_ppm_off. The exhaust fan is the natural CO2
    # vent target.
    "co2_logger": {
        "interval_s": 30,  # Poll cadence (seconds)
        "warmup_s": 30,  # Sensor warm-up window where read failures don't escalate
        "max_retries": 3,  # UART read retries per poll
        "override_ppm_on": 1000,  # Trip threshold (ppm)
        "override_ppm_off": 800,  # Release threshold (ppm), must be < on
        "override_fan": "exhaust",  # Which fans-dict role to force-on
        "sensor_type": "co2",  # Folder + filename prefix under paths.sensor_root
    },
    # Grow Light Configuration
    "growlight": {
        # "relay_only": drive GP20 relay as plain on/off, skip MCP4725 init.
        # "dimmed":     init MCP4725 DAC for ViparSpectra XS1500 dimming over
        #               the relay master-switch. Falls back to relay-only at
        #               runtime if DAC init throws (logged as warning).
        "mode": "relay_only",
        "dawn_hour": 7,  # Light ON at 7:00 AM
        "dawn_minute": 0,
        "sunset_hour": 19,  # Light OFF at 19:00 (10 PM)
        "sunset_minute": 0,
        "poll_interval_s": 60,  # Schedule check interval (seconds)
        # MCP4725 dimming DAC on shared I2C0. Only consulted when mode="dimmed".
        # Tentative default 0x60 (A0=GND); confirm with prototypes/i2c_scan.py —
        # A0=VCC is 0x61.
        "dac_i2c_address": 0x60,
        # Dimming layer over the master-switch relay. Relay handles
        # ON/OFF; DAC sets brightness via op-amp buffer to GL_CON.
        "default_level_pct": 80,  # Brightness when no override active
        "max_level_pct": 91,  # ViparSpectra XS1500 safe ceiling — never exceed
        "min_level_pct": 0,  # Below this snaps to 0 (relay off)
        "ramp_duration_s": 300,  # Linear fade duration on dawn/sunset edges
    },
    # Service Reminder Configuration
    "Service_reminder": {
        "days_interval": 7,  # Remind every 7 days
        "blink_pattern_ms": [
            200,
            200,
            200,
            800,
        ],  # ON 200ms, OFF 200ms, ON 200ms, OFF 800ms
        "blink_after_days": 3,  # Days overdue before LED switches from solid to blink
        "storage_path": "/service_reminder.txt",  # Persistence file for last-serviced timestamp
        "monitor_interval_s": 3600,  # Re-check interval when not due (seconds)
    },
    # Status LED Manager Configuration
    # Design: solid = problem, blink = activity, dark = all good
    #
    # walk_order — physical left-to-right order of the LED row on the PCB
    # (LED_CON). The POST walk lights LEDs in this sequence so the
    # visual sweep moves smoothly across the row instead of jumping
    # between GPIOs in pin-number order. Valid role names:
    #   "activity" (green, GP4), "sd" (blue, GP5),
    #   "reminder" (white, GP8), "warning" (yellow, GP6),
    #   "error" (red, GP7).
    # Heartbeat (GP25 on-board) is always appended after the row.
    "status_leds": {
        "activity_blink_ms": 50,  # Activity LED pulse duration (ms)
        "heartbeat_interval_ms": 2000,  # GP25 toggle period (ms)
        "th_warn_threshold": 3,  # Consecutive T/H read failures → warning
        "th_error_threshold": 10,  # Consecutive T/H read failures → error
        "rtc_min_year": 2025,  # Year below this → RTC invalid warning
        "rtc_max_year": 2035,  # Year above this → RTC invalid warning
        "post_enabled": True,  # Run LED power-on self-test at startup
        "post_step_ms": 150,  # Duration each LED stays on during POST walk (ms)
        "walk_order": ["activity", "sd", "reminder", "warning", "error"],
        "mem_warning_pct": 80,  # RAM usage % above this → warning LED
        "mem_error_pct": 90,  # RAM usage % above this → error LED
    },
    # Buffer Manager Configuration
    "buffer_manager": {
        "sd_mount_point": "/sd",
        "fallback_path": "/local/fallback.csv",
        "max_buffer_entries": 150,  # Ring buffer cap (reduced from 200 to reduce RAM usage)
        "max_fallback_size_kb": 50,  # Emergency fallback file size limit (KB); when exceeded, oldest entries are pruned
    },
    # Event Logger Configuration
    "event_logger": {
        "logfile": "/sd/logs/system.log",
        "max_size": 1000000,  # Max log file size (bytes) before rotation
        "info_flush_threshold": 5,  # Flush after N info-level entries buffered
        "warn_flush_threshold": 1,  # Flush after N warning-level entries (1=immediate, like ERROR)
        "log_level": "INFO",  # Minimum severity: DEBUG, INFO, WARN, ERR
        "debug_enabled": False,  # Enable DEBUG messages to console (zero-cost when disabled)
        "debug_to_file": False,  # Also write DEBUG entries to SD log (caution: fills card)
        "debug_flush_threshold": 10,  # Flush after N debug entries buffered (when debug_to_file=True)
        "debug_max_size": 1000000,  # Rotation threshold when debug_to_file=True (lower: debug spam fills log faster)
    },
    # Buzzer Configuration (passive buzzer via PWM)
    "buzzer": {
        "enabled": True,  # Master enable/disable
        "default_freq": 1000,  # Default tone frequency (Hz)
        "default_duty_pct": 50,  # Default duty cycle (% of u16 range)
        "startup_melody": [
            (1047, 100, 50),  # C6, 100ms, 50ms pause
            (1319, 100, 50),  # E6
            (1568, 200, 0),  # G6
        ],
        "error_pattern": [
            (400, 200, 100),  # Low tone, 200ms, 100ms pause
            (400, 200, 100),
            (400, 400, 0),  # Longer final beep
        ],
        "alert_pattern": [
            (2000, 150, 100),  # High tone
            (2000, 150, 100),
            (2000, 150, 0),
        ],
        "reminder_pattern": [
            (880, 100, 200),  # A5
            (880, 100, 0),
        ],
    },
    # OLED Display Configuration (SSD1306 on shared I2C1 bus)
    "display": {
        "type": "SSD1306",
        "width": 128,
        "height": 64,
        "i2c_address": 0x3C,  # SSD1306 default (RTC is 0x68; no conflict)
        "enabled": True,  # Master enable/disable (False = skip display init)
        "refresh_interval_s": 5,  # How often to re-render the current menu
        "stats_window_s": 3600,  # Look-back window for temp/hum hi/lo/avg stats
        "max_history": 120,  # Max readings to keep for stats (120 × 30 s ≈ 1 h)
        "menu_timeout_s": 30,  # Return to default menu after this many seconds of inactivity
        "display_timeout_s": 120,  # Turn off display after this many seconds of inactivity (extends OLED lifetime)
        "startup_banner_s": 2.0,  # How long to show the "Pi Greenhouse / Ready!" banner at init
        "vram_clear_delay_s": 0.05,  # Per-step delay during the triple-clear sequence at init
        "invert_delay_s": 0.1,  # Delay after invert/revert and final clear at init
        # Debug Actions sub-menu (entered from the "debug" menu via long-press).
        # Inside the sub-menu: short press cycles actions, long press executes
        # the highlighted action. Destructive actions (wipe_logs) require a
        # second long press to confirm.
        "debug": {
            "enabled": True,  # Master enable; False removes the menu entry
            "confirm_timeout_s": 8,  # Confirm prompt auto-cancels after this many seconds
            "status_show_ms": 3000,  # How long the "done"/"failed" status line stays on screen
            "feedback_blink_ms": [80, 80, 80, 80],  # Reminder LED pattern played after a successful action
            "test_heater_s": 5,  # Heater "ON-for-N-seconds" smoke-test duration
            "test_growlight_pulse_s": 2,  # Relay pulse duration for the basic growlight test
            "test_growlight_dim_levels_pct": [0, 25, 50, 75, 100, 0],  # DAC sweep when MCP4725 is present
            "test_growlight_dim_step_s": 1,  # Dwell at each dim level
            "test_relay_pulse_s": 1,  # Per-relay ON duration during the cycle test
        },
    },
    # Output Pin Initial States
    "output_pins": {
        "relay_fan_1": True,  # HIGH = off (relay module inverted logic)
        "relay_fan_2": True,  # HIGH = off (relay module inverted logic)
        "relay_growlight": True,  # HIGH = off (relay module inverted logic)
        # Reserved relay channels GP21/22/26/27 — driven HIGH at boot so the
        # active-low relay inputs don't float into a half-powered pseudo-state.
        "relay_reserved_1": True,  # HIGH = off (relay module inverted logic)
        "relay_reserved_2": True,  # HIGH = off (relay module inverted logic)
        "relay_reserved_3": True,  # HIGH = off (relay module inverted logic)
        "relay_reserved_4": True,  # HIGH = off (relay module inverted logic)
        "activity_led": False,  # LOW = off (active high LED)
        "reminder_led": False,  # LOW = off (active high LED)
        "sd_led": False,  # LOW = off (active high LED)
        "warning_led": False,  # LOW = off (active high LED)
        "error_led": False,  # LOW = off (active high LED)
        "onboard_led": False,  # LOW = off (active high LED)
    },
    # System Configuration
    "system": {
        "require_sd_startup": True,  # If True, SD mount failure at boot lights sd+error LEDs and resets after sd_fail_reset_s # noqa: E501
        "sd_fail_reset_s": 10,  # Countdown (s) the boot path waits with sd+error LEDs lit before machine.reset()
        "boot_log_path": "/boot.log",  # Internal-flash file that mirrors HardwareFactory SD diagnostics; readable over USB MSC after a reset # noqa: E501
        "boot_log_max_kb": 10,  # Cap (KB) for boot_log_path; oldest content is truncated when exceeded
        "button_debounce_ms": 60,  # Debounce delay for button presses
        "long_press_ms": 3000,  # Long-press threshold for menu action button
        "health_check_interval_s": 60,  # Normal health-check loop interval
        "sd_recovery_interval_s": 10,  # Fast retry interval when SD is unavailable
        "i2c_freq": 400000,  # I2C bus frequency in Hz (100 kHz standard, 400 kHz fast)
        "sd_power_up_ms": 1500,  # SD card power-up stabilization delay (ms); cheap cards may need >1s cold
        "sd_mount_retries": 3,  # Number of SD mount attempts at cold boot
        "sd_retry_delay_ms": 1000,  # Delay between SD mount retries (ms)
        "rtc_sync_interval_s": 3600,  # RTC-to-Pico clock sync interval (seconds)
        "button_poll_ms": 50,  # Button ISR flag polling interval (ms)
        "watchdog_timeout_ms": 8000,  # Watchdog timeout (ms); RP2040 max is ~8388ms
        "watchdog_feed_interval_ms": 2000,  # Feed watchdog every N ms (must be < timeout)
        # Write Queue Configuration (async SD write batching)
        "write_queue_max_size": 500,  # Max queue entries before overflow to fallback
        "queue_drain_interval_ms": 100,  # Milliseconds between drain cycles
        "queue_batch_size": 5,  # Max writes per drain cycle
        "sd_recovery_max_consecutive_failures": 5,  # Max failures before giving up in recovery attempt
        # Max fallback rows migrated to primary per migrate_fallback() call.
        # Caps the synchronous SD work the health-check loop does in one
        # pass so a backlog of 50+ rows cannot exceed watchdog_timeout_ms;
        # remaining rows drain on subsequent loop iterations.
        "fallback_migrate_batch_max": 20,
    },
    # Software Updater Configuration (SD-payload self-update; see lib/updater.py)
    #
    # Operator drops a payload tree under update_dir on the SD card:
    #   <update_dir>/manifest.json           — {version, files: [{path, sha256, bytes}, ...]}
    #   <update_dir>/main.py                 — replaces /main.py
    #   <update_dir>/config.py               — replaces /config.py
    #   <update_dir>/lib/<file>.py           — replaces /lib/<file>.py
    #
    # On boot, main.py calls run_pending_update() BEFORE EventLogger init.
    # The updater verifies every file (SHA-256) before writing any, retries
    # per-file writes up to max_retries on failure, renames update_dir →
    # applied_dir/<version>/ on success, appends to log_path, then calls
    # machine.reset(). Set enabled=False to skip the boot-time check entirely.
    "updater": {
        "enabled": True,
        "update_dir": "/sd/ota/pending",
        "applied_dir": "/sd/ota/applied",
        "log_path": "/sd/logs/updates.log",
        "log_max_size": 50000,  # Bytes; rotate to <name>_<ts>.log past this
        "max_retries": 3,  # Per-file write retry count on apply failure
        "retry_delay_ms": 200,  # Delay between write retries (ms)
        "verify_max_retries": 3,  # Per-file stat/hash retry count on SD glitch during verify
        "verify_retry_delay_ms": 200,  # Delay between verify retries (ms)
        "allowed_paths": ["main.py", "config.py", "config.mpy", "lib/"],  # Whitelist; anything outside fails verify
        # Legacy update_dir locations checked when the canonical update_dir
        # holds no manifest. Lets payloads dropped at the pre-2026-05-15
        # path (/sd/update) still apply without re-copying. Empty the list
        # to disable the fallback once all field cards are migrated.
        "legacy_update_dirs": ["/sd/update"],
    },
    # Updater Feedback (loading-screen LEDs + buzzer ticks during SD-payload update)
    #
    # LED chase uses status_leds.walk_order to drive a cylon-style sweep across
    # the LED row while verify/apply runs. Buzzer chirps on each per-file step
    # for audible activity. Success/failure play distinct jingles before the
    # post-apply machine.reset(). All values feed lib/updater_feedback.py
    # constructor; the boot-time hook builds the controller from config["pins"]
    # + config["status_leds"]["walk_order"] when enabled=True.
    "updater_feedback": {
        "enabled": True,
        "tick_freq_hz": 1500,  # Per-step buzzer chirp frequency (Hz)
        "tick_duration_ms": 25,  # Per-step buzzer chirp duration (ms)
        "step_delay_ms": 0,  # Min ms between chase steps (0 = bound by work)
        "success_pattern": [  # 3-note rising arpeggio on apply_ok
            (1047, 120, 40),  # C6
            (1319, 120, 40),  # E6
            (1568, 200, 0),  # G6
        ],
        "fail_pattern": [  # Descending 2-note on verify/apply failure
            (400, 200, 80),
            (250, 400, 0),
        ],
        "noop_pattern": [  # Two short blips on "already up to date" no-op
            (880, 80, 60),  # A5
            (880, 80, 0),  # A5
        ],
    },
}


_VALID_FAN_MODES = ("thermostat_schedule", "always_on", "heater_follower")
_VALID_FAN_OUTPUTS = ("relay", "pca9685")


def _validate_fans(fans_cfg, pins_cfg):
    """Validate the role-keyed fans dict (called from validate_config)."""
    if not isinstance(fans_cfg, dict) or not fans_cfg:
        raise ValueError("fans must be a non-empty dict")

    used_relay_keys = set()
    used_pca_channels = set()

    for role, cfg in fans_cfg.items():
        prefix = f"fans.{role}"
        if not isinstance(cfg, dict):
            raise ValueError(f"{prefix} must be a dict")
        for k in ("enabled", "mode", "output"):
            if k not in cfg:
                raise ValueError(f"Missing config key: {prefix}.{k}")
        if not isinstance(cfg["enabled"], bool):
            raise ValueError(f"{prefix}.enabled must be a bool")
        if cfg["mode"] not in _VALID_FAN_MODES:
            raise ValueError(f"{prefix}.mode must be one of {_VALID_FAN_MODES}")
        if cfg["output"] not in _VALID_FAN_OUTPUTS:
            raise ValueError(f"{prefix}.output must be one of {_VALID_FAN_OUTPUTS}")

        if cfg["output"] == "relay":
            if "relay_pin_key" not in cfg:
                raise ValueError(f"Missing config key: {prefix}.relay_pin_key")
            pk = cfg["relay_pin_key"]
            if not isinstance(pk, str) or pk not in pins_cfg:
                raise ValueError(f"{prefix}.relay_pin_key must reference a pin in pins section (got {pk!r})")
            if pk in used_relay_keys:
                raise ValueError(f"{prefix}.relay_pin_key={pk!r} is used by another fan")
            used_relay_keys.add(pk)
        else:  # pca9685
            if "pca9685_ch" not in cfg:
                raise ValueError(f"Missing config key: {prefix}.pca9685_ch")
            ch = cfg["pca9685_ch"]
            if not isinstance(ch, int) or not (0 <= ch <= 15):
                raise ValueError(f"{prefix}.pca9685_ch must be int 0-15")
            if ch in used_pca_channels:
                raise ValueError(f"{prefix}.pca9685_ch={ch} is used by another fan")
            used_pca_channels.add(ch)

        mode = cfg["mode"]
        if mode == "thermostat_schedule":
            required = (
                "interval_s",
                "on_time_s",
                "max_temp",
                "temp_hysteresis",
                "poll_interval_s",
                "default_duty_pct",
            )
            for k in required:
                if k not in cfg:
                    raise ValueError(f"Missing config key: {prefix}.{k}")
            if cfg["interval_s"] <= 0 or cfg["on_time_s"] <= 0:
                raise ValueError(f"{prefix}: interval_s and on_time_s must be > 0")
            if cfg["temp_hysteresis"] < 0:
                raise ValueError(f"{prefix}.temp_hysteresis must be >= 0")
            if cfg["poll_interval_s"] <= 0:
                raise ValueError(f"{prefix}.poll_interval_s must be > 0")
            v = cfg["default_duty_pct"]
            if not isinstance(v, (int, float)) or not (0 <= v <= 100):
                raise ValueError(f"{prefix}.default_duty_pct must be 0-100")
        elif mode == "always_on":
            for k in ("duty_pct", "refresh_interval_s"):
                if k not in cfg:
                    raise ValueError(f"Missing config key: {prefix}.{k}")
            v = cfg["duty_pct"]
            if not isinstance(v, (int, float)) or not (0 <= v <= 100):
                raise ValueError(f"{prefix}.duty_pct must be 0-100")
            if cfg["refresh_interval_s"] <= 0:
                raise ValueError(f"{prefix}.refresh_interval_s must be > 0")
        else:  # heater_follower
            for k in ("post_run_s", "duty_pct", "poll_interval_s"):
                if k not in cfg:
                    raise ValueError(f"Missing config key: {prefix}.{k}")
            if cfg["post_run_s"] < 0:
                raise ValueError(f"{prefix}.post_run_s must be >= 0")
            v = cfg["duty_pct"]
            if not isinstance(v, (int, float)) or not (0 <= v <= 100):
                raise ValueError(f"{prefix}.duty_pct must be 0-100")
            if cfg["poll_interval_s"] <= 0:
                raise ValueError(f"{prefix}.poll_interval_s must be > 0")


def validate_config():
    """
    Validate configuration dictionary at startup.

    Checks for required keys and reasonable value ranges.
    Raises ValueError with descriptive message if validation fails.

    Returns:
        bool: True if config is valid

    Raises:
        ValueError: If required keys are missing or values out of range
    """
    required_keys = {
        "pins": [
            "activity_led",
            "reminder_led",
            "sd_led",
            "warning_led",
            "error_led",
            "onboard_led",
            "button_menu",
            "button_reserved",
            "rtc_i2c_port",
            "rtc_sda",
            "rtc_scl",
            "relay_fan_1",
            "relay_fan_2",
            "relay_growlight",
            "relay_reserved_1",
            "relay_reserved_2",
            "relay_reserved_3",
            "relay_reserved_4",
            "co2_uart_id",
            "co2_uart_tx",
            "co2_uart_rx",
            "co2_baudrate",
            "buzzer",
            "heater_mosfet",
            "gp2_breakout",
            "adc_input",
        ],
        "spi": ["id", "baudrate", "sck", "mosi", "miso", "cs", "mount_point"],
        "files": ["system_log", "fallback_path"],
        "paths": [
            "sensor_root",
            "logs_dir",
            "ota_pending_dir",
            "ota_applied_dir",
            "diagnostics_dir",
        ],
        "sht31": ["i2c_address"],
        "temp_humidity_logger": ["interval_s", "max_retries", "max_buffer_size", "retry_delay_s", "sensor_type"],
        "pca9685": [
            "enabled",
            "i2c_address",
            "freq_hz",
        ],
        "heater": [
            "day_min_temp",
            "night_min_temp",
            "temp_hysteresis",
            "day_offset_min",
            "night_offset_min",
            "max_stale_reads",
            "poll_interval_s",
        ],
        "co2_logger": [
            "interval_s",
            "warmup_s",
            "max_retries",
            "override_ppm_on",
            "override_ppm_off",
            "override_fan",
            "sensor_type",
        ],
        "soil_logger": [
            "interval_s",
            "adc_dry_raw",
            "adc_wet_raw",
            "warn_pct_below",
            "sensor_type",
        ],
        "growlight": [
            "mode",
            "dawn_hour",
            "dawn_minute",
            "sunset_hour",
            "sunset_minute",
            "poll_interval_s",
            "dac_i2c_address",
            "default_level_pct",
            "max_level_pct",
            "min_level_pct",
            "ramp_duration_s",
        ],
        "Service_reminder": [
            "days_interval",
            "blink_pattern_ms",
            "blink_after_days",
            "storage_path",
            "monitor_interval_s",
        ],
        "buzzer": ["enabled", "default_freq", "default_duty_pct"],
        "buffer_manager": ["sd_mount_point", "fallback_path", "max_buffer_entries", "max_fallback_size_kb"],
        "event_logger": [
            "logfile",
            "max_size",
            "debug_max_size",
            "info_flush_threshold",
            "warn_flush_threshold",
            "log_level",
            "debug_enabled",
            "debug_to_file",
            "debug_flush_threshold",
        ],
        "output_pins": [
            "relay_fan_1",
            "relay_fan_2",
            "relay_growlight",
            "relay_reserved_1",
            "relay_reserved_2",
            "relay_reserved_3",
            "relay_reserved_4",
            "activity_led",
            "reminder_led",
            "sd_led",
            "warning_led",
            "error_led",
            "onboard_led",
        ],
        "status_leds": [
            "activity_blink_ms",
            "heartbeat_interval_ms",
            "th_warn_threshold",
            "th_error_threshold",
            "rtc_min_year",
            "rtc_max_year",
            "walk_order",
            "mem_warning_pct",
            "mem_error_pct",
        ],
        "display": [
            "type",
            "width",
            "height",
            "i2c_address",
            "enabled",
            "refresh_interval_s",
            "stats_window_s",
            "max_history",
            "menu_timeout_s",
            "startup_banner_s",
            "vram_clear_delay_s",
            "invert_delay_s",
            "debug",
        ],
        "updater": [
            "enabled",
            "update_dir",
            "applied_dir",
            "log_path",
            "log_max_size",
            "max_retries",
            "retry_delay_ms",
            "verify_max_retries",
            "verify_retry_delay_ms",
            "allowed_paths",
            "legacy_update_dirs",
        ],
        "updater_feedback": [
            "enabled",
            "tick_freq_hz",
            "tick_duration_ms",
            "step_delay_ms",
            "success_pattern",
            "fail_pattern",
            "noop_pattern",
        ],
        "system": [
            "require_sd_startup",
            "sd_fail_reset_s",
            "boot_log_path",
            "boot_log_max_kb",
            "button_debounce_ms",
            "long_press_ms",
            "health_check_interval_s",
            "sd_recovery_interval_s",
            "i2c_freq",
            "sd_power_up_ms",
            "sd_mount_retries",
            "sd_retry_delay_ms",
            "rtc_sync_interval_s",
            "button_poll_ms",
            "watchdog_timeout_ms",
            "watchdog_feed_interval_ms",
            "write_queue_max_size",
            "queue_drain_interval_ms",
            "queue_batch_size",
            "sd_recovery_max_consecutive_failures",
            "fallback_migrate_batch_max",
        ],
    }

    # Check all required sections and keys exist
    for section, keys in required_keys.items():
        if section not in DEVICE_CONFIG:
            raise ValueError(f"Missing config section: {section}")
        for key in keys:
            if key not in DEVICE_CONFIG[section]:
                raise ValueError(f"Missing config key: {section}.{key}")

    if "mode" not in DEVICE_CONFIG:
        raise ValueError("Missing config key: mode")
    if DEVICE_CONFIG["mode"] not in ("plant", "mushroom"):
        raise ValueError("mode must be 'plant' or 'mushroom'")

    # Validate value ranges
    if DEVICE_CONFIG["temp_humidity_logger"]["interval_s"] <= 0:
        raise ValueError("temp_humidity_logger.interval_s must be > 0")

    sht31_addr = DEVICE_CONFIG["sht31"]["i2c_address"]
    if not isinstance(sht31_addr, int) or sht31_addr not in (0x44, 0x45):
        raise ValueError("sht31.i2c_address must be 0x44 or 0x45")

    if DEVICE_CONFIG["Service_reminder"]["days_interval"] <= 0:
        raise ValueError("Service_reminder.days_interval must be > 0")

    if DEVICE_CONFIG["buzzer"]["default_freq"] <= 0:
        raise ValueError("buzzer.default_freq must be > 0")

    if not (0 < DEVICE_CONFIG["buzzer"]["default_duty_pct"] <= 100):
        raise ValueError("buzzer.default_duty_pct must be 1–100")

    if DEVICE_CONFIG["buffer_manager"]["max_buffer_entries"] <= 0:
        raise ValueError("buffer_manager.max_buffer_entries must be > 0")

    if DEVICE_CONFIG["buffer_manager"]["max_fallback_size_kb"] < 10:
        raise ValueError("buffer_manager.max_fallback_size_kb must be >= 10 (KB)")

    if DEVICE_CONFIG["event_logger"]["max_size"] <= 0:
        raise ValueError("event_logger.max_size must be > 0")

    if DEVICE_CONFIG["event_logger"]["debug_max_size"] <= 0:
        raise ValueError("event_logger.debug_max_size must be > 0")

    if DEVICE_CONFIG["event_logger"]["info_flush_threshold"] < 1:
        raise ValueError("event_logger.info_flush_threshold must be >= 1")

    if DEVICE_CONFIG["event_logger"]["warn_flush_threshold"] < 1:
        raise ValueError("event_logger.warn_flush_threshold must be >= 1")

    if DEVICE_CONFIG["event_logger"]["log_level"] not in (
        "DEBUG",
        "INFO",
        "WARN",
        "ERR",
    ):
        raise ValueError("event_logger.log_level must be one of: DEBUG, INFO, WARN, ERR")

    if not isinstance(DEVICE_CONFIG["event_logger"]["debug_enabled"], bool):
        raise ValueError("event_logger.debug_enabled must be a bool")

    if not isinstance(DEVICE_CONFIG["event_logger"]["debug_to_file"], bool):
        raise ValueError("event_logger.debug_to_file must be a bool")

    if DEVICE_CONFIG["event_logger"]["debug_flush_threshold"] < 1:
        raise ValueError("event_logger.debug_flush_threshold must be >= 1")

    if DEVICE_CONFIG["temp_humidity_logger"]["retry_delay_s"] <= 0:
        raise ValueError("temp_humidity_logger.retry_delay_s must be > 0")

    _validate_fans(DEVICE_CONFIG.get("fans"), DEVICE_CONFIG["pins"])

    if DEVICE_CONFIG["growlight"]["poll_interval_s"] <= 0:
        raise ValueError("growlight.poll_interval_s must be > 0")

    pca_cfg = DEVICE_CONFIG["pca9685"]
    if not isinstance(pca_cfg["enabled"], bool):
        raise ValueError("pca9685.enabled must be a bool")
    if not isinstance(pca_cfg["i2c_address"], int) or not (0x08 <= pca_cfg["i2c_address"] <= 0x77):
        raise ValueError("pca9685.i2c_address must be a 7-bit I2C address (0x08-0x77)")
    if not isinstance(pca_cfg["freq_hz"], int) or not (24 <= pca_cfg["freq_hz"] <= 1526):
        raise ValueError("pca9685.freq_hz must be an int 24-1526 (PCA9685 datasheet range)")

    heater_cfg = DEVICE_CONFIG["heater"]
    if heater_cfg["temp_hysteresis"] < 0:
        raise ValueError("heater.temp_hysteresis must be >= 0")
    if heater_cfg["poll_interval_s"] <= 0:
        raise ValueError("heater.poll_interval_s must be > 0")
    if heater_cfg["max_stale_reads"] < 0:
        raise ValueError("heater.max_stale_reads must be >= 0")
    if heater_cfg["day_min_temp"] < heater_cfg["night_min_temp"]:
        raise ValueError("heater.day_min_temp must be >= night_min_temp")

    co2_cfg = DEVICE_CONFIG["co2_logger"]
    if co2_cfg["interval_s"] <= 0:
        raise ValueError("co2_logger.interval_s must be > 0")
    if co2_cfg["warmup_s"] < 0:
        raise ValueError("co2_logger.warmup_s must be >= 0")
    if co2_cfg["max_retries"] < 1:
        raise ValueError("co2_logger.max_retries must be >= 1")
    if co2_cfg["override_ppm_on"] <= co2_cfg["override_ppm_off"]:
        raise ValueError("co2_logger.override_ppm_on must be > override_ppm_off")
    if co2_cfg["override_ppm_off"] < 0:
        raise ValueError("co2_logger.override_ppm_off must be >= 0")
    if co2_cfg["override_fan"] not in DEVICE_CONFIG.get("fans", {}):
        raise ValueError(f"co2_logger.override_fan must be a key in fans dict (got {co2_cfg['override_fan']!r})")
    if not isinstance(co2_cfg["sensor_type"], str) or not co2_cfg["sensor_type"]:
        raise ValueError("co2_logger.sensor_type must be a non-empty string")

    soil_cfg = DEVICE_CONFIG["soil_logger"]
    if soil_cfg["interval_s"] <= 0:
        raise ValueError("soil_logger.interval_s must be > 0")
    if not isinstance(soil_cfg["adc_dry_raw"], int) or not (0 <= soil_cfg["adc_dry_raw"] <= 1023):
        raise ValueError("soil_logger.adc_dry_raw must be an int 0-1023")
    if not isinstance(soil_cfg["adc_wet_raw"], int) or not (0 <= soil_cfg["adc_wet_raw"] <= 1023):
        raise ValueError("soil_logger.adc_wet_raw must be an int 0-1023")
    if soil_cfg["adc_dry_raw"] <= soil_cfg["adc_wet_raw"]:
        raise ValueError("soil_logger.adc_dry_raw must be > adc_wet_raw")
    if not (0 <= soil_cfg["warn_pct_below"] <= 100):
        raise ValueError("soil_logger.warn_pct_below must be 0-100")
    if not isinstance(soil_cfg["sensor_type"], str) or not soil_cfg["sensor_type"]:
        raise ValueError("soil_logger.sensor_type must be a non-empty string")

    disp_cfg = DEVICE_CONFIG["display"]
    for delay_key in ("startup_banner_s", "vram_clear_delay_s", "invert_delay_s"):
        if not isinstance(disp_cfg[delay_key], (int, float)) or disp_cfg[delay_key] < 0:
            raise ValueError(f"display.{delay_key} must be a number >= 0")

    debug_cfg = disp_cfg["debug"]
    debug_required = (
        "enabled",
        "confirm_timeout_s",
        "status_show_ms",
        "feedback_blink_ms",
        "test_heater_s",
        "test_growlight_pulse_s",
        "test_growlight_dim_levels_pct",
        "test_growlight_dim_step_s",
        "test_relay_pulse_s",
    )
    for key in debug_required:
        if key not in debug_cfg:
            raise ValueError(f"Missing config key: display.debug.{key}")
    if not isinstance(debug_cfg["enabled"], bool):
        raise ValueError("display.debug.enabled must be a bool")
    for s_key in (
        "confirm_timeout_s",
        "test_heater_s",
        "test_growlight_pulse_s",
        "test_growlight_dim_step_s",
        "test_relay_pulse_s",
    ):
        v = debug_cfg[s_key]
        if not isinstance(v, (int, float)) or v <= 0:
            raise ValueError(f"display.debug.{s_key} must be > 0")
    if not isinstance(debug_cfg["status_show_ms"], int) or debug_cfg["status_show_ms"] <= 0:
        raise ValueError("display.debug.status_show_ms must be an int > 0")
    blink = debug_cfg["feedback_blink_ms"]
    if not isinstance(blink, list) or not blink or any(not isinstance(x, int) or x < 0 for x in blink):
        raise ValueError("display.debug.feedback_blink_ms must be a non-empty list of ints >= 0")
    levels = debug_cfg["test_growlight_dim_levels_pct"]
    if not isinstance(levels, list) or not levels or any(not isinstance(x, int) or not (0 <= x <= 100) for x in levels):
        raise ValueError("display.debug.test_growlight_dim_levels_pct must be a non-empty list of ints 0-100")

    dac_addr = DEVICE_CONFIG["growlight"]["dac_i2c_address"]
    if not isinstance(dac_addr, int) or not (0x08 <= dac_addr <= 0x77):
        raise ValueError("growlight.dac_i2c_address must be a 7-bit I2C address (0x08-0x77)")

    gl_cfg = DEVICE_CONFIG["growlight"]
    if gl_cfg["mode"] not in ("dimmed", "relay_only"):
        raise ValueError("growlight.mode must be 'dimmed' or 'relay_only'")
    for key in ("default_level_pct", "max_level_pct", "min_level_pct"):
        v = gl_cfg[key]
        if not isinstance(v, (int, float)) or not (0 <= v <= 100):
            raise ValueError(f"growlight.{key} must be 0-100")
    if gl_cfg["min_level_pct"] > gl_cfg["max_level_pct"]:
        raise ValueError("growlight.min_level_pct must be <= max_level_pct")
    if gl_cfg["default_level_pct"] > gl_cfg["max_level_pct"]:
        raise ValueError("growlight.default_level_pct must be <= max_level_pct")
    if gl_cfg["ramp_duration_s"] < 0:
        raise ValueError("growlight.ramp_duration_s must be >= 0")

    if DEVICE_CONFIG["Service_reminder"]["blink_after_days"] < 0:
        raise ValueError("Service_reminder.blink_after_days must be >= 0")

    if DEVICE_CONFIG["Service_reminder"]["monitor_interval_s"] <= 0:
        raise ValueError("Service_reminder.monitor_interval_s must be > 0")

    sys_cfg = DEVICE_CONFIG["system"]
    if sys_cfg["i2c_freq"] <= 0:
        raise ValueError("system.i2c_freq must be > 0")

    if sys_cfg["button_debounce_ms"] < 0:
        raise ValueError("system.button_debounce_ms must be >= 0")

    if sys_cfg["long_press_ms"] <= 0:
        raise ValueError("system.long_press_ms must be > 0")

    if sys_cfg["sd_mount_retries"] < 1:
        raise ValueError("system.sd_mount_retries must be >= 1")

    if not isinstance(sys_cfg["require_sd_startup"], bool):
        raise ValueError("system.require_sd_startup must be a bool")

    if not isinstance(sys_cfg["sd_fail_reset_s"], (int, float)) or sys_cfg["sd_fail_reset_s"] < 1:
        raise ValueError("system.sd_fail_reset_s must be >= 1")

    if not isinstance(sys_cfg["boot_log_path"], str) or not sys_cfg["boot_log_path"].startswith("/"):
        raise ValueError("system.boot_log_path must be an absolute path string")

    if not isinstance(sys_cfg["boot_log_max_kb"], int) or sys_cfg["boot_log_max_kb"] < 1:
        raise ValueError("system.boot_log_max_kb must be an int >= 1")

    if sys_cfg["rtc_sync_interval_s"] <= 0:
        raise ValueError("system.rtc_sync_interval_s must be > 0")

    if sys_cfg["button_poll_ms"] <= 0:
        raise ValueError("system.button_poll_ms must be > 0")

    if sys_cfg["watchdog_timeout_ms"] < 1000 or sys_cfg["watchdog_timeout_ms"] > 8388:
        raise ValueError("system.watchdog_timeout_ms must be 1000-8388 (RP2040 hardware limit)")

    if sys_cfg["watchdog_feed_interval_ms"] <= 0:
        raise ValueError("system.watchdog_feed_interval_ms must be > 0")

    if sys_cfg["watchdog_feed_interval_ms"] >= sys_cfg["watchdog_timeout_ms"]:
        raise ValueError("system.watchdog_feed_interval_ms must be < watchdog_timeout_ms")

    # Validate write queue configuration
    if DEVICE_CONFIG["system"]["write_queue_max_size"] <= 0:
        raise ValueError("system.write_queue_max_size must be > 0")

    if DEVICE_CONFIG["system"]["queue_drain_interval_ms"] <= 0:
        raise ValueError("system.queue_drain_interval_ms must be > 0")

    if DEVICE_CONFIG["system"]["queue_batch_size"] <= 0:
        raise ValueError("system.queue_batch_size must be > 0")

    if DEVICE_CONFIG["system"]["sd_recovery_max_consecutive_failures"] <= 0:
        raise ValueError("system.sd_recovery_max_consecutive_failures must be > 0")

    if DEVICE_CONFIG["system"]["fallback_migrate_batch_max"] <= 0:
        raise ValueError("system.fallback_migrate_batch_max must be > 0")

    # Validate status_leds.walk_order: non-empty list of unique role names
    valid_walk_roles = ("activity", "sd", "reminder", "warning", "error")
    walk = DEVICE_CONFIG["status_leds"]["walk_order"]
    if not isinstance(walk, list) or not walk:
        raise ValueError("status_leds.walk_order must be a non-empty list")
    if len(set(walk)) != len(walk):
        raise ValueError("status_leds.walk_order entries must be unique")
    for role in walk:
        if role not in valid_walk_roles:
            raise ValueError(f"status_leds.walk_order entries must be one of {valid_walk_roles}")

    # Validate paths section: every entry must be a non-empty absolute path.
    # All five live on the SD card, so each must start with the SPI mount
    # point ('/sd' by default) — catches typos like 'sd/sensors' early.
    paths_cfg = DEVICE_CONFIG["paths"]
    sd_mount = DEVICE_CONFIG["spi"]["mount_point"].rstrip("/") or "/sd"
    for path_key in (
        "sensor_root",
        "logs_dir",
        "ota_pending_dir",
        "ota_applied_dir",
        "diagnostics_dir",
    ):
        v = paths_cfg[path_key]
        if not isinstance(v, str) or not v.startswith("/"):
            raise ValueError(f"paths.{path_key} must be an absolute path string")
        if not (v == sd_mount or v.startswith(sd_mount + "/")):
            raise ValueError(f"paths.{path_key} must live under {sd_mount}")

    # Validate updater configuration
    upd_cfg = DEVICE_CONFIG["updater"]
    if not isinstance(upd_cfg["enabled"], bool):
        raise ValueError("updater.enabled must be a bool")
    for path_key in ("update_dir", "applied_dir", "log_path"):
        v = upd_cfg[path_key]
        if not isinstance(v, str) or not v.startswith("/"):
            raise ValueError(f"updater.{path_key} must be an absolute path string")
    if not isinstance(upd_cfg["log_max_size"], int) or upd_cfg["log_max_size"] < 0:
        raise ValueError("updater.log_max_size must be an int >= 0")
    if not isinstance(upd_cfg["max_retries"], int) or upd_cfg["max_retries"] < 1:
        raise ValueError("updater.max_retries must be an int >= 1")
    if not isinstance(upd_cfg["retry_delay_ms"], int) or upd_cfg["retry_delay_ms"] < 0:
        raise ValueError("updater.retry_delay_ms must be an int >= 0")
    if not isinstance(upd_cfg["verify_max_retries"], int) or upd_cfg["verify_max_retries"] < 0:
        raise ValueError("updater.verify_max_retries must be an int >= 0")
    if not isinstance(upd_cfg["verify_retry_delay_ms"], int) or upd_cfg["verify_retry_delay_ms"] < 0:
        raise ValueError("updater.verify_retry_delay_ms must be an int >= 0")
    if not isinstance(upd_cfg["allowed_paths"], list) or not upd_cfg["allowed_paths"]:
        raise ValueError("updater.allowed_paths must be a non-empty list")
    for entry in upd_cfg["allowed_paths"]:
        if not isinstance(entry, str) or not entry:
            raise ValueError("updater.allowed_paths entries must be non-empty strings")
    if not isinstance(upd_cfg["legacy_update_dirs"], list):
        raise ValueError("updater.legacy_update_dirs must be a list")
    for entry in upd_cfg["legacy_update_dirs"]:
        if not isinstance(entry, str) or not entry.startswith("/"):
            raise ValueError("updater.legacy_update_dirs entries must be absolute path strings")

    # Validate updater_feedback configuration
    fb_cfg = DEVICE_CONFIG["updater_feedback"]
    if not isinstance(fb_cfg["enabled"], bool):
        raise ValueError("updater_feedback.enabled must be a bool")
    if not isinstance(fb_cfg["tick_freq_hz"], int) or fb_cfg["tick_freq_hz"] <= 0:
        raise ValueError("updater_feedback.tick_freq_hz must be a positive int")
    if not isinstance(fb_cfg["tick_duration_ms"], int) or fb_cfg["tick_duration_ms"] < 0:
        raise ValueError("updater_feedback.tick_duration_ms must be an int >= 0")
    if not isinstance(fb_cfg["step_delay_ms"], int) or fb_cfg["step_delay_ms"] < 0:
        raise ValueError("updater_feedback.step_delay_ms must be an int >= 0")
    for pattern_key in ("success_pattern", "fail_pattern", "noop_pattern"):
        pat = fb_cfg[pattern_key]
        if not isinstance(pat, list) or not pat:
            raise ValueError(f"updater_feedback.{pattern_key} must be a non-empty list")
        for step in pat:
            if not isinstance(step, (list, tuple)) or len(step) != 3:
                raise ValueError(f"updater_feedback.{pattern_key} entries must be (freq, dur, pause) triples")
            for v in step:
                if not isinstance(v, int) or v < 0:
                    raise ValueError(f"updater_feedback.{pattern_key} entries must contain non-negative ints")

    return True
