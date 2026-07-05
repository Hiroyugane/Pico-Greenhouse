# Next-rev PCB bring-up runner — Pi Greenhouse
# Dennis Hiro, 2026-06-30
#
# Linear, tick-as-you-go walk-through of the FIRMWARE-ASSISTED next-rev bench
# checks — the subset of docs/test/hw-test-log.md where running code helps:
# per-channel fan isolation + PWM, SD card-detect polarity, soil TLC555 raw,
# I2C scan, grow-light DAC sweep, heater-gate drive. Pure design-review /
# visual / multimeter-only items (footprints, resistor values, trace widths,
# rail voltages) and full-firmware behaviours (thermostat, SD recovery, soaks)
# live in hw-test-log.md, NOT here.
#
# Each item is presented IN ORDER: firmware takes the live reading or actuates
# the output, then you verdict it [p]ass / [f]ail / [s]kip. Notes you type are
# KEPT even if you forget the verdict letter first. A Markdown report is
# written to /sd/diagnostics/ (falling back to /local/) after every item.
#
# HOW TO RUN — needs an interactive REPL for input():
#   Thonny:   open this file, press Run (F5). Answer prompts in the Shell.
#   mpremote: mpremote run prototypes/next_rev_bringup.py   (or: run bringup)
# Run it STANDALONE (not while main.py is running) so nothing else drives the
# bus or the relays.
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
FAN_RAMP_S = 10  # fan ramp-down duration (s) for the per-channel PWM check

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
    known = {
        0x3C: "OLED",
        0x40: "PCA9685",
        0x44: "SHT31",
        0x57: "AT24C32 EEPROM (DS3231 module)",
        0x60: "MCP4725",
        0x68: "DS3231",
    }
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


def act_fan_channels():
    # Per-channel isolation + PWM: force EVERY channel off, then drive only the
    # selected one at 100 %, 50 %, and a smooth ramp to 0 % over FAN_RAMP_S.
    # Zeroing all channels first is what isolates a cross-talk / stuck-100 %
    # fault (each fan should move only while its own channel is driven).
    pca = _pca()
    if pca is None:
        return None
    roster = sorted(
        (c["pca9685_ch"], role) for role, c in DEVICE_CONFIG["fans"].items() if c.get("output") == "pca9685"
    )
    if not _confirm("    All fans clear to spin? [y/N]: "):
        return "actuation skipped"
    results = []
    steps = 50
    try:
        for ch, role in roster:
            pca.all_off()  # every channel OFF before isolating this one
            print("    --- ch%d '%s': all other channels forced OFF ---" % (ch, role))
            if _input("    Enter to spin ONLY ch%d (or 's' to skip): " % ch).strip().lower() == "s":
                results.append("ch%d/%s:skip" % (ch, role))
                continue
            pca.set_duty(ch, 100)
            _input("      100%% — confirm ONLY '%s' spins, all others OFF (Enter)..." % role)
            pca.set_duty(ch, 50)
            _input("      50%% — confirm it is visibly SLOWER (Enter)...")
            print("      ramping 50%% -> 0%% over %d s..." % FAN_RAMP_S)
            for i in range(steps + 1):
                pca.set_duty(ch, 50.0 * (steps - i) / steps)
                time.sleep(FAN_RAMP_S / steps)
            pca.set_duty(ch, 0)
            ans = _input("      ONLY ch%d ramped smoothly to a stop? [y/n] + note: " % ch).strip()
            results.append("ch%d/%s:%s" % (ch, role, ans or "?"))
    finally:
        pca.all_off()
    return " | ".join(results)


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


# --------------------------------------------------------------- checklist


def _item(id_, text, fn=None, record=False):
    return {"id": id_, "text": text, "fn": fn, "record": record}


