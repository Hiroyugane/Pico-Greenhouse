# Chat log

> Decisions, spec clarifications, deviations, issues, and non-obvious
> notes from Claude sessions. See
> [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md)
> for the entry format. Newest topic on top.

## 2026-05-19 · SD-update deploy path + updater log mirror

### issue · deploy task was writing to legacy /sd/update, hiding canonical layout from operators

`.vscode/tasks.json` `deploy-update-to-sdcard[-nocheck]` shipped with
`--copy-to G:/update` from the pre-2026-05-15 layout. Every deploy
landed in the legacy fallthrough path, so `/sd/logs/updates.log` always
opened with `payload detected at legacy /sd/update` even on fresh
builds. Repointed both tasks at `G:/ota/pending` (canonical).

### deviation · `tools/build_update_payload.py` now `mkdir -p`s the parent when SD root exists

Repointing exposed a second bug: the `--copy-to G:/ota/pending`
destination had no parent (`G:\ota`) on the SD card, so the deploy
crashed with `destination parent does not exist`. Loosened the
pre-check to verify only the drive **root** (`G:\`) — the SD-mounted
state — and `mkdir parents=True` for everything below it. Operators
no longer have to hand-create canonical subdirs on a freshly migrated
card.

### decision · mirror every `updater.log()` line into `/boot.log` on internal flash

A failing on-hardware update produced only the `start` line in
`/sd/logs/updates.log` — no `verify_fail` / `apply_fail` followed,
despite the fail jingle and red-status feedback playing. The leading
hypothesis is that the SD-side append silently failed after the first
write (best-effort log path in [updater.py:338](../../lib/updater.py#L338)).
The updater already mirrored to stdout for USB-serial debugging, but
that's invisible on a standalone Pico. Added a third sink: each
`Updater.log()` call now also writes through `lib.boot_log.write()`
into `/boot.log`. Reusing `boot_log` rather than introducing a new
flash log keeps the cap-controlled append path single-sourced and
costs no new config knobs. The success path (`apply_ok` → `machine.reset()`)
loses the entry on the next-boot truncation, which is fine; the failure
path preserves it because no reset fires.

## 2026-05-19 · R8 (MISO series resistor) identified as root cause of SD bit errors

### issue · earlier "40 MHz too aggressive" call was wrong — the resistor was the culprit

The same 2026-05-16/18 field run that produced 32× `SD status changed:
FAILED` over 42 h has been re-investigated on the bench. The cause was
not the 40 MHz SPI baudrate or the cabling — it was the series resistor
**R8** on the MISO line (GP12 ↔ SD_CON pin 3). R8 has been removed and
MISO is now a direct trace; SD mount and read/write have been stable
since.

### decision · keep `spi.baudrate` at 10 MHz for now, revisit on next bench run

The 10 MHz setting from earlier today is left in place as a precaution
until the next bench session confirms 40 MHz is reliable without R8.
Bandwidth is not the bottleneck (CSV rows are ~30 bytes), so the
downside of the conservative setting is zero; the upside of leaving
margin on the link is real until we have data. When the bench
confirms, bump `DEVICE_CONFIG["spi"]["baudrate"]` back to 40 MHz in a
separate commit.

### deviation · update earlier chat-log "drop default SPI baudrate" entry framing

The 2026-05-19 entry below ("drop default SPI baudrate from 40 MHz →
10 MHz") attributes the field failure to "40 MHz over the Pico SD_CON
path with series resistors R8/R10". That framing is now known to be
wrong: R10 (on MOSI) is fine; R8 (on MISO) was the failure mode. The
entry is left in place for history — read it together with this new
entry.

### note · PCB schematic and pin-map docs updated in the same turn

[config.py:30-40](../../config.py#L30-L40),
[config.py:92-108](../../config.py#L92-L108), and
[docs/notes/2026-05-14-pcb-codebase-gap-plan.md:33](2026-05-14-pcb-codebase-gap-plan.md#L33)
all dropped the "via R8" notation on MISO. The schematic JSON under
[docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json](../SCH_Pico-Greenhouse-PCB_2026-05-14.json)
is the original board design and is intentionally **not** rewritten —
it stays as the as-designed reference; the bypass is captured in the
PCB-revision changelog instead.

## 2026-05-19 · SD reliability + watchdog resilience pass

### issue · Pico restarted ~86× in 42 h with no exceptions in the log

The shipped `sd/logs/system.log` (1491 lines, 2026-05-16 23:30 →
2026-05-18 16:38) contained 86 `System startup` lines but zero
`[ERR]` / traceback / exception markers. Many restart clusters
were tight (1–3 min apart). Watchdog timeout was 8000 ms; the
trips were silent — no console message, just an immediate reboot.

### decision · bound `migrate_fallback()` per call and feed WDT between rows

Root cause of the silent resets was identified as
`BufferManager.migrate_fallback()` running synchronously inside the
60 s health loop with no row cap and no WDT feed. A backlog of
30+ rows on a slow SD takes longer than 8 s of synchronous SPI
work, which is the exact failure mode that resets the Pico without
logging anything.

`migrate_fallback()` now drains at most
`system.fallback_migrate_batch_max` rows per call (default 20),
feeds the watchdog between every row, and rewrites the fallback
file with the remainder so chronological order is preserved across
the multi-pass drain. The health-check loop fires it once per
cycle, so a 100-row backlog drains in ~5 health cycles instead of
one watchdog-tripping pass.

### decision · drain fallback at boot instead of wiping it

`buffer_manager.clear_fallback_startup()` was called unconditionally
in `main()` at boot, wiping the fallback CSV. That is what caused
the "truncated startup" log pattern (only `System startup`,
`CO2 override wired`, `OLED display initialized`, `Growlight ON`
surviving): log entries that hadn't flushed to primary before the
prior reset went to fallback, then got wiped on the next boot.

`main()` now calls `migrate_fallback()` up to twice at boot when SD
is mounted, preserving the prior boot's data and emitting
`[STARTUP] Drained N fallback row(s) from previous boot`. The bound
on the loop keeps init time predictable; the health loop drains
any remainder.

### decision · feed WDT inside `WriteQueueManager._drain_batch` and `sd_integration.is_mounted` recovery

Two more synchronous SD paths were unprotected: the write-queue
drain (up to 5 SPI writes per cycle) and the MBR-read-fail recovery
inside `is_mounted` (umount + SPI deinit + sleep_ms(200) + reinit +
re-read). Both now accept a `wdt_feed` callable injected from
`main.feed_wdt` and call it between each blocking step. Exceptions
from the callback are swallowed so a misbehaving WDT driver can
never abort the recovery path.

### decision · drop default SPI baudrate from 40 MHz → 10 MHz

40 MHz over the Pico SD_CON path with series resistors R8/R10 was
too aggressive for the field cabling — the 32× `SD status changed:
FAILED` over 42 h indicates SPI bit errors, not yanked cards.
10 MHz is the field-tested setting; bandwidth is not the bottleneck
(CSV rows are ~30 bytes), so this is a pure reliability win.

### decision · log `machine.reset_cause()` on every boot

`[MAIN] System startup` lines now end with the named reset cause
(`PWRON_RESET`, `WDT_RESET`, `BROWNOUT_RESET`, …). When the next
silent-reset bug shows up, the operator can tell at a glance
whether it was the watchdog, a brown-out, a soft reset from the
updater, or the user pressing RES_BTN. Mapping is best-effort:
unknown codes fall through to `code=N`; failures (older firmware
that lacks `reset_cause`) fall back to `unknown` without blocking
boot. Host shim exposes the same constants so tests stay valid.

### issue · CO2 sensor reading constant 10000 ppm on 2026-05-18

`sd/sensors/co2/2026/co2_2026-05-18.csv` has all 1696 rows pinned
at 10000 ppm, which keeps the CO2 override permanently ON and the
exhaust fan running non-stop. This is sensor-side (likely
calibration, ABC drift, or a UART framing issue) — not a software
bug — but it's contributing to the I/O / power load that the rest
of this session is trying to stabilise. **Flagged for bench
verification, not auto-fixed.** Operator should run
`prototypes/co2_test.py` (or similar) with a known-clean room and
compare against the sensor datasheet's ABC window.

### note · log timestamps go backwards in the wild

[sd/logs/system.log:230-239](../../sd/logs/system.log#L230-L239)
contains a row stamped `16:18:29` after rows stamped `16:23:23`,
because `migrate_fallback()` re-injects old rows into the primary
log after newer rows have already been written. The bounded-batch
migration doesn't fully solve this — it just makes the windows
smaller. A proper fix would teach `EventLogger` to write fallback
rows under a separate `*.replay.log` file at migration time. Left
as a follow-up; current session's priority was stopping the silent
resets.

## 2026-05-17 · OLED SYSTEM screen surfaces build version

### decision · combine date+time on row 0 to free a slot for `Ver:<hash>` on row 1

`_render_system()` previously used 5 rows for date / time / uptime /
buf / RAM, leaving no room for build identity. Row 0 now collapses
into a 16-char `YYYY-MM-DD HH:MM` (slicing `now_timestamp()[:16]`,
which fits the 16-char row truncation exactly), and row 1 becomes
`Ver:<7-char git short hash>` — e.g. `Ver:c195be2` (11 chars). No
existing field is dropped. Uptime / buf / RAM keep their rows 2–4.

### decision · stamp `lib/build_info.py` from the payload builder, fall back to `Ver:dev`

`tools/build_update_payload.py` now writes `lib/build_info.py`
(VERSION = git short hash, BUILD_TIME = full ISO timestamp) into
the working tree before collecting sources, so the raw-mode payload
picks it up automatically, Thonny-direct flashes also get a stamped
file, and `--compiled` mode additionally drops the same file into
`<out>/lib/` with a manifest entry (since the compiled collector only
takes `.mpy`). The file is gitignored. `lib/oled_display.py` does a
guarded `from lib.build_info import VERSION` with two fallbacks (`from
build_info import …` for on-device sys.path quirks, then literal
`"dev"`), so unbuilt working trees and host runs read `Ver:dev`. No
new `DEVICE_CONFIG` entries — build identity is build-time metadata,
not operator-tunable behavior.

## 2026-05-17 · Updater short-circuits when payload already on flash

### issue · same-version SD update failed with only "start" line and failure jingle

Operator boots Pico with payload at `/sd/update/` whose contents
already match what's on flash (e.g. Pico just flashed via
`flash-mpremote`, SD payload built from same git commit via
`deploy-update-to-sdcard`). Symptom: failure jingle plays,
`/sd/logs/updates.log` contains only the `start` line — no
`verify_fail` / `apply_fail` entry — and `/sd/update/` is still in
place. Root cause not fully pinned on host (host repro succeeds);
hypothesis is a MicroPython-side write-during-overwrite quirk when
apply rewrites `/lib/updater.mpy` or another in-use module, with
the subsequent `log()` call also silently failing, masking the
real error.

### decision · add `Updater.is_already_applied(manifest)` short-circuit before apply

After `verify_payload` passes, `run_pending_update` now hashes
every manifest file at `_FLASH_ROOT` and compares to the manifest
entry. If all hashes match, the apply step is skipped entirely,
`finalize()` still runs (so the trigger is consumed and the
payload is renamed under `applied/<version>/`), a new `noop`
log line is written, and a distinct `already_applied` jingle
plays. **No `machine.reset()`** — the live code is unchanged, so
boot just continues. Eliminates the failure jingle on
idempotent payloads and avoids unnecessary flash writes.

### decision · `Updater.log()` mirrors every entry to stdout

The bare `except Exception: pass` in `log()` previously hid the
real failure when the SD-side append broke (the exact bug the
operator just hit). `log()` now `print("[updater]", line)`s
before the file write so the verify_fail / apply_fail message is
visible over USB serial even when the SD log is unwritable. Print
is itself try-wrapped — logging stays best-effort.

### decision · new `updater_feedback.noop_pattern` + `UpdateFeedback.already_applied()`

Two-blip 880 Hz pattern (`[(880, 80, 60), (880, 80, 0)]`),
distinct from success (3-note rising) and failure (2-note
descending). LED row shows every other LED lit while the chime
plays so the operator can distinguish "no-op apply" from "real
apply" at a glance without listening. Wired through
`build_from_config` like the existing patterns; new validator
entry in `config.py` rejects an empty `noop_pattern`.

## 2026-05-16 · Fan-control pre-PCB refactor (FanOutput + fans dict + new policies)

### decision · land all six pre-hardware build steps in one session as a clean six-commit series

User said "implement everything that can be implemented before making
physical changes to the hardware". Steps 1-6 from
[[project_fan_hardware_revision]] all run on the current relay PCB
because the relay path stays live until the PCA9685 PCB lands. Each
step shipped as its own logical commit per
[.claude/rules/ecc/common/commit-granularity.md](../../.claude/rules/ecc/common/commit-granularity.md);
tests stay green at every commit (901 -> 989). Step 7 (flipping the
per-fan output from relay to PCA9685) is the only remaining item and
needs the new PCB.

### decision · FanController composes a FanOutput instead of inheriting RelayController

`FanController` no longer extends `RelayController`. It takes an
`output: FanOutput` argument and routes `turn_on()`/`turn_off()`
through `output.on()`/`output.off()`. `RelayFanOutput` wraps a
`RelayController` (binary), `Pca9685FanOutput` wraps a PCA9685 PWM
channel (variable). Policy code stays identical; the next-rev PCB
swap is one-line per-fan wiring in `main.py`. `.pin` exposed as a
backward-compat property for tests and OLED diagnostics.

### decision · fans dict ships all 5 roles up front, disabled-by-default for the three not yet wired

`DEVICE_CONFIG["fan_1"]` / `["fan_2"]` are gone. The new
`DEVICE_CONFIG["fans"]` dict keys by role: `exhaust`,
`growroom_walls`, `growroom_center`, `heater_distribution`, `case`.
The first two stay relay-backed and enabled today. The three
PCA9685-backed roles ship with `enabled: false` so the validator
can keep them honest and `main.py` skips them at construct time.
When the chip lands: flip `pca9685.enabled` and the three fan
`enabled` flags; no code change needed. Chosen over "migrate only
existing 2 fans now" because it makes the eventual hardware
turn-on a config-only change.

### decision · validator dispatches on mode + output rather than one-size-fits-all required-keys

`_validate_fans()` runs after the bulk required-keys pass. It
enforces: enabled bool, mode in {thermostat_schedule, always_on,
heater_follower}, output in {relay, pca9685}, no duplicate relay
pins, no duplicate PCA9685 channels, plus the per-mode required
tunables. Keeps the validator strict without coupling to one fan
shape; matches the `growlight.mode` dispatch pattern already in the
codebase.

### decision · co2_logger.override_fan switches from "fan_2" -> "exhaust", validated against fans dict keys

The CO2 override target is now a role name resolved by `main.py`
walking the constructed `fans` list looking for matching `.name`.
Validator rejects any value not present as a key in the `fans`
dict, regardless of `enabled`. Exhaust is the natural CO2 vent
target - keeping the override pointed at the highest-airflow role
survives future re-tuning of the other fans.

### decision · AlwaysOnFanController re-asserts duty every refresh_interval_s as cheap insurance

Constructor calls `output.set_duty(duty_pct)` once. `start_cycle()`
sleeps for `refresh_interval_s` (configurable, default 300 s in the
`case` entry) and re-issues the same `set_duty`. PCA9685 registers
are persistent across normal operation but I2C bus glitches happen
in long runs - a re-assert every 5 minutes is cheap and means a
hung-fan investigation has one fewer suspect. `refresh_interval_s`
is a per-fan tunable per [.claude/rules/ecc/common/configurability.md](../../.claude/rules/ecc/common/configurability.md).

### decision · HeaterFollowerFanController tracks afterrun in a per-tick countdown

Heater on -> fan on + afterrun budget set to `post_run_s`. Heater
off with budget > 0 -> fan stays on, budget decrements by
`poll_interval_s` per tick. Heater on again -> budget resets to
full. Budget reaches 0 -> fan off. Simple integer countdown rather
than monotonic-time deadline because MicroPython `time.ticks_ms()`
semantics differ across host and Pico - counting ticks is
platform-neutral and matches the existing thermostat pattern in
`FanController`.

### decision · move HeaterController construction before the fan loop in main.py

`HeaterFollowerFanController` takes the heater instance as a
constructor arg (no late wiring). The heater was constructed at
step 7b2 (after the fans loop); moved to step 6b (before the fans
loop) so the heater_follower dispatch in the loop has the reference
available. Heater depends only on time_provider/th_logger/logger
which already exist by step 6, so the move is safe.

### note · per-fan PWM proportional mode deferred

The clarifying question on whether `thermostat_schedule` should
grow a true variable-speed PWM mode was answered "binary via
`set_duty(0)/set_duty(default)` for now, revisit later". Implemented
as binary: thermostat_schedule fans call `output.set_duty(default)`
when on and `output.set_duty(0)` when off. Adding a proportional
mode later is additive - new `mode: "thermostat_proportional"`
value with its own controller class, no breaking changes to the
existing mode.

## 2026-05-16 · OLED debug actions sub-menu

### decision · separate "debug" entry menu, long-press opens sub-menu, short=cycle, long=execute

Added a tenth top-level OLED menu (`debug`) instead of overloading an
existing one. From the entry view, a long press flips the display
into a sub-menu mode where short-press cycles actions and long-press
executes the highlighted one. This keeps every other menu's
long-press semantics (clear history, reset reminder, remount SD)
untouched — an operator cannot accidentally trigger a destructive
action by holding the button on the wrong screen.

Shipped actions: `wipe_logs`, `cycle_relays`, `test_heater` (5 s),
`test_growlight` (relay pulse), `test_growlight_dim` (DAC sweep, only
listed when MCP4725 is wired). Per-fan PWM is intentionally **out**
until the PCA9685 revision lands; see
[[project_fan_hardware_revision]] for the planned hardware that
makes per-fan duty meaningful.

### decision · wipe_logs needs two-step confirm; scope = buffers + fallback + system.log

`wipe_logs` is the only destructive action. First long-press arms a
`CONFIRM?` prompt; second long-press inside `confirm_timeout_s`
(default 8 s) wipes. A short press cancels. Wipe scope is
deliberately narrow: BufferManager in-memory ring buffer, fallback
CSV (via `clear_fallback_startup`), and the EventLogger file. Sensor
CSVs under `/sd/sensors/**` are **never** removed — those are
scientific data, and an operator who needs a full reset can format
the card.

### decision · debug actions spawn async tasks; OLED stays event-loop friendly

`long_press_action()` runs from the button-poll task. Multi-second
actions (heater 5 s, dim sweep, cycle relays) would block the WDT
feeder if executed inline, so each handler is a coroutine and the
dispatcher schedules it with `asyncio.create_task()`. While an
action runs, `_debug_running=True` suppresses further button input
and the OLED shows `RUNNING...`. On completion, a `done`/`FAIL`
status line stays on screen for `status_show_ms` (3 s) and the
reminder LED plays a brief feedback blink so the operator gets
confirmation even at arm's length.

### note · per-fan PWM 0-100% deferred to PCA9685 revision

The user asked about individually testable fan PWM, but on the
current PCB fans are bare on/off relays — duty cycle isn't a
meaningful concept. The cycle_relays test pulses each fan ON for
~1 s in sequence so an operator can hear the relay click and confirm
wiring. Per-fan dim sweeps will be added in the same change that
introduces `AlwaysOnFanController` /
`HeaterFollowerFanController` on top of the PCA9685.

## 2026-05-16 · Fan control policies for PCA9685 hardware revision

### decision · case fan = always-on constant duty; heater-distribution fan = follows heater + afterrun

The next hardware revision (IRLZ44N MOSFETs on a PCA9685 PWM driver,
replacing the current 2-relay fan path) expands the fan roster to
five: exhaust, growroom_walls, growroom_center, heater_distribution,
case. Three of these inherit the existing schedule + SHT31
thermostat behavior of the current `FanController`. The two new
roles get their own control policies:

- **Case fan** runs at a constant, configurable PWM duty cycle
  whenever the system is up. No thermostat, no schedule — its job
  is steady airflow over the electronics. Implemented as a thin
  `AlwaysOnFanController` that calls `output.set_duty(duty_pct)`
  once at startup. RP2040 internal temp sensing is intentionally
  deferred until there's measured evidence the constant-duty
  approach is wrong.
- **Heater distribution fan** runs whenever the heater MOSFET is
  on, plus a configurable post-run / afterrun window so residual
  heat in the element gets purged into the room instead of
  back-soaking the device. Implemented as a new
  `HeaterFollowerFanController` that polls
  `HeaterController.is_on()` and tracks an afterrun timer.
  Polling (rather than callbacks on `HeaterController`) keeps the
  coupling to the existing codebase's polling idiom; up to one
  poll interval of lag is fine for airflow.

The cross-cutting seam for the whole revision is a `FanOutput`
abstraction (`RelayFanOutput` today, `Pca9685FanOutput` post-PCB)
so policy classes don't know whether they're driving a relay or a
PWM channel. Build steps 1–4 (output abstraction, PCA9685 driver,
config migration to a role-keyed `fans` dict with per-mode
validator dispatch) are valuable before the hardware revision;
steps 5–6 add the two new controller classes; step 7 is the
one-line per-fan wiring flip when the new PCB lands.

### note · grow-room fan variable-speed mode left open

Whether the three `thermostat_schedule` grow-room fans should grow
a true variable-speed PWM mode (duty proportional to temperature
delta above setpoint) — or stay binary on/off through
`set_duty(0)` / `set_duty(default_duty_pct)` — is not yet decided.
Worth a clarifying round when the config migration (build step 4)
lands, since that's when the per-fan duty schema crystallizes.

## 2026-05-16 · .gitignore refactor

### decision · trimmed 676-line .gitignore to ~80 lines of project-relevant rules

The old `.gitignore` was a stacked dump of GitHub templates: full
Visual Studio / .NET, Django, Flask, Scrapy, RabbitMQ, ActiveMQ,
Marimo, Streamlit, VS6, etc. — none of which apply to a MicroPython
Pi Pico project. Rewrote it to keep only: OS/editor noise (incl.
useful bits cherry-picked from a Flutter reference gitignore —
`Thumbs.db`, `Desktop.ini`, `*.swp`, `.idea/`), Python essentials
(bytecode, venv, test/lint caches), MicroPython `*.mpy`, Claude
tooling, and Pi Greenhouse runtime artifacts (`sd/`, `*.csv`,
`*.log`, `hw_probe_result.*`, `typings/`, `service_reminder.txt`,
`.main_original.py`).

### decision · .vscode/ allow-list expanded to all workspace-relative files

Audited every file in `.vscode/` for absolute-path leakage before
allow-listing. All current files use `${workspaceFolder}`, `~/`, or
`$env:` only — no `C:\Users\...` paths. So the allow-list now
covers `extensions.json`, `launch.json`, `settings.json`,
`tasks.json`, `Git-codebase.code-workspace`, `micropico-port.ps1`,
and `*.code-snippets`. Re-audit before allow-listing any new
`.vscode/` file.

### issue · `.github/workflows/ci.yml` was hidden by an accidental `.github/` ignore

The old gitignore had `.github/` as a blanket ignore, which silently
suppressed `.github/workflows/ci.yml`. `.github/copilot-instructions.md`
was already tracked despite the ignore. Dropping the `.github/` rule
in this refactor exposes `ci.yml` as untracked. Decide whether to add
it to git — it's not part of the gitignore refactor commit.

## 2026-05-16 · Updater legacy update_dir fallback

### decision · `updater.legacy_update_dirs` keeps pre-2026-05-15 payloads applicable

After the SD layout refactor moved `/sd/update` → `/sd/ota/pending`
([c1f4c07](c1f4c07)), a field Pico booted normally instead of
applying a payload that had been copied to the old `/sd/update`
location. `lib/updater.py` `has_pending_update()` only checks the
canonical `update_dir`, so the legacy path was invisible.

Added a new config key `updater.legacy_update_dirs` (default
`["/sd/update"]`) and a fallback in `run_pending_update()`: if the
canonical `update_dir` has no `manifest.json`, the boot hook walks
the legacy list in order and uses the first one that does. The
matched directory is fed straight into `Updater`, so `finalize()`
still renames it into the **canonical** `applied_dir`
(`/sd/ota/applied/<version>/`) — legacy payloads end up in the new
applied tree on success, so the legacy path self-clears.

The start-log line is annotated `payload detected at legacy <path>`
when the fallback fires, to make it obvious in `/sd/logs/updates.log`
which path was consumed. Operators clear the fallback by setting
`legacy_update_dirs: []` once all field cards are migrated.

### note · canonical wins when both paths have a manifest

If someone builds a payload at the new path AND leaves an old one at
`/sd/update`, the canonical `update_dir` always wins. The legacy
directory is only consulted when the canonical has no manifest, so a
fresh build is never silently overridden by stale legacy data.

### note · `tools/build_update_payload.py` examples now show `G:/ota/pending`

Docstring examples were still showing `--copy-to G:/update`, which is
how the legacy payload got onto the card in the first place. Updated
all five example lines so future copies land at the canonical path.

## 2026-05-15 · Boot SD diagnostics tee'd to /boot.log

### decision · mirror HardwareFactory pre-EventLogger output to flash file

Standalone Pico has no USB serial reader attached, so the diagnostic
prints that explain *why* the boot SD mount failed
(`[HardwareFactory] SD mount attempt N/M...`, the `mount_sd` error
line, the `is_mounted fallback` step) were invisible when the system
entered the `require_sd_startup` reset loop. New
[lib/boot_log.py](../../lib/boot_log.py) tees those lines into a file
on internal flash so the operator can read them over USB MSC after
power-cycling out of the loop.

Defaults: `/boot.log`, 10 KB cap, truncated on the first write per
process so each boot starts fresh. `boot_log_path` and
`boot_log_max_kb` live in `DEVICE_CONFIG["system"]` with the usual
validator+test plumbing. `main.py` calls `boot_log.configure()`
immediately after `validate_config()` so HardwareFactory's first
`_debug` / explicit `boot_log.log` calls land in the configured
file.

### note · boot_log only routes when no EventLogger is wired

`HardwareFactory._debug` falls through to `boot_log.log` only when
neither a logger nor a debug_callback is attached — i.e. during
boot, before `EventLogger` is constructed. Once the logger is wired,
every debug call goes there and the boot log stops growing. This
keeps the helper scoped to the diagnostic gap it was created for and
avoids overlap with `system.log` rotation.

## 2026-05-15 · Cold-boot SD mount — timing + is_mounted fallback

### issue · SPI reinit alone did not unblock cold-boot mount

After landing the SPI-reinit-between-retries fix and the
`require_sd_startup` hard-fail wiring, on-hardware test still showed
boot mount failing — the new sd_led+error_led countdown was firing
correctly and the Pico kept cycling. Manual menu remount continued to
work. That ruled out SPI bus state as the dominant cause and pointed
at total elapsed time: by the time the operator can press the menu
button, the card has had many seconds to settle; at boot, the retry
loop gave it ~1.75 s before declaring failure.

### decision · longer cold-boot waits + is_mounted as final fallback

`_init_sd` now:

- feeds the injected WDT inside the retry loop so longer waits don't
  trip the watchdog (HardwareFactory now takes a `wdt=` constructor
  arg, wired from `main.py`),
- `_safe_umount()`s the mount point between attempts to clear any
  half-mounted node a previous attempt left behind,
- after all `mount_sd` attempts fail, runs one more pass via
  `lib.sd_integration.is_mounted(None, None, return_instances=True)`
  — the exact code path the menu remount uses, which builds a fresh
  SPI/SDCard pair and has its own MBR-read retry,
- prints `[HardwareFactory] SD mount attempt N/M...` and the
  fallback line so the operator can capture the failing step from
  the USB console.

Config defaults bumped: `system.sd_power_up_ms` 250 → 1500 and
`system.sd_retry_delay_ms` 500 → 1000. Total cold-boot budget is
now ~5.5 s, still well under the 8 s WDT (which is fed mid-loop).

### note · why "just call is_mounted" works

`is_mounted(sd=None, spi=None)` builds a brand-new SPI bus inside
its own `_init_sd_local` helper, attempts `os.mount`, falls back to
a `umount → deinit → sleep 200 ms → re-init → re-read MBR`
sequence on MBR-read failure, and only returns True after the MBR
has actually been read. That second-chance MBR retry is the bit the
`mount_sd` retry loop doesn't have. Folding it in as the boot
path's final attempt closes that gap without having to duplicate
the recovery code into `mount_sd` itself.

## 2026-05-15 · Boot SD mount recovery + hard-fail

### issue · SD failed to mount on cold boot but worked from menu remount

User reported that since the SD layout refactor landed, the card no
longer mounts at boot — yet a long-press menu remount succeeded every
time. Investigation found three problems compounding rather than one
clean regression:

1. `HardwareFactory._init_sd` reused the same `self.spi` across its
   three retries. A failed `sdcard.SDCard(spi, cs)` call can leave the
   SPI bus in a half-init state that every subsequent retry on the
   same bus inherits, so the loop never recovered. `is_mounted()`
   (the menu remount path) builds a fresh `SPI()` each call, which is
   why manual remount worked.
2. `StatusManager.run_post()` drives every owned LED OFF at the end
   of the walk. `main.py` called `set_sd_status()` *before* POST, so
   even when boot mount failed the visual walk masked the LED.
3. `system.require_sd_startup` existed in config but was never read
   anywhere — there was no path that turned SD failure into a hard
   stop.

### decision · cold-boot SD mount reinits SPI between retries

`_init_sd` now calls a new `_reinit_spi()` helper between attempts,
which `deinit()`s the existing bus (best-effort) and rebuilds it via
`_init_spi()`. Matches the implicit fresh-bus behavior of
`is_mounted()` on the menu path. Retry count and delay are unchanged
(3 × 500 ms with a 250 ms power-up); the bus reinit is the change
that makes retries meaningful rather than free.

### decision · require_sd_startup now defaults True, drives hard-fail

`system.require_sd_startup` defaults to `True` and is consumed in
`main.py` right after `status_manager.set_sd_status()`. On failure
the new helper `_enter_sd_failure_state()` lights sd_led + error_led,
feeds the WDT in 0.5 s ticks for `system.sd_fail_reset_s` seconds
(default 10), then calls `machine.reset()`. The visible countdown
gives the operator a chance to see *why* the Pico cycled, which is
the key difference from a watchdog-induced reset. Cold-boot SD
failures are usually transient (connector seating, brown-out, slow
card), so a bounded reset loop tends to recover on its own.

### note · POST now reasserts SD state after the walk

After `run_post()` returns, `main.py` re-calls
`status_manager.set_sd_status(hardware.is_sd_mounted())` so the SD
LED reflects reality once the walk is over. Currently only SD state
gets this treatment because it is the only condition raised before
POST; warnings/errors raised later are unaffected.

### deviation · no compatibility shim for the old behavior

Per `coding-style.md` and the user's prior preference, no flag was
added to preserve the old "boot continues silently on SD failure"
default. Operators who want that path set
`system.require_sd_startup=False` explicitly — that branch is still
wired and tested.

## 2026-05-15 · SD card layout refactor

### decision · sensor-first tree under `/sd/sensors/<type>/YYYY/`

Reshaped the SD root from a flat dump of CSVs and logs into a typed
hierarchy so adding a new sensor type only needs a config row, not
new path code. Layout:

- `/sd/sensors/<type>/YYYY/<type>_YYYY-MM-DD.csv` — daily-rotated
  CSVs, kept forever (no auto-pruner — operator clears manually).
  All paths flow through [lib/sensor_paths.py](../../lib/sensor_paths.py)
  `daily_csv_path()`.
- `/sd/logs/system.log` — EventLogger, existing size-based rotation
  (`event_logger.max_size`).
- `/sd/logs/updates.log` — Updater log, **new** size-based rotation
  via `updater.log_max_size` (default 50 KB → renames to
  `updates_<ts>.log`).
- `/sd/ota/{pending,applied}` — OTA payload staging (was `/sd/update`
  and `/sd/applied`).
- `/sd/diagnostics/hw_probe_*.json` — hw_probe output.

Layout roots live in `DEVICE_CONFIG["paths"]`; the validator enforces
that every entry is absolute and lives under `spi.mount_point`.

### deviation · no boot-time migration of legacy root files

Per operator preference, files left at `/sd/*.csv`, `/sd/system.log`,
`/sd/updates.log`, `/sd/update/`, `/sd/applied/`, and
`/sd/hw_probe_*.json` are **not** moved by the Pico. New writes go
straight to the new tree; the old files coexist until the operator
decides what to do. Skipping migration removes a class of boot-time
failures and keeps the apply path simple — the cost is that
historical data must be merged manually if you want one continuous
timeline.

### note · BufferManager now auto-creates parent dirs

`BufferManager.write` / `_flush_inner` / `_migrate_fallback_inner`
call a new `_ensure_parent_dir()` before each `open(..., "a")`.
Required because nested relpaths like
`sensors/co2/2026/co2_2026-05-15.csv` would otherwise fail with
`OSError(ENOENT)` on the year subdir. MicroPython build uses a
recursive `os.mkdir` walk (no `os.makedirs` available); host CPython
uses `os.makedirs(..., exist_ok=True)`.

### note · sensor logger constructors took a clean break

Dropped the `filename_base` / `filename` constructor args on
CO2Logger, SoilLogger, TempHumidityLogger and replaced them with
`sensor_root` + `sensor_type`. Config keys followed
(`co2_logger.filename_base` → `co2_logger.sensor_type`, same for
soil and a new `temp_humidity_logger.sensor_type`). Per coding-style
guidance, no backward-compat shim was kept.

## 2026-05-15 · Plant/mushroom operating mode

### decision · single top-level `mode` key drives optional component wiring

Added `DEVICE_CONFIG["mode"]` with two values: `"plant"` enables the
MCP4725-dimmed grow light path and constructs the soil-moisture
logger on GP28; `"mushroom"` runs the relay-only grow light and
skips `SoilLogger` entirely (no task, no ADC init). The mode is
validated at boot and is the sole switch — operators flip one key
and reboot. Default is `"mushroom"` per user preference.

### deviation · `growlight.mode` is no longer consulted at runtime

The previous `growlight.mode` key (`"dimmed"` vs `"relay_only"`) is
shadowed by the new top-level `mode`: plant ⇒ dimmed, mushroom ⇒
relay-only. The growlight.mode field still validates so existing
configs don't fail, but `main.py` derives the wiring purely from the
top-level mode. Kept the field rather than deleting it to avoid
churning every test fixture; future cleanup can remove it.

### note · disabled components are not constructed at all

Per user direction the disabled-in-mushroom path is "skip
construction" rather than "construct then idle". This keeps RAM
free on the Pico and means a mushroom-mode boot leaves GP28 as a
plain GPIO and skips MCP4725 I2C probing — both visible in the
startup log lines.

## 2026-05-15 · Relay diagnostic tool added

### issue · relays behave randomly across restarts — needs bench probe

User reports the 8-channel relay board behaves erratically, especially
after a reset. Added [tools/relay_diag.py](../../tools/relay_diag.py)
as a standalone MicroPython script that bypasses `lib/relay.py`,
config, and DI. It probes each of the 7 wired relay GPIOs in input
mode first (to capture float-state at boot — the most likely cause
of "clicks on at restart" with an active-low module), then drives
each HIGH, sweeps one at a time, runs an all-on stress, and leaves
everything off. Eyes-on checklist filed in
[docs/test/hw-test-log.md](../test/hw-test-log.md). The 8th relay
channel on REL_CON is intentionally unwired on this PCB — only 7
GPIO control lines exist (REL_CON pins 2-8).

### note · diag-script dwell/gap timings stay inline, not in DEVICE_CONFIG

`DWELL_S`, `GAP_S`, `STRESS_S` in the diag script are named constants
at the top of the file rather than `DEVICE_CONFIG` entries, because
this tool is a one-off bench utility run standalone via Thonny —
the [configurability.md](../../.claude/rules/ecc/common/configurability.md)
rule targets the runtime path, not tooling. Adjust by editing the
script.

### finding · relay-diag bench run — runtime path clean, boot transient is the cause

Bench run of `tools/relay_diag.py` (2026-05-15) confirmed three
distinct symptoms and split them by root cause:

1. **GP27 floats LOW persistently** (raw=0 in Phase 1) — explains
   `reserved_4` (REL_CON 8) clicking on at every reset.
2. **GP26 latches transiently during 3V3_EN reset** — Phase 1 reports
   raw=1 because by the time MicroPython probes, the line has
   drifted back HIGH. The relay still fires because the boot-window
   dip is long enough to latch the coil.
3. **REPL idle dim-LED on all 7 channels** — canonical floating-input
   signature; the GPIOs are high-Z whenever MicroPython hasn't taken
   ownership.

Phases 2–5 (Pico actively driving the pins) all passed: single
clicks per channel, no neighbour activity, no brownout under
simultaneous all-on stress. **The firmware path is healthy; the
problem is exclusively pre-MicroPython and REPL-idle, both of which
are windows the firmware cannot reach.** Full notes recorded in the
hw-test-log entry for the same date.

### decision · fix is hardware-only — track in dedicated PCB-revision doc

Software can't close the reset transient (the window between 3V3_EN
release and `Pin(gp, Pin.OUT, value=1)` executing) — by then the
relay has already latched. The correct fix is an external 10 kΩ
pull-up from each REL_CON IN line to the relay module's VCC rail.
That holds the line HIGH even with the Pico unpowered or in REPL
idle.

Created [pcb-revision-changes.md](pcb-revision-changes.md) as the
rolling source of truth for changes that require a PCB spin
(separate from [2026-05-14-pcb-codebase-gap-plan.md](2026-05-14-pcb-codebase-gap-plan.md),
which covers firmware gaps against the *current* board). Filed two
entries: (a) pull-ups on REL_CON pins 2–8, (b) decision on the
unwired 8th channel (pull-up vs. wire to spare GPIO — needs DMM
check of the existing 3V3 strap first).

## 2026-05-15 · Capacitive soil sensor unresponsive — NE555 unit, replace

### decision · require TLC555/7555-class chip; this unit was dead

Operator reported the soil sensor on GP28 returning random low values
that didn't move when the probe was submerged in water and only
"changed on restart". Bench-trace:

1. Initial wiring had sensor VCC tied to ADC_VREF (Pico pin 35) instead
   of 3V3 (pin 36). ADC_VREF is an RC-filtered reference, not a power
   rail; loading it with the sensor's ~5 mA draw dragged the reference
   itself, corrupting every ADC read on the Pico. Rewired VCC to 3V3.
2. After rewire, `print_raw()` returned 0–14 and AOUT-to-GND sat at
   ~0.3 V. Chip on the sensor PCB confirmed as **NE555** (bipolar,
   ≥4.5 V to oscillate), not TLC555 / 7555 / LMC555 (CMOS, run at 2 V).
   3.3 V is below the NE555's start threshold, so the oscillator never
   ran and AOUT floated.
3. Moved VCC to VBUS (Pico pin 40, measured 4.7 V) and added a 6.8 kΩ
   top + 10 kΩ bottom divider on AOUT → GP28 (ratio 0.595; worst-case
   5 V → 2.98 V at GP28, safely under the 3.3 V ADC ceiling, source
   impedance ~4 kΩ within the RP2040's recommended <10 kΩ window).
4. AOUT-to-GND still read 0 V at the sensor header even with the
   divider lifted (one resistor leg disconnected to rule out loading).
   The NE555 is dead — likely a damaged passive on the oscillator or
   the chip itself. 0.2 V residual is leakage, not a real signal.

Decision: replace with a TLC555-class capacitive sensor (DFRobot
SEN0193, Adafruit #4026, or any board where the seller confirms the
timer chip is CMOS — TLC555 / 7555 / ICM7555 / LMC555). With a
TLC555 unit the wiring reverts to VCC → 3V3 (pin 36), GND → any GND,
AOUT → GP28 with **no divider**. Keep the 6.8 k + 10 k pair for the
next project. Calibration values in `config.py` (`adc_dry_raw=850`,
`adc_wet_raw=350`) stay until the replacement arrives and a fresh
three-point `print_raw()` (air / moist soil / water) gives real
numbers; the eyes-on verification lives in
[docs/test/hw-test-log.md](../test/hw-test-log.md).

### note · ADC_VREF is not a power rail

For future reference on this board: Pico pin 35 (ADC_VREF) is filtered
3V3 meant to feed the ADC's reference voltage, not source current to
external loads. Anything that draws more than a few µA must come from
3V3 OUT (pin 36) or VBUS (pin 40), never ADC_VREF. Mis-wiring VCC to
ADC_VREF corrupts **every** ADC channel on the Pico, not just the
sensor's own pin.

## 2026-05-15 · Reserved relay GPIOs floated, parked HIGH

### decision · park GP21/22/26/27 HIGH via output_pins, not Pin.IN+PULL_UP

Operator reported the four reserved relay channels on REL_CON
(GP21, GP22, GP26, GP27) sitting in a half-powered pseudo-state and
asked for them to be pulled if unused. Root cause: the pins were
declared under `DEVICE_CONFIG["pins"]` but not listed in
`output_pins`, so `HardwareFactory._init_pins()` never configured
them — they boot as floating inputs and feed the active-low relay
inputs with an indeterminate voltage. Fix is to add all four to
`output_pins` with `True` (HIGH = relay off, matching the three
active relays). Chose Pin.OUT driven HIGH over Pin.IN + PULL_UP
because (a) it matches the existing pattern for `relay_fan_1/2` and
`relay_growlight`, (b) a deterministic CMOS drive is stiffer than
the RP2040's ~50 kΩ internal pull against a relay opto-isolator
load, and (c) the validator/test plumbing for output_pins already
exists. Validator entry and a `test_reserved_relays_parked_high`
guard ship in the same commit.

### issue · 3V3 rail on REL_CON measures dead

Separately reported: the REL_CON 3V3 pin reads 0 V. Pure hardware,
not addressable in software. Logged under `docs/test/hw-test-log.md`
with a bench checklist (3V3 pin continuity to Pico 3V3, JD-VCC /
VCC jumper position on the relay board, R/trace check on the rail).

## 2026-05-15 · SD-update version string scheme

### decision · use UTC datetime + git short hash, drop per-day bump

`tools/build_update_payload.py` previously generated versions of the
form `YYYY-MM-DD.N` and tried to bump `N` per day. Two bugs made `N`
always 1: the lookup path was `out_dir.parent` instead of `out_dir`
(stat'd `build/manifest.json`, which never exists), and `_clean_out_dir`
wiped the directory before the bump logic ran. Rather than fix the
bump, the format now embeds the build identity directly:
`YYYYMMDDTHHMMSSZ-<shorthash>` (UTC, ISO 8601 basic, FAT32-safe — no
colons). Hash comes from `git rev-parse --short HEAD`; falls back to
`nogit` when git is unavailable. `lib/updater.py` treats version as an
opaque string, so no consumer changes were needed and all 55 updater
tests still pass.

## 2026-05-15 · SD-update loading-screen feedback

### decision · standalone UpdateFeedback, built only when an update fires

The updater runs at `main.py:175` BEFORE EventLogger and BEFORE the
full `StatusManager` / `BuzzerController` are wired (per the
comments at `main.py:168-181`). To keep that ordering intact, the
loading-screen feedback ships as `lib/updater_feedback.UpdateFeedback`
— a self-contained class that owns its own `machine.Pin` row and
`machine.PWM` buzzer, with no dependency on `StatusManager` or
`BuzzerController`. `run_pending_update` only constructs it after
`has_pending_update()` returns True, so a boot with no payload leaves
the LED row dark and the buzzer silent.

### decision · reuse `status_leds.walk_order` for the chase direction

The chase LEDs are driven from `pins.{activity,sd,reminder,warning,
error}_led` resolved through `config["status_leds"]["walk_order"]`
rather than a new pin list under `updater_feedback`. That keeps the
POST sweep and the update sweep visually consistent — reorder the row
in one place and both follow.

### decision · per-file ticks audible, per-chunk steps silent

`Updater._step_feedback(audio=True)` fires once per file in
`verify_payload` and in `apply` so the buzzer chirps at honest "one
file done" intervals. The per-chunk calls inside `_hash_file` and
`_copy_file` pass `audio=False` so the chase keeps moving on big
payloads without turning the buzzer into a buzzsaw. A user
`step_delay_ms` knob throttles the visible chase when chunks come
faster than the row can read.

### decision · success/fail jingles play before `machine.reset()`

On `apply_ok` the success jingle plays while all five LEDs are lit,
then `finish()` clears outputs and `machine.reset()` reboots into the
new code. On verify/apply/load-manifest failure, the failure jingle
plays and the function returns normally so the rest of boot can
continue with the still-installed code.

## 2026-05-15 · Button debounce: no caps, external pull-up only (this rev)

### decision · RES_BTN direct short; MEN_BTN with 10 kΩ external pull-up, no cap

Bench-tested both buttons on the assembled PCB. RES_BTN (3V3_EN to GND)
and MEN_BTN (GP9 to GND) both behaved sporadically with a 100 nF cap to
GND; RES_BTN as a direct short worked flawlessly, and MEN_BTN works
reliably with an external 10 kΩ pull-up to 3V3 and no cap. A 100 nF
cap on MEN_BTN was also tried in parallel with the 10 kΩ pull-up and
still misbehaved.

Why the cap fails on 3V3_EN: that pin is the RT6150 regulator enable,
not a logic input. It has a real on/off threshold with a deadband
(~1.0–1.2 V). With 100 nF the line drifts up through the deadband over
~10 ms on release, so the regulator brown-outs / restarts / oscillates
during POR. Direct switch crosses the threshold in ns and POR is
clean.

Why the cap fails on GP9 even with a stronger pull-up: with the cap
sitting directly across the switch (no series resistance), each
contact closure dumps the cap instantly. The cap therefore provides no
press-side debounce benefit, and on release the bounce can still pull
the partly-recharged cap back to 0 V — producing extra falling edges
*outside* the 60 ms software debounce window. Result: false "press"
events on release. A 10 kΩ pull-up alone (no cap) leaves GP9 as a
clean digital input that the 60 ms software debounce in
[lib/led_button.py:142](../../lib/led_button.py#L142) handles fine.

Next board revision adds a 1 kΩ series resistor between the MEN_BTN
switch and GP9 so the canonical three-component debounce (10 kΩ
pull-up + 1 kΩ series + 100 nF cap to GND) can be reinstated. Until
then: caps are off the BOM for both buttons. The firmware still asks
for `Pin.PULL_UP` internally; that's redundant with the external 10 kΩ
but harmless — leave it for the host-shim path and so the input
floats sanely if the external resistor is ever removed.

## 2026-05-15 · POST LED walk follows physical row order

### decision · Drive POST walk from `status_leds.walk_order`

The five status LEDs on LED_CON sit in one row, left-to-right: green
(activity, GP4), blue (sd, GP5), white (reminder, GP8), yellow
(warning, GP6), red (error, GP7). `run_post()` previously walked them
in GPIO-instantiation order (activity → reminder → sd → warning →
error), which visually jumps across the row instead of sweeping
along it. Added a new `status_leds.walk_order` config entry — a list
of role names — that `run_post()` resolves to LED instances at boot,
with the on-board heartbeat LED always appended last so it's still
verified. Stored as role names rather than GPIO numbers so the
physical layout is readable in `config.py` without cross-referencing
the pin map. Validator rejects empty lists, unknown roles, and
duplicates; matching tests cover the new ordering and a missing-
reminder fallback. Operator can rewire the LED row and re-tune the
walk by editing one config line, no code change.

## 2026-05-15 · OLED warmup delays moved to config

### decision · Promote SSD1306 init sleeps to DEVICE_CONFIG["display"]

`OLEDDisplay._init_display()` ran a fixed `time.sleep(2.0)` startup
banner plus several smaller VRAM-clear / invert sleeps totalling ~2.4 s
per construction. Under host pytest this was ~150 s of the 155 s
suite (~50 fixture builds + ~14 `test_main` runs that build a real
OLEDDisplay). Promoted to three config keys — `startup_banner_s`
(2.0), `vram_clear_delay_s` (0.05), `invert_delay_s` (0.1) — with
validator entries and `test_config` rows. Tests pass 0 to skip the
sleeps; production defaults are unchanged. `test_main` additionally
stubs `OLEDDisplay` with `Mock()` since those tests don't exercise
the display. Full suite: 155 s → 9.5 s.

### note · Two construction sites in test_oled_display

Both the `oled_display` conftest fixture and the local
`_make_display` helper / `test_init_failure_is_non_fatal` /
`test_long_press_no_remount_cb_safe` direct constructions had to be
updated to pass `startup_banner_s=0`. If a future OLED test
constructs `OLEDDisplay` directly without those kwargs, it will be
~2.4 s slow — fixture this in the test if it spreads.

## 2026-05-15 · SD-update payload now ships compiled .mpy

### decision · Compile config and lib for SD-update payloads, keep main.py raw

`deploy-update-to-sdcard` (and `-nocheck`) now depend on `build-mpy`
and call `tools/build_update_payload.py --compiled`, which reads from
the `build/` tree instead of the source tree. Payload layout matches
flash-mpremote exactly: `main.py` raw (boot entry name), `config.mpy`,
and `lib/*.mpy`. Rationale: same size win on the SD-update path as on
the flash path, and a single artifact shape for both deployment
routes. `build_update_payload.py` still defaults to source-py mode
when run by hand without `--compiled`.

### decision · allowed_paths gains config.mpy, keeps config.py

`DEVICE_CONFIG["updater"]["allowed_paths"]` now lists `"main.py"`,
`"config.py"`, `"config.mpy"`, `"lib/"`. The `lib/` prefix already
matches `lib/*.mpy`. Both raw-py and compiled payloads pass the
updater's whitelist so an operator running the script manually
without `--compiled` still gets a valid payload.

## 2026-05-15 · Coverage push to 90%

### decision · Bumped global coverage from 88.68% to 92.94%

Added targeted tests for the lowest-covered modules so every `lib/`
file is ≥88% individually while leaving the `pyproject.toml`
`fail_under` gate at 88. New file `tests/test_sht31.py` covers the
driver end-to-end (100%). Existing test files were extended:
`test_sd_integration.py` (75 → 93%), `test_buffer_manager.py`
(78 → 89%, including the previously-untested
`start_fallback_prune_task` loop body), `test_co2_logger.py`
(85 → 96%), `test_soil_logger.py` (83 → 97%), `test_led_button.py`
(87 → 90%). 767 tests pass; the gate stays at 88 so future changes
can absorb minor regressions without rewriting tests.

### note · Async-loop test idiom for the prune task

`start_fallback_prune_task` is a `while True` loop driven by
`asyncio.sleep`. The pattern used for buffer_manager / co2_logger /
soil_logger error-path tests: patch `asyncio.sleep` with a side-effect
list that returns `None` once (allowing one iteration of the loop
body) then raises `CancelledError`. Combined with `pytest.raises`
this exercises both the body and the cancellation handler in one
test without leaking tasks.

## 2026-05-15 · SD-payload software updater — implementation

### decision · Updater promoted from scaffold to working implementation

All 15 xfailed scaffold tests now drive the real `lib/updater.py`
implementation. `has_pending_update`, `load_manifest`, `verify_payload`,
`apply`, `finalize`, `log`, `_is_path_allowed`, `_hash_file`, and
`run_pending_update` are functional on both host (CPython) and target
(MicroPython). Hex digests come from `binascii.hexlify(h.digest())` for
portability — MicroPython's `uhashlib.sha256` has no `hexdigest()`.

### decision · Apply target lives on a module-level `_FLASH_ROOT`

`apply()` writes verified files under `lib.updater._FLASH_ROOT` (default
`"/"` on the Pico). Tests monkeypatch this to a `tmp_path` so the host
flow can run end-to-end without touching real flash. Keeping it as a
module global (not a constructor arg) matches the test contract from
the scaffold round.

### note · Finalize is idempotent against half-finished prior runs

`finalize()` clears any stale `applied/<version>/` directory before
renaming `update/` into place. Without this, a Pico that died between
apply and reset would leave the previous apply's directory there and
`os.rename` would fail on the next boot.

### note · Apply-OK still resets even if finalize warns

If `apply` succeeded but `finalize` raises (rare: e.g. SD pull-out
between writing the last file and renaming the dir), the new code is
already live on flash. `run_pending_update` logs the finalize warning,
then still calls `machine.reset()` so the freshly-applied code boots
clean. `/sd/update/` may still be present and would re-trigger on next
boot, but verify would pass again (hashes match what we just wrote), so
worst case is a redundant apply.

### decision · Host helper `tools/build_update_payload.py` ships

Operator workflow: `python tools/build_update_payload.py [--copy-to
G:/update]`. Walks `main.py`, `config.py`, and `lib/*.py` excluding
vendored drivers (`ds3231.py`, `ds2321_gen.py`, `sdcard.py`, `ssd1306.py`,
and any `picozero*` / `sdcard-*` / `ssd1306-*` siblings). Auto-versions
as `YYYY-MM-DD.N` bumping N when a same-day build already exists in the
parent output dir. Round-trip verified against `Updater.verify_payload`
on the just-built output.

### note · VSCode tasks `build-update-payload` / `deploy-update-to-sdcard`

Two tasks added to `.vscode/tasks.json`: `build-update-payload` writes
into `build/update_payload/`, `deploy-update-to-sdcard` runs pytest
first then copies to `G:/update` with `--no-confirm`. A
`deploy-update-to-sdcard-nocheck` variant skips pytest for tight inner
loops. `.vscode/` is gitignored, so these tasks live only on Dennis's
working copy; the helper script itself (`tools/build_update_payload.py`)
is committed and works standalone from the CLI.

## 2026-05-15 · SD-payload software-update scaffold

### decision · Boot-time SD-payload updater replaces lib/, main.py, config.py

New `lib/updater.py` (scaffold) implements an operator workflow: drop a
payload tree under `/sd/update/` with a `manifest.json` listing per-file
SHA-256 hashes, power-cycle the Pico, and the device replaces its own
code without Thonny. Wire-in lives in `main.py` between
`HardwareFactory.setup()` (SD must be mounted) and `EventLogger` init
(so logging code can itself be replaced). On success the updater renames
`/sd/update/` to `/sd/applied/<version>/`, appends to `/sd/updates.log`,
and calls `machine.reset()`.

### decision · Full code+config replacement (overwrites config.py)

The payload is allowed to replace `main.py`, `config.py`, and any file
under `lib/`. Operator-tuned values in `config.py` are NOT preserved
across updates — the payload's `config.py` wins. The whitelist is
enforced by `Updater._is_path_allowed` and configured via
`updater.allowed_paths`. Anything outside the whitelist is a
verification failure and live code is never touched.

### decision · Integrity = per-file SHA-256 in manifest.json

Every file in the payload has a SHA-256 hash and byte count in
`manifest.json`. `verify_payload()` checks all files before any write;
a single hash mismatch or path-whitelist violation aborts the apply
with `/sd/update/` left untouched, so the next boot can retry after
the operator fixes the payload.

### decision · No backup of live code; retry-on-failure recovery

Per the 2026-05-15 clarifying round, the updater does NOT snapshot the
current `/lib/` before writing. If a write fails mid-loop, the updater
retries each file up to `updater.max_retries` (default 3). If retries
exhaust, the apply halts and logs `apply_fail`; live code may be in a
partial state, but `/sd/update/` is left in place so the next reboot
re-attempts. Recovery from a fundamentally bad payload is the
operator's responsibility — fix the SD card and reboot.

### note · Wire-in is live but guarded against the scaffold stub

`main.py` calls `run_pending_update(DEVICE_CONFIG, hardware, wdt)`
inside a `try/except Exception` so the current `NotImplementedError`
from the stub is caught and printed without blocking boot. Once the
real implementation lands, the same call site continues to work; the
guard remains as the documented "updater failures must never block
normal boot" policy.

### issue · Operator tooling not in scaffold — RESOLVED 2026-05-15

A helper (`tools/build_update_payload.py`) that walks a source tree
and emits `manifest.json` with computed hashes was out of scope for
the scaffold. It now ships in the implementation commit alongside
VSCode tasks `build-update-payload` and `deploy-update-to-sdcard`.

## 2026-05-15 · Growlight mode flag (relay_only vs dimmed)

### decision · Add `growlight.mode` config flag, default `relay_only`

Introduce `DEVICE_CONFIG["growlight"]["mode"]` with values `"dimmed"`
(MCP4725 DAC drives ViparSpectra XS1500 brightness over the GP20 relay
master-switch) or `"relay_only"` (skip MCP4725 init entirely, treat the
lamp as plain on/off). Default is `"relay_only"` — the current
deployment has reverted to the bare relay-pin connection and the
dimming hardware is not wired in. Operators that want XS1500 dimming
must opt in by setting `mode="dimmed"`. The existing implicit fallback
(warn + relay-only if DAC init throws while `mode="dimmed"`) is
preserved so a flaky DAC doesn't brick the lamp schedule.

### note · Validator enforces the enum

`validate_config()` rejects any value other than `"dimmed"` or
`"relay_only"`. Two new rows in `tests/test_config.py` cover the
invalid-string and the dimmed-happy-path. No change to the
`GrowlightController` class — `main.py` already passes `dac=None`
through the same constructor, so the controller is mode-agnostic.

## 2026-05-15 · DHT22 → SHT31 sensor migration

### decision · Replace DHT22 with SHT31-D on shared I2C0, no fallback path

The one-wire DHT22 on GP15 is replaced by a Sensirion SHT31-D on the
shared I2C0 bus (RTC + OLED + DAC). New driver is `lib/sht31.py`
(CRC-validated single-shot high-repeatability, addresses 0x44 / 0x45).
GP15 becomes free for future use. The user explicitly waived a DHT21
fallback path — no dual-sensor support, no probe wrapper. Existing
`/sd/dht_log_*.csv` files stay on disk but new logs use `th_log_*.csv`.

### decision · Rename DHTLogger → TempHumidityLogger and inject sensor

`lib/dht_logger.py` becomes `lib/temp_humidity_logger.py` with class
`TempHumidityLogger`. The sensor is now constructor-injected (any
object with `measure() / temperature() / humidity()`) instead of
being built from a GPIO pin inside `__init__`. Downstream consumers
that previously took `dht_logger=` now take `th_logger=`
(FanController, HeaterController, OLEDDisplay). Status-manager keys
follow the rename: `dht_intermittent` → `th_intermittent`,
`dht_dead` → `th_dead`.

### decision · CSV columns unchanged, filename renamed to th_log

CSV header stays `Timestamp,Temperature,Humidity` so downstream
dashboards / readers keep working. Filename basename moves from
`dht_log` to `th_log` to match the rename-everywhere choice. Old
`dht_log_*.csv` files are not migrated; they sit alongside the new
files until the operator archives them manually.

### note · Probe data carries over, fail-rate revised

`PROBE.dht` becomes `PROBE.sht31` in `host_shims/_probe_data.py`.
Temperature/humidity distributions inherit the legacy DHT22 probe
data (same greenhouse) but the simulated fail rate drops from 2% to
0.5% and `min_interval_s` drops to 0.05 s to reflect I2C reliability
and a 16 ms high-repeatability conversion time. `hw_probe.py` now
runs `probe_sht31_endurance` in place of the old DHT22 bucket.

## 2026-05-14 · Phase 4 — Soil moisture (GP28 ADC)

### decision · SoilLogger mirrors CO2Logger / DHTLogger shape

`SoilLogger` is another BufferManager-backed CSV writer with date
rollover and an async `log_loop()` that yields. The only structural
difference is the input source (`machine.ADC.read_u16()` instead of a
UART frame) and a status-manager hook for the low-moisture warning.
Keeping the shape uniform across loggers means the next agent reads
one pattern, not three.

### decision · Calibration constants live in 0-1023 space, not raw u16

`read_u16()` returns 0–65535 on the RP2040, but the project convention
(plan section 4.1, REPL `print_raw()`, hardware datasheets) all speak
in 10-bit 0–1023. `SoilLogger` scales the u16 read down internally and
exposes only the 10-bit value as `last_raw` / in the CSV / in the OLED
"Raw:" row. Operators recalibrating with `print_raw()` see the same
units that go into `adc_dry_raw` / `adc_wet_raw`.

### decision · Warning LED via StatusManager.set_warning("soil_low", …)

Per the chosen option, soil low-moisture surfaces only on the warning
LED + OLED, not via the buzzer or EventLogger (beyond the natural
`WARN`/`INFO` lines on each transition). The warning key is
`soil_low`; the LED stays solid as long as the percent is below
`warn_pct_below` and clears on the first recovery cycle. No event-log
re-firing on every cycle because StatusManager already de-duplicates
keys.

### decision · `validate_config()` rejects dry <= wet at boot

Calibration mistakes (swapping dry/wet, or using the same raw value
for both) would silently produce nonsensical percentages or
divide-by-zero ratios. Catching it at boot is consistent with how the
heater's `day_min_temp >= night_min_temp` and the CO2 logger's
`override_ppm_on > override_ppm_off` are guarded. SoilLogger's
constructor also re-asserts the inequality so the unit tests can
exercise the guard without booting the whole config.

### note · OLED CO2 page upgraded as part of this phase

Phase 3 landed the CO2 logger but left the OLED `co2` menu as a
"Not active / future" placeholder. Phase 4 already had to extend
`OLEDDisplay` to inject `soil_logger`, so the `co2_logger` kwarg
landed in the same commit and the placeholder render was replaced
with `PPM: N` + `Vent: ON/off`. Future phases should not re-touch
this surface unless they add new fields.

### decision · ADC `read_u16` → 0-1023 uses round-half-up

The naive integer downscale `(u16 * 1023) // 65535` truncates and
gives off-by-one results at calibration anchor points
(`u16 == raw10 * 65535 / 1023`). `SoilLogger` uses
`(u16 * 1023 + 32767) // 65535` so a round-tripped calibration value
maps back to itself. Negligible cost on the Pico and removes a class
of test-flakiness.

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
