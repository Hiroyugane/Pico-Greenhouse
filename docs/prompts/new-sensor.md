# Prompt: Add a New Sensor

Use this prompt to add a new sensor reader (e.g., CO2/UART, soil moisture/ADC, light level/I2C).

---

## Pipeline integration

This is a **Phase 3 sub-prompt** for the agent pipeline (`docs/prompts/pipeline.md`). When used from the pipeline, Phase 2 produces the implementation plan based on these steps, and Phase 3 executes it. Can also be used standalone.

---

## Context

You are working on the Pi Greenhouse project — a MicroPython system on a Raspberry Pi Pico. Sensor data is logged to CSV files via `BufferManager` (SD → fallback → RAM). The existing `DHTLogger` is the reference implementation for sensor modules.

## Task

Add a new sensor logger called `{SensorName}Logger` for `{sensor_description}`.

## Step-by-step

### 1. Config (`config.py`)

```python
"{config_key}": {
    "interval_s": 30,          # Read interval in seconds
    "max_retries": 3,          # Sensor read retries
    "retry_delay_s": 0.5,      # Delay between retries
    "max_buffer_size": 200,    # Max in-memory readings
    # Sensor-specific thresholds:
    # "min_value": ...,
    # "max_value": ...,
},
```

Add required keys + validation to `validate_config()`.

### 2. Sensor logger class (`lib/{module_name}.py`)

```python
class {SensorName}Logger:
    def __init__(self, pin, time_provider, buffer_manager, logger,
                 interval, max_retries=3, retry_delay_s=0.5,
                 status_manager=None, filename="/sd/{csv_base}"):
        self.pin = pin
        self.time_provider = time_provider
        self.buffer_manager = buffer_manager
        self.logger = logger
        self.interval = interval
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s
        self.status_manager = status_manager
        self.base_filename = filename
        self._current_date = None
        self._current_file = None
        self.last_value = None
        # Initialize hardware sensor via DI
        self.logger.info("{SensorName}Logger", "Initialized")

    def read_sensor(self):
        """Read sensor with retry — Pattern 2."""
        for attempt in range(self.max_retries):
            try:
                value = self._do_read()  # hardware-specific
                if self._validate(value):
                    return value
                self.logger.warning("{SensorName}Logger",
                    f"Out of range: {value}")
            except Exception as e:
                self.logger.warning("{SensorName}Logger",
                    f"Read attempt {attempt+1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay_s)
        return None

    async def log_loop(self):
        """Async logging loop — Pattern 1."""
        while True:
            try:
                value = self.read_sensor()
                if value is not None:
                    self.last_value = value
                    self._write_csv(value)
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                self.logger.warning("{SensorName}Logger", "Task cancelled")
                raise
            except Exception as e:
                self.logger.error("{SensorName}Logger", f"Unexpected error: {e}")
                await asyncio.sleep(1)

    def _write_csv(self, value):
        """Write reading to date-based CSV via BufferManager."""
        timestamp = self.time_provider.now_timestamp()
        date_str = timestamp[:10]  # YYYY-MM-DD

        # Date-based rollover
        if date_str != self._current_date:
            self._current_date = date_str
            self._current_file = f"{self.base_filename}_{date_str}.csv"
            # Write header to new file
            self.buffer_manager.write(
                self._strip_sd(self._current_file),
                "timestamp,{field1},{field2}\n"
            )

        self.buffer_manager.write(
            self._strip_sd(self._current_file),
            f"{timestamp},{value}\n"
        )
```

### 3. Host shim (`host_shims/{shim_name}.py`)

If the sensor needs a MicroPython driver not available on CPython:

```python
class {SensorDriver}:
    """Host simulation stub for {sensor_description}."""
    def __init__(self, *args, **kwargs):
        self._value = 400  # sensible default

    def measure(self):
        import random
        self._value += random.uniform(-5, 5)

    @property
    def value(self):
        return self._value
```

### 4. Wire in `main.py`

After existing loggers (Step 6 block), add:

```python
{var_name}_config = DEVICE_CONFIG.get("{config_key}", {})
{var_name} = {SensorName}Logger(
    pin=DEVICE_CONFIG["pins"]["{pin_key}"],
    time_provider=time_provider,
    buffer_manager=buffer_manager,
    logger=logger,
    interval={var_name}_config.get("interval_s", 30),
    max_retries={var_name}_config.get("max_retries", 3),
    status_manager=status_manager,
    retry_delay_s={var_name}_config.get("retry_delay_s", 0.5),
)
```

In Step 9: `asyncio.create_task({var_name}.log_loop())`

### 5. Tests

- **Fixture** in `conftest.py` using `mock_event_logger`, `buffer_manager`, `time_provider`
- **Test read_sensor**: successful read, retry on failure, all retries exhausted
- **Test log_loop**: one iteration writes CSV
- **Test date rollover**: changing date creates new file with header
- **Test CancelledError**: clean shutdown
- **Test validation**: out-of-range values rejected

## Verification checklist

- [ ] Config section with defaults + `validate_config()` updated
- [ ] Logger class follows DHTLogger patterns (DI, retry, async loop)
- [ ] CSV uses ISO-8601 timestamps, date-based rollover, header row
- [ ] Writes via `buffer_manager.write(relpath, data)` — relative paths only
- [ ] Host shim added (if needed for MicroPython-only driver)
- [ ] Wired in `main.py` with graceful degradation fallback
- [ ] Tests cover read/retry/loop/rollover/cancel/error
- [ ] `ruff check .` + `pytest tests/ -v` pass
