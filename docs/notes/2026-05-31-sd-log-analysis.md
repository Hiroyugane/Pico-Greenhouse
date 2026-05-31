# SD log & sensor analysis — 12-day field run (2026-05-19 → 2026-05-31)

**Source:** `sd/` snapshot pulled from the Pico's SD card after >10 days
continuous uptime (mushroom mode).
**Streams:** `sensors/th/*` (temp+RH) and `sensors/co2/*`, both 30 s cadence;
`logs/system.log` (4366 lines), `logs/updates.log`.
**Coverage:** 34,298 samples per stream, 2026-05-19 20:06:53 →
2026-05-31 19:40:43. Focus per request: firmware/control logic,
storage/logging, reliability.

---

## 1. Sensor aggregation (daily + overall)

### Temperature (°C)

| Date | n | min | mean | max | σ |
|------|----:|----:|-----:|----:|---:|
| 05-19 (partial) | 368 | 20.5 | 20.83 | 21.8 | 0.30 |
| 05-20 | 2870 | 19.4 | 20.43 | 24.1 | 0.94 |
| 05-21 | 2871 | 20.1 | 20.88 | 22.3 | 0.37 |
| 05-22 | 2870 | 20.2 | 22.37 | 25.6 | 1.52 |
| 05-23 | 2871 | 20.9 | 22.77 | 25.4 | 1.02 |
| 05-24 | 2870 | 22.0 | 22.99 | 24.7 | 0.73 |
| 05-25 | 2871 | 22.7 | 23.45 | 25.6 | 0.41 |
| 05-26 | 2871 | 22.3 | 24.79 | 30.2 | 2.01 |
| 05-27 | 2870 | 22.8 | 24.28 | 25.2 | 0.59 |
| 05-28 | 2871 | 22.3 | 23.85 | 25.3 | 0.83 |
| 05-29 | 2870 | 22.7 | 24.13 | 25.9 | 0.93 |
| 05-30 | 2871 | 23.0 | 24.43 | 25.3 | 0.53 |
| 05-31 (partial) | 2354 | 23.7 | 24.46 | 25.3 | 0.44 |
| **Overall** | **34298** | **19.4** | **23.19** | **30.2** | **1.69** |

### Humidity (% RH)

| Date | n | min | mean | max | σ |
|------|----:|----:|-----:|----:|---:|
| 05-19 (partial) | 368 | 60.0 | 63.30 | 65.8 | 1.29 |
| 05-20 | 2870 | 55.9 | 64.65 | 89.5 | 4.03 |
| 05-21 | 2871 | 50.3 | 63.98 | 70.1 | 5.09 |
| 05-22 | 2870 | 42.5 | 56.36 | 64.6 | 6.77 |
| 05-23 | 2871 | 48.4 | 57.84 | 61.8 | 3.04 |
| 05-24 | 2870 | 48.0 | 60.59 | 66.4 | 4.00 |
| 05-25 | 2871 | 44.9 | 60.62 | 65.9 | 3.78 |
| 05-26 | 2871 | 28.2 | 50.04 | 62.2 | 10.56 |
| 05-27 | 2870 | 52.5 | 55.40 | 60.9 | 2.09 |
| 05-28 | 2871 | 31.5 | 45.61 | 61.2 | 5.53 |
| 05-29 | 2870 | 39.0 | 50.66 | 64.4 | 8.26 |
| 05-30 | 2871 | 56.2 | 59.69 | 62.4 | 1.33 |
| 05-31 (partial) | 2354 | 47.9 | 60.22 | 66.0 | 3.83 |
| **Overall** | **34298** | **28.2** | **57.16** | **89.5** | **7.83** |

### CO₂ (ppm)

| Date | n | min | mean | max | σ |
|------|----:|----:|-----:|----:|---:|
| 05-19 (partial) | 368 | 2510 | 3368 | 3848 | 312 |
| 05-20 | 2870 | 1828 | 3339 | 5681 | 839 |
| 05-21 | 2871 | 1709 | 2632 | 4661 | 861 |
| 05-22 | 2870 | 1681 | 2120 | 2909 | 234 |
| 05-23 | 2871 | 1678 | 2275 | 3103 | 350 |
| 05-24 | 2870 | 1790 | 3074 | 4767 | 815 |
| 05-25 | 2871 | 1666 | 3212 | 5095 | 1188 |
| 05-26 | 2871 | 1663 | 2167 | 3311 | 454 |
| 05-27 | 2870 | 1746 | 2223 | 3896 | 346 |
| 05-28 | 2871 | 1752 | 2041 | 4286 | 283 |
| 05-29 | 2870 | 1678 | 1892 | 2494 | 194 |
| 05-30 | 2871 | 1502 | 2063 | 2465 | 282 |
| 05-31 (partial) | 2354 | 1471 | 1734 | 2395 | 275 |
| **Overall** | **34298** | **1471** | **2418** | **5681** | **793** |

