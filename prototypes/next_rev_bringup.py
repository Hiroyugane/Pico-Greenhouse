# Next-rev PCB bring-up runner — Pi Greenhouse
# Dennis Hiro, 2026-06-30
#
# Linear, tick-as-you-go walk-through of the FIRMWARE-ASSISTED next-rev bench
# checks that are still OUTSTANDING — the subset of docs/test/hw-test-log.md
# where running code helps and the item has not yet passed:
#   * single-channel fan PWM sanity (invert direction + does duty 0 fully
#     stop — see config pca9685.invert and the fans pca9685_ch map),
#   * soil TLC555 three-point calibration (dry > wet),
#   * per-relay isolation cycle over the wired REL_CON ports only.
# Checks that already PASSED (SD card-detect polarity, I2C scan, grow-light
# DAC sweep, heater-gate drive, soil AOUT-moves) were removed once recorded
# in docs/test/next-rev-results.md — re-add them here only if a board change
# invalidates the pass. Pure design-review / visual / multimeter-only items
# and full-firmware behaviours (SD recovery, soaks) live in hw-test-log.md.
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
# SAFETY: the fan-spin and per-relay steps actuate real loads. Each asks for
# explicit confirmation first and forces every output back OFF afterwards
# (try/finally). The relay cycle energises one relay at a time — anything
# wired to the growlight or reserved channels (mains grow light, pumps) WILL
# switch, so run it with those loads unplugged unless you intend them to fire.

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
SOIL_PIN = _PINS["adc_input"]  # GP28
I2C_PORT = _PINS["rtc_i2c_port"]
I2C_SDA = _PINS["rtc_sda"]
I2C_SCL = _PINS["rtc_scl"]
I2C_FREQ = DEVICE_CONFIG.get("system", {}).get("i2c_freq", 400000)
FAN_RAMP_S = 10  # fan ramp-down duration (s) for the per-channel PWM check
RELAY_PULSE_S = DEVICE_CONFIG.get("display", {}).get("debug", {}).get("test_relay_pulse_s", 1)

# Relay roster for the isolation cycle: only the REL_CON channels actually
# populated with a relay, active-low (HIGH=off, LOW=on). The 2026-07-05
# bench found REL_CON pins 6-8 (GP22/GP26/GP27, the old relay_reserved_2/3/4)
# carry no relay module — GP22 is the future water-level input and GP26/GP27
# are the future I2C1 bus (docs/hardware/next-revision.md). So cycle the four
# wired ports only: growlight (drives a real load) plus the two fan relays
# freed by the PCA9685 move plus the one wired reserved channel.
_RELAY_KEYS = (
    "relay_growlight",
    "relay_cooler",
    "relay_humidifier",
    "relay_reserved_1",
)
RELAY_PINS = [(k, _PINS[k]) for k in _RELAY_KEYS if k in _PINS]

# Accumulated verdicts; the report is rebuilt from this after each item.
RESULTS = []

# Lazily-built, cached hardware handles (None until first needed / on host).
_I2C = None
_PCA = None


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
        _PCA = PCA9685(bus, address=cfg["i2c_address"], freq_hz=cfg["freq_hz"], invert=cfg.get("invert", False))
    except Exception as e:
        print("  PCA9685 init failed (%s) — chip absent? record manually." % e)
        _PCA = None
    return _PCA


def _safe_all_off():
    """Force every actuated output OFF. Called on exit no matter what."""
    if machine is None:
        return
    try:
        if _PCA is not None:
            _PCA.all_off()
    except Exception:
        pass
    # Drive every relay pin to its OFF level (HIGH = off, active-low modules).
    for _, pin_no in RELAY_PINS:
        try:
            machine.Pin(pin_no, machine.Pin.OUT).value(1)
        except Exception:
            pass


# ------------------------------------------------------------ action fns
# Each returns a short string captured into the report's "value" column,
# or None. They never raise out — _run_item wraps them too.


