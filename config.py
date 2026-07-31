# Pi Greenhouse Configuration
# Dennis Hiro, 2024-06-08
# Ver: InDev1.0
#
# Central configuration for all hardware pins, intervals, file paths, and thresholds.
# Modify values here to tune device behavior without editing module code.
#
# I²C device address map (keep this current — it's the first place to look
# for an address conflict before adding a device):
#
#   I²C0 — shared bus (GP0/GP1, port 0), pulled up via R1/R2:
#     0x3C  SSD1306 OLED display
#     0x40  PCA9685 16-channel PWM fan driver
#     0x44  SHT31-D temperature/humidity sensor (0x45 if ADDR→VCC)
#     0x60  MCP4725 grow-light dimming DAC (plant mode; 0x61 if A0→VCC)
#     0x68  DS3231 RTC
#     (no soil address — the soil sensor is ANALOG on GP28/ADC2, TLC555)
#
#   I²C1 — SEPARATE future bus (hydroponics, not yet wired). These are on
#   a different bus, so do NOT mistake them for I²C0 conflicts:
#     0x63  Atlas EZO-pH
#     0x64  Atlas EZO-EC

# ---------------------------------------------------------------------------
# Regulation matrix — shared parameter schemas
# (see docs/prompts/regulation-matrix.md)
# ---------------------------------------------------------------------------
# Each regulator's 2D hinge surface is defined by this ordered parameter set.
# The engine freezes every surface into an array('f') addressed by the index
# of the name in _SURFACE_PARAMS, so ORDER IS LOAD-BEARING — append new params
# at the end, never reorder. Tuple entries are (name, lo, hi, neutral_default);
# the neutral defaults make an untouched surface a pass-through so a regulator
# only needs to spell out the params it actually tunes.
_SURFACE_PARAMS = (
    # ca/sa started life as cos/sin of a plane rotation and were bounded to
    # [-1, 1] to match. Nothing in regulation_surface.evaluate() requires unit
    # norm: they are a weight PAIR that multiplies gain (and cross), so scaling
    # both by k is identical to scaling gain and cross by k. The tuning explorer
    # authors them freely, and clamping its export would silently change a
    # tuning, so the bound now matches the other coupling params.
    ("ca", -100.0, 100.0, 1.0),  # x weight of the linear plane (was cos(angle))
    ("sa", -100.0, 100.0, 0.0),  # y weight of the linear plane (was sin(angle))
    ("cross", -100.0, 100.0, 0.0),  # cross-axis coupling
    ("gain", -100.0, 100.0, 0.0),  # linear bandwidth (slope of the plane)
    ("offset", -1000.0, 1000.0, 0.0),  # shift
    ("hx_hi1", -100.0, 100.0, 0.0),  # x-high hinge 1 slope
    ("bx_hi1", -200.0, 200.0, 50.0),  # x-high hinge 1 breakpoint
    ("hx_hi2", -100.0, 100.0, 0.0),
    ("bx_hi2", -200.0, 200.0, 50.0),
    ("hx_lo1", -100.0, 100.0, 0.0),  # x-low hinge 1 slope
    ("bx_lo1", -200.0, 200.0, 50.0),
    ("hx_lo2", -100.0, 100.0, 0.0),
    ("bx_lo2", -200.0, 200.0, 50.0),
    ("hy_hi1", -100.0, 100.0, 0.0),  # y-high hinge 1 slope
    ("by_hi1", -200.0, 200.0, 50.0),
    ("hy_hi2", -100.0, 100.0, 0.0),
    ("by_hi2", -200.0, 200.0, 50.0),
    ("hy_lo1", -100.0, 100.0, 0.0),  # y-low hinge 1 slope
    ("by_lo1", -200.0, 200.0, 50.0),
    ("hy_lo2", -100.0, 100.0, 0.0),
    ("by_lo2", -200.0, 200.0, 50.0),
    ("x_top", -200.0, 200.0, 200.0),  # boost upper edge on x (neutral = out of range)
    ("x_bot", -200.0, 200.0, -100.0),  # boost lower edge on x
    ("y_top", -200.0, 200.0, 200.0),
    ("y_bot", -200.0, 200.0, -100.0),
    ("boost_base", 0.0, 100.0, 1.0),  # boost value inside the deadband
    ("grad", -100.0, 100.0, 0.0),  # boost gradient beyond the edges
    ("mult", -100.0, 100.0, 1.0),  # overall multiplier
    ("out_min", -1000.0, 1000.0, 0.0),  # clamp lo (also rescale floor)
    ("out_max", -1000.0, 1000.0, 100.0),  # clamp hi (also rescale ceil)
)
_SURFACE_PARAM_NAMES = tuple(p[0] for p in _SURFACE_PARAMS)

# Deviation dimensions and the ordered regulator (command-vector) names. The
# arbiter's target vector T[] is indexed by _REG_NAMES order — also load-bearing.
_REG_DIMENSIONS = ("temp", "humidity", "co2")
# Escalation CAUSES: one per dimension per direction, in the order the arbiter
# bit-indexes them (dim_index * 2, +1 for the low side). These name which
# deviation direction fired an emergency/latch, so a regulator can respond
# differently to "too hot" than to "too wet" — forcing the heater off is
# correct for the first and actively harmful for the second.
_REG_CAUSES = tuple("{}_{}".format(d, side) for d in _REG_DIMENSIONS for side in ("high", "low"))
_REG_NAMES = (
    "heater",
    "heater_follower",
    "cooler",
    "humidifier",
    "exhaust",
    "circulation",
    "growlight",
)
# Physical-unit anchor keys for one dimension in one phase (strictly ascending).
_ANCHOR_KEYS = ("at_0", "at_50", "at_100")
# Category → top-level mode consistency map (regulation profile must match).
_REG_CATEGORY_MODE = {"mushroom": "mushroom", "plant": "plant"}


