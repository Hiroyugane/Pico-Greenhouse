# Next-rev PCB bring-up runner — Pi Greenhouse
# Dennis Hiro, 2026-06-30
#
# Linear, tick-as-you-go walk-through of the two next-rev hardware
# checklists in docs/test/hw-test-log.md:
#   - 2026-06-30 · Next-rev migration bring-up (B1-B4: all-PCA9685 fans,
#     SD card-detect / DET polarity, TLC555 soil).
#   - 2026-05-23 · Next-rev post-fab verification (EasyEDA design review:
#     Schottky drops, TVS, LM358 gain, SD module, S8 divider, I2C pull-ups,
#     MCP1416 gate driver, power-good LEDs, test points, XT60/F1, stackup).
#
# Each item is presented IN ORDER. Where firmware can help it takes a live
# reading (DET level, i2c.scan, soil raw) or actuates an output (spins each
# fan channel, sweeps the grow-light DAC, drives the heater gate). Multimeter
# / scope / visual items are presented as a printed instruction plus a
# "record value" prompt so the run is gap-free. You verdict every item
# [p]ass / [f]ail / [s]kip; a Markdown report mirroring the checklist is
# written to /sd/diagnostics/ (falling back to /local/) after every item.
#
# HOW TO RUN — needs an interactive REPL for input():
#   Thonny:   open this file, press Run (F5). Answer prompts in the Shell.
#   mpremote: mpremote run prototypes/next_rev_bringup.py   (or: run bringup)
# Run it STANDALONE (not while main.py is running) so nothing else drives the
# bus or the relays. B2.3/B2.4/B3.2/B4.* note where main.py or a reboot is
# required — those stay observational.
#
# SAFETY: fan-spin, grow-light DAC and the heater-gate (GP3) steps actuate
# real loads. Each asks for explicit confirmation first and forces the output
# back OFF afterwards (try/finally). Do not run the heater-gate drive with a
# live heater unless you intend to measure V_GS with the heater safely loaded.

import os
import sys
import time

try:
    import machine
except ImportError:  # host / CPython — hardware actions degrade to manual
    machine = None  # type: ignore[assignment]

# On CPython let the checklist at least import + preview; on-device paths are
# already correct (config.py and lib/ are on the flash root).
if sys.implementation.name != "micropython":
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    sys.path.insert(0, os.path.join(_ROOT, "host_shims"))

from config import DEVICE_CONFIG  # noqa: E402  (kept after the host path shim)

_PINS = DEVICE_CONFIG["pins"]
HEATER_PIN = _PINS["heater_mosfet"]  # GP3
SD_LED_PIN = _PINS["sd_led"]  # GP5
DET_PIN = _PINS["sd_detect"]  # GP15
SOIL_PIN = _PINS["adc_input"]  # GP28
I2C_PORT = _PINS["rtc_i2c_port"]
I2C_SDA = _PINS["rtc_sda"]
I2C_SCL = _PINS["rtc_scl"]
I2C_FREQ = DEVICE_CONFIG.get("system", {}).get("i2c_freq", 400000)

# Accumulated verdicts; the report is rebuilt from this after each item.
RESULTS = []

# Lazily-built, cached hardware handles (None until first needed / on host).
_I2C = None
_PCA = None
_DAC = None
_DET = None


class _Quit(Exception):
    """Raised internally when the tester chooses [q]uit; saves + exits."""


# ----------------------------------------------------------------- prompts


