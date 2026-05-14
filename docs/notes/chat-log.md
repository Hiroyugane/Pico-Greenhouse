# Chat log

> Decisions, spec clarifications, deviations, issues, and non-obvious
> notes from Claude sessions. See
> [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md)
> for the entry format. Newest topic on top.

## 2026-05-14 · Phase 3 — CO2 logger + fan override

### decision · CO2Logger mirrors DHTLogger shape, not a new abstraction

`CO2Logger` is structurally a `DHTLogger` clone: BufferManager-backed
CSV with `Timestamp,PPM`, date-based rollover, optional WriteQueue
plumbing, async `log_loop()` that yields between polls. Reusing the
same shape keeps the read path obvious for the next agent and the
SD-resilience guarantees come for free. The differences are scoped to
the sensor (UART instead of DHT22 driver) and the override flag.

### decision · External override is a callable attribute on FanController, not a setter method

`FanController.external_override` is a plain attribute typed as
"callable returning bool or None". The CO2 path assigns it via DI in
`main.py:417` (`fans[fan_index].external_override = co2_logger_obj.is_override_active`).
This keeps the FanController interface unchanged for legacy callers
that don't wire an override (default `None` = no hook) and lets a
future feature (e.g. an OLED manual-override page) replace the
callable without subclassing.

### decision · Override priority: thermostat > external > schedule

In the cycle tick, thermostat fires first and latches; if it's
active, the external override is skipped entirely. This protects
against the corner case where CO2 reads stale-low (false negative
release) while temperature is genuinely high — we never want CO2 to
release the thermostat-fired fan. The external override only outranks
the time-of-day schedule.

### deviation · Removed the cargo-cult `uart.flush()` call

The CO2 prototype in [`tests/co2log.py`](../../tests/co2log.py) called
`uart.flush()` before every write. MicroPython's UART has no documented
`flush()` semantics that affect RX (and on some ports the method does
not exist at all), so the call was meaningless or actively harmful
depending on the host shim. The driver omits it. The test fixture's
fake-UART originally cleared RX on flush, which surfaced the issue.

### decision · fan_2 is the CO2 override target

`co2_logger.override_fan` defaults to `"fan_2"` because fan_2 has the
higher `max_temp` and thus the larger ventilator role in the existing
schedule. Operators can flip to `"fan_1"` in config.py without code
changes. Validator rejects anything else so a typo doesn't silently
mean "no override".

### note · OLED CO2 page and warmup-tier escalation still deferred

The plan section 4.1 calls for a dedicated OLED page (ppm + 1-hour
trend arrow) and treating sensor warm-up vs steady-state failures
distinctly in StatusManager. Phase 3 lands the override + logging
core; OLED page and StatusManager wiring follow with the deferred
OLED batch from phases 1-2.

## 2026-05-14 · PCB gap plan — phases 0, 2, 1 implemented

### decision · Ordered phase 2 (heater) before phase 1 (DAC dimming)

Followed the plan's recommended order (section 7) rather than the
section-numbered order: phase 0 I2C scan → phase 2 heater → phase 1
DAC dimming. Heater is the smallest scope with the biggest immediate
field value, and it's independent of the I2C probe. Phase 1 depends
on the MCP4725 address being confirmed but proceeds with the
tentative `0x60` default per
[`2026-05-14-pcb-codebase-gap-plan.md`](2026-05-14-pcb-codebase-gap-plan.md).

### deviation · MCP4725 driver vendored under The Unlicense, not Apache-2.0

The plan listed `wayoda/micropython-mcp4725` as Apache-2.0; the
upstream LICENSE file actually says The Unlicense (public domain
dedication). Even more permissive than expected, so vendoring is
safe. The vendored copy at [`lib/mcp4725.py`](../../lib/mcp4725.py)
is a minimal adaptation (default address `0x60`, fast-write only —
the `read()` and `config()` paths were dropped as unused).

### decision · Heater is active-HIGH, NOT routed through `RelayController`

`HeaterController` in [`lib/heater.py`](../../lib/heater.py) talks
directly to `machine.Pin` with `value(1)` = on, `value(0)` = off.
Reusing `RelayController(invert=True)` would have implied "drive
LOW to activate", which is wrong for the MOSFET gate on GP3.
Sharing the relay base class also would have hidden the polarity
difference behind a flag — the explicit pin-level driver makes the
gate logic visible at the call site.

### decision · Heater day/night window inherits growlight schedule

Per locked design (plan section 4.1), the heater day window is
`growlight.dawn_*` + `heater.day_offset_min`, and the night window
is `growlight.sunset_*` + `heater.night_offset_min`. With both
offsets at 0 (the defaults) the heater follows the lamp 1:1. The
window computation lives in [`main.py`](../../main.py) so
`HeaterController` stays unaware of the growlight schedule — it
just gets `day_start_*` / `night_start_*` numbers via DI.

