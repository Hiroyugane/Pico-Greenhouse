# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Pi Greenhouse — a MicroPython environmental control system for the Raspberry Pi Pico (SHT31-D sensing on shared I2C0, two-fan relay control with thermostat override, scheduled grow light, SD logging with fallback). Same source runs on the Pico under MicroPython and on Windows/CPython for development via shims in [host_shims/](host_shims/).

## Common commands

Setup and tests run from the repo root with the project venv (`.venv/`) active:

```powershell
pip install -r requirements.txt              # pytest, pytest-asyncio, ruff, pre-commit
pytest tests/                                # full suite (asyncio_mode=auto)
pytest tests/test_relay.py                   # single file
pytest tests/test_relay.py::TestFanController::test_thermostat_on -v
pytest tests/ --cov=lib --cov=config --cov-report=term-missing   # coverage; gate is fail_under=88
ruff check . --fix                           # lint+autofix (config in pyproject.toml)
ruff format .                                # format
pre-commit run --all-files                   # ruff + pytest pre-push gate
python main.py                               # run the full system on host using shims
```

On-device (via Thonny on the Pico): run [rtc_set_time.py](rtc_set_time.py) once to seed the DS3231, then [main.py](main.py).

## Architecture — what's not obvious from the file tree

**Same code, two runtimes.** [main.py:29-34](main.py#L29-L34) detects `sys.implementation.name != "micropython"` and prepends [host_shims/](host_shims/) to `sys.path`. The shims provide `machine`, `micropython`, `os`, `framebuf`, an `sht31` simulator that mirrors [lib/sht31.py](lib/sht31.py), and a `uasyncio` that aliases standard `asyncio`. Anything new that imports MicroPython-only APIs needs a corresponding shim, or it will only work on-device.

**Tests never import shims.** [tests/conftest.py](tests/conftest.py) replaces `sys.modules["machine"|"micropython"|"uasyncio"]` with `MagicMock`-based stubs **before** any `lib/` import, and monkey-patches `asyncio.sleep_ms` / `time.sleep_ms` / `time.ticks_ms` so MicroPython idioms work under CPython pytest. Importing `lib.*` at module top-level in a test file will bypass these patches — always import inside the test or fixture (the existing fixtures do this).

**DI + factory, no globals.** [main.py](main.py) is the only place that wires components. Order matters and is enforced by [lib/hardware_factory.py](lib/hardware_factory.py): RTC (critical) → SPI/SD → GPIO. All timestamps flow through a single `RTCTimeProvider` ([lib/time_provider.py](lib/time_provider.py)); no module calls the RTC directly.

**Tiered writes go through one chokepoint.** All persistent writes (`TempHumidityLogger`, `EventLogger`) call into [lib/buffer_manager.py](lib/buffer_manager.py), which tries SD → `/local/fallback.csv` → in-memory ring buffer, and migrates fallback rows back to SD when the card returns. SD hot-swap recovery is driven by the main loop polling `is_mounted()`; do not bypass `BufferManager` with direct file I/O. Async drainage is coordinated by [lib/write_queue_manager.py](lib/write_queue_manager.py).

**Relays are inverted.** All relay GPIOs are active-low (HIGH=off, LOW=on). [lib/relay.py](lib/relay.py) `RelayController(invert=True, ...)` handles this; downstream code uses `on()`/`off()` semantically. Don't write raw `pin.value(1)` for "on".

**Fan thermostat reads from `TempHumidityLogger`.** `FanController` does not own a sensor — it reads `th_logger.last_temperature` cached on the logger. A fan running in tests therefore needs a `mock_th_logger` (or the real one) wired in, even if you only care about the schedule path.

**Configuration is one dict, validated at boot.** [config.py](config.py) `DEVICE_CONFIG` holds every pin / interval / threshold; `validate_config()` runs at startup and is the only check. New config keys must be added to both the dict and the validator, and to [tests/test_config.py](tests/test_config.py).

**Watchdog is async.** `feed_watchdog()` in [main.py:53](main.py#L53) runs as a uasyncio task. If the scheduler stalls, the WDT resets the Pico — long-blocking operations inside any task will brick the system on real hardware even when host tests pass. Keep tasks await-friendly.

## Coverage and lint config

[pyproject.toml](pyproject.toml) is the single source of truth: `asyncio_mode = "auto"`, coverage `fail_under = 88`, ruff `line-length = 120` selecting `E,F,I` (Pyflakes + isort). Vendored drivers (`lib/picozero*`, `lib/sdcard*`, `lib/ds3231.py`, `lib/ds2321_gen.py`, `lib/ssd1306*`), `host_shims/`, and `typings/` are excluded from both lint and coverage — don't try to "fix" them.

## Project-specific instructions

This repo loads detailed rules from [.claude/rules/ecc/common/](.claude/rules/ecc/common/) on every session. Three are load-bearing for day-to-day work:

- [clarifying-questions.md](.claude/rules/ecc/common/clarifying-questions.md) — at the start of any new work-shaped prompt, ask 3–4 clarifying questions via `AskUserQuestion` before planning or editing. Skip for mechanical follow-ups, pure information requests, or when the user says "just do it".
- [documentation-routine.md](.claude/rules/ecc/common/documentation-routine.md) — after any session that touches user-visible behavior, hardware, permissions, or anything not exercisable by `pytest`, append a checklist entry to [docs/test/hw-test-log.md](docs/test/hw-test-log.md). After any session that produced a decision, spec clarification, deviation, issue, or non-obvious note, append to [docs/notes/chat-log.md](docs/notes/chat-log.md). Mention both files in the end-of-turn summary.
- [commit-granularity.md](.claude/rules/ecc/common/commit-granularity.md) — one logical change per commit so future AI sessions can reconstruct intent from `git log` alone. Refactor and behavior changes split into separate commits; tests ship with the code they cover; no `wip` / `checkpoint` / grab-bag commits; no squash-merging.