def _surface(**over):
    """Build a full surface-param dict from neutral defaults + overrides.

    Overriding an unknown key raises at import so a typo in DEVICE_CONFIG fails
    loudly instead of silently doing nothing.
    """
    surface = {name: default for name, _lo, _hi, default in _SURFACE_PARAMS}
    for key, value in over.items():
        if key not in surface:
            raise KeyError("unknown surface param: {!r}".format(key))
        surface[key] = float(value)
    return surface


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
    # idle objects holding RAM. The active regulation.profile's category
    # must match this mode (validated at boot).
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
    #   GP15:      SD card-detect (DET) input from SD_CON (Adafruit 4682 CD
    #              switch; formerly DHT22 data, freed when SHT31 moved to I2C0)
    #   GP16:      UART0 TX → CO2 sensor (via R9 to CO2_CON pin 4)
    #   GP17:      UART0 RX ← CO2 sensor (via R11 from CO2_CON pin 3)
    #   GP18:      Relay 1 — cooler     (REL_CON pin 2, ex fan 1)
    #   GP19:      Relay 2 — humidifier (REL_CON pin 3, ex fan 2)
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
        # SD card-detect (DET) input — Adafruit 4682 CD switch on SD_CON
        "sd_detect": 15,  # GP15 — SD card-detect input (see sd_detect block)
        # CO2 sensor (UART0 with series resistors R9/R11)
        "co2_uart_id": 0,  # UART0
        "co2_uart_tx": 16,  # GP16 — UART0 TX → CO2_CON pin 4 (via R9)
        "co2_uart_rx": 17,  # GP17 — UART0 RX ← CO2_CON pin 3 (via R11)
        "co2_baudrate": 9600,
        # Relays (REL_CON pins 2-8 → 7 GPIO control lines)
        "relay_cooler": 18,  # GP18 — Cooler relay (REL_CON pin 2, ex fan 1)
        "relay_humidifier": 19,  # GP19 — Humidifier relay (REL_CON pin 3, ex fan 2)
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
    # SPI Configuration (SD Card via SD_CON; MOSI via R10, MISO via R8 = 33 Ω)
    #
    # baudrate: a field run on 2026-05-16/18 produced 32× `SD status
    # changed: FAILED` over 42 h. R8 (the 33 Ω series damper on the MISO
    # line, GP12 ↔ SD_CON pin 3) was suspected at the time, but the root
    # cause was VSYS starvation from the 1N4002 input diodes (chat-log
    # 2026-05-19). R8 STAYS on the next-rev PCB as a useful SPI signal
    # damper at 10 MHz (chat-log 2026-05-23 "keep R8 = 33 Ω; fix the
    # firmware comment instead"). The actual SD-init reliability fix is a
    # 10 kΩ pull-up from SPI_RX (GP12/MISO) → 3V3, queued under the SD
    # card module entry in docs/hardware/next-revision.md. Baudrate stays
    # at 10 MHz until a bench run on the new board confirms higher is
    # safe; bandwidth is not the bottleneck (CSV rows are ~30 bytes).
    "spi": {
        "id": 1,
        "baudrate": 10000000,
        "sck": 10,  # GP10 → SD_CON.SCK
        "mosi": 11,  # GP11 → R10 → SD_CON.MOSI
        "miso": 12,  # GP12 → SD_CON.MISO (via R8 = 33 Ω damper; + 10 kΩ pull-up to 3V3 next-rev)
        "cs": 13,  # GP13 → SD_CON.CS
        "mount_point": "/sd",
    },
    # SD card-detect (DET) — Adafruit 4682 breakout card-detect switch.
    #
    # Field-observed polarity (2026-06-30 bring-up, system.log): with the
    # internal pull-up, GP15 reads HIGH with a card seated and LOW with the
    # slot empty — i.e. the CD switch shorts to GND when EMPTY and opens when
    # a card is inserted, so present_when_low=False (present = GP15 HIGH).
    # The earlier ASSUMED present_when_low=True made the health loop report
    # no_card_inserted ~60 s after every clean boot; see chat-log 2026-06-30.
    # Polarity + pull stay configurable because they are board-specific.
    #
    # When enabled=False the DET line is ignored and SD hot-swap recovery
    # falls back to the pre-DET poll-only behavior — HardwareFactory.
    # is_card_present() then always reports True, so the health loop keeps
    # probing the bus the way it did before DET was wired.
    "sd_detect": {
        "enabled": True,
        "present_when_low": False,  # GP15 HIGH = card seated (field-observed 2026-06-30)
        "pull": "up",  # internal pull on the DET input: "up" | "down" | "none"
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
    # Only fans OUTSIDE the RegulationEngine pipeline live here. The
    # regulated fans (exhaust ch4, circulation center ch0 / walls ch1,
    # heater follower ch2) are engine actuators configured under
    # regulation.regulators.*.adapter — do not re-add them here or the
    # channel would be claimed twice.
    #
    # pca9685_ch is the BENCH-CONFIRMED physical map (2026-07-05 fan
    # bring-up, re-run): ch0=growroom_center, ch1=growroom_walls,
    # ch2=heater_distribution, ch3=case, ch4=exhaust. Do not "tidy" channel
    # numbers without re-running the bring-up fan check.
    #
    # Modes:
    #   always_on — constant duty (AlwaysOnFanController). Needs duty_pct,
    #               refresh_interval_s.
    #
    # Outputs:
    #   relay    — wraps a RelayController on the pin named by
    #              relay_pin_key (must reference DEVICE_CONFIG["pins"]).
    #   pca9685  — drives PCA9685 channel pca9685_ch (0..15).
    "fans": {
        "case": {
            "enabled": True,
            "mode": "always_on",
            "output": "pca9685",
            "pca9685_ch": 3,
            "duty_pct": 60,
            "refresh_interval_s": 300,
        },
    },
    # PCA9685 PWM driver (16-channel I2C, shared I2C0 bus).
    #
    # Drives IRLZ44N MOSFET gates for variable-speed fan control on the
    # next-rev PCB (see lib/pca9685.py, lib/fan_output.py). Enabled now
    # that the chip is on the board and all five fans run from ch0–ch4.
    # If the chip is absent, _init_pca9685() records the error and leaves
    # get_pca9685() == None, and every pca9685-backed fan is skipped at
    # boot — so do NOT enable this without the chip present or cooling
    # stops (no relay fallback once the roster is all-PCA9685).
    #
    # i2c_address: A5..A0 strap pins on the PCA9685 select 0x40..0x7F;
    # 0x40 is the default with all straps tied LOW.
    # freq_hz: shared across all 16 channels per datasheet, 24..1526 Hz.
    # Set to 60 Hz on 2026-07-28 as an audible-noise trial, SUPERSEDING the
    # 2026-07-06 "run at the 1526 Hz ceiling" plan in
    # docs/hardware/next-revision.md. Since the fan MOSFET moved into the
    # motor's ground return, this frequency is the chopping rate of the fan's
    # own supply current, so the motor radiates a tone at exactly this pitch.
    # The PCA9685 is an LED driver and cannot reach the ~25 kHz that makes fan
    # PWM inaudible, so the only choice is WHICH audible tone: 1000-1526 Hz
    # sits near the ear's most sensitive band (a whine), while 60 Hz drops
    # below it (a low drone). 60 Hz costs torque smoothness — at low duty the
    # rotor coasts up to ~16 ms between pulses, so the minimum duty at which a
    # fan STARTS from rest can rise. The regulation fan floors were
    # characterised at 1000 Hz and must be re-checked here (hw-test-log
    # FAN.Q). Revert to 1000 if a fan will not start at its configured floor.
    # invert: the next-rev fan/solenoid MOSFET gate stage is inverting —
    # bench (2026-07-05) showed a PWM ramp-DOWN spun the fans UP and duty 0
    # never fully stopped them, i.e. fan speed tracks (100 - duty). True
    # makes lib/pca9685.py map set_duty(pct) -> 100-pct so on/off/ramp read
    # right everywhere (main.py fan control AND the bring-up runner). Applies
    # to every channel; the solenoid stage (future ch5) shares the wiring.
    "pca9685": {
        "enabled": True,
        "i2c_address": 0x40,
        "freq_hz": 60,
        "invert": False,
    },
    # Soil Moisture Logger Configuration (GP28 / ADC2, single-probe)
    #
    # NOTE (2026-06-29): the dead NE555 capacitive probe is replaced by a
    # TLC555-class CMOS sensor (TLC555 / 7555 / ICM7555 / LMC555) — a
    # HARDWARE-ONLY swap. The earlier Adafruit STEMMA #4026 I²C plan is
    # deferred (chat-log 2026-06-29); the analog ADC path stays. Firmware
    # impact is ZERO code change: `adc_input: 28`, lib/soil_logger.py, and
    # the `adc_dry_raw > adc_wet_raw` convention already match a capacitive
    # sensor (dry = high AOUT = high raw). The only firmware action is a
    # bench recalibration of adc_dry_raw / adc_wet_raw once the TLC555 unit
    # is fitted — the 850/350 defaults below are NE555-era placeholders and
    # the 3V3 TLC555 range will differ. Wiring: VCC → 3V3 (Pico pin 36, NOT
    # 5 V and NOT ADC_VREF pin 35), AOUT → GP28, no divider. See
    # docs/hardware/next-revision.md "Soil moisture sensor".
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
    # The override_ppm thresholds drive the logger's is_override_active()
    # advisory flag (shown on the OLED CO2 page); actual venting is the
    # RegulationEngine's job via the CO2 deviation dimension.
    "co2_logger": {
        "interval_s": 30,  # Poll cadence (seconds)
        "warmup_s": 30,  # Sensor warm-up window where read failures don't escalate
        "max_retries": 3,  # UART read retries per poll
        "override_ppm_on": 2500,  # Trip threshold (ppm)
        "override_ppm_off": 2200,  # Release threshold (ppm), must be < on
        "sensor_type": "co2",  # Folder + filename prefix under paths.sensor_root
    },
    # Grow light schedule + dimming live under regulation.regulators.growlight
    # (tod-driven, MCP4725 via adapter dac_i2c_address/dac_max_pct).
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
        "sd_fault_blink_ms": 500,  # SD LED toggle period while SD mount_failed (ms)
        "th_warn_threshold": 3,  # Consecutive T/H read failures → warning
        "th_error_threshold": 10,  # Consecutive T/H read failures → error
        "rtc_min_year": 2025,  # Year below this → RTC invalid warning
        "rtc_max_year": 2035,  # Year above this → RTC invalid warning
        "post_enabled": True,  # Run LED power-on self-test at startup
        "post_step_ms": 150,  # Duration each LED stays on during POST walk (ms)
        "walk_order": ["activity", "sd", "reminder", "warning", "error"],
        "mem_warning_pct": 85,  # RAM usage % above this → warning LED
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
        # Rotate the active log when it crosses this size. Kept small on purpose:
        # every rotation is now an atomic os.rename (O(1)), so the active log
        # stays tiny and rotation never blocks the async watchdog feed. (The old
        # 1 MB cap let system.log grow for days, then the rotation copy of a ~1 MB
        # file starved the 8 s WDT -> bootloop; see docs/notes/chat-log 2026-07-20.)
        "max_size": 131072,  # 128 KB — max active-log size (bytes) before rotation
        "info_flush_threshold": 5,  # Flush after N info-level entries buffered
        "warn_flush_threshold": 1,  # Flush after N warning-level entries (1=immediate, like ERROR)
        "log_level": "INFO",  # Minimum severity: DEBUG, INFO, WARN, ERR
        "debug_enabled": False,  # Enable DEBUG messages to console (hot loops guard on logger.debug_enabled)
        "debug_to_file": False,  # Also write DEBUG entries to SD log (caution: fills card)
        "debug_flush_threshold": 10,  # Flush after N debug entries buffered (when debug_to_file=True)
        "debug_max_size": 65536,  # 64 KB — rotation threshold when debug_to_file=True (debug spam fills faster)
        # Retention: keep archives from the most recent N distinct log-dates and
        # delete older ones after each rotation. Bounds the file count in /sd/logs
        # so a rotation storm can never accumulate thousands of files again.
        "log_retention_days": 30,
    },
    # Diagnostics / instrumentation toggles
    #
    # mem_trend_log: when True, the health loop writes one greppable INFO
    # "mem trend" line per cycle (pre/post-GC heap, reclaimed churn, task
    # count, buffer + write-queue depth) to system.log. Persists WITHOUT
    # enabling event_logger.debug_to_file, so a headless greenhouse records
    # the slow climb toward mem_warning_pct for offline diagnosis. Default
    # off — it adds one INFO line every health_check_interval_s.
    # metrics_log: when True, the health loop appends one row per cycle to a
    # daily metrics CSV on the SD card (RAM free/alloc/used%, regulation
    # tick-timing, buffer/write-queue/task depth, and the engine's severity /
    # band / latch / commanded actuator vector). Charts like the th/co2/soil
    # logs so a soak run can prove the regulation engine runs smoothly.
    # OFF by default: the ~25-column row and its snapshot dict pushed steady
    # heap from ~81% to 91.3% (over the 90% mem_error threshold) on the
    # 2026-07-19 build, leaving no headroom for the I2C error path. Turn on
    # explicitly for a soak run once heap has margin.
    "diagnostics": {
        "mem_trend_log": True,
        "metrics_log": True,
    },
    # Memory management (MicroPython gc tuning)
    #
    # gc_threshold_b: when > 0, main() calls gc.threshold(gc_threshold_b) at
    # boot so the runtime auto-collects after this many bytes are allocated
    # since the last collection — not only on OOM. Curbs the pre-GC
    # allocation peaks (the 2026-07-03 bench run saw them reach ~99% of the
    # ~245 KB heap) and the fragmentation behind cold-boot framebuffer alloc
    # failures. ~24 KB ≈ half the steady-state free heap (~2 collects per
    # 60 s churn window); tune against the mem_trend_log output. Set to -1 to
    # keep MicroPython's default (collect-on-OOM only). No-op on CPython.
    "memory": {
        "gc_threshold_b": 24000,
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
        # Consecutive render (I2C) failures before the OLED self-disables at
        # runtime, so a dead/marginal display can never keep hammering the
        # shared bus or starve the watchdog (2026-07-19 bootloop guard). The
        # boot-time `enabled` flag remains the hard off-switch.
        "max_render_errors": 5,
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
        "relay_cooler": True,  # HIGH = off (relay module inverted logic)
        "relay_humidifier": True,  # HIGH = off (relay module inverted logic)
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
        # I2C bus frequency (Hz). Dropped 400k->100k after the 2026-07-19
        # bootloop: at 400 kHz the shared bus's 10k pull-ups give marginal
        # rise times with 7+ devices, so short transfers passed but the 1 KB
        # OLED framebuffer render timed out (ETIMEDOUT). 100 kHz restores
        # margin with the existing pull-ups; raise back to 400000 only once
        # the pull-ups are reworked (see docs/hardware/next-revision.md).
        "i2c_freq": 100000,
        # Shared-I2C fault resilience (RecoverableI2C, lib/i2c_guard.py).
        "i2c_use_soft": True,  # Use machine.SoftI2C (bounded timeout + recoverable); False = raw hardware I2C
        "i2c_timeout_us": 50000,  # Per-transfer SoftI2C timeout (us); bounds a stuck-bus block well under the watchdog
        "i2c_recover_on_error": True,  # On OSError, unstick the bus (pulse SCL) + rebuild + retry once
        "i2c_recover_clocks": 9,  # SCL pulses to clock a wedged slave out (9 = one byte + ACK)
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
        # Refuse payloads whose manifest declares an "mpy_abi" that the running
        # firmware cannot import. A .mpy file is only loadable by the bytecode
        # ABI its mpy-cross targeted; a mismatched payload passes SHA-256
        # (integrity, not compatibility), applies, resets, and then fails every
        # import on the next boot. With this True the mismatch is a logged
        # verify_fail and live code is never touched. Manifests with no
        # "mpy_abi" key (raw-.py payloads, and every payload built before this
        # existed) are unaffected — they recompile on-device. Set False only to
        # force a payload through when you know the ABI stamp is wrong.
        "enforce_mpy_abi": True,
        # After a successful apply, delete files under the allowed_paths roots
        # that this payload did not ship. Without it flash is strictly additive:
        # a lib/<mod>.mpy left over from a pre-freeze deploy keeps shadowing its
        # frozen twin forever (imports resolve lib-first), so the freeze buys
        # nothing for that module and nothing warns you. The sweep only ever
        # deletes inside allowed_paths, only .py/.mpy, and only when the frozen
        # fw_info.FROZEN_MODULES proves the firmware carries a replacement —
        # except for same-stem twins of a shipped file (config.py next to a
        # shipped config.mpy), which are safe to drop regardless. Set False to
        # keep the pre-2026-07-28 additive behaviour.
        "prune_stale": True,
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
    # Regulation matrix (3.5-D situation→reaction engine).
    #
    # One config-driven pipeline replaces the per-device fan thermostat/
    # schedule, heater cycle, CO2 override, and growlight scheduler. Read
    # docs/prompts/regulation-matrix.md for the full model. Consumed DI-only:
    # main.py reads this dict and passes plain values into the engine; no
    # lib/ module imports DEVICE_CONFIG.
    #
    # enabled=True since the actuator wiring swap: main.py builds the adapter
    # stack from this block and the engine owns every regulated actuator.
    # Setting False leaves only the case fan and sensor loggers running.
    "regulation": {
        "enabled": True,
        "tick_s": 30,  # Evaluation cadence (seconds)
        # Active species profile — must exist in profiles below AND its
        # category must match the top-level mode (mushroom↔mushroom, plant↔plant).
        "profile": "cubensis",
        # Severity band edges (strictly ascending, last = 50):
        # perfect / ideal / organic / minor / major / emergency / shutdown.
        "band_edges": [5, 10, 20, 30, 40, 50],
        # Time-of-day blend (minutes since midnight). b=1 full day, b=0 full
        # night, linear ramp of width transition_min on each edge.
        "day_start_min": 420,  # 07:00
        "day_end_min": 1140,  # 19:00
        "transition_min": 30,
        # Optional external SHT31 (gates exhaust effectiveness only). When
        # disabled the multiplier is a constant 1.0. full_delta = outside must
        # be cooler/drier by this much for full effect; min_factor = floor when
        # outside is as warm/humid or worse.
        "external_sensor": {
            "enabled": False,
            "i2c_address": 0x45,
            "full_delta_c": 3.0,
            "min_factor": 0.2,
            "full_delta_rh": 10.0,
            "min_factor_rh": 0.4,
        },
        # Escalation gating — which deviation DIRECTIONS may escalate to the
        # forced emergency / latch vectors.
        #
        # Severity is |d-50| and therefore saturates at 50 the moment a reading
        # passes an outer anchor. A freshly set-up tent legitimately starts far
        # from ideal (dry air, stale CO2), so ungated escalation latched the
        # system into the safe-state vector on the first tick — with the very
        # actuators that would fix it (humidifier, heater) forced off, so the
        # severity could never fall back under release_max. Deadlock; see
        # docs/notes/chat-log.md 2026-07-21.
        #
        # Only the hazardous HIGH side escalates: too hot cooks the culture and
        # too wet invites bacterial blotch, and both run away without
        # intervention. Too dry / too cold / any CO2 level are correctable
        # conditions the surfaces drive toward ideal on their own — that is the
        # normal startup case, not an emergency. Floors, conflict rules and the
        # surfaces all still see the full ungated severity.
        "escalation": {
            "temp": {"high": True, "low": False},
            "humidity": {"high": True, "low": False},
            "co2": {"high": False, "low": False},
        },
        # Latch (escalating severity == 50): hold the safe-state vector until
        # ALL severities <= release_max for release_ticks consecutive ticks AND
        # min_s elapsed. enter_ticks requires the latch condition to persist
        # that many consecutive ticks before it fires, so one bad sensor read or
        # a door-open transient cannot shut the system down.
        "latch": {
            "enter_ticks": 3,
            "release_max": 30,
            "release_ticks": 3,
            "min_s": 300,
        },
        # Species profiles. Each dimension has three physical-unit anchors per
        # phase: at_0 (deviation 0 = far too low), at_50 (ideal), at_100 (far
        # too high). Strictly ascending; asymmetric spacing = strict vs loose.
        # Tune these first — they set what "50 = ideal" means per organism.
        "profiles": {
            # --- Mushrooms (fruiting chamber: high RH, low CO2, small day/night swing) ---
            # cubensis = the FRUITING phase. Fruiting bodies need continuous
            # fresh-air exchange: much above ~1000 ppm pins abort and stems
            # stretch, so at_50 sits far below the inoculation / colonization
            # figures (where several thousand ppm is desirable — add a separate
            # profile when that phase gets automated). CO2 keeps the same
            # at_50 day and night; a fruiting chamber has no night-time CO2
            # tolerance the way a plant tent does.
            #
            # The mushroom CO2 anchors are deliberately WIDE either side of that
            # ideal, because deviation saturates at the outer anchor and a
            # saturated dimension pins global severity at 50 — the top band —
            # for a condition the room cannot leave. Room air here runs 500 ppm
            # on a good day and 1300 ppm on a bad one, and outdoor air is ~420,
            # so the old 400/1200 envelope reported the normal indoor range as
            # maximum deviation in both directions. at_100 = 2000 puts full
            # severity where a fruiting chamber genuinely is in trouble; at_0 =
            # 0 means low CO2 never registers as a fault, which is correct —
            # there is no such thing as too much fresh air for a fruiting body.
            #
            # Night runs deliberately cooler than day: ideal temp drops 3 C
            # (24 -> 21) rather than tracking day, because the dark phase is
            # where the cool/humid shift that favours pinning is cheapest to
            # hold — no lamp load fighting the cooler.
            #
            # HUMIDITY at_100 IS DELIBERATELY UNREACHABLE (102 %RH), and that is
            # the point of the anchor rather than an off-by-something.
            # Deviation saturates at the outer anchor, and a saturated dimension
            # pins severity at 50 — the latch edge. With at_100 = 100 %RH that
            # ceiling sat on a reading the tent reaches routinely: a saturated
            # chamber scored maximum severity, fired emergency + latch, and the
            # safe-state vector then forced the heater to 0. Heater off cooled
            # the tent, colder air raised RH further at unchanged absolute
            # moisture, severity stayed pinned, and the latch release
            # (emax <= 30) became unreachable — a closed loop the firmware could
            # not exit. It held that way for 12.3 h on 2026-07-30/31, with the
            # grow light dark for ~19 h (docs/notes/chat-log.md 2026-07-31).
            #
            # 102 is chosen TIGHTLY, not generously. Saturation now scores
            # deviation 85.7 / severity 35.7: past the conflict edge (30) so the
            # mold-risk rule still arms and the exhaust still saturates at 100,
            # but short of the emergency edge (40) so RH can never again be the
            # dimension that latches the system. A looser 105 was tried first
            # and rejected — it drops saturation to severity 25, which halves
            # the exhaust (100 -> 57.5) and the circulation (100 -> 44) at
            # exactly the condition they exist to correct, and demotes a
            # saturated tent to the "organic" band where it reads as normal.
            #
            # at_50 = 95 %RH is the operator's fruiting target. The KPI +-10
            # band is therefore RH 91.0-96.4, which is where a fruiting chamber
            # actually lives. Day and night share it. TWO other things are
            # calibrated against this ideal and had to move with it: the
            # humidifier ramp (regulators.humidifier) and the mold-risk conflict
            # rule's humidity threshold (see conflicts, below).
            "cubensis": {
                "category": "mushroom",
                "day": {
                    "temp": {"at_0": 16.0, "at_50": 24.0, "at_100": 30.0},
                    "humidity": {"at_0": 75.0, "at_50": 95.0, "at_100": 102.0},
                    "co2": {"at_0": 0.0, "at_50": 600.0, "at_100": 2000.0},
                },
                "night": {
                    "temp": {"at_0": 15.0, "at_50": 21.0, "at_100": 29.0},
                    "humidity": {"at_0": 75.0, "at_50": 95.0, "at_100": 102.0},
                    "co2": {"at_0": 0.0, "at_50": 600.0, "at_100": 2000.0},
                },
            },
            "oyster": {
                "category": "mushroom",
                "day": {
                    "temp": {"at_0": 10.0, "at_50": 18.0, "at_100": 26.0},
                    "humidity": {"at_0": 70.0, "at_50": 87.0, "at_100": 98.0},
                    "co2": {"at_0": 0.0, "at_50": 600.0, "at_100": 2000.0},
                },
                "night": {
                    "temp": {"at_0": 10.0, "at_50": 17.0, "at_100": 25.0},
                    "humidity": {"at_0": 70.0, "at_50": 87.0, "at_100": 98.0},
                    "co2": {"at_0": 0.0, "at_50": 700.0, "at_100": 2000.0},
                },
            },
            "lions_mane": {
                "category": "mushroom",
                "day": {
                    "temp": {"at_0": 12.0, "at_50": 20.0, "at_100": 28.0},
                    "humidity": {"at_0": 80.0, "at_50": 92.0, "at_100": 100.0},
                    "co2": {"at_0": 0.0, "at_50": 700.0, "at_100": 2000.0},
                },
                "night": {
                    "temp": {"at_0": 12.0, "at_50": 19.0, "at_100": 27.0},
                    "humidity": {"at_0": 80.0, "at_50": 92.0, "at_100": 100.0},
                    "co2": {"at_0": 0.0, "at_50": 800.0, "at_100": 2000.0},
                },
            },
            # --- Plants (wider day/night swing, moderate RH, CO2 enrichment tolerated) ---
            "seedling": {
                "category": "plant",
                "day": {
                    "temp": {"at_0": 16.0, "at_50": 24.0, "at_100": 32.0},
                    "humidity": {"at_0": 50.0, "at_50": 70.0, "at_100": 95.0},
                    "co2": {"at_0": 350.0, "at_50": 800.0, "at_100": 1600.0},
                },
                "night": {
                    "temp": {"at_0": 14.0, "at_50": 20.0, "at_100": 28.0},
                    "humidity": {"at_0": 50.0, "at_50": 70.0, "at_100": 95.0},
                    "co2": {"at_0": 350.0, "at_50": 800.0, "at_100": 1600.0},
                },
            },
            "cannabis": {
                "category": "plant",
                "day": {
                    "temp": {"at_0": 18.0, "at_50": 26.0, "at_100": 32.0},
                    "humidity": {"at_0": 35.0, "at_50": 55.0, "at_100": 75.0},
                    "co2": {"at_0": 400.0, "at_50": 1000.0, "at_100": 1600.0},
                },
                "night": {
                    "temp": {"at_0": 15.0, "at_50": 20.0, "at_100": 28.0},
                    "humidity": {"at_0": 35.0, "at_50": 55.0, "at_100": 75.0},
                    "co2": {"at_0": 400.0, "at_50": 800.0, "at_100": 1400.0},
                },
            },
            "bellpepper": {
                "category": "plant",
                "day": {
                    "temp": {"at_0": 16.0, "at_50": 24.0, "at_100": 32.0},
                    "humidity": {"at_0": 45.0, "at_50": 65.0, "at_100": 85.0},
                    "co2": {"at_0": 400.0, "at_50": 800.0, "at_100": 1500.0},
                },
                "night": {
                    "temp": {"at_0": 12.0, "at_50": 18.0, "at_100": 26.0},
                    "humidity": {"at_0": 45.0, "at_50": 65.0, "at_100": 85.0},
                    "co2": {"at_0": 400.0, "at_50": 800.0, "at_100": 1500.0},
                },
            },
        },
        # Regulators (command-vector slots). driven: "surface" evaluates the
        # 2D hinge surface over dims=[x,y]; "follower" derives from the heater
        # command; "tod" is driven by the time-of-day blend (growlight).
        # slew_normal/_fast bound the per-tick delta of the ORGANIC output;
        # floor/emergency_value/safe_state are forced values applied AFTER slew.
        #
        # Relay pin_keys reference the freed fan-relay channels (fans moved to
        # PCA9685): cooler→relay_cooler (GP18), humidifier→relay_humidifier (GP19).
        "regulators": {
            "heater": {
                "driven": "surface",
                "dims": ["temp", "humidity"],
                # Cold (temp dev < 51) → heat. Humidity amplifies (warming
                # lowers relative humidity) via the y-boost, which only scales
                # the already-active cold response — no heat when it is hot.
                #
                # Operator surface, exported verbatim from the tuning explorer
                # on 2026-07-22. It replaces the earlier 47/30 ramp, which was
                # still too slow to hold the KPI (inside ±10 of ideal 95 % of
                # the time, ±5 of ideal 85 %): reaching only ~18 % duty a whole
                # 1.6 °C below ideal meant the excursion had already happened
                # before the heater did anything about it.
                #
                # With mult 1.5 the ramp is command = 3.75 * (51 - dev):
                #   dev 50 (24.0 °C, ideal)  →  3.8 %
                #   dev 40 (22.4 °C)         → 41 %
                #   dev 24.3 (19.9 °C)       → 100 % (clamped from here down)
                # so the breakpoint deliberately sits ONE point above ideal —
                # the heater trims continuously around the setpoint instead of
                # waiting for the room to fall out of the band. The trim is
                # bounded by the adapter, not the surface: min_on_s 30 s in a
                # 600 s window is a 5 % floor on realizable duty, so at ideal
                # the element fires 30 s per 10 minutes at most.
                #
                # bx_lo2 = 10 keeps the second hinge as pure reserve — the
                # command has already clamped at 100 by dev 24 — and the y-boost
                # from dev 58 (93.3 % RH) reaches 1.88× at RH 100.
                "surface": _surface(
                    hx_lo1=2.5,
                    bx_lo1=51.0,
                    hx_lo2=2.0,
                    bx_lo2=10.0,
                    y_top=58.0,
                    grad=0.021,
                    mult=1.5,
                ),
                "adapter": {
                    "type": "heater",
                    "pin_key": "heater_mosfet",
                    "window_s": 600,  # time-proportioning window (resistive load)
                    "min_on_s": 30,
                    "min_off_s": 30,
                },
                "slew_normal": 20.0,
                "slew_fast": 50.0,
                "floor": 0.0,
                "emergency_value": 0.0,  # heat source off in emergency
                "safe_state": 0.0,
                # ...but NOT when the emergency is "too wet". Relative humidity
                # is temperature-coupled, so cutting the heat in a saturated
                # tent raises RH further and the severity that fired the
                # emergency can never fall — the 2026-07-30/31 deadlock, where
                # the tent cooled 2.8 C over the 12.3 h it was held. Freeing the
                # heater lets its own surface keep holding temperature, which is
                # what stops the spiral; the surface commands 0 once the room is
                # warm enough, so it cannot overheat.
                #
                # The cubensis anchors make RH-driven escalation unreachable on
                # their own (at_100 = 102 %RH), so for that profile this is
                # defence in depth. It is NOT redundant: every other profile
                # still has a reachable humidity at_100 (oyster 98, lions_mane
                # 100, ...) and the validator cannot enforce unreachability, so
                # this is the fix that holds regardless of profile.
                #
                # Both vectors carry it because emergency is applied BEFORE the
                # latch: freeing the heater only in safe_state would leave it
                # already pinned to 0 by the time the latch stage runs.
                "emergency_by_cause": {"humidity_high": None},
                "safe_state_by_cause": {"humidity_high": None},
            },
            "heater_follower": {
                "driven": "follower",
                "follower_gain": 0.8,
                "follower_floor": 0.0,
                "adapter": {"type": "pwm", "pca9685_ch": 2},
                "slew_normal": 30.0,
                "slew_fast": 60.0,
                "floor": 0.0,
                "emergency_value": 0.0,
                "safe_state": 0.0,
            },
            "cooler": {
                "driven": "surface",
                "dims": ["temp", "humidity"],
                # Hot (temp dev > 50) → cool, narrow deadband above dev 53,
                # steeper above 70. Humidity amplifies (compressor coils
                # condense moisture) via the y-boost; because it only scales the
                # hot-side response it cannot overcool a cold+humid room.
                #
                # This was by far the slowest actuator in the system. The
                # shipped surface reached the relay's on_above of 60 only at
                # deviation 87 — 28.4 °C against an ideal of 24 — so the room
                # had to be more than four degrees hot before the air
                # conditioner switched on at all, and the tent spent the whole
                # approach outside the band the KPI cares about.
                #
                # Surface and adapter thresholds below are ONE calibration.
                # Re-derive them together: the surface sets how command maps to
                # deviation, and on_above/off_below pick the two points on that
                # curve where the compressor actually switches.
                "surface": _surface(
                    hx_hi1=2.5,
                    bx_hi1=53.0,
                    hx_hi2=1.5,
                    bx_hi2=70.0,
                    x_top=200.0,
                    x_bot=-100.0,  # neutral x-boost
                    y_top=60.0,
                    y_bot=-100.0,  # humid (y>60) amplifies
                    grad=0.01,
                ),
                # Switch points on the ramp above, with d = temp deviation and
                # command = 2.5 * (d - 53):
                #   on_above  12.0 → closes at dev 57.8 (24.9 °C day cubensis)
                #   off_below  2.5 → opens  at dev 54.0 (24.5 °C)
                # so the compressor works a ~0.5 °C band just above ideal
                # instead of a 3 °C band starting well outside it. The band is
                # deliberately tight because min_on_s / min_off_s — not the
                # hysteresis width — are what bound the cycle rate here: the
                # shortest possible period is 120 s on + 300 s off = 7 minutes.
                "adapter": {
                    "type": "relay",
                    "pin_key": "relay_cooler",  # GP18 (freed fan relay 1)
                    "on_above": 12.0,
                    "off_below": 2.5,
                    "min_on_s": 120,
                    "min_off_s": 300,  # compressor anti-short-cycle
                },
                "slew_normal": 100.0,
                "slew_fast": 100.0,
                "floor": 0.0,
                # None = "free": the forced vectors leave the cooler on its
                # organic surface output. Escalation only fires on the hot/wet
                # side, where the cooler is the corrective actuator — pinning it
                # to 0 there turned the air conditioner OFF during a heat
                # emergency and left the latch with no way to release. Free
                # cannot overcool either: the surface commands 0 once the room
                # is no longer hot.
                "emergency_value": None,
                "safe_state": None,
            },
            "humidifier": {
                "driven": "surface",
                "dims": ["humidity", "temp"],
                # x = RH dev, y = temp dev. Retuned 2026-07-22 in the tuning
                # explorer and exported from there verbatim; the values below
                # are the blessed ones, this comment explains what they do.
                #
                # The plane is now rotated (ca=-1.2, sa=1.4) with a cross term
                # (0.5) rather than the pure additive temp coupling it carried
                # before, so the temp bias on the RH response grows with how far
                # RH itself has drifted instead of being a constant offset. The
                # sign of the coupling is unchanged: hot → humidify MORE
                # (evaporative cooling), cold → humidify LESS (misting would
                # chill further). hy_lo1/hy_lo2 add a mild cold-side taper so a
                # cold chamber backs off progressively rather than in one step.
                #
                # The RH response is a proportional ramp that ends just ABOVE
                # ideal (hx_lo1 = 1.4 from bx_lo1 = 53), and it deliberately
                # carries no deadband of its own. A relay actuator only ever
                # observes two points on the curve — where the command crosses
                # the adapter's on_above / off_below — so a surface-level
                # deadband around ideal just means the relay never closes. The
                # deadband-below-40 version shipped before 2026-07-21 commanded
                # 48.9 at RH 80.4% against an ideal of 92%, under an on_above of
                # 60, and left the humidifier off in a drying tent
                # (docs/notes/chat-log.md 2026-07-21). The hysteresis band lives
                # entirely in the adapter, which is what on_above/off_below are
                # for.
                #
                # hx_hi1/-bx_hi1 and hx_hi2 cut the command back once the air is
                # already humid, so the evaporative bias never adds moisture to
                # a humid room.
                #
                # bx_lo1 moved 43 -> 53 on 2026-07-31 because the ramp ended
                # SEVEN deviation points BELOW ideal, and off_below opened the
                # contact earlier still: driving this surface through the
                # shipped adapter, the relay opened at RH 89.6 against a 92 %
                # ideal. The tent could not reach its own setpoint. On
                # 2026-07-29, the last full day with the relay in control, RH
                # averaged 89.9 % — the predicted ceiling to within a rounding
                # error — and the operator bypassed the relay onto mains because
                # the ideal "looked too low". It was not too low, it was
                # unreachable.
                #
                # This is the same correction the heater received on 2026-07-22
                # (bx_lo1 = 51, one point above its ideal, so it "trims
                # continuously around the setpoint instead of waiting for the
                # room to fall out of the band"). The humidifier never got it,
                # which is exactly why temperature held 99.3 % inside the KPI
                # band that day while humidity met it on no day at all. 53
                # rather than 51 because the relay's own hysteresis costs a
                # further ~2 points of RH before the contact opens.
                "surface": _surface(
                    ca=-1.2,
                    sa=1.4,
                    cross=0.5,
                    gain=0.2,
                    hx_hi1=-0.7,
                    bx_hi1=55.0,
                    hx_hi2=0.2,
                    hx_lo1=1.4,
                    bx_lo1=53.0,
                    hy_lo1=0.2,
                    hy_lo2=0.1,
                ),
                # Hysteresis band, in command units, matched to the surface
                # above. The surface and these two thresholds are ONE
                # calibration, not two knobs — re-derive both whenever the
                # slope, the hinges, or the humidity anchors change. Values
                # exported alongside the surface from the tuning explorer.
                #
                # The temp coupling shifts the effective RH switch points by a
                # couple of points across the working range — a hot chamber
                # mists sooner, a cold one later. That bias is intended; cut
                # gain/cross toward 0 if the band should be temperature-
                # independent instead.
                #
                # off_below DELIBERATELY STAYS 7.0 while the surface's bx_lo1
                # moved 43 -> 53 (2026-07-31). Measured at the ideal temperature
                # against the 75/95/102 anchors, the relay opens at:
                #   bx_lo1 43, off_below 7  →  RH 89.6   (old: 2.4 points short)
                #   bx_lo1 53, off_below 7  →  RH 94.5   ← shipped, 0.5 short
                #   bx_lo1 53, off_below 5  →  RH 94.9
                #   bx_lo1 53, off_below 3  →  RH 95.1
                # Moving the ramp alone recovers almost all of the shortfall,
                # and the last half point is not worth buying. This surface's
                # humid-AND-hot residue is 4.3 command units (evaluate at x=80,
                # y=100), and a relay whose command never falls back under
                # off_below can never be released — so off_below must stay above
                # that residue. At 7.0 the guard keeps 2.7 units of margin; at
                # 3.0 it inverts, and the humidifier could be held closed in a
                # hot, near-saturated tent. tests/test_regulation_surface.py
                # asserts exactly this, and it caught the 3.0 attempt.
                #
                # Resulting band at ideal temperature: RH 92.7 (close) .. 94.6
                # (open), with min_on_s / min_off_s bounding the cycling.
                "adapter": {
                    "type": "relay",
                    "pin_key": "relay_humidifier",  # GP19 (freed fan relay 2)
                    "on_above": 18.0,
                    "off_below": 7.0,
                    "min_on_s": 30,
                    "min_off_s": 30,
                },
                "slew_normal": 100.0,
                "slew_fast": 100.0,
                "floor": 0.0,
                "emergency_value": 0.0,  # humidity source off in emergency
                "safe_state": 0.0,
            },
            "exhaust": {
                "driven": "surface",
                "dims": ["temp", "humidity"],
                # Venting dumps BOTH heat and moisture, so hot (high-x) and humid
                # (high-y) each drive it additively — either one alone opens the
                # exhaust; both open it further. Narrow deadband above dev 52,
                # steeper above 75 on each axis. The external-effectiveness
                # multiplier (engine) gates this by whether outside air is
                # actually better.
                #
                # The old break at 60 put the start of the response exactly at
                # the edge of the band the system is meant to hold, and a slope
                # of 1.5 meant deviation 61 asked the fan for 1.5 % — nominally
                # acting, physically stationary. It now reaches 20 % by
                # deviation 60 on either axis and full output by deviation 88.
                "surface": _surface(
                    hx_hi1=2.5,
                    bx_hi1=52.0,
                    hx_hi2=1.5,
                    bx_hi2=75.0,
                    hy_hi1=2.5,
                    by_hi1=52.0,
                    hy_hi2=1.5,
                    by_hi2=75.0,
                ),
                # CO2 enters additively as co2_gain * relu(co2_dev - co2_break),
                # which is the ONLY path by which CO2 moves any actuator — no
                # surface takes co2 as a dimension.
                #
                # The shipped 0.8 / 60.0 pair could not do that. The term is
                # bounded by co2_gain * (100 - co2_break), so it saturated at
                # 0.8 * 40 = 32 — below this regulator's own floor of 40, which
                # the arbiter forces whenever temp or RH severity reaches the
                # minor edge. In every realistic tent state the exhaust was
                # pinned at 40 and CO2 from 0 to 2000 ppm changed nothing; at
                # the 1200 ppm actually observed on the OLED the term was 9.1
                # (docs/notes/chat-log.md 2026-07-22).
                #
                # Gain and break are ONE calibration with the floor below — the
                # term must be able to clear the floor well inside the profile's
                # CO2 anchor range, or the floor silently swallows it again.
                # Against the cubensis fruiting anchors (0 / 600 / 2000 ppm):
                #   deadband ends   co2_dev 55  →   740 ppm
                #   clears floor 5  co2_dev 57  →   796 ppm
                #   saturates 100   co2_dev 95  →  1860 ppm
                # The deadband keeps normal indoor drift (~400-700 ppm) from
                # running the fan; above it the response is deliberately steep,
                # because stale air in a fruiting chamber is a fast problem.
                "co2_gain": 2.5,
                "co2_break": 55.0,
                "external": True,  # apply external-effectiveness multiplier
                "adapter": {"type": "pwm", "pca9685_ch": 4},
                "slew_normal": 25.0,
                "slew_fast": 60.0,
                # Walked down 40 → 25 → 10 → 5, each step on operator
                # instruction. At 40 the floor sat above everything CO2 could
                # command and hid the whole ramp. At 5 it is an idle trickle
                # rather than a minimum exchange rate: the CO2 term, the temp/RH
                # surface and the conflict rules do all the work, and the floor
                # only keeps the fan from being fully stopped while any
                # dimension is off-ideal.
                #
                # 5 % is very likely BELOW the exhaust fan's start-from-rest
                # duty, so the guarantee is probably nominal — the command is
                # nonzero but the rotor does not turn. That is the intent of an
                # idle setting this low; hw-test CO2.2 measures the real
                # threshold, and this only needs raising if a genuinely
                # continuous trickle turns out to be wanted.
                "floor": 5.0,
                "emergency_value": 100.0,  # vent hard in emergency
                "safe_state": 100.0,
            },
            "circulation": {
                "driven": "surface",
                "dims": ["temp", "humidity"],
                # Mix air whenever EITHER dimension drifts off-ideal in EITHER
                # direction — a symmetric V-shape (bowl) from four hinges,
                # deadband within dev 47-53 on each axis. Breaks up
                # microclimates so every other actuator reads a representative
                # sensor.
                #
                # The bowl was widened and steepened for the same reason as the
                # rest: at deadband 40-60 and slope 1.0 the pair was still
                # commanding 0 at the exact deviation where the tent is about to
                # leave the target band, and mixing is the cheapest correction
                # available — it costs a few watts and it makes every other
                # regulator's sensor reading honest.
                "surface": _surface(
                    hx_hi1=2.0,
                    bx_hi1=53.0,
                    hx_lo1=2.0,
                    bx_lo1=47.0,
                    hy_hi1=2.0,
                    by_hi1=53.0,
                    hy_lo1=2.0,
                    by_lo1=47.0,
                ),
                # CO2 enters additively here for the same reason it does on the
                # exhaust: no surface takes CO2 as a dimension, so the additive
                # term is the only path from a CO2 reading to an actuator.
                #
                # Venting alone does not clear a fruiting chamber. The exhaust
                # pulls from one point; without mixing, the stale air sits in
                # the dead zones between the blocks and the CO2 sensor reads a
                # room that is only locally fresh. So the circulation pair ramps
                # with CO2 too, and the two run together above the deadband.
                #
                # Gain and break are ONE calibration with the floor below.
                # Against the cubensis fruiting anchors (0 / 600 / 2000 ppm):
                #   deadband ends    co2_dev 55  →   740 ppm
                #   clears floor 30  co2_dev 70  →  1160 ppm
                #   saturates 100    co2_dev 105 →  never on its own (the
                #                    temp/RH surface makes up the rest)
                # Below 1160 ppm the floor already runs the pair at 30 whenever
                # any of its dimensions is past the minor edge, so the ramp only
                # becomes the binding term where the air is genuinely stale.
                "co2_gain": 2.0,
                "co2_break": 55.0,
                # No external gating: outside air quality decides whether
                # VENTING helps, not whether stirring the tent helps.
                "external": False,
                "adapter": {
                    "type": "pwm_pair",
                    "center_ch": 0,
                    "wall_ch": 1,
                    "center_scale": 1.0,
                    "wall_scale": 0.8,
                },
                "slew_normal": 30.0,
                "slew_fast": 60.0,
                "floor": 30.0,
                "emergency_value": 100.0,
                "safe_state": 100.0,
            },
            "growlight": {
                "driven": "tod",
                "light_level_day": 80.0,  # dimmable target at full day (b=1)
                # The light is TWO actuators driven by one command: the mains
                # relay and the 0-10V dimmer line. Left on because the dimmer
                # does nothing for mushrooms but costs nothing when the MCP4725
                # is fitted; drop to False on a build with no DAC at all.
                "dimmable": True,
                "adapter": {
                    "type": "growlight",
                    "pin_key": "relay_growlight",
                    "dac_i2c_address": 0x60,
                    "dac_max_pct": 91,  # ViparSpectra XS1500 safe ceiling — never exceed
                    # Operator spec: any command >= 1% closes the relay and puts
                    # that level on the dimmer; 0% means 0V AND relay open. The
                    # old 50/40 pair was correct for a plain bulb but would have
                    # ignored every dim level below half brightness — the dawn
                    # and dusk halves of the time-of-day ramp included. Both
                    # thresholds sit BELOW 1 because the adapter compares
                    # strictly (> on_above / < off_below), so a command of
                    # exactly 1% must still land on the on side. Relay wear is
                    # bounded by min_on_s / min_off_s, not by this band.
                    "on_above": 0.5,
                    "off_below": 0.25,
                    "min_on_s": 60,
                    "min_off_s": 60,
                },
                "slew_normal": 100.0,
                "slew_fast": 100.0,
                "floor": 0.0,
                "emergency_value": 0.0,
                "safe_state": 0.0,
                # Light-off is a real mitigation for an over-TEMPERATURE
                # emergency: the panel is lamp load, and cutting it removes heat
                # the tent cannot otherwise shed. It does nothing whatsoever for
                # an over-humidity one — the lamp is not a moisture source — so
                # there it is pure loss. Light is the pinning trigger for
                # cubensis, and the tent went dark for ~19 h during the
                # 2026-07-30/31 latch because the vector could not tell the two
                # emergencies apart.
                "emergency_by_cause": {"humidity_high": None},
                "safe_state_by_cause": {"humidity_high": None},
            },
        },
        # Conflict override rules (global band >= 30), applied in order — later
        # rules win. when-terms are AND-combined: (dimension, above|below, band
        # severity threshold on the signed side of 50). force sets exact values;
        # prefer applies max(). Ship the mold-risk rule: hot+humid → humidifier
        # hard-cut, exhaust+cooler preferred.
        #
        # The humidity threshold is 0 — "at or above ideal" — and it is a
        # re-derivation, not a loosening. It was 30 (deviation >= 80) when the
        # humidity anchors were 75/92/100, where deviation 80 meant RH 96.8.
        # Under 75/95/102 that same 30 would mean RH 99.2, leaving the rule dark
        # through most of the band where blotch develops. Worse, the protection
        # at 28 C / 96 %RH never came from this rule at all: it came from the
        # humidifier surface's own high-side cut-back at deviation 55, which
        # used to land on RH 92.8 and now lands on RH 95.7 — so raising the
        # ideal quietly moved that guard 3 points up and opened a window where a
        # 28 C, 96 %RH tent was commanded to mist (25.6, well over the relay's
        # on_above of 18). Bacterial-blotch conditions, created by the anchor
        # change itself. Threshold 0 restores the guard as an explicit rule
        # rather than a side effect of surface geometry: above 27.6 C, stop
        # adding water once humidity reaches ideal. Verified to hold the
        # humidifier at 0 for 27.8/95.5, 28/96, 28.2/97.5 and 30/98, while 24 C
        # misting and 26 C misting (below the temp gate) are untouched.
        "conflicts": [
            {
                "when": [["humidity", "above", 0], ["temp", "above", 30]],
                "force": {"humidifier": 0.0},
                "prefer": {"exhaust": 60.0, "cooler": 100.0},
            },
        ],
    },
}


