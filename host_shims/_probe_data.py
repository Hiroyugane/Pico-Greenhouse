"""Probe data loader — bridges real hardware measurements into host shims.

Reads the JSON output from ``hw_probe.py`` (collected on the real Pico) and
exposes calibrated constants that each host shim imports.  If no probe data
file is found, sensible defaults (informed by datasheets & manual observation)
are returned so the shims always work.

Usage inside a shim::

    from host_shims._probe_data import PROBE

    dht_fail_rate = PROBE.dht.fail_rate
    sd_statvfs    = PROBE.sd.statvfs_tuple
    gpio_boot     = PROBE.gpio.boot_state
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ── Locate probe results ──────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SEARCH_PATHS = [
    # probe_results/ in project root (pulled from device)
    _PROJECT_ROOT / "probe_results",
    # Project root
    _PROJECT_ROOT,
]


def _find_latest_probe_json() -> dict | None:
    """Find and load the most recent hw_probe_*.json file."""
    candidates: list[Path] = []
    for d in _SEARCH_PATHS:
        if d.is_dir():
            candidates.extend(d.glob("hw_probe*.json"))
    if not candidates:
        return None
    # Sort by modification time, newest first
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    try:
        with open(candidates[0], "r") as f:
            return json.load(f)
    except Exception:
        return None


# ── Data classes for typed access ─────────────────────────────────────────

@dataclass
class GPIODefaults:
    """Default GPIO pin values observed at cold boot before any init."""

    # Map of gpio_number (int) → resting value (0 or 1).
    boot_state: dict[int, int] = field(default_factory=lambda: {  # type: ignore[assignment]
        # Datasheet defaults: all GPIO float at boot; pull-ups on I2C lines
        # may read 1, everything else ≈ 0 (input high-Z with ~60µA sink).
        0: 1, 1: 1,         # I2C SDA/SCL — external pull-ups
        2: 0, 3: 0,         # UART TX/RX
        4: 0, 5: 0, 6: 0, 7: 0, 8: 0,  # LEDs
        9: 1, 14: 1,        # Buttons with PULL_UP
        10: 0, 11: 0, 12: 0, 13: 1,  # SPI (CS is pulled high)
        15: 0,              # DHT22 data
        16: 1, 17: 1, 18: 1,  # Relays (pull HIGH = off)
        19: 0, 20: 0, 21: 0, 22: 0,  # Reserved
        25: 0,              # On-board LED
        26: 0, 27: 0, 28: 0,  # ADC
    })


@dataclass
class I2CDefaults:
    """I2C bus scan results and timing."""

    addresses: list[int] = field(default_factory=lambda: [0x68])  # type: ignore[assignment]  # DS3231
    scan_us: int = 2500  # Typical scan duration at 100 kHz
    # DS3231 register state at boot
    ds3231_control: int = 0x1C   # INTCN=1, A2IE=A1IE=0
    ds3231_status: int = 0x00    # OSF=0, no alarms
    aging_offset: int = 0
    drift_ppm: float = 0.5      # Typical DS3231 drift


@dataclass
class DHTDefaults:
    """DHT22 sensor behaviour model calibrated from probe data."""

    temp_mean: float = 23.0
    temp_stddev: float = 0.8
    temp_min: float = 18.0
    temp_max: float = 35.0
    humid_mean: float = 60.0
    humid_stddev: float = 3.0
    humid_min: float = 30.0
    humid_max: float = 90.0
    # Error injection model
    fail_rate: float = 0.02       # 2% of reads fail (OSError)
    max_consecutive_fails: int = 3
    min_interval_s: float = 0.5   # Minimum time between reads
    measure_duration_us: int = 5000  # Typical measure() duration
    # Error types observed
    error_types: dict[str, float] = field(default_factory=lambda: {  # type: ignore[assignment]
        "OSError": 0.95,   # Most common
        "EAGAIN": 0.05,    # Occasional
    })


@dataclass
class SDDefaults:
    """SD card behaviour model."""

    init_time_us: int = 250_000   # Typical init duration at 100 kHz
    read_512b_mean_us: int = 800  # Mean single-block read latency
    read_512b_max_us: int = 5000
    write_512b_mean_us: int = 3000
    write_512b_max_us: int = 50_000  # Write can have long busy-waits
    card_sectors: int = 15_523_840  # ~8 GB
    card_size_mb: float = 7580.0
    max_baudrate: int = 40_000_000
    # statvfs values (real FAT32 stats)
    statvfs_tuple: tuple = (4096, 4096, 1940480, 1920000, 1920000, 0, 0, 0, 0, 255)
    # Hot-swap error signatures
    hotswap_errors: dict[str, dict] = field(default_factory=lambda: {  # type: ignore[assignment]
        "readblocks": {"type": "OSError", "errno": 5, "message": "[Errno 5] EIO"},
        "writeblocks": {"type": "OSError", "errno": 5, "message": "[Errno 5] EIO"},
        "open_file": {"type": "OSError", "errno": 2, "message": "[Errno 2] ENOENT"},
        "statvfs": {"type": "OSError", "errno": 19, "message": "[Errno 19] ENODEV"},
    })
    # File I/O benchmarks (KB/s)
    file_write_kBps: float = 180.0
    file_read_kBps: float = 500.0


@dataclass
class ButtonDefaults:
    """Button bounce characteristics."""

    avg_bounce_edges: float = 4.0
    avg_bounce_duration_us: int = 2500
    min_edge_interval_us: int = 50
    max_edge_interval_us: int = 3000


@dataclass
class LEDDefaults:
    """GPIO toggle timing."""

    toggle_pair_us_mean: float = 2.0     # ~2µs for a HIGH+LOW pair at 125 MHz
    toggle_pair_us_max: float = 10.0


@dataclass
class MemoryDefaults:
    """Heap profile."""

    mem_total: int = 192_512    # Typical Pico free heap
    mem_free_at_boot: int = 160_000
    mem_alloc_at_boot: int = 32_512


@dataclass
class PlatformDefaults:
    """Platform identification strings returned by MicroPython."""

    implementation_name: str = "micropython"
    implementation_version: list = field(default_factory=lambda: [1, 24, 1])  # type: ignore[assignment]
    sys_platform: str = "rp2"
    uname_sysname: str = "rp2"
    uname_nodename: str = "rp2"
    uname_release: str = "1.24.1"
    uname_version: str = "v1.24.1 on 2024-11-29 (GNU 13.2.0 MinSizeRel)"
    uname_machine: str = "Raspberry Pi Pico with RP2040"
    machine_freq_hz: int = 125_000_000
    unique_id: str = "e66038b713784a32"


@dataclass
class ADCDefaults:
    """ADC baseline readings."""

    internal_temp_c_mean: float = 27.0
    internal_temp_c_stddev: float = 0.5
    vsys_v_mean: float = 3.28
    floating_noise_u16_max: int = 500


@dataclass
class ProbeData:
    """Top-level container for all probe-derived calibration data."""

    gpio: GPIODefaults = field(default_factory=GPIODefaults)  # type: ignore[assignment]
    i2c: I2CDefaults = field(default_factory=I2CDefaults)  # type: ignore[assignment]
    dht: DHTDefaults = field(default_factory=DHTDefaults)  # type: ignore[assignment]
    sd: SDDefaults = field(default_factory=SDDefaults)  # type: ignore[assignment]
    button: ButtonDefaults = field(default_factory=ButtonDefaults)  # type: ignore[assignment]
    led: LEDDefaults = field(default_factory=LEDDefaults)  # type: ignore[assignment]
    memory: MemoryDefaults = field(default_factory=MemoryDefaults)  # type: ignore[assignment]
    platform: PlatformDefaults = field(default_factory=PlatformDefaults)  # type: ignore[assignment]
    adc: ADCDefaults = field(default_factory=ADCDefaults)  # type: ignore[assignment]
    loaded_from: str | None = None


def _populate_from_json(data: dict, probe: ProbeData) -> None:
    """Overwrite defaults with real probe measurements where available."""
    probes = data.get("probes", {})

    # -- GPIO boot state --
    gbs = probes.get("gpio_boot_state", {}).get("gpio_values", {})
    for k, v in gbs.items():
        try:
            probe.gpio.boot_state[int(k)] = int(v)
        except (ValueError, TypeError):
            pass

    # -- Platform --
    plat = probes.get("platform", {})
    impl = plat.get("implementation", {})
    if impl.get("name"):
        probe.platform.implementation_name = impl["name"]
    if impl.get("version"):
        probe.platform.implementation_version = impl["version"]
    uname = plat.get("uname", {})
    for field_name in ("sysname", "nodename", "release", "version", "machine"):
        val = uname.get(field_name)
        if val:
            setattr(probe.platform, "uname_" + field_name, val)
    if plat.get("machine_freq_hz"):
        probe.platform.machine_freq_hz = plat["machine_freq_hz"]
    if plat.get("unique_id"):
        probe.platform.unique_id = plat["unique_id"]

    # -- I2C scan --
    i2c = probes.get("i2c_scan", {})
    scan_100 = i2c.get("100kHz", {})
    if scan_100.get("addresses_int"):
        probe.i2c.addresses = scan_100["addresses_int"]
    if scan_100.get("scan_us"):
        probe.i2c.scan_us = scan_100["scan_us"]

    # -- DS3231 registers --
    ds = probes.get("ds3231_registers", {})
    if ds.get("aging_offset") is not None:
        probe.i2c.aging_offset = ds["aging_offset"]
    ctrl = ds.get("control_reg")
    if ctrl:
        probe.i2c.ds3231_control = int(ctrl, 16)
    stat = ds.get("status_reg")
    if stat:
        probe.i2c.ds3231_status = int(stat, 16)

    # -- DHT22 endurance --
    dht = probes.get("dht22_endurance", {})
    totals = dht.get("totals", {})
    if totals.get("overall_fail_rate") is not None:
        probe.dht.fail_rate = totals["overall_fail_rate"]
    temp_all = totals.get("temperature_all", {})
    if temp_all.get("mean") is not None:
        probe.dht.temp_mean = temp_all["mean"]
    if temp_all.get("stddev") is not None:
        probe.dht.temp_stddev = temp_all["stddev"]
    if temp_all.get("min") is not None:
        probe.dht.temp_min = temp_all["min"]
    if temp_all.get("max") is not None:
        probe.dht.temp_max = temp_all["max"]
    humid_all = totals.get("humidity_all", {})
    if humid_all.get("mean") is not None:
        probe.dht.humid_mean = humid_all["mean"]
    if humid_all.get("stddev") is not None:
        probe.dht.humid_stddev = humid_all["stddev"]
    if humid_all.get("min") is not None:
        probe.dht.humid_min = humid_all["min"]
    if humid_all.get("max") is not None:
        probe.dht.humid_max = humid_all["max"]
    # Inspect interval buckets for min_interval and measure_duration
    buckets = dht.get("interval_buckets", {})
    for bk, bv in buckets.items():
        dur = bv.get("measure_duration_us", {})
        if dur.get("mean"):
            probe.dht.measure_duration_us = int(dur["mean"])
        # Find the fastest interval with 0% fail rate
        if bv.get("fail_rate", 1) == 0:
            probe.dht.min_interval_s = bv.get("interval_s", 0.5)

    # -- SD card --
    sd = probes.get("sd_card", {})
    if sd.get("card_sectors"):
        probe.sd.card_sectors = sd["card_sectors"]
    if sd.get("card_size_mb"):
        probe.sd.card_size_mb = sd["card_size_mb"]
    if sd.get("init_100khz_us"):
        probe.sd.init_time_us = sd["init_100khz_us"]
    rd = sd.get("read_512b_us", {})
    if rd.get("mean"):
        probe.sd.read_512b_mean_us = int(rd["mean"])
    if rd.get("max"):
        probe.sd.read_512b_max_us = int(rd["max"])
    wr = sd.get("write_512b_us", {})
    if wr.get("mean"):
        probe.sd.write_512b_mean_us = int(wr["mean"])
    if wr.get("max"):
        probe.sd.write_512b_max_us = int(wr["max"])
    svfs = sd.get("statvfs", {})
    if svfs:
        probe.sd.statvfs_tuple = (
            svfs.get("f_bsize", 4096),
            svfs.get("f_frsize", 4096),
            svfs.get("f_blocks", 0),
            svfs.get("f_bfree", 0),
            svfs.get("f_bavail", 0),
            svfs.get("f_files", 0),
            svfs.get("f_ffree", 0),
            svfs.get("f_favail", 0),
            svfs.get("f_flag", 0),
            svfs.get("f_namemax", 255),
        )
    fio = sd.get("file_io", {})
    for sz_key, sz_data in fio.items():
        if "write_kBps" in sz_data:
            probe.sd.file_write_kBps = sz_data["write_kBps"]
        if "read_kBps" in sz_data:
            probe.sd.file_read_kBps = sz_data["read_kBps"]
    # Hot-swap errors
    hswap = probes.get("sd_hotswap", {})
    for entry in hswap.get("errors_captured", []):
        op = entry.get("operation", "")
        if "readblock" in op:
            probe.sd.hotswap_errors["readblocks"] = {
                "type": entry.get("type", "OSError"),
                "message": entry.get("message", ""),
            }
        elif "writeblock" in op:
            probe.sd.hotswap_errors["writeblocks"] = {
                "type": entry.get("type", "OSError"),
                "message": entry.get("message", ""),
            }

    # -- Button bounce --
    btn = probes.get("button_bounce", {})
    summary = btn.get("summary", {})
    if summary.get("avg_bounce_edges"):
        probe.button.avg_bounce_edges = summary["avg_bounce_edges"]
    if summary.get("avg_total_duration_us"):
        probe.button.avg_bounce_duration_us = int(summary["avg_total_duration_us"])

    # -- LED timing --
    led = probes.get("led_timing", {})
    for led_name, led_data in led.items():
        tp = led_data.get("toggle_pair_us", {})
        if tp.get("mean"):
            probe.led.toggle_pair_us_mean = tp["mean"]
        if tp.get("max"):
            probe.led.toggle_pair_us_max = tp["max"]
        break  # Use first LED's data as representative

    # -- Memory --
    mem = probes.get("memory", {})
    if mem.get("mem_total"):
        probe.memory.mem_total = mem["mem_total"]
    if mem.get("mem_free"):
        probe.memory.mem_free_at_boot = mem["mem_free"]
    if mem.get("mem_alloc"):
        probe.memory.mem_alloc_at_boot = mem["mem_alloc"]

    # -- ADC baseline --
    adc = probes.get("adc_baseline", {})
    it = adc.get("internal_temp_adc4", {}).get("temp_c", {})
    if it.get("mean"):
        probe.adc.internal_temp_c_mean = it["mean"]
    if it.get("stddev"):
        probe.adc.internal_temp_c_stddev = it["stddev"]
    vsys = adc.get("gp29_vsys", {}).get("vsys_v", {})
    if vsys.get("mean"):
        probe.adc.vsys_v_mean = vsys["mean"]

    # -- RTC drift --
    drift = probes.get("rtc_drift", {})
    if drift.get("drift_ppm") is not None:
        probe.i2c.drift_ppm = drift["drift_ppm"]


def load_probe_data() -> ProbeData:
    """Load probe data from the most recent JSON file, or use defaults."""
    probe = ProbeData()
    raw = _find_latest_probe_json()
    if raw:
        _populate_from_json(raw, probe)
        # Record which file was loaded
        for d in _SEARCH_PATHS:
            if d.is_dir():
                files = sorted(d.glob("hw_probe*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                if files:
                    probe.loaded_from = str(files[0])
                    break
    return probe


# ── Module-level singleton ────────────────────────────────────────────────
PROBE = load_probe_data()
