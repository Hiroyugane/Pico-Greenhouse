# Prompt: Implement the RegulationEngine (3.5-D situation → reaction matrix)

Use this prompt with Claude (Fable) to replace all per-device control logic
(fan thermostat/schedule, heater cycle, CO2 override, growlight scheduler)
with one unified, config-driven regulation pipeline.

Architecture was decided by council deliberation on 2026-07-06 — see
chat-log.
Do not re-litigate the encoding choice; open questions are listed at the end.

---

## Context

Pi Greenhouse: MicroPython on a Raspberry Pi Pico, same source runs on host
CPython via `host_shims/`. Read `CLAUDE.md` first — DI-only wiring in
`main.py`, `RelayController(invert=True)` for all relays (active-low), all
config in `DEVICE_CONFIG` validated at boot, coverage gate 88 %, async
watchdog (long-blocking code bricks the device). **Heap is at ~81 % of
245 KB** — the per-tick path must be allocation-free (pre-built float
arrays, reused buffers, no dict/list/f-string churn in the loop; debug
logging guarded by a flag).

## Goal

Every 30 s (configurable), the engine:

1. reads cached sensor values (existing loggers stay the sensor source,
   e.g. `th_logger.last_temperature` — do not add new sensor reads),
2. normalizes them into **deviation space**: each dimension 0–100 where
   50 = ideal for the *current mode and time of day*,
3. evaluates one tuned **2D hinge surface per regulator** → raw intensity
   0–100,
4. classifies severity bands and runs an **arbitration pass** (floors,
   conflict overrides, emergency, latch),
5. writes the commanded vector through **actuator adapters** (PWM directly;
   relays via hysteresis + min-cycle).

Dimensions: temperature, humidity, CO2. Time-of-day is **not** a deviation
dimension — it blends day/night setpoint profiles and drives the growlight.
External temperature/humidity (second sensor, may be absent) only gates
exhaust effectiveness. This is the "3.5".

## Stage 1 — Normalization

- Per mode (`greenhouse`, `mushroom`, extensible), per phase (`day`,
  `night`), each dimension has three anchors in physical units:
  `at_0`, `at_50`, `at_100` (asymmetric piecewise-linear; strict vs loose
  tuning = anchor spacing). Example: day temp `{at_0: 14.0, at_50: 24.0,
  at_100: 34.0}` → 29 °C maps to 75.
- Time-of-day blend `b ∈ [0,1]` from the RTC time provider: `day_start_min`,
  `day_end_min`, `transition_min` (linear ramp on both edges; `b=1` full
  day, `b=0` full night). Effective anchor = `night + b·(day − night)`.
- Growlight target = `b × light_level_day` for the dimmable path (gradual
  dawn/dusk dimming falls out of the blend for free); on/off bulbs get the
  hysteresis adapter over the same value.
- Deviation `d ∈ [0,100]`, severity `s = abs(d − 50) ∈ [0,50]`.

## Stage 2 — Surfaces (the ported Excel model)

Each surface is a pure function `f(x, y) → 0..100` over two deviation
inputs. Exact math (float, no allocation; `relu(v) = v if v > 0 else 0`):

```
xc = x - 50 ; yc = y - 50
lin    = gain * (xc*ca + yc*sa) + offset - cross * (xc*sa + yc*ca)
hinges = hx_hi1*relu(x - bx_hi1) + hx_hi2*relu(x - bx_hi2)
       + hx_lo1*relu(bx_lo1 - x) + hx_lo2*relu(bx_lo2 - x)
       + hy_hi1*relu(y - by_hi1) + hy_hi2*relu(y - by_hi2)
       + hy_lo1*relu(by_lo1 - y) + hy_lo2*relu(by_lo2 - y)
boost_axis(v, hi, lo) = base + (v - hi)*grad  if v > hi
                        base + (lo - v)*grad  if v < lo
                        1                     otherwise
raw = (lin + hinges) * mult * boost_axis(x,...) * boost_axis(y,...)
out = min(max(raw, out_min), out_max)   # then rescale to 0..100 command
```

Mapping from the operator's Excel sheet (German: `WENN`=IF,
`GANZZAHL`=INT, comma decimals): Angle/Rotation → `ca`/`sa`/`cross`;
Shift → `offset`; Bandwidth → `gain`; the eight `[X±1/2] [Y±1/2]`
Angle/Shift rows → hinge slope/breakpoint pairs; Top/Bot-X/Y → boost
edges; Multiplier/Gradient → `mult`/`grad`; Minimum/Maximum → clamps.
The port is parameter-compatible in spirit, **golden vectors define
truth** (see Testing) — do not chase cell-by-cell Excel equivalence.