_VALID_FAN_MODES = ("always_on",)
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

        # mode is guaranteed always_on here (checked against _VALID_FAN_MODES).
        for k in ("duty_pct", "refresh_interval_s"):
            if k not in cfg:
                raise ValueError(f"Missing config key: {prefix}.{k}")
        v = cfg["duty_pct"]
        if not isinstance(v, (int, float)) or not (0 <= v <= 100):
            raise ValueError(f"{prefix}.duty_pct must be 0-100")
        if cfg["refresh_interval_s"] <= 0:
            raise ValueError(f"{prefix}.refresh_interval_s must be > 0")


def _validate_surface(surface, ctx):
    """Validate one surface param dict against _SURFACE_PARAMS (loop, not hand-written)."""
    if not isinstance(surface, dict):
        raise ValueError("{} must be a dict".format(ctx))
    for name, lo, hi, _default in _SURFACE_PARAMS:
        if name not in surface:
            raise ValueError("Missing config key: {}.{}".format(ctx, name))
        value = surface[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not (lo <= value <= hi):
            raise ValueError("{}.{} must be a number in [{}, {}]".format(ctx, name, lo, hi))
    if surface["out_min"] >= surface["out_max"]:
        raise ValueError("{}.out_min must be < out_max".format(ctx))


def _validate_anchor_set(anchors, ctx):
    """Validate one dimension's {at_0, at_50, at_100} strictly-ascending anchors."""
    if not isinstance(anchors, dict):
        raise ValueError("{} must be a dict".format(ctx))
    vals = []
    for key in _ANCHOR_KEYS:
        if key not in anchors:
            raise ValueError("Missing config key: {}.{}".format(ctx, key))
        v = anchors[key]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError("{}.{} must be a number".format(ctx, key))
        vals.append(v)
    if not (vals[0] < vals[1] < vals[2]):
        raise ValueError("{} anchors must be strictly ascending (at_0 < at_50 < at_100)".format(ctx))


def _validate_reg_adapter(adapter, reg_name, pins_cfg):
    """Validate a regulator's actuator-adapter block by type."""
    ctx = "regulation.regulators.{}.adapter".format(reg_name)
    if not isinstance(adapter, dict) or "type" not in adapter:
        raise ValueError("{} must be a dict with a type".format(ctx))
    atype = adapter["type"]

    def _pin(key_name):
        pk = adapter.get(key_name)
        if not isinstance(pk, str) or pk not in pins_cfg:
            raise ValueError("{}.{} must reference a pin in pins section".format(ctx, key_name))

    def _cycle():
        for k in ("min_on_s", "min_off_s"):
            v = adapter.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                raise ValueError("{}.{} must be a number >= 0".format(ctx, k))

    def _hysteresis():
        for k in ("on_above", "off_below"):
            v = adapter.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 100):
                raise ValueError("{}.{} must be 0-100".format(ctx, k))
        if adapter["on_above"] <= adapter["off_below"]:
            raise ValueError("{}.on_above must be > off_below".format(ctx))

    def _channel(key_name):
        ch = adapter.get(key_name)
        if not isinstance(ch, int) or isinstance(ch, bool) or not (0 <= ch <= 15):
            raise ValueError("{}.{} must be an int 0-15".format(ctx, key_name))

    if atype == "pwm":
        _channel("pca9685_ch")
    elif atype == "pwm_pair":
        _channel("center_ch")
        _channel("wall_ch")
        if adapter["center_ch"] == adapter["wall_ch"]:
            raise ValueError("{} center_ch and wall_ch must differ".format(ctx))
        for k in ("center_scale", "wall_scale"):
            v = adapter.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 2):
                raise ValueError("{}.{} must be 0-2".format(ctx, k))
    elif atype == "heater":
        _pin("pin_key")
        w = adapter.get("window_s")
        if not isinstance(w, (int, float)) or isinstance(w, bool) or w <= 0:
            raise ValueError("{}.window_s must be > 0".format(ctx))
        _cycle()
    elif atype == "relay":
        _pin("pin_key")
        _hysteresis()
        _cycle()
    elif atype == "growlight":
        _pin("pin_key")
        _hysteresis()
        _cycle()
        addr = adapter.get("dac_i2c_address")
        if not isinstance(addr, int) or isinstance(addr, bool) or not (0x08 <= addr <= 0x77):
            raise ValueError("{}.dac_i2c_address must be a 7-bit I2C address".format(ctx))
        cap = adapter.get("dac_max_pct")
        if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not (0 <= cap <= 100):
            raise ValueError("{}.dac_max_pct must be 0-100".format(ctx))
    else:
        raise ValueError("{}.type {!r} is not a known adapter type".format(ctx, atype))


