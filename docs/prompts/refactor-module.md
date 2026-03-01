# Prompt: Refactor a Module

Use this prompt to safely refactor an existing module while maintaining DI contracts and test coverage.

---

## Context

The Pi Greenhouse uses dependency injection throughout. Modules communicate via injected interfaces, not imports. Tests mock these interfaces via fixtures in `conftest.py`. Changing a module's constructor signature or public API may break:

- `main.py` (wiring)
- `conftest.py` (fixtures)
- Other modules that receive this module via DI
- Test files that use the affected fixtures

## Task

Refactor `lib/{module_name}.py` to {describe the refactoring goal}.

## Pre-refactor checklist

Before making changes:

1. **Read the module** — understand all public methods, constructor params, and DI contracts.
2. **Find all consumers** — search for who imports or receives this module:

   ```bash
   grep -r "{ClassName}" main.py lib/ tests/
   ```

3. **Run baseline tests** — ensure all tests pass before refactoring:

   ```bash
   pytest tests/test_{module_name}.py -v
   pytest tests/ -v  # full suite
   ```

4. **Note the public API** — list all methods that other modules call. These are the contracts to preserve.

## Safe refactoring rules

### Constructor changes

If adding a new parameter:

- **Always** give it a default value (`param=None` or `param=default`) to avoid breaking existing callers.
- Update `main.py` wiring to pass the new parameter.
- Update `conftest.py` fixture to include the parameter.

### Method signature changes

If changing a public method signature:

- Search all callers: `grep -r "\.method_name(" lib/ main.py tests/`
- Update all call sites.
- Update test assertions.

### Extracting a new class

When splitting a class:

- Keep the original class name and interface intact.
- Delegate to the new class internally.
- Add the new class to `conftest.py` if it needs its own fixture.
- Export from the module: `from lib.{module} import {NewClass}`.

### Renaming

- Configure your editor to find all references before renaming.
- Update: module imports, `main.py` wiring, `conftest.py`, test files, `copilot-instructions.md`, `conventions.md`.

## Post-refactor checklist

- [ ] **Tests pass**: `pytest tests/ -v` — full suite, not just the changed module
- [ ] **Lint passes**: `ruff check .`
- [ ] **Host simulation runs**: `python main.py` (should start without error)
- [ ] **Coverage maintained**: `pytest tests/ --cov --cov-fail-under=88`
- [ ] **DI contracts preserved**: constructor signature is backward-compatible (new params have defaults)
- [ ] **Docs updated**: `.github/copilot-instructions.md` if module responsibilities changed
- [ ] **Commit message**: `refactor({scope}): {description}` following Conventional Commits

## Common refactorings

### Adding optional logger to a module that uses `print()`

```python
# Before
class MyModule:
    def __init__(self, pin):
        self.pin = pin
        print(f"[MyModule] Init pin={pin}")

# After
class MyModule:
    def __init__(self, pin, logger=None):
        self.pin = pin
        self._logger = logger
        if self._logger:
            self._logger.info("MyModule", f"Init pin={pin}")
        else:
            print(f"[MyModule] Init pin={pin}")
```

### Extracting shared logic into base class

```python
# Before: duplicated code in FanController and GrowlightController
# After: shared logic in RelayController base, specifics in subclasses
# Keep all existing method names — just move implementations up
```

### Adding structured debug logging

```python
# Add debug calls at key decision points:
self.logger.debug("FanController", "evaluating thermostat",
                  temp=current_temp, threshold=self.max_temp,
                  hysteresis=self.temp_hysteresis, relay_on=self.is_on())
```