def _load_print_raw():
    try:
        from lib.soil_logger import print_raw

        return print_raw
    except Exception as e:
        print("    lib.soil_logger.print_raw unavailable: %s" % e)
        return None


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
    # Single-channel PWM sanity check. The 2026-07-05 re-run confirmed every
    # channel spins hardware-side, so the per-channel sweep is dropped — one
    # representative channel is enough to verify duty direction and the OPEN
    # question: does duty 0 reach a true mechanical stop? Force EVERY channel
    # off first (isolates cross-talk), drive the lowest-numbered pca9685 fan at
    # 100 %, 50 %, then ramp to 0 % over FAN_RAMP_S. Duty is corrected by
    # pca9685.invert, so the ramp should visibly SLOW the fan; a fan that speeds
    # UP means the invert flag is wrong, and a fan that keeps windmilling at 0 %
    # is the inverting gate stage not pulling the MOSFET fully off (hardware —
    # see docs/hardware/next-revision.md fan gate-stage entry).
    pca = _pca()
    if pca is None:
        return None
    roster = sorted(
        (c["pca9685_ch"], role) for role, c in DEVICE_CONFIG["fans"].items() if c.get("output") == "pca9685"
    )
    if not roster:
        print("    no pca9685-backed fans in config — nothing to spin.")
        return None
    ch, role = roster[0]
    if not _confirm("    Fan clear to spin? [y/N]: "):
        return "actuation skipped"
    steps = 50
    try:
        pca.all_off()  # every channel OFF before isolating this one
        print("    --- ch%d '%s': all other channels forced OFF ---" % (ch, role))
        pca.set_duty(ch, 100)
        _input("      100%% — confirm ONLY '%s' (ch%d) spins, all others OFF (Enter)..." % (role, ch))
        pca.set_duty(ch, 50)
        _input("      50%% — confirm it is visibly SLOWER (Enter)...")
        print("      ramping 50%% -> 0%% over %d s..." % FAN_RAMP_S)
        for i in range(steps + 1):
            pca.set_duty(ch, 50.0 * (steps - i) / steps)
            time.sleep(FAN_RAMP_S / steps)
        pca.set_duty(ch, 0)
        ans = _input("      ch%d ramped smoothly and came to a FULL stop at 0%%? [y/n] + note: " % ch).strip()
        return "ch%d/%s:%s" % (ch, role, ans or "?")
    finally:
        pca.all_off()


def act_relays():
    # Per-relay isolation cycle: force EVERY relay OFF, then energise one at a
    # time (active-low: value(0)=on) for RELAY_PULSE_S so a single click /
    # module LED / load pins the wiring to exactly one GP pin. Confirms no
    # pin<->relay swap and that idle relays don't twitch when a neighbour fires.
    if machine is None:
        print("    [machine unavailable — record relay clicks manually]")
        return None
    if not RELAY_PINS:
        print("    no relay_* pins in config — nothing to cycle.")
        return None
    if not _confirm("    Relays clear to switch (loads unplugged unless intended)? [y/N]: "):
        return "actuation skipped"
    pins = {k: machine.Pin(p, machine.Pin.OUT) for k, p in RELAY_PINS}
    for p in pins.values():
        p.value(1)  # all OFF (active-low) before isolating any one
    results = []
    try:
        for key, pin_no in RELAY_PINS:
            print("    --- %s (GP%d): all other relays forced OFF ---" % (key, pin_no))
            prompt = "    Enter to energise ONLY %s for %ss (or 's' to skip): " % (key, RELAY_PULSE_S)
            if _input(prompt).strip().lower() == "s":
                results.append("%s:skip" % key)
                continue
            pins[key].value(0)  # ON
            time.sleep(RELAY_PULSE_S)
            pins[key].value(1)  # OFF
            ans = _input("      ONLY %s clicked ON then OFF, others idle? [y/n] + note: " % key).strip()
            results.append("%s:%s" % (key, ans or "?"))
    finally:
        for p in pins.values():
            p.value(1)
    return " | ".join(results)


# --------------------------------------------------------------- checklist


def _item(id_, text, fn=None, record=False):
    return {"id": id_, "text": text, "fn": fn, "record": record}


# Firmware-assisted bench items only, and only those still OUTSTANDING —
# passed checks live in docs/test/next-rev-results.md; design-review /
# multimeter-only checks and full-firmware behaviours in hw-test-log.md.
SECTIONS = [
    (
        "Fans — single-channel PWM sanity (PCA9685, invert + hard-stop check)",
        [
            _item(
                "FAN.1",
                "One representative channel ramps 100->50->0; confirm it slows (invert correct) and "
                "reaches a FULL stop at 0%.",
                act_fan_channels,
            ),
        ],
    ),
    (
        "Soil (TLC555 / GP28, plant mode)",
        [
            _item(
                "SOIL.2",
                "3-point air/moist/water separate, dry>wet; then set adc_dry_raw/adc_wet_raw + reboot for %/LED/CSV.",
                act_soil_three_point,
            ),
        ],
    ),
    (
        "Relays — per-channel isolation cycle (active-low)",
        [
            _item(
                "REL.1",
                "Each wired relay energises ALONE (others off): growlight + the two freed fan relays + "
                "the one wired reserved channel click on/off, no pin<->relay swap.",
                act_relays,
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