def _validate_regulation(reg_cfg, pins_cfg, top_mode):
    """Validate the DEVICE_CONFIG['regulation'] block (called from validate_config)."""
    if not isinstance(reg_cfg, dict):
        raise ValueError("regulation must be a dict")
    for key in ("enabled", "tick_s", "profile", "band_edges"):
        if key not in reg_cfg:
            raise ValueError("Missing config key: regulation.{}".format(key))
    if not isinstance(reg_cfg["enabled"], bool):
        raise ValueError("regulation.enabled must be a bool")
    if not isinstance(reg_cfg["tick_s"], (int, float)) or reg_cfg["tick_s"] <= 0:
        raise ValueError("regulation.tick_s must be > 0")

    edges = reg_cfg["band_edges"]
    if not isinstance(edges, list) or not edges:
        raise ValueError("regulation.band_edges must be a non-empty list")
    # The arbiter derives its minor/conflict/emergency/latch thresholds from
    # the last four edges, so at least four are required.
    if len(edges) < 4:
        raise ValueError("regulation.band_edges must have at least 4 entries")
    if edges[-1] != 50:
        raise ValueError("regulation.band_edges must end at 50")
    for i, e in enumerate(edges):
        if not isinstance(e, (int, float)) or isinstance(e, bool) or not (0 < e <= 50):
            raise ValueError("regulation.band_edges entries must be in (0, 50]")
        if i > 0 and e <= edges[i - 1]:
            raise ValueError("regulation.band_edges must be strictly ascending")

    for key in ("day_start_min", "day_end_min", "transition_min"):
        v = reg_cfg.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= 1440):
            raise ValueError("regulation.{} must be an int 0-1440".format(key))
    if reg_cfg["day_start_min"] >= reg_cfg["day_end_min"]:
        raise ValueError("regulation.day_start_min must be < day_end_min")

    ext = reg_cfg.get("external_sensor")
    if not isinstance(ext, dict):
        raise ValueError("regulation.external_sensor must be a dict")
    if not isinstance(ext.get("enabled"), bool):
        raise ValueError("regulation.external_sensor.enabled must be a bool")
    if not isinstance(ext.get("i2c_address"), int) or not (0x08 <= ext["i2c_address"] <= 0x77):
        raise ValueError("regulation.external_sensor.i2c_address must be a 7-bit I2C address")
    for key in ("full_delta_c", "full_delta_rh"):
        v = ext.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise ValueError("regulation.external_sensor.{} must be > 0".format(key))
    for key in ("min_factor", "min_factor_rh"):
        v = ext.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 1):
            raise ValueError("regulation.external_sensor.{} must be 0-1".format(key))

    esc = reg_cfg.get("escalation")
    if not isinstance(esc, dict) or set(esc) != set(_REG_DIMENSIONS):
        raise ValueError("regulation.escalation must have exactly the keys {}".format(_REG_DIMENSIONS))
    for dim in _REG_DIMENSIONS:
        side_cfg = esc[dim]
        if not isinstance(side_cfg, dict) or set(side_cfg) != {"high", "low"}:
            raise ValueError("regulation.escalation.{} must have keys high/low".format(dim))
        for side in ("high", "low"):
            if not isinstance(side_cfg[side], bool):
                raise ValueError("regulation.escalation.{}.{} must be a bool".format(dim, side))

    latch = reg_cfg.get("latch")
    if not isinstance(latch, dict):
        raise ValueError("regulation.latch must be a dict")
    rmax = latch.get("release_max")
    if not isinstance(rmax, (int, float)) or isinstance(rmax, bool) or not (0 <= rmax <= 50):
        raise ValueError("regulation.latch.release_max must be 0-50")
    enter_ticks = latch.get("enter_ticks")
    if not isinstance(enter_ticks, int) or isinstance(enter_ticks, bool) or enter_ticks < 1:
        raise ValueError("regulation.latch.enter_ticks must be an int >= 1")
    if not isinstance(latch.get("release_ticks"), int) or latch["release_ticks"] < 1:
        raise ValueError("regulation.latch.release_ticks must be an int >= 1")
    if not isinstance(latch.get("min_s"), (int, float)) or latch["min_s"] < 0:
        raise ValueError("regulation.latch.min_s must be >= 0")

    profiles = reg_cfg.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("regulation.profiles must be a non-empty dict")
    for pname, pcfg in profiles.items():
        pctx = "regulation.profiles.{}".format(pname)
        if not isinstance(pcfg, dict):
            raise ValueError("{} must be a dict".format(pctx))
        if pcfg.get("category") not in _REG_CATEGORY_MODE:
            raise ValueError("{}.category must be 'mushroom' or 'plant'".format(pctx))
        for phase in ("day", "night"):
            if phase not in pcfg:
                raise ValueError("Missing config key: {}.{}".format(pctx, phase))
            for dim in _REG_DIMENSIONS:
                if dim not in pcfg[phase]:
                    raise ValueError("Missing config key: {}.{}.{}".format(pctx, phase, dim))
                _validate_anchor_set(pcfg[phase][dim], "{}.{}.{}".format(pctx, phase, dim))

    profile = reg_cfg["profile"]
    if profile not in profiles:
        raise ValueError("regulation.profile {!r} not in profiles".format(profile))
    if profiles[profile]["category"] != _REG_CATEGORY_MODE.get(top_mode):
        raise ValueError("regulation.profile category must match top-level mode {!r}".format(top_mode))

    regulators = reg_cfg.get("regulators")
    if not isinstance(regulators, dict):
        raise ValueError("regulation.regulators must be a dict")
    if set(regulators) != set(_REG_NAMES):
        raise ValueError("regulation.regulators must be exactly {}".format(_REG_NAMES))
    for rname in _REG_NAMES:
        rcfg = regulators[rname]
        rctx = "regulation.regulators.{}".format(rname)
        if not isinstance(rcfg, dict):
            raise ValueError("{} must be a dict".format(rctx))
        driven = rcfg.get("driven")
        if driven not in ("surface", "follower", "tod"):
            raise ValueError("{}.driven must be surface|follower|tod".format(rctx))
        for key in ("slew_normal", "slew_fast"):
            v = rcfg.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                raise ValueError("{}.{} must be > 0".format(rctx, key))
        v = rcfg.get("floor")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 100):
            raise ValueError("{}.floor must be 0-100".format(rctx))
        # emergency_value / safe_state accept None = "free" (the forced vector
        # leaves this regulator on its arbitrated organic output).
        for key in ("emergency_value", "safe_state"):
            if key not in rcfg:
                raise ValueError("Missing config key: {}.{}".format(rctx, key))
            v = rcfg[key]
            if v is None:
                continue
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 100):
                raise ValueError("{}.{} must be 0-100 or None".format(rctx, key))
        # emergency_by_cause / safe_state_by_cause are OPTIONAL per-regulator
        # overrides keyed by which deviation direction escalated ("temp_high",
        # "humidity_low", ...). Absent = the scalar above applies to every
        # cause, which is the pre-2026-07-31 behaviour. See the arbiter for the
        # merge rule when several causes escalate at once.
        for key in ("emergency_by_cause", "safe_state_by_cause"):
            by_cause = rcfg.get(key)
            if by_cause is None:
                continue
            if not isinstance(by_cause, dict):
                raise ValueError("{}.{} must be a dict or absent".format(rctx, key))
            for cause, v in by_cause.items():
                if cause not in _REG_CAUSES:
                    raise ValueError("{}.{} key {!r} must be one of {}".format(rctx, key, cause, _REG_CAUSES))
                if v is None:
                    continue
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 100):
                    raise ValueError("{}.{}.{} must be 0-100 or None".format(rctx, key, cause))
        if driven == "surface":
            dims = rcfg.get("dims")
            if not isinstance(dims, list) or len(dims) != 2 or any(d not in _REG_DIMENSIONS for d in dims):
                raise ValueError("{}.dims must be two of {}".format(rctx, _REG_DIMENSIONS))
            _validate_surface(rcfg.get("surface"), "{}.surface".format(rctx))
        elif driven == "follower":
            for key in ("follower_gain", "follower_floor"):
                v = rcfg.get(key)
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise ValueError("{}.{} must be a number".format(rctx, key))
        else:  # tod
            v = rcfg.get("light_level_day")
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 100):
                raise ValueError("{}.light_level_day must be 0-100".format(rctx))
            if not isinstance(rcfg.get("dimmable"), bool):
                raise ValueError("{}.dimmable must be a bool".format(rctx))
        # CO2 additive term — optional, and available to any surface regulator
        # (the exhaust and the circulation pair ship with it). The three keys
        # are one block: a gain without a break, or either without the external
        # flag, would leave the engine reading a key that is not there.
        co2_keys = ("co2_gain", "co2_break", "external")
        if any(key in rcfg for key in co2_keys):
            missing = [key for key in co2_keys if key not in rcfg]
            if missing:
                raise ValueError("{}: CO2 term needs all of {} (missing {})".format(rctx, co2_keys, missing))
            if driven != "surface":
                raise ValueError("{}: CO2 term requires driven='surface'".format(rctx))
            if not isinstance(rcfg["co2_gain"], (int, float)) or isinstance(rcfg["co2_gain"], bool):
                raise ValueError("{}.co2_gain must be a number".format(rctx))
            if rcfg["co2_gain"] < 0:
                raise ValueError("{}.co2_gain must be >= 0".format(rctx))
            cb = rcfg["co2_break"]
            if not isinstance(cb, (int, float)) or isinstance(cb, bool) or not (0 <= cb <= 100):
                raise ValueError("{}.co2_break must be 0-100".format(rctx))
            if not isinstance(rcfg["external"], bool):
                raise ValueError("{}.external must be a bool".format(rctx))
        elif rname == "exhaust":
            # The exhaust is the primary CO2 actuator; losing the term there is
            # a silent regression, not a configuration choice.
            raise ValueError("{}: must carry the CO2 term keys {}".format(rctx, co2_keys))
        _validate_reg_adapter(rcfg.get("adapter"), rname, pins_cfg)

    conflicts = reg_cfg.get("conflicts")
    if not isinstance(conflicts, list):
        raise ValueError("regulation.conflicts must be a list")
    for i, rule in enumerate(conflicts):
        cctx = "regulation.conflicts[{}]".format(i)
        if not isinstance(rule, dict):
            raise ValueError("{} must be a dict".format(cctx))
        when = rule.get("when")
        if not isinstance(when, list) or not when:
            raise ValueError("{}.when must be a non-empty list".format(cctx))
        for term in when:
            if not isinstance(term, (list, tuple)) or len(term) != 3:
                raise ValueError("{}.when terms must be [dimension, above|below, threshold]".format(cctx))
            dim, op, thresh = term
            if dim not in _REG_DIMENSIONS:
                raise ValueError("{}.when dimension {!r} unknown".format(cctx, dim))
            if op not in ("above", "below"):
                raise ValueError("{}.when op must be 'above' or 'below'".format(cctx))
            if not isinstance(thresh, (int, float)) or isinstance(thresh, bool) or not (0 <= thresh <= 50):
                raise ValueError("{}.when threshold must be 0-50".format(cctx))
        for action in ("force", "prefer"):
            block = rule.get(action, {})
            if not isinstance(block, dict):
                raise ValueError("{}.{} must be a dict".format(cctx, action))
            for reg_name, value in block.items():
                if reg_name not in _REG_NAMES:
                    raise ValueError("{}.{} references unknown regulator {!r}".format(cctx, action, reg_name))
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not (0 <= value <= 100):
                    raise ValueError("{}.{}.{} must be 0-100".format(cctx, action, reg_name))


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
            "relay_cooler",
            "relay_humidifier",
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
            "sd_detect",
        ],
        "spi": ["id", "baudrate", "sck", "mosi", "miso", "cs", "mount_point"],
        "sd_detect": ["enabled", "present_when_low", "pull"],
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
            "invert",
        ],
        "co2_logger": [
            "interval_s",
            "warmup_s",
            "max_retries",
            "override_ppm_on",
            "override_ppm_off",
            "sensor_type",
        ],
        "soil_logger": [
            "interval_s",
            "adc_dry_raw",
            "adc_wet_raw",
            "warn_pct_below",
            "sensor_type",
        ],
        "Service_reminder": [
            "days_interval",
            "blink_pattern_ms",
            "blink_after_days",
            "storage_path",
            "monitor_interval_s",
        ],
        "buzzer": ["enabled", "default_freq", "default_duty_pct"],
        "diagnostics": ["mem_trend_log", "metrics_log"],
        "memory": ["gc_threshold_b"],
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
            "log_retention_days",
        ],
        "output_pins": [
            "relay_cooler",
            "relay_humidifier",
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
            "sd_fault_blink_ms",
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
            "max_render_errors",
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
            "enforce_mpy_abi",
            "prune_stale",
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
            "i2c_use_soft",
            "i2c_timeout_us",
            "i2c_recover_on_error",
            "i2c_recover_clocks",
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

    if (
        not isinstance(DEVICE_CONFIG["event_logger"]["log_retention_days"], int)
        or DEVICE_CONFIG["event_logger"]["log_retention_days"] <= 0
    ):
        raise ValueError("event_logger.log_retention_days must be an int > 0")

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

    if not isinstance(DEVICE_CONFIG["diagnostics"]["mem_trend_log"], bool):
        raise ValueError("diagnostics.mem_trend_log must be a bool")

    if not isinstance(DEVICE_CONFIG["diagnostics"]["metrics_log"], bool):
        raise ValueError("diagnostics.metrics_log must be a bool")

    gc_threshold = DEVICE_CONFIG["memory"]["gc_threshold_b"]
    if not isinstance(gc_threshold, int) or gc_threshold == 0 or gc_threshold < -1:
        raise ValueError("memory.gc_threshold_b must be a positive int or -1 (disabled)")

    if DEVICE_CONFIG["temp_humidity_logger"]["retry_delay_s"] <= 0:
        raise ValueError("temp_humidity_logger.retry_delay_s must be > 0")

    _validate_fans(DEVICE_CONFIG.get("fans"), DEVICE_CONFIG["pins"])

    pca_cfg = DEVICE_CONFIG["pca9685"]
    if not isinstance(pca_cfg["enabled"], bool):
        raise ValueError("pca9685.enabled must be a bool")
    if not isinstance(pca_cfg["i2c_address"], int) or not (0x08 <= pca_cfg["i2c_address"] <= 0x77):
        raise ValueError("pca9685.i2c_address must be a 7-bit I2C address (0x08-0x77)")
    if not isinstance(pca_cfg["freq_hz"], int) or not (24 <= pca_cfg["freq_hz"] <= 1526):
        raise ValueError("pca9685.freq_hz must be an int 24-1526 (PCA9685 datasheet range)")
    if not isinstance(pca_cfg["invert"], bool):
        raise ValueError("pca9685.invert must be a bool")

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

    sd_detect_cfg = DEVICE_CONFIG["sd_detect"]
    if not isinstance(sd_detect_cfg["enabled"], bool):
        raise ValueError("sd_detect.enabled must be a bool")
    if not isinstance(sd_detect_cfg["present_when_low"], bool):
        raise ValueError("sd_detect.present_when_low must be a bool")
    if sd_detect_cfg["pull"] not in ("up", "down", "none"):
        raise ValueError("sd_detect.pull must be 'up', 'down', or 'none'")

    disp_cfg = DEVICE_CONFIG["display"]
    for delay_key in ("startup_banner_s", "vram_clear_delay_s", "invert_delay_s"):
        if not isinstance(disp_cfg[delay_key], (int, float)) or disp_cfg[delay_key] < 0:
            raise ValueError(f"display.{delay_key} must be a number >= 0")
    if not isinstance(disp_cfg["max_render_errors"], int) or disp_cfg["max_render_errors"] < 1:
        raise ValueError("display.max_render_errors must be an int >= 1")

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

    if DEVICE_CONFIG["Service_reminder"]["blink_after_days"] < 0:
        raise ValueError("Service_reminder.blink_after_days must be >= 0")

    if DEVICE_CONFIG["Service_reminder"]["monitor_interval_s"] <= 0:
        raise ValueError("Service_reminder.monitor_interval_s must be > 0")

    sys_cfg = DEVICE_CONFIG["system"]
    if sys_cfg["i2c_freq"] <= 0:
        raise ValueError("system.i2c_freq must be > 0")

    if not isinstance(sys_cfg["i2c_use_soft"], bool):
        raise ValueError("system.i2c_use_soft must be a bool")
    if not isinstance(sys_cfg["i2c_timeout_us"], int) or not (1000 <= sys_cfg["i2c_timeout_us"] <= 1000000):
        raise ValueError("system.i2c_timeout_us must be an int in 1000..1000000")
    if not isinstance(sys_cfg["i2c_recover_on_error"], bool):
        raise ValueError("system.i2c_recover_on_error must be a bool")
    if not isinstance(sys_cfg["i2c_recover_clocks"], int) or not (8 <= sys_cfg["i2c_recover_clocks"] <= 16):
        raise ValueError("system.i2c_recover_clocks must be an int in 8..16")

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

    if DEVICE_CONFIG["status_leds"]["sd_fault_blink_ms"] <= 0:
        raise ValueError("status_leds.sd_fault_blink_ms must be > 0")

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
    if not isinstance(upd_cfg["enforce_mpy_abi"], bool):
        raise ValueError("updater.enforce_mpy_abi must be a bool")
    if not isinstance(upd_cfg["prune_stale"], bool):
        raise ValueError("updater.prune_stale must be a bool")
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

    if "regulation" not in DEVICE_CONFIG:
        raise ValueError("Missing config section: regulation")
    _validate_regulation(DEVICE_CONFIG["regulation"], DEVICE_CONFIG["pins"], DEVICE_CONFIG["mode"])

    return True