### decision · Dimming layer baked into `GrowlightController`, not a wrapper

`set_level(pct)` was added to `GrowlightController` directly rather
than introducing a `DimmableGrowlight` wrapper. The controller
already owns the relay; the DAC is a second device on the same
on/off boundary, so co-locating brightness with the master switch
is the smallest readable surface. DAC injection is optional —
passing `dac=None` keeps the relay-only legacy path so the unit
tests that don't care about brightness still work unchanged.

### decision · DAC write fires before relay close on rising edges

`set_level()` writes the DAC value first, then closes the relay.
This prevents a brief full-brightness flash when the DAC was sitting
at a stale high value from a previous session. The reverse on
falling edges is fine — the relay opens, then DAC goes to 0 — the
op-amp output collapses with the load.

### note · OLED pages and ramp scheduler deferred

Per scope agreed at the start of this session: phases 0, 2, and 1
land the controllers and the static-default brightness, but the
OLED menu pages for CO2 / Soil / Heater / Dim and the dawn/sunset
ramp scheduler are deferred to a later phase. The dimming layer
already supports arbitrary `set_level()` calls; a future ramp task
just needs to schedule those calls over `ramp_duration_s`.

## 2026-05-14 · Configurability rule

### decision · Added `.claude/rules/ecc/common/configurability.md` as a load-bearing rule

Policy: every tunable behavior value (pins, intervals, thresholds,
timeouts, retry counts, buffer sizes, feature toggles, paths,
freq/duty/brightness defaults) MUST go through `DEVICE_CONFIG` in
[config.py](../../config.py), with a matching `validate_config()`
entry and a row in [tests/test_config.py](../../tests/test_config.py),
landing in the same commit. Pure algorithmic constants stay inline.
Escape hatch is a `# fixed: <reason>` comment above the literal —
the only acceptable form of hardcoded tunable. Consumers in `lib/`
receive values via DI from [main.py](../../main.py) and don't import
`DEVICE_CONFIG`. Chose "any tunable behavior value" as the trigger
(strictest reasonable bar without forcing math constants into the
dict) so the field can be retuned without touching logic, matching
the project's embedded long-life profile.

## 2026-05-14 · PCB ↔ codebase gap analysis

### note · Full netlist walk produced a per-peripheral implementation plan

Extracted the complete netlist from
`docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json` (union-find over wire
endpoints + pin endpoints + netflag anchors → 49 named nets, 23
short unnamed nets). Cross-checked every Pico GPIO and shared bus
against `config.py`, `main.py`, and `lib/`. Result lives in
[`2026-05-14-pcb-codebase-gap-plan.md`](2026-05-14-pcb-codebase-gap-plan.md).

### issue · Four firmware-actionable gaps identified

1. **Dimmable grow light** — MCP4725 DAC + op-amp + GL_CON wired on
   the PCB but no driver and no hook into `GrowlightController`. The
   relay (GP20) is currently the only control; brightness is wasted.
2. **Heater control** — GP3 → R6 → IRLZ44N → HE_CON path exists but no
   `HeaterController`. Config has the pin key only.
3. **CO2 sensor in main loop** — UART0 on GP16/17 wired through R9/R11
   to CO2_CON, but only prototype code in `tests/co2log.py` /
   `co2test.py`. No production driver, no main-loop wiring.
4. **GP28 ADC** — ADC_CON pin 4 wired but firmware purpose
   unspecified (soil moisture? light meter? second thermistor?).

Reserved relays GP21/22/26/27 are wired to REL_CON 5–8 but
intentionally dormant; low-priority.

### decision · Phase order = heater → DAC dim → CO2 → ADC

Recorded in the plan doc. Rationale: heater is smallest-scope and
biggest immediate value (greenhouse needs heat before it needs
brightness control); DAC dimming follows because it depends on Q5
(I2C address verification, which Phase 0 resolves); CO2 is largest
scope; ADC is gated on Q1 (purpose). Six open questions (Q1–Q6) are
listed at the top of the plan doc and should be answered via a
single `AskUserQuestion` round at the start of phase 1.

## 2026-05-14 · PCB pin remap (Pi-Greenhouse-PCB v2026-05-14)

### decision · Remapped every GPIO to match the printed PCB

The board layout in `docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json` (EasyEDA
schematic, post-PCB-print) reassigns almost every Pico GPIO from the original
prototype wiring. `config.py` is now the single source of truth, and
`validate_config()` requires the new pin keys.

Key moves:

