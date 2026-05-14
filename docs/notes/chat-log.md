# Chat log

> Decisions, spec clarifications, deviations, issues, and non-obvious
> notes from Claude sessions. See
> [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md)
> for the entry format. Newest topic on top.

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