**Trends:** room temperature drifts up over the run (mean 20.4 → 24.5 °C,
seasonal); CO₂ trends down (mean ~3340 → ~1730 ppm) consistent with a
colonization→fruiting transition; RH is the noisiest channel (σ 7.8,
several daily dips into the 30s–40s %).

---

## 2. Findings & optimizations (prioritized)

### [HIGH · logging] 95 % of `system.log` is routine fan-schedule spam
`growroom_walls` runs a 20 s-ON / ~8.3 min-period circulation duty cycle.
Every transition is logged at INFO: **2042 `SCHEDULE ON` + 2054
`SCHEDULE OFF` = 4096 of 4366 lines (94 %)**. This buries the only signal
that matters — 2 `ERR` and 35 `WARN`, all on commissioning day — and each
transition is also an SD append through `BufferManager`.
**Fix:** demote scheduled (non-override) fan transitions to DEBUG or
suppress entirely; keep `THERMOSTAT`/`EXTERNAL OVERRIDE` transitions at
INFO. Optionally log a once-per-hour fan-runtime summary instead. Net
log drops to ~18 meaningful lines/day.

### [MEDIUM · reliability/HW] `growroom_walls` relay cycles ~62,600×/year
172 cycles/day × 365 ≈ 62.6 k. A mechanical relay switching an inductive
fan is rated ~100 k cycles under load → **~1.6 yr contact life**, then
arcing/weld risk. Already covered by the queued **PCA9685 PWM fan
revision** (`project_fan_hardware_revision`); this run quantifies the
urgency. A wall-circulation fan ideally shouldn't be relay-cycled at
all — continuous low-speed PWM is the correct model once the driver lands.
No new next-revision entry — reinforces the existing one.

### [MEDIUM · control] CO₂ override target (>1000 ppm) is never reached
CO₂ floor across 12 days is **1471 ppm** (mean 2418); it never drops below
1000. Only 2 `exhaust EXTERNAL OVERRIDE ON` events exist, both on
commissioning day, **none in steady state**. Either (a) the override path
isn't firing after boot, or (b) exhaust lacks fresh-air-exchange capacity
to pull below 1000. If the high CO₂ is intentional for the colonization
phase, the 1000 ppm threshold is misleading and should be re-stated.
**Action:** confirm the CO₂→exhaust override actually engages in steady
state (instrument the transition), then set the threshold to match crop
phase rather than leaving a setpoint the system can't meet.

### [LOW · control] Heater is effectively idle; cooling now dominates
After 05-24 ambient sits above the 22 °C day setpoint, so the heater
rarely engages. Exhaust thermostat activations rise instead (15 over the
run, accelerating). The exhaust band is tight (ON 23.8 / OFF 23.3,
0.5 °C hysteresis) and produced brief re-trigger chatter (e.g. 05-23
11:36→11:45→11:47). **Action:** seasonal setpoint review; consider
widening exhaust hysteresis to ~1.0 °C to cut short-cycling.

### [INFO · reliability] Steady-state is excellent; instability was boot-only
11.9 days continuous since the last reset (05-19 20:58) — **zero resets,
zero data gaps, zero sensor failures** in steady state. Commissioning day
alone saw 3 WDT + 7 PWRON resets and one 49-min data gap; the WDT resets
mean the main loop blocked past the watchdog window during early boot
(likely SD-mount retries / sensor init). Self-resolved, never recurred.
**Residual risk:** a field power-cycle coinciding with an SD hiccup could
re-enter that boot-WDT loop. Consider feeding the WDT during long init
steps or staging initialization.

### [LOW · storage] CSV cadence is clean; no retention policy yet
2871/2880 expected rows/day (99.7 %); the ~9 missing/day is loop-period
drift just over 30 s, **not gaps** (one real 49-min gap, commissioning
only). Volume ≈ 144 KB/day both streams → ~52 MB/yr. Fine for the card,
but no rotation/retention exists. Minor: `ServiceReminder` re-logs
`Init: 7d interval` on every boot (10× during commissioning).

---

## 3. Reproduce

Ad-hoc analysis scripts were run against `sd/` and not committed (the
aggregation is captured in the tables above). Cadence = 30 s; rows parsed
with `%Y-%m-%d %H:%M:%S`; daily buckets keyed on local date; gaps flagged
at >3× median inter-sample delta.