- **Status LEDs reshuffled on LED_CON** — activity=GP4 (unchanged),
  SD=GP5 (was GP8), warning=GP6 (unchanged), error=GP7 (unchanged),
  reminder=GP8 (was GP5). Net effect: SD ↔ reminder swap vs. the original
  prototype wiring. (Corrected post-PCB-print after eyes-on confirmation
  by the user.)
- **CO2 UART → UART0 on GP16/GP17** (was UART1 on GP2/GP3). R9/R11 sit between
  the Pico and CO2_CON as series resistors.
- **Buzzer GP14** (was GP20), with R3 pull-down to GND on the buzzer line.
- **Relays consolidated on REL_CON** — fan_1=GP18, fan_2=GP19, growlight=GP20
  (old values were 16/18/17). Four further relay slots reserved on
  GP21/GP22/GP26/GP27.
- **New peripherals** added as config keys with no behavior yet: heater MOSFET
  on GP3 (via R6 → IRLZ44N gate), ADC input on GP28 (ADC_CON pin 4), and the
  MCP4725 grow-light DAC on the existing I2C0 bus (default address 0x60).
- **RES_BTN now drives 3V3_EN** (Pico hardware reset), not a GPIO. The legacy
  `button_reserved` key is kept (validator stability) and points at the GP2
  breakout header for any future software-side button.

### note · `main.py` and `lib/hardware_factory.py` are fully config-driven

Confirmed by grep: no hardcoded GPIO numbers outside `config.py` (only
`Pin(<config>...)` constructions through DI). The remap therefore touched
zero `lib/` files. 546 pytest tests + ruff stayed green after the edit.

### issue · GL_DAC / heater / ADC have no driver yet

The PCB exposes hardware the firmware does not yet exercise: MCP4725 grow-light
DAC on I2C0 (0x60), heater MOSFET on GP3, and ADC input on GP28. Config keys
are in place so future work can wire them without touching the schema again.
Verification of these channels is captured in `docs/test/hw-test-log.md` as
"no driver yet — must not energize" checks.

## 2026-05-14 · Commit-on-stop enforcement

### decision · Stop hook blocks turn-end while tracked tree is dirty

Extended `commit-granularity.md` with a "Commit before ending the
turn" section: when Claude finishes a task, all of its work must
already be committed. Enforced by `.claude/hooks/check-clean-tree.ps1`,
wired as a `Stop` hook in `.claude/settings.json`. The hook runs
`git status --porcelain`, ignores untracked entries (`??`), and
returns `{"decision":"block","reason":"..."}` if any tracked file is
modified or staged — re-prompting Claude with the dirty file list
and a pointer to the rule.

### deviation · Hook scope limited to tracked changes

User chose "any tracked changes Claude touched" over "entire working
tree must be clean" for the scope. Practical consequence: if Claude
creates a brand-new file and forgets to `git add` it, the hook
**will not catch it** — only the rule does. The hook is a backstop
for the common case (modifying tracked files); Claude is still
expected to follow the rule's letter for new files. This was the
explicit trade-off to avoid blocking on user-vintage untracked junk
(scratch files, build artifacts, `docs/notes/` before it was
committed).

### decision · Per-turn opt-out via sentinel file

When the user says "leave it uncommitted" / "don't commit yet" /
equivalent, Claude creates `.claude/.skip-commit-check`. The hook
consumes and deletes the sentinel on next Stop, allowing one turn to
end uncommitted. The opt-out is per-turn, not per-session — each
subsequent dirty Stop needs its own sentinel. This keeps the default
("commit before done") strict and makes the escape hatch feel
deliberate.

### note · `.claude/` is gitignored on this repo

The new rule file, hook script, and settings change all live under
`.claude/` which is in `.gitignore` (line 21). They exist only on
this machine and won't propagate via `git pull`. Other contributors
who want the same enforcement need to add the same files locally.
Promoting any of this to checked-in territory would require either
unignoring `.claude/` or moving the rule/hook to a tracked location
(e.g. `docs/` for the rule, a top-level `hooks/` for the script).

## 2026-05-14 · Commit granularity rule

### decision · One logical change per commit, with refactor/behavior split

Added [.claude/rules/ecc/common/commit-granularity.md](../../.claude/rules/ecc/common/commit-granularity.md)
as a third load-bearing rule alongside `clarifying-questions.md` and
`documentation-routine.md`. Sizing is "one logical change per commit"
regardless of file count — a coherent change can span multiple files
when they form one indivisible unit (e.g. a config key + its validator
+ its test row), but a refactor and a behavior change in the same
working tree must split into two commits. Banned patterns:
`wip`/`checkpoint`/`misc` messages, refactor mixed with behavior change,
tests bundled with unrelated code, and squash-merging into `main`.
Rationale: future AI sessions read `git log` to reconstruct intent;
construction-site commits force them to diff a swamp.
