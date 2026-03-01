# Prompt: Add a New Relay Controller

Use this prompt with any AI coding agent to add a new relay-controlled device (e.g., CO2 solenoid, humidifier, exhaust fan, heater).

---

## Pipeline integration

This is a **Phase 3 sub-prompt** for the agent pipeline (`docs/prompts/pipeline.md`). When used from the pipeline, Phase 2 produces the implementation plan based on these steps, and Phase 3 executes it. Can also be used standalone.

---

## Context

You are working on the Pi Greenhouse project — a MicroPython system running on a Raspberry Pi Pico. The codebase uses dependency injection, `uasyncio` for concurrency, and `RelayController` as a base class for all relay-driven devices. GPIO logic is **inverted** (HIGH=off, LOW=on).

## Task

Add a new relay controller called `{ControllerName}Controller` for `{device_description}`.

## Step-by-step

### 1. Config (`config.py`)

Add a new section to `DEVICE_CONFIG`:

```python
"{config_key}": {
    "interval_s": ...,       # Cycle interval in seconds
    "on_time_s": ...,        # ON duration per cycle
    # Add device-specific thresholds:
    # "max_value": ...,
    # "hysteresis": ...,
    "poll_interval_s": 5,    # Control loop check interval
},
```

Add required keys to `validate_config()`:

```python
"{config_key}": ["interval_s", "on_time_s", "poll_interval_s"],
```

Add value range checks:

```python
if DEVICE_CONFIG["{config_key}"]["on_time_s"] <= 0 or DEVICE_CONFIG["{config_key}"]["interval_s"] <= 0:
    raise ValueError("{config_key} timing values must be > 0")
```

### 2. Controller class (`lib/relay.py`)

Subclass `RelayController`:

```python
class {ControllerName}Controller(RelayController):
    def __init__(self, pin, time_provider, logger, interval_s, on_time_s, poll_interval_s, name="{ControllerName}"):
        super().__init__(pin, invert=True, name=name)
        self.time_provider = time_provider
        self.logger = logger
        self.interval_s = interval_s
        self.on_time_s = on_time_s
        self.poll_interval_s = poll_interval_s
        self.logger.info(name, f"Init: interval={interval_s}s on={on_time_s}s")

    async def start_cycle(self):
        """Main async control loop — Pattern 1."""
        while True:
            try:
                # ... control logic ...
                await asyncio.sleep(self.poll_interval_s)
            except asyncio.CancelledError:
                self.turn_off()
                self.logger.warning(self.name, "Task cancelled, relay OFF")
                raise
            except Exception as e:
                self.logger.error(self.name, f"Unexpected error: {e}")
                await asyncio.sleep(1)

    def get_state(self):
        state = super().get_state()
        state.update({
            "interval_s": self.interval_s,
            "on_time_s": self.on_time_s,
            # ... device-specific state ...
        })
        return state
```

### 3. Wire in `main.py`

In Step 7 block:

```python
{var_name}_config = DEVICE_CONFIG.get("{config_key}", {})
{var_name} = {ControllerName}Controller(
    pin=DEVICE_CONFIG["pins"]["{pin_key}"],
    time_provider=time_provider,
    logger=logger,
    interval_s={var_name}_config.get("interval_s", 600),
    on_time_s={var_name}_config.get("on_time_s", 20),
    poll_interval_s={var_name}_config.get("poll_interval_s", 5),
    name="{ControllerName}",
)
```

In Step 9: `asyncio.create_task({var_name}.start_cycle())`

### 4. Fixture in `tests/conftest.py`

```python
@pytest.fixture
def {var_name}_controller(time_provider, mock_event_logger):
    from lib.relay import {ControllerName}Controller
    return {ControllerName}Controller(
        pin=99, time_provider=time_provider, logger=mock_event_logger,
        interval_s=600, on_time_s=20, poll_interval_s=5,
    )
```

### 5. Test file `tests/test_{test_name}.py`

Create tests following this structure:

- `TestInit`: verify all params stored, logger called
- `TestState`: `get_state()` returns expected dict
- `TestOnOff`: `turn_on()`/`turn_off()` toggle relay
- `TestAsyncCycle`: one iteration with `asyncio.sleep` patched to raise `RuntimeError`
- `TestCancelledError`: verify relay OFF + re-raise
- `TestUnexpectedError`: verify error logged + loop continues

### 6. Update docs

Add the new controller to:

- `.github/copilot-instructions.md` module table and Mermaid diagram
- `tests/README.md` test file table

## Verification checklist

- [ ] Config section with sensible defaults
- [ ] `validate_config()` checks required keys and value ranges
- [ ] Controller subclasses `RelayController` with `invert=True`
- [ ] Async loop uses Pattern 1 (CancelledError + Exception)
- [ ] `get_state()` includes all controller-specific fields
- [ ] Wired in `main.py` Steps 7 + 9
- [ ] conftest.py fixture added
- [ ] Test file with init/state/async/error coverage
- [ ] `ruff check .` passes
- [ ] `pytest tests/ -v` passes
- [ ] `python main.py` host simulation runs without error
