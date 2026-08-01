# MicroPython freeze manifest for the Pi Greenhouse custom firmware.
#
# Consumed by the RP2 port build:
#     make -C ports/rp2 BOARD=RPI_PICO FROZEN_MANIFEST=<abs path to this file>
#
# This is NOT an importable module — it is executed by MicroPython's
# tools/makemanifest.py with freeze()/module()/package()/include() injected as
# globals. Do not import it from device code or from tests.
#
# What belongs here (plan section 2): anything that IS the fixed PCB's
# interface — bus drivers, storage plumbing, LED/button/buzzer, factory wiring.
# What must never appear here: anything that DECIDES when or how much the
# sensors, relays, fans, lights, or heater run. A frozen module can only be
# changed by rebuilding and reflashing the firmware; the SD-payload updater
# cannot touch it. Freeze only what is genuinely cold.
#
# Deliberately absent, and each for a reason:
#   lib/updater.py           the one module whose own bug cannot be fixed by
#                            the mechanism it implements (plan 2.5)
#   lib/regulation_*.py      surface math is stable but retunes land here
#   lib/oled_display.py      new pages ship with every feature
#   lib/relay.py             needs the FanController/GrowlightController split
#                            before its low-level half can freeze cleanly
#   config.py, main.py       the entire mutable OTA surface
#
# WHY TOP-LEVEL MODULES AND NOT A `lib` PACKAGE (2026-07-23, learned the hard way)
#
# This manifest used to freeze `package("lib", ...)`. The firmware built fine
# and contained every module — and nothing could import them. Default RP2
# sys.path is ['', '.frozen', '/lib'], so `''` is searched first: the moment a
# filesystem /lib directory exists (and it must, for the mutable modules), the
# package name `lib` resolves to THAT directory, and the frozen `lib` package
# is never consulted. `import lib.sht31` raised ImportError while
# `help('modules')` happily listed `lib/sht31`.
#
# A package cannot be split across frozen and filesystem. So the frozen set is
# frozen as TOP-LEVEL modules (`sht31`, not `lib.sht31`), and every import site
# tries `lib.<mod>` first and falls back to the bare name:
#
#     try:
#         from lib.sht31 import SHT31
#     except ImportError:      # frozen into the firmware as a top-level module
#         from sht31 import SHT31
#
# lib-first, not frozen-first, on purpose: it keeps host and test behaviour
# byte-identical to a filesystem checkout (host_shims/ contains its own sht31
# simulator that a frozen-first order would start picking up), and only the
# device ever takes the second branch.
#
# Environment inputs (set by the build scripts):
#   PG_REPO_DIR        absolute path to the greenhouse repo root      (required)
#   PG_FW_INFO_DIR     directory holding the generated fw_info.py     (required)
#   PG_FREEZE_TIER1_ONLY  set to 1 to freeze only the Tier-1 set      (optional)
#   PG_FREEZE_ONLY     comma-separated filenames; freeze just these   (optional)

import os

# --- Tier 1: cold, hardware-shaped. The default freeze set. -----------------
TIER1 = (
    # Vendored drivers — protocol-fixed, changed only for upstream bugfixes.
    "sdcard.py",
    "ds3231.py",
    "ssd1306.py",
    # First-party device drivers — register-level, one commit each since 2026.
    "sht31.py",
    "pca9685.py",
    "mcp4725.py",
    # Boot-critical plumbing. Frozen bytecode executes from flash, which is
    # worth most exactly here: these are resident at the moment early-boot OTA
    # is fighting for the last kilobytes of heap (main.py Step 0).
    "boot_log.py",
    "i2c_guard.py",
    # Leaf helpers with no hardware and no policy.
    "sensor_paths.py",
    "buzzer.py",
)

# --- Tier 2: stable plumbing. Frozen since 2026-07-23. ----------------------
# Their 2026 churn came from the still-open fan-channel remap (B2) and DET
# recovery refactor (B4), which is why they were held back initially. Included
# by operator decision once P0.5 measured the heap at 97.5% full: a change to
# one of these now costs a firmware rebuild + reflash instead of an OTA drop.
# Restrict back to Tier-1 with PG_FREEZE_TIER1_ONLY=1 if that trade stops
# paying.
#
# co2_logger.py is NOT here even though its sense+cache half qualifies: it
# still carries the binary hysteresis override that the 0-100 CO2 ramp
# replaces, and freezing the module would freeze that decision logic too.
TIER2 = (
    "status_manager.py",
    "led_button.py",
    "time_provider.py",
    "sd_integration.py",
    "write_queue_manager.py",
    "event_logger.py",
    "buffer_manager.py",
    "hardware_factory.py",
    "temp_humidity_logger.py",
    "metrics_logger.py",
    "soil_logger.py",
)


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            "freeze_manifest.py: %s is not set. This manifest is meant to be invoked by "
            "tools/build_firmware.ps1, which sets it." % name
        )
    return value


_REPO_DIR = _require_env("PG_REPO_DIR")
_FW_INFO_DIR = _require_env("PG_FW_INFO_DIR")

_modules = TIER1 if os.environ.get("PG_FREEZE_TIER1_ONLY") == "1" else TIER1 + TIER2

_only = os.environ.get("PG_FREEZE_ONLY")
if _only:
    # Subset selection for the P0.5 "freeze the coldest first and re-measure"
    # loop. Names outside the tier lists are a typo, not a feature.
    wanted = tuple(name.strip() for name in _only.split(",") if name.strip())
    unknown = [name for name in wanted if name not in TIER1 + TIER2]
    if unknown:
        raise SystemExit("freeze_manifest.py: PG_FREEZE_ONLY names unknown modules: %s" % ", ".join(unknown))
    _modules = wanted

# Keep the port's own defaults — the rp2 board manifest freezes asyncio and
# friends, and dropping them would take the whole async task model with it.
include("$(PORT_DIR)/boards/manifest.py")  # noqa: F821 — injected by makemanifest.py

# Frozen as TOP-LEVEL modules, not as a `lib` package — see the header. The
# sources still live in lib/ in the repo; only their frozen name differs.
_LIB_DIR = _REPO_DIR.rstrip("/").rstrip("\\") + "/lib"
for _name in _modules:
    module(_name, base_path=_LIB_DIR)  # noqa: F821 — injected by makemanifest.py

# The firmware's own identity (plan section 4.2). Frozen so no OTA payload can
# overwrite it: a unit must not be able to lie about which firmware it runs.
module("fw_info.py", base_path=_FW_INFO_DIR)  # noqa: F821 — injected by makemanifest.py