# Firmware-assisted bench items only. Design-review / visual / multimeter-only
# checks and full-firmware behaviours live in docs/test/hw-test-log.md, not here.
SECTIONS = [
    (
        "Fans — per-channel isolation + PWM (PCA9685 ch0-ch4)",
        [
            _item(
                "FAN.1",
                "Each channel spins ALONE (all others off) and ramps 100->50->0 smoothly; confirm role<->channel.",
                act_fan_channels,
            ),
        ],
    ),
    (
        "SD card-detect (DET / GP15)",
        [
            _item(
                "DET.1",
                "Polarity: DET with card vs empty; confirm sd_detect.present_when_low matches reality.",
                act_det_polarity,
            ),
            _item(
                "DET.2",
                "Firmware read cross-check: GP15 level maps to card PRESENT / ABSENT as expected.",
                act_det_read,
            ),
        ],
    ),
    (
        "Soil (TLC555 / GP28, plant mode)",
        [
            _item(
                "SOIL.1",
                "AOUT moves on submersion (VCC->3V3 pin36, AOUT->GP28, no divider).",
                act_soil_live,
            ),
            _item(
                "SOIL.2",
                "3-point air/moist/water separate, dry>wet; then set adc_dry_raw/adc_wet_raw + reboot for %/LED/CSV.",
                act_soil_three_point,
            ),
        ],
    ),
    (
        "I2C bus scan",
        [
            _item(
                "I2C.1",
                "Scan lists 0x3C OLED, 0x40 PCA9685, 0x44 SHT31, 0x57 EEPROM, 0x60 MCP4725, 0x68 DS3231.",
                act_i2c_scan,
            ),
        ],
    ),
    (
        "Grow light — MCP4725 DAC + LM358",
        [
            _item(
                "GL.1",
                "DAC sweep 0/25/50/75/100 %; GL_DIM+ ~0/2.6/5.2/7.7/10.3 V, ~9.4 V clamp at 100 %.",
                act_dac_sweep,
            ),
        ],
    ),
    (
        "Heater gate driver (MCP1416 / GP3)",
        [
            _item(
                "GATE.1",
                "Drive GP3 HIGH (gated): IRLZ44N V_GS ~5 V; scope the edge here for GD.8 if wanted.",
                act_gp3_drive,
            ),
        ],
    ),
]


# ------------------------------------------------------------------ runner


_VERDICTS = {"p": "x", "pass": "x", "f": "!", "fail": "!", "s": "~", "skip": "~", "q": "QUIT", "quit": "QUIT"}


def _prompt_verdict(has_fn):
    # A note typed before (or instead of) a verdict is KEPT, not discarded —
    # the tester can jot an observation and still be asked for the verdict.
    opts = "[p]ass [f]ail [s]kip%s [q]uit" % (" [r]epeat" if has_fn else "")
    pending = ""
    while True:
        raw = _input("  -> %s  ('f my note' inline, or type a note then a verdict): " % opts).strip()
        if not raw:
            print("     verdict required — enter p / f / s%s / q" % (" / r" if has_fn else ""))
            continue
        if raw.startswith("+"):  # explicit note marker
            raw = raw[1:].strip()
        parts = raw.split(None, 1)
        tok = parts[0].lower()
        inline = parts[1].strip() if len(parts) > 1 else ""
        verdict = _VERDICTS.get(tok)
        if verdict is None and tok in ("r", "repeat") and has_fn:
            verdict = "REPEAT"
        if verdict is None:
            # Not a verdict -> the whole line is a note. Keep it and re-ask.
            pending = (pending + " " + raw).strip()
            print("     note kept — now give a verdict (p / f / s%s / q)" % (" / r" if has_fn else ""))
            continue
        note = (pending + " " + inline).strip()
        return verdict, note


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
        "Runner: prototypes/next_rev_bringup.py (firmware-assisted next-rev bench items).",
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


# Slug is fixed on the first save so the per-item crash-safety saves
# overwrite ONE report per run instead of leaving a file per answer.
_RUN_SLUG = None


def _write_report():
    global _RUN_SLUG
    if _RUN_SLUG is None:
        _RUN_SLUG = _ts().replace(" ", "_").replace(":", "")
    slug = _RUN_SLUG
    text = _report_text()
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
