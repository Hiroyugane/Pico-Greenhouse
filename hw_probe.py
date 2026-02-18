# Hardware Probe Suite — Pi Greenhouse
# Dennis Hiro, 2026-02-17
#
# Comprehensive on-device diagnostic that collects real hardware behaviour data
# for calibrating the host_shims.  Run via:
#     mpremote run hw_probe.py          (quick, no flash needed)
#     mpremote mount . run hw_probe.py  (if lib/ isn't already on flash)
#
# Outputs:
#   - Human-readable console log (always)
#   - JSON file on SD  at /sd/hw_probe_<timestamp>.json   (preferred)
#   - JSON file on flash at /local/hw_probe.json           (fallback)
#
# Duration: 4–6 hours (configurable via DRIFT_HOURS below).
# The suite is self-contained — it imports only MicroPython builtins.
# Probes are independent: one failure never aborts the rest.

import gc
import json
import sys
import time

# ── Tunables ──────────────────────────────────────────────────────────────
DRIFT_HOURS = 4  # How long to measure RTC drift (hours)
DHT_READS_PER_INTERVAL = 250  # Reads per DHT interval bucket
DHT_INTERVALS_S = [0.5, 1.0, 2.0, 5.0]  # Seconds between reads to test
SD_BENCHMARK_BLOCKS = 100  # Number of block reads/writes for benchmarks
BUTTON_TIMEOUT_S = 60  # Seconds to wait for button presses
BUTTON_PRESSES = 10  # Number of button presses to collect
LED_TOGGLE_COUNT = 1000  # Number of LED toggles for timing

# ── Pin map (derived from config.py) ─────────────────────────────────────
from config import DEVICE_CONFIG as _CFG  # noqa: E402

PINS = dict(_CFG["pins"])
# Also expose SPI pins under spi_* aliases (probe code references these)
_spi = _CFG["spi"]
PINS["spi_sck"] = _spi["sck"]
PINS["spi_mosi"] = _spi["mosi"]
PINS["spi_miso"] = _spi["miso"]
PINS["spi_cs"] = _spi["cs"]

HEARTBEAT_PIN = PINS["onboard_led"]
I2C_PORT = PINS["rtc_i2c_port"]
I2C_FREQ = _CFG.get("system", {}).get("i2c_freq", 100_000)
SPI_ID = _spi["id"]
SPI_BAUDRATE = _spi["baudrate"]
DS3231_ADDR = 0x68
SSD1306_ADDR = _CFG.get("display", {}).get("i2c_address", 0x3C)

# ── Results accumulator ──────────────────────────────────────────────────
_results = {}
_errors = []
_probe_log = []  # (timestamp_ms, probe_name, status, message)


# ── Utilities ─────────────────────────────────────────────────────────────
def _ts():
    """ISO-8601 local timestamp string from system clock."""
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6])


def _tms():
    """Current time in milliseconds (wrapping)."""
    return time.ticks_ms()


def _tus():
    """Current time in microseconds (wrapping)."""
    return time.ticks_us()


def _tdiff_ms(start, end):
    return time.ticks_diff(end, start)


def _tdiff_us(start, end):
    return time.ticks_diff(end, start)


def _mean(vals):
    if not vals:
        return 0
    return sum(vals) / len(vals)


def _stddev(vals):
    if len(vals) < 2:
        return 0
    m = _mean(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def _stats(vals):
    """Return dict with min/max/mean/stddev/count."""
    if not vals:
        return {"count": 0, "min": None, "max": None, "mean": None, "stddev": None}
    return {
        "count": len(vals),
        "min": min(vals),
        "max": max(vals),
        "mean": round(_mean(vals), 4),
        "stddev": round(_stddev(vals), 4),
    }


def _bcd2bin(v):
    return (v or 0) - 6 * ((v or 0) >> 4)


def _heartbeat_on():
    from machine import Pin

    Pin(HEARTBEAT_PIN, Pin.OUT).value(1)


def _heartbeat_off():
    from machine import Pin

    Pin(HEARTBEAT_PIN, Pin.OUT).value(0)


def _heartbeat_blink(n=3, ms=100):
    """Quick blink pattern to show life."""
    from machine import Pin

    led = Pin(HEARTBEAT_PIN, Pin.OUT)
    for _ in range(n):
        led.value(1)
        time.sleep_ms(ms)
        led.value(0)
        time.sleep_ms(ms)


def _log(probe_name, status, msg):
    """Print and record a log entry."""
    tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "SKIP": "[SKIP]", "INFO": "[INFO]"}.get(status, "[????]")
    line = "{} {} {} — {}".format(_ts(), tag, probe_name, msg)
    print(line)
    _probe_log.append((_tms(), probe_name, status, msg))


