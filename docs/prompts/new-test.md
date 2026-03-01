# Prompt: Generate Tests for a Module

Use this prompt to generate a comprehensive test file for an existing or new module.

---

## Context

You are working on the Pi Greenhouse project. Tests live in `tests/test_<module>.py` and use `pytest` + `pytest-asyncio` (auto mode) + `pytest-mock`. Fixtures are defined in `tests/conftest.py`. MicroPython modules (`machine`, `dht`, `uasyncio`) are mocked at import time.

## Task

Generate tests for `lib/{module_name}.py` (or `{file_name}.py`).

## Instructions

### 1. Read the source module

Read through `lib/{module_name}.py` and identify:

- All public methods and their signatures
- Constructor parameters and stored state
- Error paths (try/except blocks)
- Async methods (need `async def test_*()`)
- Dependencies injected via constructor

### 2. Create or update fixture in `conftest.py`

Follow the existing pattern:

```python
@pytest.fixture
def {fixture_name}(time_provider, mock_event_logger, buffer_manager):
    from lib.{module_name} import {ClassName}
    return {ClassName}(
        # wire DI dependencies from existing fixtures
        time_provider=time_provider,
        logger=mock_event_logger,
        buffer_manager=buffer_manager,
        # ... module-specific params with test-friendly values
    )
```

### 3. Test file structure

File: `tests/test_{module_name}.py`

```python
# Tests for lib/{module_name}.py
# Covers: {brief description of what's tested}

from unittest.mock import Mock, patch
from tests.conftest import FAKE_LOCALTIME


class TestInit:
    """Constructor stores params correctly."""

    def test_init_stores_params(self, {fixture_name}):
        assert {fixture_name}.some_param == expected_value

    def test_init_logs_startup(self, {fixture_name}):
        # Verify logger.info was called during init
        {fixture_name}.logger.info.assert_called()


class TestPublicMethods:
    """Tests for each public method."""

    def test_method_happy_path(self, {fixture_name}):
        result = {fixture_name}.method()
        assert result == expected

    def test_method_error_path(self, {fixture_name}):
        # Force error condition, verify logging + graceful handling
        pass


class TestAsyncMethods:
    """Tests for async methods (if any)."""

    async def test_async_one_iteration(self, {fixture_name}):
        """Run one loop iteration by making sleep raise."""
        with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
            try:
                await {fixture_name}.async_method()
            except RuntimeError:
                pass
        # Assert expected state after one tick

    async def test_cancelled_error_cleanup(self, {fixture_name}):
        """CancelledError triggers cleanup and re-raises."""
        import asyncio
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await {fixture_name}.async_method()
        # Assert cleanup happened (e.g., relay turned off)

    async def test_unexpected_error_continues(self, {fixture_name}):
        """Unexpected errors are logged, loop continues."""
        call_count = 0
        async def controlled_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("stop")
        # Patch to cause one error, then stop
        pass


class TestEdgeCases:
    """Boundary values and unusual inputs."""

    def test_none_optional_dependency(self, time_provider, mock_event_logger):
        """Module works when optional dependency is None."""
        from lib.{module_name} import {ClassName}
        obj = {ClassName}(..., status_manager=None)
        # Verify no crash

    def test_boundary_value(self, {fixture_name}):
        pass
```

### 4. Coverage targets

- All public methods have at least one happy-path test
- All `except` blocks are exercised
- Async methods tested for: one iteration, CancelledError, unexpected error
- Optional dependencies tested with `None`
- Boundary values for numeric thresholds

## Key fixtures available in conftest.py

| Fixture | Type | Description |
| --------- | ------ | ------------- |
| `time_provider` | `RTCTimeProvider` | Real provider with mock RTC |
| `base_time_provider` | `TimeProvider` | Simpler base class |
| `buffer_manager` | `BufferManager` | Real instance with `tmp_path` filesystem |
| `event_logger` | `EventLogger` | Real wired instance |
| `mock_event_logger` | `Mock` | Lightweight mock with `.info/.warning/.error/.debug` |
| `mock_status_manager` | `Mock` | Mock StatusManager |
| `mock_rtc` | `Mock` | Mock DS3231 RTC |
| `dht_logger` | `DHTLogger` | Real instance with mocked sensor |
| `fan_controller` | `FanController` | Wired with mocks |
| `growlight_controller` | `GrowlightController` | Wired with mocks |
| `buzzer_controller` | `BuzzerController` | Wired with mocks |
| `led_handler` | `LEDButtonHandler` | Wired with mock pins |

## Verification checklist

- [ ] Fixture added to `conftest.py` (if new module)
- [ ] One test class per logical unit
- [ ] Happy path + error path for each public method
- [ ] Async tests use `async def` (pytest-asyncio auto mode)
- [ ] CancelledError test for every async loop
- [ ] `mock_event_logger` used for lightweight tests, `event_logger` for integration
- [ ] All tests pass: `pytest tests/test_{module_name}.py -v`
- [ ] Coverage adequate: `pytest tests/test_{module_name}.py --cov=lib.{module_name} --cov-report=term-missing`
