# Pi Greenhouse — Coding Conventions

This document captures the project's coding conventions, decision rationale, and patterns for both human and AI contributors.

## Architecture principles

1. **Dependency injection everywhere** — Components receive their dependencies via constructor parameters. No module-level hardware initialisation. This makes every module independently testable with mocks.

2. **Single hardware factory** — Only `HardwareFactory` creates hardware objects (`Pin`, `I2C`, `SPI`). All other modules receive pre-created objects.

3. **Async-only long-running logic** — Every loop that runs for the lifetime of the program must be a `uasyncio` task using `await asyncio.sleep()`. Never use busy-wait or blocking `time.sleep()` in tasks (exception: short retry delays in sensor reads).

4. **Tiered storage** — `BufferManager` owns all file I/O: SD card (primary) → `/local/fallback.csv` (degraded) → RAM buffer (last resort). On SD recovery, fallback entries are migrated before new writes to preserve CSV ordering.

5. **The greenhouse must keep running** — Prefer degraded operation over hard failure. If a component fails, disable it and continue. Only RTC failure is fatal (timestamps would be meaningless).

## Naming conventions

| Kind | Convention | Examples |
| ------ | ----------- | ---------- |
| Classes | `PascalCase` | `FanController`, `BufferManager`, `RTCTimeProvider` |
| Functions / methods | `snake_case` | `read_sensor()`, `start_cycle()`, `get_state()` |
| Variables / params | `snake_case` | `time_provider`, `max_retries`, `poll_interval_s` |
| Constants | `UPPER_SNAKE` | `DEVICE_CONFIG`, `FAKE_LOCALTIME` |
| Files / modules | `snake_case` | `buffer_manager.py`, `dht_logger.py` |
| Config section names | `snake_case` | `fan_1`, `dht_logger`, `event_logger` |
| Logger module tags | Class name string | `"FanController"`, `"DHTLogger"`, `"BufferMgr"` |

**Legacy exception**: `Service_reminder` config key uses mixed case. Do not rename it (would break on-device config files), but use `snake_case` for all new keys.

## GPIO conventions

- **Relay logic is inverted**: `Pin.value(1)` = OFF, `Pin.value(0)` = ON. All relay controllers use `RelayController(pin, invert=True)`.
- **LEDs are active-HIGH**: `Pin.value(1)` = ON, `Pin.value(0)` = OFF.
- **Button is active-LOW** with internal pull-up: pressed = `value() == 0`.
- All pin assignments live in `DEVICE_CONFIG["pins"]` — never hardcode GPIO numbers.

## Logging decision tree

```text
Is it a development diagnostic / state snapshot / cycle tick?
  → DEBUG (console-only by default; costs nothing when disabled)

Is it a normal operational event (startup, state change, scheduled action)?
  → INFO (buffered, flushed every 5 entries)

Is it a recoverable problem (retry, degraded mode, threshold crossed)?
  → WARN (buffered, flushed every 3 entries)

Is it a failure that needs human attention (data loss risk, component down)?
  → ERROR (immediate flush + error LED)
```

### Structured debug fields

Use keyword arguments for machine-parseable diagnostics:

```python
self.logger.debug("FanController", "cycle tick",
                  temp=23.5, state="ON", elapsed_s=45, threshold=23.8)
# Output: [2026-03-01 14:23:45] [DEBUG] [FanController] cycle tick | temp=23.5 state=ON elapsed_s=45 threshold=23.8
```

### Pre-logger bootstrap

Before `EventLogger` exists (Steps 1–4 of init), use bare `print()`:

```python
print("[STARTUP] Configuration validated")
print("[STARTUP ERROR] Critical hardware initialization failed")
```

After init, always use `self.logger.info/warning/error/debug()`.

## Error handling decision tree

```text
Async task loop (fan cycle, sensor log, scheduler)?
  → Pattern 1: while True / try / CancelledError (re-raise) / Exception (log + backoff)

Sensor read / SD mount (finite retries)?
  → Pattern 2: for attempt in range(max_retries) / try / except (log + delay)

Multi-component init (HardwareFactory)?
  → Pattern 3: accumulate errors in list, continue setup, report at end

File I/O (BufferManager)?
  → Pattern 4: try SD → try fallback → buffer in RAM

Component init with optional dependency?
  → Pattern 5: try with dep → except → retry without dep (graceful degradation)
```

### Rules

- **Always** separate `asyncio.CancelledError` from `Exception` and re-raise it.
- **Never** silently swallow exceptions — minimum severity is `WARNING`.
- **Always** include the exception string in the log message: `f"Failed: {e}"`.
- Use `self.logger.error()` only for conditions that need human attention (it triggers the error LED and immediate flush).

## Config conventions

- All tunable values live in `DEVICE_CONFIG` in `config.py`.
- Every new feature section needs:
  1. A key block in `DEVICE_CONFIG` with sensible defaults.
  2. Required key names added to `validate_config()`'s `required_keys` dict.
  3. Value range checks in `validate_config()`.
- Units should be clear from key names: `_s` for seconds, `_ms` for milliseconds, `_pct` for percentages, `_hz` for Hz.

## CSV conventions

- Timestamps: ISO-8601 `YYYY-MM-DD HH:MM:SS` from `TimeProvider.now_timestamp()`.
- Header row written on file creation (first write to a new date-based file).
- Date-based rollover: `dht_log_YYYY-MM-DD.csv`.
- Always use `BufferManager.write(relpath, data)` with relative paths.

## Commit message format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<scope>): <description>

[optional body]
```

| Type | When |
| ------ | ------ |
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `ci` | CI/CD pipeline changes |
| `chore` | Build process, dependency updates |

Scope matches the module: `relay`, `buffer`, `logger`, `dht`, `config`, `main`, `ci`.

## Test conventions

- Every `lib/<module>.py` has `tests/test_<module>.py`.
- One test class per logical unit (e.g., `TestFanController`, `TestRelayController`).
- Fixtures in `conftest.py` provide pre-wired component instances.
- Async tests: just declare `async def test_*()` — pytest-asyncio auto mode handles the loop.
- Coverage threshold: 88% (enforced in CI and `pyproject.toml`).
- Use `tmp_path` for all filesystem tests — never write to the real project directory.

## File organisation

```text
config.py                          # DEVICE_CONFIG + validate_config()
main.py                            # 9-step DI orchestrator
lib/
  buffer_manager.py                # Tiered storage (SD → fallback → RAM)
  buzzer.py                        # PWM buzzer controller
  dht_logger.py                    # DHT22 sensor reader + CSV writer
  event_logger.py                  # System logger (DEBUG/INFO/WARN/ERR)
  hardware_factory.py              # Hardware init (RTC, SPI, SD, GPIO)
  led_button.py                    # LED + button + ServiceReminder
  relay.py                         # RelayController → Fan/Growlight
  sd_integration.py                # SD mount/unmount helpers
  status_manager.py                # Status LEDs + heartbeat
  time_provider.py                 # TimeProvider + sunrise/sunset
host_shims/                        # CPython stubs for MicroPython modules
tests/
  conftest.py                      # Mock stubs + shared fixtures
  test_<module>.py                 # One per lib/ module
docs/
  conventions.md                   # This file
  prompts/                         # AI prompt templates
.github/
  copilot-instructions.md          # AI agent instructions
  workflows/ci.yml                 # GitHub Actions CI pipeline
```
