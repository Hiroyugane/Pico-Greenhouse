# Prompt: Diagnose and Fix a Bug

Use this prompt to guide a systematic bug investigation through diagnosis, minimal fix, and regression testing.

---

## Pipeline integration

This is a **Phase 3 sub-prompt** for the agent pipeline (`docs/prompts/pipeline.md`). When used from the pipeline, Phase 1 (Brainstorm) produces the root cause analysis, Phase 2 (Design) defines the fix strategy, and this prompt guides Phase 3 implementation. Can also be used standalone.

---

## Context

You are working on the Pi Greenhouse project — a MicroPython system on a Raspberry Pi Pico. The codebase uses dependency injection, `uasyncio` for concurrency, and tiered storage (SD → fallback → RAM). All modules are independently testable with mocks via `conftest.py` fixtures.

## Task

Diagnose and fix: **{describe the symptom — e.g., "Fan relay stays on after temperature drops below threshold"}**

## Step 1 — Reproduce and isolate

1. **Check existing tests** — does `pytest tests/test_{module}.py -v` pass? If yes, the bug is in an untested code path.
2. **Search for the symptom** in logs or code:

   ```bash
   # In device logs (if available):
   grep -i "error\|warn\|fail" sd/system.log

   # In code:
   grep -rn "{keyword}" lib/ main.py
   ```

3. **Trace the call chain** — starting from the symptom, walk backwards through:
   - Which method produces the wrong output?
   - What inputs does it receive? Are they correct?
   - Who calls this method? (`grep -rn "method_name" lib/ main.py`)
4. **Check the DI wiring** in `main.py` — is the correct dependency injected? Wrong provider or missing config key?

## Step 2 — Identify root cause

Classify the bug:

| Category | Examples | Where to look |
| -------- | -------- | ------------- |
| Logic error | Wrong comparison, off-by-one, inverted condition | The method itself |
| DI wiring | Wrong object injected, missing dependency | `main.py` init steps |
| Config | Missing key, wrong default, no validation | `config.py` + `validate_config()` |
| Async | Missing `await`, CancelledError swallowed, race condition | Async task loops |
| State | Stale cache, missing reset, wrong init order | Constructor + state variables |
| GPIO | Inverted logic not applied, wrong pin number | `HardwareFactory` + relay controllers |
| Storage | Path error, fallback not triggered, buffer overflow | `BufferManager` calls |
| Timing | Interval too short/long, timezone issue, rollover bug | `TimeProvider` usage |

## Step 3 — Implement the fix

**Rules**:

- **Minimal change** — fix only what's broken. Don't refactor unrelated code in the same change.
- **Preserve DI contracts** — if you change a constructor signature, new params must have defaults.
- **Follow error handling patterns** — use the correct pattern (1–5) from `docs/conventions.md`.
- **Add a regression test** — write a test that **fails without the fix** and **passes with it**. Place it in the relevant test class or create a new `TestBugFix{Description}` class.
- **Log the fix** — add a `DEBUG` log at the fix site so the issue is diagnosable if it recurs:

  ```python
  self.logger.debug("Module", "fix applied", key=value, state=new_state)
  ```

## Step 4 — Write regression test

```python
class TestBugFix{ShortDescription}:
    """Regression test for: {one-line symptom description}."""

    def test_{symptom_description}(self, {fixtures}):
        """Verify {what was broken} now works correctly."""
        # Arrange — set up the conditions that triggered the bug
        ...

        # Act — execute the code path that was broken
        ...

        # Assert — verify the correct behaviour
        ...
```

For async bugs, test the full loop iteration:

```python
    async def test_{symptom}_async(self, {fixtures}):
        """Verify async loop handles {condition} correctly."""
        call_count = 0

        async def stop_after_one(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise RuntimeError("stop")

        with patch("asyncio.sleep", side_effect=stop_after_one):
            with pytest.raises(RuntimeError, match="stop"):
                await component.start_loop()

        # Assert the fix is in effect
        ...
```

## Step 5 — Verify

Run the full gate:

```bash
ruff check .
python -m pytest tests/ -v --tb=short --cov=lib --cov=config --cov-fail-under=88
python main.py  # host-sim smoke — Ctrl+C after 5 seconds
```

## Verification checklist

- [ ] Root cause identified and documented in the test docstring
- [ ] Fix is minimal — no unrelated changes
- [ ] Regression test fails without the fix, passes with it
- [ ] Constructor signatures are backward-compatible (new params have defaults)
- [ ] `DEBUG` log added at fix site for future diagnosis
- [ ] `ruff check .` passes
- [ ] `pytest tests/ -v` passes (full suite, not just changed module)
- [ ] Coverage ≥ 88%: `pytest tests/ --cov --cov-fail-under=88`
- [ ] Host simulation runs: `python main.py`
- [ ] Commit message: `fix({scope}): {description}`