Per-regulator assignment:

| Regulator            | x        | y       | Extras                                          |
|----------------------|----------|---------|-------------------------------------------------|
| heater               | temp dev | RH dev  | —                                               |
| heater_follower fan  | — derived: `clamp(heater_out*gain + floor)` |         |
| cooler               | temp dev | RH dev  | on/off adapter, compressor min-cycle            |
| humidifier           | RH dev   | temp dev| —                                               |
| exhaust fan          | temp dev | RH dev  | `+ co2_gain*relu(co2_dev − co2_break)` additive; × external-effectiveness multiplier |
| circulation (center+wall) | temp dev | RH dev | one surface, two duty scalers (`center_scale`, `wall_scale`) |
| growlight            | — driven by ToD blend, not a surface |  | participates in emergency/latch |

External-effectiveness multiplier (exhaust only): from the *optional*
second SHT31 (`external_sensor.enabled`, default `false` → multiplier 1.0).
Piecewise-linear over `(T_inside − T_outside)`: full effect when outside is
cooler by ≥ `full_delta_c`, floor `min_factor` when outside is as warm/
warmer; an analogous RH factor; multiply both.

## Stage 3 — Band classification

`band_edges = [5, 10, 20, 30, 40, 50]` (configurable, strictly ascending,
last = 50): perfect / ideal / organic / minor / major / emergency /
shutdown. A regulator's band = max severity over the dimensions it consumes
(exhaust includes CO2). A global band = max over all dimensions.

## Stage 4 — Arbitration (order is safety-critical)

Per tick, in exactly this order — **stages 3–6 write forced values AFTER
the slew limiter and are never slew-limited.** A conflict cut (e.g. mold
risk) must land in one tick, not smeared across several:

1. **Surfaces** → target vector `T[7]`.
2. **Slew limit** vs last commanded: max delta/tick = `slew_normal`
   (band < 20) or `slew_fast` (band 20–39). Organic output only.
3. **Floors** (regulator band ≥ 20): `T[i] = max(T[i], floor)` — floors
   only push toward stronger actuation.
4. **Conflict overrides** (global band ≥ 30): ordered rule list from
   config, later rules win. Rule shape:
   `{"when": [("humidity", "above", 30), ("temp", "above", 30)],
     "force": {"humidifier": 0}, "prefer": {"exhaust": 60, "cooler": 100}}`
   — `when` terms AND-combined (`above`/`below` × severity-band
   threshold on the *signed* side of 50), `force` sets exact values,
   `prefer` applies `max()`. Ship the canonical example above (hot+humid
   → humidifier hard-cut, exhaust+cooler preferred) as a default rule.
5. **Emergency** (any dim severity ≥ 40): apply per-regulator emergency
   values, sound buzzer pattern, write event log (rate-limited to one
   entry per band entry, not per tick).
6. **Latch** (any dim severity = 50): switch to the configured safe-state
   vector (heat + humidity sources off, exhaust max, alarm) and **latch**:
   release only after ALL severities ≤ `latch_release_max` (default 30)
   for `latch_release_ticks` consecutive ticks AND `latch_min_s` elapsed.
   Entry and exit both event-logged.

## Stage 5 — Actuator adapters

Surfaces stay continuous; device quirks live only here:

- **PWM fans** (PCA9685 ch0 center, ch1 walls, ch2 heater-follower,
  ch4 exhaust): intensity → duty via existing `fan_output` path (respect
  the `invert` config; never raw writes).
- **Heater** (MOSFET GP3, on/off today): time-proportioning window —
  duty = intensity over `window_s` (default 600 s), with `min_on_s`/
  `min_off_s`. Design the adapter so a future gate-driver rev can switch
  it to real PWM by config.
- **Relays** (cooler, humidifier, growlight-as-bulb): hysteresis
  `on_above` / `off_below` (in intensity units, `on_above > off_below`)
  plus `min_on_s` / `min_off_s`. Cooler defaults `min_off_s = 300`
  (compressor anti-short-cycle). All through
  `RelayController(invert=True)`.
- **Growlight dimmable path**: MCP4725 DAC (`lib/mcp4725.py`) 0–10 V via
  the LM358 stage; `dimmable: true|false` selects DAC vs relay adapter.

## Config schema

Everything above lands under `DEVICE_CONFIG["regulation"]` — modes/anchors,
`tick_s`, band edges, per-regulator `{surface: {...}, adapter: {...},
slew_normal, slew_fast, floor, emergency_value, safe_state}`, `conflicts`
(ordered list), `external_sensor`, latch keys. Consumption is DI-only:
`main.py` reads the dict, the engine takes plain values/arrays — no
`DEVICE_CONFIG` import inside `lib/`.