def run_probe(name, fn):
    """Run a single probe with exception safety, timing, and logging."""
    gc.collect()
    mem_before = gc.mem_free()
    _log(name, "INFO", "starting...")
    _heartbeat_blink(1, 50)
    t0 = _tms()
    try:
        result = fn()
        dur = _tdiff_ms(t0, _tms())
        gc.collect()
        mem_after = gc.mem_free()
        result["_duration_ms"] = dur
        result["_mem_before"] = mem_before
        result["_mem_after"] = mem_after
        _results[name] = result
        _log(name, "PASS", "completed in {} ms".format(dur))
        _save_partial_results(name)
        return result
    except Exception as e:
        dur = _tdiff_ms(t0, _tms())
        err_msg = "{}: {}".format(type(e).__name__, e)
        _errors.append({"probe": name, "error": err_msg, "elapsed_ms": dur})
        _results[name] = {"_error": err_msg, "_duration_ms": dur}
        _log(name, "FAIL", err_msg)
        _save_partial_results(name)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  Platform metadata
# ═══════════════════════════════════════════════════════════════════════════
def probe_platform():
    try:
        unique_id = machine.unique_id().hex()
    except Exception:
        unique_id = "unknown"
    try:
        freq = machine.freq()
    except Exception:
        freq = "unknown"
    try:
        import uos  # type: ignore[import-not-found]

        uname = uos.uname()
        uname_dict = {
            "sysname": uname.sysname,
            "nodename": uname.nodename,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
        }
    except Exception:
        uname_dict = {
            "sysname": "unknown",
            "nodename": "unknown",
            "release": "unknown",
            "version": "unknown",
            "machine": "unknown",
        }
    return {
        "implementation": {
            "name": sys.implementation.name,
            "version": list(sys.implementation.version),
        },
        "sys_version": sys.version,
        "sys_platform": sys.platform,
        "uname": uname_dict,
        "machine_freq_hz": freq,
        "unique_id": unique_id,
        "gc_mem_free": gc.mem_free(),
        "gc_mem_alloc": gc.mem_alloc(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  GPIO boot-state (read every pin BEFORE any init)
# ═══════════════════════════════════════════════════════════════════════════
def probe_gpio_boot_state():
    """Read every GPIO as input and record its resting value.

    This must run FIRST before any other probe that calls Pin(n, Pin.OUT).
    """
    from machine import Pin

    readings = {}
    for gp in range(29):  # GP0 .. GP28
        try:
            p = Pin(gp, Pin.IN)
            readings[str(gp)] = p.value()
        except Exception as e:
            readings[str(gp)] = "error: {}".format(e)
    return {"gpio_values": readings}


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  I2C bus scan
# ═══════════════════════════════════════════════════════════════════════════
def probe_i2c_scan():
    from machine import I2C, Pin

    results = {}
    for freq_label, freq_val in [("100kHz", 100_000), ("400kHz", 400_000)]:
        try:
            bus = I2C(I2C_PORT, sda=Pin(PINS["rtc_sda"]), scl=Pin(PINS["rtc_scl"]), freq=freq_val)
            t0 = _tus()
            addrs = bus.scan()
            dur = _tdiff_us(t0, _tus())
            results[freq_label] = {
                "addresses_hex": ["0x{:02X}".format(a) for a in addrs],
                "addresses_int": addrs,
                "scan_us": dur,
            }
        except Exception as e:
            results[freq_label] = {"error": str(e)}
    return results


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  DS3231 register dump + temperature
# ═══════════════════════════════════════════════════════════════════════════
def probe_ds3231_registers():
    from machine import I2C, Pin

    bus = I2C(I2C_PORT, sda=Pin(PINS["rtc_sda"]), scl=Pin(PINS["rtc_scl"]), freq=I2C_FREQ)

    # Read all 19 registers (0x00–0x12)
    raw = bus.readfrom_mem(DS3231_ADDR, 0x00, 19)
    regs = list(raw)

    # Decode time registers
    second = _bcd2bin(regs[0] & 0x7F)
    minute = _bcd2bin(regs[1] & 0x7F)
    hour = _bcd2bin(regs[2] & 0x3F)
    weekday = _bcd2bin(regs[3] & 0x07)
    day = _bcd2bin(regs[4] & 0x3F)
    month = _bcd2bin(regs[5] & 0x1F)
    year = _bcd2bin(regs[6]) + 2000

    # Control register (0x0E)
    control = regs[14]
    # Status register (0x0F)
    status = regs[15]
    # Aging offset (0x10) — signed 8-bit
    aging_raw = regs[16]
    aging = aging_raw if aging_raw < 128 else aging_raw - 256
    # Temperature (0x11–0x12) — 10-bit, 0.25°C resolution
    temp_msb = regs[17]
    temp_lsb = regs[18]
    if temp_msb & 0x80:
        temp_c = -((~temp_msb & 0xFF) + 1) + (temp_lsb >> 6) * 0.25
    else:
        temp_c = temp_msb + (temp_lsb >> 6) * 0.25

    return {
        "raw_hex": ["0x{:02X}".format(b) for b in regs],
        "time": {
            "year": year,
            "month": month,
            "day": day,
            "weekday": weekday,
            "hour": hour,
            "minute": minute,
            "second": second,
            "iso": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(year, month, day, hour, minute, second),
        },
        "control_reg": "0x{:02X}".format(control),
        "status_reg": "0x{:02X}".format(status),
        "aging_offset": aging,
        "board_temp_c": temp_c,
        "alarm1_raw": ["0x{:02X}".format(regs[i]) for i in range(7, 11)],
        "alarm2_raw": ["0x{:02X}".format(regs[i]) for i in range(11, 14)],
        "oscillator_stopped": bool(status & 0x80),
        "32khz_enabled": bool(status & 0x08),
        "busy_converting": bool(status & 0x04),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  ADC baseline (internal temp, Vsys, floating analog pins)
# ═══════════════════════════════════════════════════════════════════════════
def probe_adc_baseline():
    from machine import ADC, Pin

    result = {}
    # Internal temperature sensor is ADC channel 4
    channels = {
        "internal_temp_adc4": ADC(4),
        "gp26_floating": ADC(Pin(26)),
        "gp27_floating": ADC(Pin(27)),
        "gp28_floating": ADC(Pin(28)),
    }
    # GP29 = Vsys on Pico (may not be accessible on all boards)
    try:
        channels["gp29_vsys"] = ADC(Pin(29))
    except Exception as e:
        result["gp29_vsys"] = {"error": str(e)}

    for name, adc in channels.items():
        readings = []
        for _ in range(100):
            readings.append(adc.read_u16())
            time.sleep_us(100)
        vals = readings
        # Convert internal temp: T = 27 - (ADC_V - 0.706) / 0.001721
        if name == "internal_temp_adc4":
            volts = [r * 3.3 / 65535 for r in vals]
            temps = [27.0 - (v - 0.706) / 0.001721 for v in volts]
            result[name] = {
                "raw_u16": _stats(vals),
                "voltage": _stats(volts),
                "temp_c": _stats(temps),
            }
        elif name == "gp29_vsys":
            volts = [r * 3.3 / 65535 * 3 for r in vals]  # Vsys divider ×3
            result[name] = {"raw_u16": _stats(vals), "vsys_v": _stats(volts)}
        else:
            result[name] = {"raw_u16": _stats(vals)}
    return result


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  Memory profile
# ═══════════════════════════════════════════════════════════════════════════
def probe_memory():
    import micropython

    gc.collect()
    info = {
        "mem_free": gc.mem_free(),
        "mem_alloc": gc.mem_alloc(),
        "mem_total": gc.mem_free() + gc.mem_alloc(),
    }
    # Try verbose mem_info — prints to console, can't capture easily
    try:
        micropython.mem_info()  # prints block map to REPL
    except Exception:
        pass
    return info


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  DHT22 endurance (long-running)
# ═══════════════════════════════════════════════════════════════════════════
def probe_dht22_endurance():
    import dht
    from machine import Pin

    sensor = dht.DHT22(Pin(PINS["dht22"]))
    result = {"interval_buckets": {}, "all_temps": [], "all_humids": [], "errors": []}

    total_success = 0
    total_fail = 0

    for interval in DHT_INTERVALS_S:
        bucket_key = "{:.1f}s".format(interval)
        temps = []
        humids = []
        durations_us = []
        errors = []
        consecutive_fails = 0
        max_consecutive_fails = 0
        success = 0
        fail = 0

        _log("dht22_endurance", "INFO", "interval={}s × {} reads".format(interval, DHT_READS_PER_INTERVAL))

        for i in range(DHT_READS_PER_INTERVAL):
            # Heartbeat every 50 reads
            if i % 50 == 0:
                _heartbeat_blink(1, 20)

            t0 = _tus()
            try:
                sensor.measure()
                dur = _tdiff_us(t0, _tus())
                t = sensor.temperature()
                h = sensor.humidity()
                temps.append(t)
                humids.append(h)
                durations_us.append(dur)
                result["all_temps"].append(t)
                result["all_humids"].append(h)
                success += 1
                total_success += 1
                consecutive_fails = 0
            except Exception as e:
                dur = _tdiff_us(t0, _tus())
                fail += 1
                total_fail += 1
                consecutive_fails += 1
                max_consecutive_fails = max(max_consecutive_fails, consecutive_fails)
                errors.append(
                    {
                        "index": i,
                        "type": type(e).__name__,
                        "message": str(e),
                        "args": [str(a) for a in e.args],
                        "duration_us": dur,
                    }
                )

            # Wait the interval (minus measurement time)
            elapsed_ms = dur / 1000
            wait_ms = int(interval * 1000 - elapsed_ms)
            if wait_ms > 0:
                time.sleep_ms(wait_ms)

        result["interval_buckets"][bucket_key] = {
            "interval_s": interval,
            "attempts": DHT_READS_PER_INTERVAL,
            "success": success,
            "fail": fail,
            "fail_rate": round(fail / DHT_READS_PER_INTERVAL, 4) if DHT_READS_PER_INTERVAL else 0,
            "max_consecutive_fails": max_consecutive_fails,
            "temperature": _stats(temps),
            "humidity": _stats(humids),
            "measure_duration_us": _stats(durations_us),
            "error_types": {},
            "errors_sample": errors[:20],  # Keep first 20 errors per bucket
        }
        # Count error types
        for err in errors:
            etype = err["type"]
            result["interval_buckets"][bucket_key]["error_types"][etype] = (
                result["interval_buckets"][bucket_key]["error_types"].get(etype, 0) + 1
            )

    result["totals"] = {
        "total_success": total_success,
        "total_fail": total_fail,
        "overall_fail_rate": round(total_fail / (total_success + total_fail), 4) if (total_success + total_fail) else 0,
        "temperature_all": _stats(result["all_temps"]),
        "humidity_all": _stats(result["all_humids"]),
    }
    # Remove bulky arrays from final output
    del result["all_temps"]
    del result["all_humids"]
    return result


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  SD card init timing + benchmark
# ═══════════════════════════════════════════════════════════════════════════
def probe_sd_card():
    import os

    from machine import SPI, Pin

    result = {}

    # -- Init timing at 100 kHz (standard init speed) ---------------------
    cs_pin = Pin(PINS["spi_cs"], Pin.OUT, value=1)
    spi = SPI(
        SPI_ID, baudrate=100_000, sck=Pin(PINS["spi_sck"]), mosi=Pin(PINS["spi_mosi"]), miso=Pin(PINS["spi_miso"])
    )

    try:
        # Import the sdcard driver from lib/
        from lib.sdcard import SDCard

        t0 = _tus()
        sd = SDCard(spi, cs_pin)
        init_dur = _tdiff_us(t0, _tus())
        result["init_100khz_us"] = init_dur
        result["card_sectors"] = sd.sectors
        result["card_size_mb"] = round(sd.sectors * 512 / (1024 * 1024), 1)
        _log("sd_card", "INFO", "Init@100kHz: {} us, {} sectors".format(init_dur, sd.sectors))
    except Exception as e:
        result["init_100khz_error"] = str(e)
        _log("sd_card", "FAIL", "Init@100kHz failed: {}".format(e))
        # Try to continue with higher speed
        sd = None

    # -- Test various baudrates -------------------------------------------
    baudrate_results = {}
    for baud_label, baud_val in [
        ("1MHz", 1_000_000),
        ("10MHz", 10_000_000),
        ("20MHz", 20_000_000),
        ("40MHz", 40_000_000),
    ]:
        try:
            spi2 = SPI(
                SPI_ID,
                baudrate=baud_val,
                sck=Pin(PINS["spi_sck"]),
                mosi=Pin(PINS["spi_mosi"]),
                miso=Pin(PINS["spi_miso"]),
            )
            sd2 = SDCard(spi2, Pin(PINS["spi_cs"], Pin.OUT, value=1))
            # Read block 0 (MBR) as quick test
            buf = bytearray(512)
            t0 = _tus()
            sd2.readblocks(0, buf)
            rd = _tdiff_us(t0, _tus())
            baudrate_results[baud_label] = {"ok": True, "read_block0_us": rd}
        except Exception as e:
            baudrate_results[baud_label] = {"ok": False, "error": str(e)}
    result["baudrate_tests"] = baudrate_results

    # -- Block-level read benchmark at working speed ----------------------
    try:
        spi_fast = SPI(
            SPI_ID,
            baudrate=SPI_BAUDRATE,
            sck=Pin(PINS["spi_sck"]),
            mosi=Pin(PINS["spi_mosi"]),
            miso=Pin(PINS["spi_miso"]),
        )
        sd_fast = SDCard(spi_fast, Pin(PINS["spi_cs"], Pin.OUT, value=1))
        buf = bytearray(512)

        # Single block reads
        read_times = []
        for i in range(SD_BENCHMARK_BLOCKS):
            t0 = _tus()
            sd_fast.readblocks(i, buf)
            read_times.append(_tdiff_us(t0, _tus()))
        result["read_512b_us"] = _stats(read_times)

        # Single block writes (use high block numbers to avoid MBR/FAT)
        test_block_start = sd_fast.sectors - SD_BENCHMARK_BLOCKS - 100
        if test_block_start < 1000:
            test_block_start = 1000  # Safety margin
        write_times = []
        test_data = bytearray(b"\xa5" * 512)
        for i in range(SD_BENCHMARK_BLOCKS):
            t0 = _tus()
            sd_fast.writeblocks(test_block_start + i, test_data)
            write_times.append(_tdiff_us(t0, _tus()))
        result["write_512b_us"] = _stats(write_times)

    except Exception as e:
        result["benchmark_error"] = str(e)

    # -- VFS-level statvfs ------------------------------------------------
    try:
        svfs = os.statvfs("/sd")
        result["statvfs"] = {
            "f_bsize": svfs[0],
            "f_frsize": svfs[1],
            "f_blocks": svfs[2],
            "f_bfree": svfs[3],
            "f_bavail": svfs[4],
            "f_files": svfs[5],
            "f_ffree": svfs[6],
            "f_favail": svfs[7],
            "f_flag": svfs[8],
            "f_namemax": svfs[9],
        }
    except Exception as e:
        result["statvfs_error"] = str(e)

    # -- VFS-level file I/O timing ----------------------------------------
    try:
        test_path = "/sd/_hw_probe_test.bin"
        sizes = [512, 4096, 16384, 65536]
        file_io = {}
        for sz in sizes:
            data = bytearray(b"\xbb" * sz)
            # Write
            t0 = _tus()
            with open(test_path, "wb") as f:
                f.write(data)
            write_dur = _tdiff_us(t0, _tus())
            # Read
            t0 = _tus()
            with open(test_path, "rb") as f:
                _ = f.read()
            read_dur = _tdiff_us(t0, _tus())
            file_io["{}B".format(sz)] = {
                "write_us": write_dur,
                "read_us": read_dur,
                "write_kBps": round(sz / (write_dur / 1_000_000) / 1024, 1) if write_dur else 0,
                "read_kBps": round(sz / (read_dur / 1_000_000) / 1024, 1) if read_dur else 0,
            }
        result["file_io"] = file_io
        # Cleanup
        try:
            os.remove(test_path)
        except Exception:
            pass
    except Exception as e:
        result["file_io_error"] = str(e)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  SD hot-swap error signatures
# ═══════════════════════════════════════════════════════════════════════════
def probe_sd_hotswap():
    import os

    from machine import SPI, Pin

    result = {"prompted": True, "errors_captured": []}

    print("\n" + "=" * 60)
    print("  SD HOT-SWAP PROBE")
    print("  Remove the SD card NOW, then re-insert when prompted.")
    print("  Waiting up to 30 seconds for card removal...")
    print("=" * 60 + "\n")

    spi = SPI(
        SPI_ID, baudrate=SPI_BAUDRATE, sck=Pin(PINS["spi_sck"]), mosi=Pin(PINS["spi_mosi"]), miso=Pin(PINS["spi_miso"])
    )
    cs = Pin(PINS["spi_cs"], Pin.OUT, value=1)

    try:
        from lib.sdcard import SDCard

        sd = SDCard(spi, cs)
    except Exception as e:
        result["pre_eject_error"] = str(e)
        return result

    buf = bytearray(512)
    card_gone = False
    deadline = time.ticks_add(_tms(), 30_000)

    # Poll until card read fails (= card removed) or timeout
    while _tdiff_ms(_tms(), deadline) > 0:
        try:
            sd.readblocks(0, buf)
            time.sleep_ms(500)
        except Exception as e:
            card_gone = True
            result["errors_captured"].append(
                {
                    "operation": "readblocks_during_eject",
                    "type": type(e).__name__,
                    "message": str(e),
                    "args": [str(a) for a in e.args],
                }
            )
            break

    if not card_gone:
        result["timeout"] = True
        result["prompted"] = False
        _log("sd_hotswap", "SKIP", "Card was not removed within 30s")
        return result

    _log("sd_hotswap", "INFO", "Card removal detected — testing error signatures")

    # Test various operations with card removed
    error_ops = [
        ("readblocks_no_card", lambda: sd.readblocks(0, buf)),
        ("writeblocks_no_card", lambda: sd.writeblocks(0, buf)),
    ]
    # VFS-level ops
    vfs_ops = [
        ("open_read_no_card", lambda: open("/sd/_test.txt", "r")),
        ("open_write_no_card", lambda: open("/sd/_test.txt", "w")),
        ("statvfs_no_card", lambda: os.statvfs("/sd")),
        ("listdir_no_card", lambda: os.listdir("/sd")),
    ]
    for op_name, op_fn in error_ops + vfs_ops:
        try:
            op_fn()
            result["errors_captured"].append(
                {"operation": op_name, "type": "NO_ERROR", "message": "succeeded unexpectedly"}
            )
        except Exception as e:
            result["errors_captured"].append(
                {
                    "operation": op_name,
                    "type": type(e).__name__,
                    "message": str(e),
                    "args": [str(a) for a in e.args],
                }
            )

    # Prompt re-insertion
    print("\n  Re-insert the SD card NOW and press Enter (or wait 30s)...\n")
    reinsert_deadline = time.ticks_add(_tms(), 30_000)
    reinserted = False
    while _tdiff_ms(_tms(), reinsert_deadline) > 0:
        try:
            spi2 = SPI(
                SPI_ID,
                baudrate=100_000,
                sck=Pin(PINS["spi_sck"]),
                mosi=Pin(PINS["spi_mosi"]),
                miso=Pin(PINS["spi_miso"]),
            )
            sd2 = SDCard(spi2, Pin(PINS["spi_cs"], Pin.OUT, value=1))
            sd2.readblocks(0, buf)
            reinserted = True
            result["reinsert_ok"] = True
            _log("sd_hotswap", "INFO", "Card re-inserted successfully")
            break
        except Exception:
            time.sleep_ms(1000)

    if not reinserted:
        result["reinsert_ok"] = False
        _log("sd_hotswap", "INFO", "Card not re-inserted within timeout")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  Relay switching timing
# ═══════════════════════════════════════════════════════════════════════════
def probe_relays():
    from machine import Pin

    relay_pins = {
        "relay_fan_1": PINS["relay_fan_1"],
        "relay_fan_2": PINS["relay_fan_2"],
        "relay_growlight": PINS["relay_growlight"],
    }
    result = {}

    for name, gpio in relay_pins.items():
        entry = {}

        # Read pre-init state
        p_in = Pin(gpio, Pin.IN)
        entry["pre_init_value"] = p_in.value()

        # Init as output, HIGH (relay OFF due to inverted logic)
        p = Pin(gpio, Pin.OUT, value=1)
        entry["init_value_readback"] = p.value()

        # Measure LOW→HIGH (ON→OFF transition, inverted)
        toggle_times_on = []
        toggle_times_off = []
        for _ in range(50):
            # Turn ON (LOW)
            t0 = _tus()
            p.value(0)
            dur = _tdiff_us(t0, _tus())
            toggle_times_on.append(dur)
            readback_on = p.value()
            time.sleep_ms(20)

            # Turn OFF (HIGH)
            t0 = _tus()
            p.value(1)
            dur = _tdiff_us(t0, _tus())
            toggle_times_off.append(dur)
            readback_off = p.value()
            time.sleep_ms(20)

        entry["turn_on_us"] = _stats(toggle_times_on)
        entry["turn_off_us"] = _stats(toggle_times_off)
        entry["readback_on_matches"] = readback_on == 0  # ON = LOW
        entry["readback_off_matches"] = readback_off == 1  # OFF = HIGH

        # Leave relay OFF (HIGH)
        p.value(1)
        entry["final_state"] = p.value()

        result[name] = entry

    return result


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  Button bounce characterization
# ═══════════════════════════════════════════════════════════════════════════
def probe_button_bounce():
    from machine import Pin

    result = {
        "pin": PINS["button_menu"],
        "pull": "PULL_UP",
        "presses_requested": BUTTON_PRESSES,
        "events": [],
        "press_analyses": [],
    }

    btn = Pin(PINS["button_menu"], Pin.IN, Pin.PULL_UP)
    events = []  # (ticks_us, edge_direction)

    def _isr(pin):
        t = _tus()
        v = pin.value()
        events.append((t, v))

    btn.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=_isr)

    print("\n" + "=" * 60)
    print("  BUTTON BOUNCE PROBE (GP{})".format(PINS["button_menu"]))
    print("  Press the menu button {} times.".format(BUTTON_PRESSES))
    print("  Waiting up to {} seconds...".format(BUTTON_TIMEOUT_S))
    print("=" * 60 + "\n")

    deadline = time.ticks_add(_tms(), BUTTON_TIMEOUT_S * 1000)
    press_count = 0
    last_event_count = 0

    # Wait for button activity — detect "press" as a burst of events
    # followed by 500ms of silence
    while _tdiff_ms(_tms(), deadline) > 0 and press_count < BUTTON_PRESSES:
        time.sleep_ms(100)
        if len(events) > last_event_count:
            # Events arrived — wait for 500ms silence to call it "one press"
            silence_start = _tms()
            while _tdiff_ms(silence_start, _tms()) < 500:
                if len(events) > last_event_count + (len(events) - last_event_count):
                    silence_start = _tms()
                time.sleep_ms(10)
                current_count = len(events)
                if current_count != last_event_count:
                    last_event_count = current_count
                    silence_start = _tms()
            press_count += 1
            _log(
                "button_bounce",
                "INFO",
                "Press {}/{} detected ({} edges)".format(press_count, BUTTON_PRESSES, len(events)),
            )
            last_event_count = len(events)

    # Disable IRQ
    btn.irq(handler=None)

    # Store raw events
    result["total_edges"] = len(events)
    result["events_raw"] = [(t, v) for t, v in events[:500]]  # Cap at 500

    # Analyze: group events into presses (gaps > 200ms)
    if events:
        presses = []
        current_press = [events[0]]
        for i in range(1, len(events)):
            gap = _tdiff_us(events[i - 1][0], events[i][0])
            if gap > 200_000:  # 200ms gap = new press
                presses.append(current_press)
                current_press = [events[i]]
            else:
                current_press.append(events[i])
        presses.append(current_press)

        for pi, press_events in enumerate(presses):
            if len(press_events) < 2:
                continue
            # Find first falling (value=0) and last rising (value=1)
            fallings = [(t, v) for t, v in press_events if v == 0]
            risings = [(t, v) for t, v in press_events if v == 1]
            total_dur = _tdiff_us(press_events[0][0], press_events[-1][0])

            # Bounce: edges between first FALLING and first stable low
            bounce_edges = len(press_events) - 2  # exclude first and last
            # Intervals between consecutive edges
            intervals = [_tdiff_us(press_events[j][0], press_events[j + 1][0]) for j in range(len(press_events) - 1)]

            result["press_analyses"].append(
                {
                    "press_index": pi,
                    "total_edges": len(press_events),
                    "falling_edges": len(fallings),
                    "rising_edges": len(risings),
                    "total_duration_us": total_dur,
                    "bounce_edge_count": bounce_edges,
                    "edge_intervals_us": _stats(intervals),
                }
            )

    result["summary"] = {
        "presses_detected": len(result["press_analyses"]),
        "avg_bounce_edges": _mean([p["bounce_edge_count"] for p in result["press_analyses"]])
        if result["press_analyses"]
        else 0,
        "avg_total_duration_us": _mean([p["total_duration_us"] for p in result["press_analyses"]])
        if result["press_analyses"]
        else 0,
    }
    return result


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  LED toggle timing
# ═══════════════════════════════════════════════════════════════════════════
def probe_led_timing():
    from machine import Pin

    led_pins = {
        "activity_led_gp4": PINS["activity_led"],
        "reminder_led_gp5": PINS["reminder_led"],
        "sd_led_gp6": PINS["sd_led"],
        "warning_led_gp7": PINS["warning_led"],
        "error_led_gp8": PINS["error_led"],
        "onboard_led_gp25": PINS["onboard_led"],
    }
    result = {}

    for name, gpio in led_pins.items():
        p = Pin(gpio, Pin.OUT, value=0)
        durations = []
        for _ in range(LED_TOGGLE_COUNT):
            t0 = _tus()
            p.value(1)
            p.value(0)
            dur = _tdiff_us(t0, _tus())
            durations.append(dur)
        result[name] = {
            "gpio": gpio,
            "toggle_pair_us": _stats(durations),
        }
        p.value(0)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# PROBE:  RTC drift measurement (LONG RUNNING)
# ═══════════════════════════════════════════════════════════════════════════
def probe_rtc_drift():
    from machine import I2C, Pin

    bus = I2C(I2C_PORT, sda=Pin(PINS["rtc_sda"]), scl=Pin(PINS["rtc_scl"]), freq=I2C_FREQ)
    result = {
        "drift_hours": DRIFT_HOURS,
        "measurements": [],
        "ds3231_temps": [],
    }

    def _read_rtc_seconds():
        """Read DS3231 time and return total seconds since midnight."""
        raw = bus.readfrom_mem(DS3231_ADDR, 0x00, 7)
        s = _bcd2bin(raw[0] & 0x7F)
        m = _bcd2bin(raw[1] & 0x7F)
        h = _bcd2bin(raw[2] & 0x3F)
        d = _bcd2bin(raw[4] & 0x3F)
        return d * 86400 + h * 3600 + m * 60 + s

    def _read_ds3231_temp():
        """Read DS3231 internal temperature register."""
        raw = bus.readfrom_mem(DS3231_ADDR, 0x11, 2)
        msb = raw[0]
        lsb = raw[1]
        if msb & 0x80:
            return -((~msb & 0xFF) + 1) + (lsb >> 6) * 0.25
        return msb + (lsb >> 6) * 0.25

    def _system_seconds():
        """Pico system time as total seconds since midnight."""
        t = time.localtime()
        return t[2] * 86400 + t[3] * 3600 + t[4] * 60 + t[5]

    # Initial readings
    rtc0 = _read_rtc_seconds()
    sys0 = _system_seconds()
    t0_ms = _tms()

    _log("rtc_drift", "INFO", "Starting {}h drift measurement".format(DRIFT_HOURS))
    total_measurements = DRIFT_HOURS * 60  # one per minute

    # Also set up DHT sensor for interleaved reads during drift
    dht_temps = []
    dht_humids = []
    dht_errors = 0
    try:
        import dht

        dht_sensor = dht.DHT22(Pin(PINS["dht22"]))
    except Exception:
        dht_sensor = None

    for i in range(total_measurements):
        time.sleep(60)  # Wait 1 minute

        # RTC drift measurement
        try:
            rtc_now = _read_rtc_seconds()
            sys_now = _system_seconds()
            elapsed_ms = _tdiff_ms(t0_ms, _tms())

            rtc_elapsed = rtc_now - rtc0
            sys_elapsed = sys_now - sys0
            drift_ms = (rtc_elapsed - sys_elapsed) * 1000

            ds3231_temp = _read_ds3231_temp()

            result["measurements"].append(
                {
                    "elapsed_min": round(elapsed_ms / 60000, 2),
                    "rtc_elapsed_s": rtc_elapsed,
                    "sys_elapsed_s": sys_elapsed,
                    "drift_ms": drift_ms,
                    "ds3231_temp_c": ds3231_temp,
                }
            )
            result["ds3231_temps"].append(ds3231_temp)
        except Exception as e:
            result["measurements"].append(
                {
                    "elapsed_min": round(_tdiff_ms(t0_ms, _tms()) / 60000, 2),
                    "error": str(e),
                }
            )

        # Interleaved DHT22 read (every other minute)
        if dht_sensor and i % 2 == 0:
            try:
                dht_sensor.measure()
                dht_temps.append(dht_sensor.temperature())
                dht_humids.append(dht_sensor.humidity())
            except Exception:
                dht_errors += 1

        # Progress heartbeat + console update every 10 min
        _heartbeat_blink(1, 30)
        if (i + 1) % 10 == 0:
            _log(
                "rtc_drift",
                "INFO",
                "Progress: {}/{} min, drift={} ms, temp={:.1f}°C".format(
                    i + 1,
                    total_measurements,
                    result["measurements"][-1].get("drift_ms", "?"),
                    result["measurements"][-1].get("ds3231_temp_c", 0),
                ),
            )

    # Summary
    drifts = [m["drift_ms"] for m in result["measurements"] if "drift_ms" in m]
    result["drift_summary"] = _stats(drifts)
    if len(drifts) >= 2:
        # Compute ppm: drift_ms over elapsed_s
        total_elapsed_s = result["measurements"][-1].get("rtc_elapsed_s", 1)
        if total_elapsed_s:
            result["drift_ppm"] = round((drifts[-1] / 1000) / total_elapsed_s * 1_000_000, 3)
    result["ds3231_temp_summary"] = _stats(result["ds3231_temps"])
    result["interleaved_dht"] = {
        "temperatures": _stats(dht_temps),
        "humidities": _stats(dht_humids),
        "errors": dht_errors,
    }
    del result["ds3231_temps"]  # Remove bulky array
    return result


# ═══════════════════════════════════════════════════════════════════════════
# OUTPUT:  Write JSON + console summary
# ═══════════════════════════════════════════════════════════════════════════
def write_results():
    import os

    payload = {
        "probe_version": "1.0.0",
        "probe_start": _ts(),
        "probes": _truncate_large_arrays(_results),
        "errors": _errors,
        "log": [{"ts_ms": e[0], "probe": e[1], "status": e[2], "msg": e[3]} for e in _probe_log],
    }

    json_str = json.dumps(payload)

    paths_tried = []
    for path in ["/sd/hw_probe_{}.json".format(_ts().replace(" ", "_").replace(":", "")), "/local/hw_probe.json"]:
        try:
            dir_path = "/".join(path.split("/")[:-1])
            if dir_path:
                try:
                    os.makedirs(dir_path)
                except Exception:
                    pass
            with open(path, "w") as f:
                f.write(json_str)
            _log("output", "PASS", "JSON written to {}  ({} bytes)".format(path, len(json_str)))
            payload["_output_path"] = path
            return payload
        except Exception as e:
            paths_tried.append("{}: {}".format(path, e))

    _log("output", "FAIL", "Could not write JSON: {}".format(paths_tried))
    print("\n--- JSON OUTPUT (copy/paste) ---")
    print(json_str)
    print("--- END JSON ---\n")
    return payload


def _save_partial_results(probe_name):
    import os

    partial_payload = {
        "probe_version": "1.0.0",
        "probe_start": _ts(),
        "probes": _truncate_large_arrays(_results),
        "errors": _errors,
        "log": [{"ts_ms": e[0], "probe": e[1], "status": e[2], "msg": e[3]} for e in _probe_log],
        "last_probe": probe_name,
    }
    try:
        json_str = json.dumps(partial_payload)
        for path in ["/sd/hw_probe_partial.json", "/local/hw_probe_partial.json"]:
            try:
                dir_path = "/".join(path.split("/")[:-1])
                if dir_path:
                    try:
                        os.makedirs(dir_path)
                    except Exception:
                        pass
                with open(path, "w") as f:
                    f.write(json_str)
                break
            except Exception:
                continue
    except Exception:
        pass


def _truncate_large_arrays(results):
    # Truncate or summarize large arrays in probe results
    truncated = {}
    for k, v in results.items():
        if k == "rtc_drift" and "measurements" in v:
            arr = v["measurements"]
            if len(arr) > 12:
                v["measurements"] = arr[:6] + arr[-6:]
                v["measurements_truncated"] = True
        if k == "dht22_endurance" and "interval_buckets" in v:
            for bucket in v["interval_buckets"].values():
                for arr_key in ["errors_sample"]:
                    if arr_key in bucket and isinstance(bucket[arr_key], list) and len(bucket[arr_key]) > 20:
                        bucket[arr_key] = bucket[arr_key][:10] + bucket[arr_key][-10:]
                        bucket[arr_key + "_truncated"] = True
        truncated[k] = v
    return truncated


def print_summary():
    print("\n" + "=" * 70)
    print("  HARDWARE PROBE SUITE — SUMMARY")
    print("=" * 70)
    for name, data in _results.items():
        err = data.get("_error")
        dur = data.get("_duration_ms", "?")
        if err:
            print("  [FAIL] {:<30s} {}ms — {}".format(name, dur, err))
        else:
            print("  [PASS] {:<30s} {}ms".format(name, dur))
    if _errors:
        print("\n  Errors:")
        for e in _errors:
            print("    - {}: {}".format(e["probe"], e["error"]))
    print("=" * 70 + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN — Orchestrate all probes
# ═══════════════════════════════════════════════════════════════════════════
import machine  # noqa: E402  — imported here to keep probes self-contained

print("\n" + "#" * 70)
print("#  Pi Greenhouse — Hardware Probe Suite v1.0")
print("#  Date: {}".format(_ts()))
print("#  Implementation: {}".format(sys.implementation.name))
print("#  Estimated duration: {}+ hours".format(DRIFT_HOURS))
print("#" * 70 + "\n")

# Phase 1: Passive probes (must run GPIO boot state FIRST)
run_probe("gpio_boot_state", probe_gpio_boot_state)
run_probe("platform", probe_platform)
run_probe("i2c_scan", probe_i2c_scan)
run_probe("ds3231_registers", probe_ds3231_registers)
run_probe("adc_baseline", probe_adc_baseline)
run_probe("memory", probe_memory)

# Phase 2: Active probes
run_probe("led_timing", probe_led_timing)
run_probe("relays", probe_relays)
run_probe("button_bounce", probe_button_bounce)

# Phase 3: SD card probes
run_probe("sd_card", probe_sd_card)
run_probe("sd_hotswap", probe_sd_hotswap)

# Phase 4: Long-running probes
run_probe("dht22_endurance", probe_dht22_endurance)
run_probe("rtc_drift", probe_rtc_drift)

# Phase 5: Output
write_results()
print_summary()

_heartbeat_blink(5, 200)
print("Probe suite complete.")