def _input(prompt):
    """input() wrapper; surfaces Ctrl-C/EOF as a clean quit."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise _Quit()


def _confirm(prompt, strict=False):
    """Yes/no gate. strict=True requires the full word 'yes'."""
    ans = _input(prompt).strip().lower()
    return ans == "yes" if strict else ans in ("y", "yes")


def _ts():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6])


# ----------------------------------------------------------------- handles


def _i2c():
    global _I2C
    if machine is None:
        print("  [machine unavailable — record this item manually]")
        return None
    if _I2C is None:
        _I2C = machine.I2C(I2C_PORT, sda=machine.Pin(I2C_SDA), scl=machine.Pin(I2C_SCL), freq=I2C_FREQ)
    return _I2C


def _pca():
    global _PCA
    if _PCA is not None:
        return _PCA
    bus = _i2c()
    if bus is None:
        return None
    try:
        from lib.pca9685 import PCA9685

        cfg = DEVICE_CONFIG["pca9685"]
        _PCA = PCA9685(bus, address=cfg["i2c_address"], freq_hz=cfg["freq_hz"])
    except Exception as e:
        print("  PCA9685 init failed (%s) — chip absent? record manually." % e)
        _PCA = None
    return _PCA


def _dac():
    global _DAC
    if _DAC is not None:
        return _DAC
    bus = _i2c()
    if bus is None:
        return None
    addr = DEVICE_CONFIG["growlight"]["dac_i2c_address"]
    try:
        present = bus.scan()
    except Exception as e:
        print("  i2c scan failed: %s" % e)
        return None
    if addr not in present and 0x61 not in present:
        print("  MCP4725 not on the bus (looked for 0x%02X / 0x61) — DAC sweep not possible." % addr)
        return None
    try:
        from lib.mcp4725 import MCP4725

        _DAC = MCP4725(bus, address=addr if addr in present else 0x61)
    except Exception as e:
        print("  MCP4725 init failed: %s" % e)
        _DAC = None
    return _DAC


def _det_pin():
    global _DET
    if machine is None:
        return None
    if _DET is None:
        pull_name = DEVICE_CONFIG["sd_detect"].get("pull", "up")
        pull = {
            "up": getattr(machine.Pin, "PULL_UP", None),
            "down": getattr(machine.Pin, "PULL_DOWN", None),
            "none": None,
        }.get(pull_name, getattr(machine.Pin, "PULL_UP", None))
        if pull is None:
            _DET = machine.Pin(DET_PIN, machine.Pin.IN)
        else:
            _DET = machine.Pin(DET_PIN, machine.Pin.IN, pull)
    return _DET


def _safe_all_off():
    """Force every actuated output OFF. Called on exit no matter what."""
    if machine is None:
        return
    try:
        if _PCA is not None:
            _PCA.all_off()
    except Exception:
        pass
    try:
        machine.Pin(HEATER_PIN, machine.Pin.OUT).value(0)
    except Exception:
        pass
    try:
        machine.Pin(SD_LED_PIN, machine.Pin.OUT).value(0)
    except Exception:
        pass
    try:
        if _DAC is not None:
            _DAC.write(0)
    except Exception:
        pass


# ------------------------------------------------------------ action fns
# Each returns a short string captured into the report's "value" column,
# or None. They never raise out — _run_item wraps them too.


def act_i2c_scan():
    bus = _i2c()
    if bus is None:
        return None
    known = {0x3C: "OLED", 0x40: "PCA9685", 0x44: "SHT31", 0x60: "MCP4725", 0x68: "DS3231"}
    addrs = bus.scan()
    for a in addrs:
        print("    0x%02X  %s" % (a, known.get(a, "unknown")))
    expect = (0x3C, 0x44, 0x60, 0x68)
    missing = ["0x%02X" % a for a in expect if a not in addrs]
    if missing:
        print("    MISSING expected: %s" % ", ".join(missing))
    print("    PCA9685 0x40: %s" % ("present" if 0x40 in addrs else "absent (populate before B2)"))
    return "scan=" + ",".join("0x%02X" % a for a in addrs)


def act_det_polarity():
    pin = _det_pin()
    if pin is None:
        return None
    _input("    Insert a card, then press Enter to read DET (GP%d)..." % DET_PIN)
    v_in = pin.value()
    _input("    Now REMOVE the card, then press Enter to read again...")
    v_out = pin.value()
    print("    DET with card=%d, empty=%d" % (v_in, v_out))
    cfg = DEVICE_CONFIG["sd_detect"]["present_when_low"]
    if v_in == 0 and v_out == 1:
        observed_low = True
    elif v_in == 1 and v_out == 0:
        observed_low = False
    else:
        print("    INCONCLUSIVE: levels did not change between in/out — check wiring.")
        return "card=%d empty=%d (no change)" % (v_in, v_out)
    print("    Observed present_when_low=%s ; config has %s" % (observed_low, cfg))
    if observed_low != cfg:
        print("    >>> FLIP config sd_detect.present_when_low to %s before trusting B4." % observed_low)
    else:
        print("    Config polarity matches reality.")
    return "card=%d empty=%d present_when_low_observed=%s cfg=%s" % (v_in, v_out, observed_low, cfg)


def act_det_read():
    pin = _det_pin()
    if pin is None:
        return None
    v = pin.value()
    present_low = DEVICE_CONFIG["sd_detect"]["present_when_low"]
    present = (v == 0) if present_low else (v == 1)
    print("    DET GP%d = %d -> firmware reads card %s" % (DET_PIN, v, "PRESENT" if present else "ABSENT"))
    return "det=%d present=%s" % (v, present)


def _load_print_raw():
    try:
        from lib.soil_logger import print_raw

        return print_raw
    except Exception as e:
        print("    lib.soil_logger.print_raw unavailable: %s" % e)
        return None


def act_soil_live():
    pr = _load_print_raw()
    if pr is None:
        return None
    print("    Watching GP%d for ~8 s — submerge / lift the probe and watch it move:" % SOIL_PIN)
    last = None
    for _ in range(16):
        try:
            last = pr(SOIL_PIN)
        except Exception as e:
            print("    read failed: %s" % e)
            break
        time.sleep(0.5)
    return "last_raw=%s" % last


def act_soil_three_point():
    pr = _load_print_raw()
    if pr is None:
        return None
    vals = {}
    for label in ("air/bone-dry", "moist soil", "water"):
        _input("    Place probe in %s, then press Enter to read..." % label)
        try:
            vals[label] = pr(SOIL_PIN)
        except Exception as e:
            print("    read failed: %s" % e)
            vals[label] = None
    dry = vals.get("air/bone-dry")
    wet = vals.get("water")
    if isinstance(dry, int) and isinstance(wet, int):
        if dry > wet:
            print("    OK: dry(%d) > wet(%d). Set soil_logger.adc_dry_raw=%d, adc_wet_raw=%d." % (dry, wet, dry, wet))
        else:
            print("    >>> PROBLEM: dry(%d) must be > wet(%d) for the validator/convention." % (dry, wet))
    return "air=%s moist=%s water=%s" % (vals.get("air/bone-dry"), vals.get("moist soil"), vals.get("water"))


def act_fan_roster():
    pca = _pca()
    if pca is None:
        return None
    roster = sorted(
        (c["pca9685_ch"], role) for role, c in DEVICE_CONFIG["fans"].items() if c.get("output") == "pca9685"
    )
    if not _confirm("    Are all fans clear to spin? [y/N]: "):
        return "actuation skipped"
    swaps = []
    try:
        for ch, role in roster:
            pca.set_duty(ch, 100)
            ans = _input("    ch%d driving — is THIS the '%s' fan, spinning? [y/n]: " % (ch, role)).strip().lower()
            pca.set_duty(ch, 0)
            if ans.startswith("n"):
                swaps.append("ch%d!=%s" % (ch, role))
    finally:
        pca.all_off()
    return ("swaps: " + ",".join(swaps)) if swaps else "ch0-ch4 roster matches harness"


def act_fan_duty_sweep():
    pca = _pca()
    if pca is None:
        return None
    ch = DEVICE_CONFIG["fans"]["case"]["pca9685_ch"]
    if not _confirm("    Spin the 'case' fan (ch%d) at 100%% then 60%%? [y/N]: " % ch):
        return "actuation skipped"
    try:
        pca.set_duty(ch, 100)
        _input("    ch%d at 100%% — note the speed, then press Enter..." % ch)
        pca.set_duty(ch, 60)
        _input("    ch%d at 60%% — is it visibly SLOWER (PWM proof)? Press Enter..." % ch)
    finally:
        pca.all_off()
    return None


def act_dac_sweep():
    dac = _dac()
    if dac is None:
        return None
    expect = {0: "~0 V", 25: "~2.6 V", 50: "~5.2 V", 75: "~7.7 V", 100: "~10.3 V (fw clamps 91%->~9.4 V)"}
    readings = []
    try:
        for pct in (0, 25, 50, 75, 100):
            dac.write(round(pct / 100.0 * 4095))
            mv = _input("    DAC=%d%% (expect %s) — measure GL_DIM+, type V (Enter=skip): " % (pct, expect[pct]))
            readings.append("%d%%=%s" % (pct, mv.strip() or "?"))
    finally:
        dac.write(0)
    return " ".join(readings)


def act_gp3_drive():
    if machine is None:
        return None
    print("    !! Driving GP3 HIGH turns the heater MOSFET gate ON (heater fires if connected).")
    if not _confirm("    Type 'yes' to drive GP3 HIGH: ", strict=True):
        return "actuation skipped"
    p = machine.Pin(HEATER_PIN, machine.Pin.OUT)
    try:
        p.value(1)
        _input("    GP3 HIGH — measure IRLZ44N V_GS now (expect ~5 V), then press Enter to release...")
    finally:
        p.value(0)
        print("    GP3 LOW (heater gate off).")
    return None


def act_sd_led_demo():
    if machine is None:
        return None
    if not _confirm("    Demo the SD LED states (solid vs 500 ms blink) on GP%d? [y/N]: " % SD_LED_PIN):
        return None
    led = machine.Pin(SD_LED_PIN, machine.Pin.OUT)
    try:
        print("    SOLID ON for 3 s  = no_card state...")
        led.value(1)
        time.sleep(3)
        led.value(0)
        print("    BLINK 500 ms for 5 s = mount_failed state...")
        for _ in range(5):
            led.value(1)
            time.sleep(0.5)
            led.value(0)
            time.sleep(0.5)
    finally:
        led.value(0)
    return None


# --------------------------------------------------------------- checklist


def _item(id_, text, fn=None, record=False):
    return {"id": id_, "text": text, "fn": fn, "record": record}


SECTIONS = [
    (
        "2026-06-30 · B2 — all-PCA9685 fan roster (ch0-ch4)",
        [
            _item(
                "B2.1",
                "Each fan spins from its channel (exhaust0/walls1/center2/heaterdist3/case4); no swap.",
                act_fan_roster,
            ),
            _item(
                "B2.2", "Duty sweep: case at 60% visibly slower than 100% (proves PWM, not on/off).", act_fan_duty_sweep
            ),
            _item(
                "B2.3",
                "[main.py] Temp > a fan max_temp forces it on; heater_distribution follows heater +60 s afterrun.",
                record="observed",
            ),
            _item(
                "B2.4",
                "[reboot w/ PCA pulled] Boot log shows pca init error and every fan skipped (no relay fallback).",
                record="boot-log line",
            ),
        ],
    ),
    (
        "2026-06-30 · B3 — SD card-detect (DET) polarity (do first)",
        [
            _item(
                "B3.1",
                "Polarity (load-bearing): DET GP15 with card vs empty; confirm present_when_low=True matches.",
                act_det_polarity,
            ),
            _item(
                "B3.2",
                "[config sd_detect.enabled=False + reboot] Recovery falls back to poll-only; still boots + logs to SD.",
                record="observed",
            ),
        ],
    ),
    (
        "2026-06-30 · B4 — card-detect-driven SD recovery (needs main.py running)",
        [
            _item(
                "B4.1",
                "[run main.py] Pull card -> SD LED SOLID ON (no_card), NO 'retrying soon' spam.",
                act_sd_led_demo,
            ),
            _item(
                "B4.2",
                "Re-insert card -> remount on next fast poll (~sd_recovery_interval_s), rows flush, SD LED OFF.",
                record="remount s",
            ),
            _item(
                "B4.3",
                "Corrupt/unseat-but-detected (DET present, mount fails) -> SD LED BLINKS 500 ms + 'retrying soon'.",
                act_sd_led_demo,
            ),
        ],
    ),
    (
        "2026-06-30 · B1 — TLC555 soil sensor recalibration (plant mode)",
        [
            _item(
                "B1.1",
                "Fit TLC555 (VCC->3V3 pin36, AOUT->GP28, no divider). Confirm AOUT moves on submersion.",
                act_soil_live,
            ),
            _item(
                "B1.2",
                "print_raw air/moist/water separate, dry>wet; set adc_dry_raw/adc_wet_raw, reboot, check %/LED/CSV.",
                act_soil_three_point,
            ),
        ],
    ),
    (
        "2026-05-23 · Power input — Schottky swap (D1-D6) + bulk caps",
        [
            _item("PI.1", "D5 = MBR20100CT (TO-220) on heater path; Vf at 3.4 A / 6.8 A ~ 0.4-0.5 V.", record="Vf V"),
            _item("PI.2", "D1,D2,D3,D4,D6 = MBRD1045 (D-PAK); Vf at typical load ~ 0.3 V/diode.", record="Vf V"),
            _item("PI.3", "5 V VSYS bulk cap = 1000 uF / 16 V (read rating off the body).", record="cap marking"),
            _item(
                "PI.4", "F1 upstream of D5 (19V_IN->F1->D5->bulk->HE_MOSFET); trace continuity.", record="continuity"
            ),
            _item("PI.5", "5 A+ heater ON: 19.5 V rail at bulk cap during switch-on; sag < 0.5 V.", record="sag V"),
            _item("PI.6", "12 V rail during fan startup (post-PCA9685); sag < 0.3 V.", record="sag V"),
            _item("PI.7", "VSYS at Pico pin 39 idle: 4.6-4.8 V (was 3.05-3.4 V pre-Schottky).", record="VSYS V"),
        ],
    ),
    (
        "2026-05-23 · Power input — TVS clamps",
        [
            _item(
                "TVS.1",
                "SMAJ5.0CA on 5 V, SMAJ15CA on 12 V, SMAJ24CA on 19.5 V (all SMA) installed.",
                record="confirmed",
            ),
            _item(
                "TVS.2",
                "Standoff: rails at nominal (5/12/19.5 V) with TVS in place — no clamping engages.",
                record="rail V",
            ),
        ],
    ),
    (
        "2026-05-23 · Grow light — LM358 swap + gain retune",
        [
            _item(
                "GL.1",
                "LM358DR (SOIC-8) in GL_OP-AMP; pin 8 to pin 4 ~ 12 V (no abs-max violation).",
                record="supply V",
            ),
            _item("GL.2", "R4 = 10 kOhm, R5 = 4.7 kOhm.", record="values"),
            _item(
                "GL.3",
                "DAC sweep 0/25/50/75/100 %; GL_DIM+ ~0/2.6/5.2/7.7/10.3 V; 100% clamps to ~9.4 V (verify clamp).",
                act_dac_sweep,
            ),
            _item(
                "GL.4",
                "Sweep continuously: output monotonic, no steps/plateaus/oscillation (scope).",
                record="scope note",
            ),
        ],
    ),
    (
        "2026-05-23 · SD module swap — AZDelivery -> Adafruit 4682",
        [
            _item(
                "SD.1",
                "Silkscreen footprint = Adafruit 4682 (3V,GND,CLK,SO,SI,CS,DET); DAT2/D1/D3 pads exposed/unused.",
                record="confirmed",
            ),
            _item(
                "SD.2",
                "SD power pin -> 3V3 net (not 5 V); probe '3V' pad, no card: 3.30 +/- 0.10 V.",
                record="3V pad V",
            ),
            _item(
                "SD.3", "100 uF electrolytic + 100 nF ceramic adjacent to '3V' pad, leads < 5 mm.", record="confirmed"
            ),
            _item(
                "SD.4",
                "10 kOhm 0603 to 3V3 (log:GP13; config+memory corrected to GP12/MISO - confirm pad); reads ~3.3 V.",
                record="pin + V",
            ),
            _item("SD.5", "Cold-boot single-attempt mount, repeat 10x: 10/10 first-attempt mounts.", record="x/10"),
            _item(
                "SD.6",
                "Cold-boot no card (require_sd_startup=True): sd+error LEDs, reset after sd_fail_reset_s=10 s.",
                record="observed",
            ),
            _item(
                "SD.7",
                "Hot-swap card pulled: writes fall to /local/fallback.csv, no crash/WDT. Wait 60 s.",
                record="observed",
            ),
            _item(
                "SD.8",
                "Hot-swap re-inserted: within sd_recovery_interval_s=10 s remount + migrate fallback rows.",
                record="observed",
            ),
            _item(
                "SD.9",
                "10-min log at interval_s=30: ~20 rows, none missing/corrupt, no SD ERROR rows.",
                record="row count",
            ),
            _item("SD.10", "Scope 3V3 at '3V' pad during write burst: sag < 0.1 V (flag if > 0.2 V).", record="sag V"),
            _item(
                "SD.11",
                "DET readout: GP15 defined level no-card, flips on insert; cross-check firmware sd_detect.",
                act_det_read,
            ),
            _item(
                "SD.12",
                "Compare vs AZDelivery baseline: cold-mount / hot-swap / throughput all >= prior board.",
                record="observed",
            ),
        ],
    ),
    (
        "2026-05-23 · Senseair S8 — UART RX divider",
        [
            _item("S8.1", "R11 = 2.2 kOhm and new R_RX_DIV = 3.3 kOhm installed.", record="values"),
            _item("S8.2", "DC at Pico GP17 during S8 idle (TXD high): ~3.0 V (not ~5 V).", record="GP17 V"),
            _item(
                "S8.3",
                "CO2 logging still works post-divider: co2_logger retry counter flat over 24 h.",
                record="retry count",
            ),
        ],
    ),
    (
        "2026-05-23 · I2C bus — pull-ups dropped to 2.2 kOhm",
        [
            _item("I2C.1", "R1 = 2.2 kOhm and R2 = 2.2 kOhm on SDA / SCL.", record="values"),
            _item("I2C.2", "Scope SDA/SCL rise time at far end (RJ12): < 1 us at 250 pF.", record="rise us"),
            _item(
                "I2C.3",
                "Scan responds: 0x3C OLED, 0x44 SHT31, 0x60 MCP4725, 0x68 DS3231, 0x40 PCA9685 (if populated).",
                act_i2c_scan,
            ),
            _item("I2C.4", "24 h soak: no I2C error counts climbing in the event log.", record="error count"),
        ],
    ),
    (
        "2026-05-23 · R3 correction + button surface",
        [
            _item(
                "RB.1",
                "R3 = 10 kOhm (not 10 Ohm): GP14->GND continuity with buzzer disconnected ~10 kOhm.",
                record="ohms",
            ),
            _item("RB.2", "Press menu button repeatedly — no firmware glitches / spurious resets.", record="observed"),
        ],
    ),
    (
        "2026-05-23 · Heater MOSFET gate driver (MCP1416)",
        [
            _item("GD.1", "MCP1416T-E/OT (SOT-23-5) installed between GP3 and IRLZ44N gate.", record="confirmed"),
            _item("GD.2", "MCP1416 V_DD (pin 1) -> 5 V, pin 3 -> GND; 100 nF decoupling present.", record="confirmed"),
            _item("GD.3", "R6 = 47 Ohm (was 100 Ohm) between MCP1416 OUT and IRLZ44N gate.", record="value"),
            _item("GD.4", "10 kOhm pull-down from IRLZ44N gate to source/GND.", record="value"),
            _item(
                "GD.5", "Pico in reset / pre-firmware: IRLZ44N V_GS = 0 V (heater off during boot).", record="V_GS V"
            ),
            _item("GD.6", "Drive GP3 HIGH: IRLZ44N V_GS ~ 5 V (was ~3.3 V direct-drive).", act_gp3_drive),
            _item("GD.7", "HE_MOSFET V_ds with heater current: ~0.15 V at 6.8 A.", record="Vds V"),
            _item(
                "GD.8",
                "Scope gate edge turn-on/off: clean monotonic, rise/fall < 1 us, ringing < 10 %.",
                record="scope note",
            ),
        ],
    ),
    (
        "2026-05-23 · Heater MOSFET thermal",
        [
            _item("HT.1", "Clip-on heatsink (SK 104-25 STS or equiv) mounted on HE_MOSFET.", record="confirmed"),
            _item("HT.2", "Full duty 30 min in sealed enclosure: heatsink < 70 C above ambient.", record="delta C"),
        ],
    ),
    (
        "2026-05-23 · Power-good LEDs",
        [
            _item("PG.1", "LEDs light on all four rails (3V3 / 5V / 12V / 19.5V) at power-up.", record="observed"),
            _item(
                "PG.2",
                "Brightness ~ Pico onboard LED (~0.7 mA target); resistors 750/4.7k/10k/22k (3V3/5V/12V/19.5V).",
                record="observed",
            ),
            _item(
                "PG.3",
                "Bank NOT uniform: 5 V dimmest (~0.47 mA), 12 V brightest (~0.92 mA) — expected.",
                record="observed",
            ),
            _item(
                "PG.4",
                "3V3 LED Vf-sensitive: if dim/bright, measure Vf at ~1 mA and hand-pick its resistor (750 Ohm nom).",
                record="Vf V",
            ),
        ],
    ),
    (
        "2026-05-23 · Test points",
        [
            _item(
                "TP.1",
                "8 labelled pads (3V3/5V/12V/19.5V/GND/GND/SDA/SCL) populated at 2.54 mm pitch.",
                record="confirmed",
            ),
            _item("TP.2", "Land a 6-pin pogo fixture on the row; contact to all pads.", record="confirmed"),
        ],
    ),
    (
        "2026-05-23 · Brownout supervisor",
        [
            _item("BO.1", "MAX809 (or TPS3839K33) installed on Pico RUN line (pin 30).", record="confirmed"),
            _item(
                "BO.2",
                "Drop supply 5.0 -> 2.5 V slowly: clean reset cycle at supervisor threshold (~3.0 V).",
                record="threshold V",
            ),
        ],
    ),
    (
        "2026-05-23 · VBUS / DEBUG_CON backfeed",
        [
            _item("VB.1", "SS14 Schottky in series on INT_CON-4 (VBUS).", record="confirmed"),
            _item("VB.2", "SS14 Schottky in series on DEBUG_CON-2 (5 V).", record="confirmed"),
            _item("VB.3", "USB unplugged, 5 V supply on: INT_CON-4 = 0 V (no backfeed).", record="INT_CON-4 V"),
        ],
    ),
    (
        "2026-05-23 · Pico footprint label",
        [
            _item("PF.1", "Silkscreen reads RPI-PICO-V1 (matching footprint in EasyEDA).", record="confirmed"),
        ],
    ),
    (
        "2026-05-23 · Power input connectors (XT60 x3) + F1 fuse",
        [
            _item("XT.1", "XT60 installed on all three inputs (5 V / 12 V / 19.5 V).", record="confirmed"),
            _item("XT.2", "Silkscreen labels 5V / 12V / 19.5V with +/- polarity marks.", record="confirmed"),
            _item(
                "XT.3", "Board-edge clearance allows full XT60 seating on all three (no overhang).", record="confirmed"
            ),
            _item("XT.4", "F1 = 10 A 5x20 mm T slow-blow glass in THT holder, upstream of D5.", record="confirmed"),
            _item(
                "XT.5", "Both heaters parallel ON (~6.8 A): F1 no nuisance trip on bulk-cap inrush.", record="observed"
            ),
            _item(
                "XT.6",
                "Short heater output (dummy load, current-limited 19.5 V): F1 clears < 2 s at 2x rated.",
                record="clear s",
            ),
        ],
    ),
    (
        "2026-05-23 · PCB stackup and trace widths",
        [
            _item(
                "PCB.1", "Fab order specifies 2 oz copper on both outer layers (screenshot / CoC).", record="confirmed"
            ),
            _item(
                "PCB.2", "Heater path (F1->D5->bulk->HE_MOSFET->HE_CON) >= 3 mm trace width (narrowest).", record="mm"
            ),
            _item("PCB.3", "12 V buck output trace >= 2.5 mm.", record="mm"),
            _item(
                "PCB.4", "Clearance 0.15 mm signal / 0.3 mm power; remaining DRC warnings reviewed.", record="DRC note"
            ),
        ],
    ),
]


# ------------------------------------------------------------------ runner


def _prompt_verdict(has_fn):
    opts = "[p]ass [f]ail [s]kip%s [q]uit" % (" [r]epeat" if has_fn else "")
    while True:
        raw = _input("  -> %s (+ optional note): " % opts).strip()
        if not raw:
            print("     enter p / f / s / q")
            continue
        parts = raw.split(None, 1)
        tok = parts[0].lower()
        note = parts[1].strip() if len(parts) > 1 else ""
        if tok in ("p", "pass"):
            return "x", note
        if tok in ("f", "fail"):
            return "!", note
        if tok in ("s", "skip"):
            return "~", note
        if tok in ("r", "repeat") and has_fn:
            return "REPEAT", note
        if tok in ("q", "quit"):
            return "QUIT", note
        print("     unrecognized: %r" % tok)


def _run_item(item, section):
    print("\n--- [%s] %s" % (item["id"], item["text"]))
    while True:
        value = None
        if item["fn"]:
            try:
                value = item["fn"]()
            except _Quit:
                raise
            except Exception as e:
                print("  action error: %s" % e)
        if item["record"]:
            label = item["record"] if isinstance(item["record"], str) else "value"
            mv = _input("  record %s (Enter to skip): " % label).strip()
            if mv:
                value = (value + " | " + mv) if value else mv
        verdict, note = _prompt_verdict(bool(item["fn"]))
        if verdict == "REPEAT":
            continue
        if verdict == "QUIT":
            raise _Quit()
        RESULTS.append(
            {
                "id": item["id"],
                "section": section,
                "text": item["text"],
                "verdict": verdict,
                "value": value,
                "note": note,
            }
        )
        _write_report()
        return


def _report_text():
    lines = [
        "# Next-rev bring-up run -- %s" % _ts(),
        "",
        "Source: docs/test/hw-test-log.md (2026-06-30 next-rev bring-up + 2026-05-23 post-fab review).",
        "Markers: [x] pass, [!] fail, [~] skip/blocked, [ ] not reached.",
        "",
    ]
    seen = []
    for r in RESULTS:
        if r["section"] not in seen:
            seen.append(r["section"])
            lines.append("")
            lines.append("## " + r["section"])
        extra = ""
        if r["value"]:
            extra += "  --  " + r["value"]
        if r["note"]:
            extra += "  --  note: " + r["note"]
        lines.append("- [%s] %s %s%s" % (r["verdict"], r["id"], r["text"], extra))
    return "\n".join(lines) + "\n"


def _write_report():
    text = _report_text()
    slug = _ts().replace(" ", "_").replace(":", "")
    for path in ("/sd/diagnostics/bringup_%s.md" % slug, "/local/bringup_%s.md" % slug):
        try:
            d = "/".join(path.split("/")[:-1])
            if d:
                try:
                    os.makedirs(d)
                except Exception:
                    pass
            with open(path, "w") as f:
                f.write(text)
            return path
        except Exception:
            continue
    return None


def _print_summary(path):
    counts = {"x": 0, "!": 0, "~": 0}
    for r in RESULTS:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    total = sum(1 for _, items in SECTIONS for _ in items)
    print("\n" + "=" * 72)
    print("  BRING-UP SUMMARY -- %d/%d items verdicted" % (len(RESULTS), total))
    print("  pass=%d  fail=%d  skip=%d" % (counts["x"], counts["!"], counts["~"]))
    fails = [r for r in RESULTS if r["verdict"] == "!"]
    if fails:
        print("  FAILED:")
        for r in fails:
            print("    [!] %s %s" % (r["id"], (r["note"] or r["text"])[:60]))
    if path:
        print("  report: %s" % path)
    else:
        print("  report: could not write to SD or /local -- console output below:")
        print(_report_text())
    print("=" * 72)


def run():
    print("#" * 72)
    print("#  Pi Greenhouse -- next-rev PCB bring-up runner")
    print("#  %s  (implementation: %s)" % (_ts(), sys.implementation.name))
    print(
        "#  %d items across %d sections. p/f/s per item, q to quit + save."
        % (
            sum(len(items) for _, items in SECTIONS),
            len(SECTIONS),
        )
    )
    print("#" * 72)
    try:
        for section, items in SECTIONS:
            print("\n" + "=" * 72)
            print("## " + section)
            print("=" * 72)
            for item in items:
                _run_item(item, section)
    except _Quit:
        print("\n[bringup] quit early -- partial results saved.")
    finally:
        _safe_all_off()
        path = _write_report()
        _print_summary(path)


if __name__ == "__main__":
    run()