Define the surface/adapter parameter sets **once** as shared schemas
(name, type, lo, hi). `validate_config()` loops regulators × schema;
`tests/test_config.py` uses `pytest.parametrize` over the same schema —
do NOT hand-write ~190 per-key asserts (they'd be rubber-stamped noise).
Also validate cross-key invariants: anchors strictly ordered, band edges
ascending to 50, `on_above > off_below`, `slew_* > 0`, conflict rules
reference real regulator/dimension names.

At boot, freeze each regulator's params into `array('f')` (or tuples)
addressed by index; the tick reads/writes preallocated buffers only.

## Module layout

Flat in `lib/` per project convention, each file focused (<400 lines):
`regulation_normalizer.py`, `regulation_surface.py`,
`regulation_arbiter.py`, `regulation_adapters.py`,
`regulation_engine.py` (the uasyncio task: tick loop, await-friendly,
feeds state to `status_manager`/OLED as the old controllers did).

## Replacement scope

Remove once the engine owns the actuator (same commit as the wiring swap,
per commit-granularity):

- `FanController` thermostat/schedule paths (circulation + exhaust now
  engine-driven; `AlwaysOnFanController` for the case fan **stays**),
- `HeaterFollowerFanController` (becomes the derived-output adapter),
- heater cycle logic in `lib/heater.py` (adapter replaces it),
- growlight scheduler,
- CO2 override relay logic (audit `co2_logger`'s override; its
  ventilation response folds into the exhaust surface — CO2 *injection*
  is out of scope).

Keep: loggers (sensor cache + SD logging), `BufferManager` chokepoint,
watchdog, OLED/status, debug menu (extend to show deviations, bands,
commanded vector, latch state).

## Host visualization tool (replaces the Excel sheet)

`prototypes/plot_regulation_surfaces.py`, host-only: renders each
regulator's surface from `DEVICE_CONFIG` as a heatmap (matplotlib if
available, else ASCII/CSV grid), and exports the golden-vector CSVs. The
operator tunes config values and re-runs it to see the new behavior —
this is the tuning loop, so make it pleasant (one command, all surfaces).

## Testing (gate: full suite green, coverage ≥ 88 %)

- **Golden vectors**: `tests/golden/regulation_<name>.csv` — an
  (x, y) → out grid per regulator generated by the host tool and
  spot-checked by the operator; device math must match within ±1
  (catches MicroPython float divergence near hinge breakpoints).
- **Property tests**: clamps hold everywhere; deadband (both severities
  < 10) commands no change; output monotonic along cardinal axes away
  from 50; hysteresis + min-cycle honored with a fake time provider.
- **Arbitration order** (the critical ones): an emergency/override cut is
  applied in ONE tick even when the slew limiter would forbid the delta;
  floors never reduce actuation; later conflict rules win; latch enters
  at severity 50 and does not release before `latch_release_ticks` +
  `latch_min_s` even if readings recover instantly.
- **Scenario table**: (temp, RH, CO2) tuples → expected direction per
  regulator, including hot+humid → humidifier 0 / exhaust+cooler up, and
  exhaust suppressed when outside is hotter (gate enabled).
- Remember `tests/conftest.py` stubs MicroPython modules — import `lib.*`
  inside tests/fixtures, never at module top level.

## Process requirements

- Follow the commit-granularity convention: config schema
  commit first (dict + validator + tests), then one commit per stage
  (module + its tests), then per-actuator wiring swaps (each removing the
  superseded controller), then the host tool, then docs. Run
  `pytest tests/` + `ruff check .` before each commit; `python main.py`
  host run must stay clean.
- End-of-session: append to `the internal chat-log` and
  `the internal hw-test-log` (bench checklist for the new engine —
  extend the `REG.1` entry), per the documentation routine.

## Open items — resolve with the user at session start (AskUserQuestion)

1. **Relay slot assignment** for cooler and humidifier (spare relay
   channels exist; confirm pins/channels and load type).
2. **Golden-vector blessing**: operator reviews the generated heatmaps
   before the wiring-swap commits land.
3. **Default anchors** per mode (greenhouse day/night temps, RH, CO2 ppm;
   mushroom equivalents) — propose defaults, let the user adjust.
4. **Heater window** default (600 s?) and cooler min-off (300 s?).
5. External SHT31 ships `enabled: false` until the sensor is installed
   (queued in `docs/hardware/next-revision.md`).
