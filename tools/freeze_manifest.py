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
# Environment inputs (set by tools/build_firmware.ps1):
#   PG_REPO_DIR      absolute path to the greenhouse repo root       (required)
#   PG_FW_INFO_DIR   directory holding the generated fw_info.py      (required)
#   PG_FREEZE_TIER2  set to 1 to also freeze the Tier-2 plumbing set (optional)
#   PG_FREEZE_ONLY   comma-separated filenames; freeze just these    (optional)

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

# --- Tier 2: stable plumbing, blocked on the next-rev migration. ------------
# Their 2026 churn came from the still-open fan-channel remap (B2) and DET
# recovery refactor (B4). Freezing them before those close means a firmware
# rebuild per migration commit. Opt in with PG_FREEZE_TIER2=1 once both land
# and the bench has signed off.
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

_modules = TIER1
if os.environ.get("PG_FREEZE_TIER2") == "1":
    _modules = _modules + TIER2

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

# Frozen as the `lib` package, so `from lib.sht31 import SHT31` resolves
# identically whether the module is frozen or on the filesystem.
package("lib", _modules, base_path=_REPO_DIR)  # noqa: F821 — injected by makemanifest.py

# The firmware's own identity (plan section 4.2). Frozen so no OTA payload can
# overwrite it: a unit must not be able to lie about which firmware it runs.
module("fw_info.py", base_path=_FW_INFO_DIR)  # noqa: F821 — injected by makemanifest.py
