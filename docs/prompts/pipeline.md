# Agent Pipeline — Brainstorm → Design → Implement → Verify → Review

This master prompt orchestrates a multi-phase development pipeline using Copilot Chat with handoffs between Plan and Act modes. Each phase has a defined output and an explicit checkpoint where the agent pauses for human approval before continuing.

**Scope**: New components, bug fixes, and refactors.

---

## How to use

1. Start Copilot Chat in **Plan mode**.
2. Paste this prompt (or attach with `#file:docs/prompts/pipeline.md`).
3. Describe the task — e.g., *"Add a CO2 sensor on UART GP0/GP1 that logs ppm to CSV every 30 seconds."*
4. The agent will run Phase 1 (Brainstorm) and pause for your approval.
5. Approve or adjust. The agent continues through each phase, pausing at checkpoints.

Attach `#file:.github/copilot-instructions.md` and `#file:docs/conventions.md` for full project context.

---

## Phase 1 — Brainstorm (Plan mode)

**Goal**: Understand the problem and explore approaches before committing to an implementation.

**Agent instructions**:

1. Research the codebase to identify all modules, fixtures, and config sections affected by this task.
2. Determine the **task type** (new component | bug fix | refactor) and note which sub-prompt applies:
   - New relay controller → `docs/prompts/new-controller.md`
   - New sensor → `docs/prompts/new-sensor.md`
   - Bug fix → `docs/prompts/bug-fix.md`
   - Refactor → `docs/prompts/refactor-module.md`
3. List dependencies and integration points (what imports, injects, or calls the affected modules).
4. Propose 2–3 approach options with **pros / cons** for each.
5. Identify risks: What could break? What edge cases exist? What existing tests might be affected?

**Output format**:

```markdown
### Task analysis
- **Type**: {new component | bug fix | refactor}
- **Sub-prompt**: `docs/prompts/{file}.md`
- **Affected files**: {list}
- **Dependencies**: {list of modules that import/inject affected code}

### Approach options
1. **{Option A}** — {description}
   - Pros: ...
   - Cons: ...
2. **{Option B}** — {description}
   - Pros: ...
   - Cons: ...

### Risks
- {risk 1}
- {risk 2}

### Recommendation
{Which approach and why}
```

> **CHECKPOINT**: Present the analysis and wait for the user to pick an approach or request changes. Do not proceed to Phase 2 until approved.

---

## Phase 2 — Design (Plan mode)

**Goal**: Create a detailed, step-by-step implementation plan that maps to specific code changes.

**Agent instructions**:

1. Load the relevant sub-prompt (`#file:docs/prompts/{sub-prompt}.md`) and follow its step-by-step structure.
2. For each step, describe the specific code change (file, location, what changes) but **do not write code yet**.
3. Plan the test strategy: which test classes to add, what scenarios to cover, which fixtures to use/create.
4. Plan config changes: new `DEVICE_CONFIG` keys, `validate_config()` additions, value ranges.
5. List the implementation order — dependencies between steps matter (e.g., config before class, class before wiring).

**Output format**:

```markdown
### Implementation plan

#### Step 1: Config ({config_key})
- Add section to `DEVICE_CONFIG` in `config.py` with keys: ...
- Add keys to `validate_config()` required_keys dict
- Add range checks: ...

#### Step 2: {Class/Module}
- Create/modify `lib/{file}.py`
- Constructor params: ...
- Public methods: ...
- Error handling: Pattern {N}

#### Step 3: Main wiring
- Add to `main.py` Step {N}: ...
- Spawn task in Step 9: ...

#### Step 4: Tests
- Fixture in `conftest.py`: ...
- Test classes: TestInit, TestState, TestAsync, TestEdgeCases
- Scenarios: ...

#### Step 5: Docs
- Update copilot-instructions.md: module table, Mermaid diagram
- Update conventions.md if needed

### Implementation order
1 → 2 → 3 → 4 → 5
```

> **CHECKPOINT**: Present the implementation plan and wait for the user to approve, adjust, or add steps. Do not proceed to Phase 3 until approved.

---

## Phase 3 — Implement (Act mode — handoff)

**Goal**: Execute the approved plan, writing all code changes step by step.

**Agent instructions**:

1. **Set up a todo list** tracking each step from the approved plan.
2. Implement steps in the approved order, marking each complete as you go.
3. Reference the relevant sub-prompt for code templates and patterns:
   - Controllers: `#file:docs/prompts/new-controller.md` (RelayController subclass, Pattern 1 async loop, `get_state()`)
   - Sensors: `#file:docs/prompts/new-sensor.md` (DHTLogger-style class, retry Pattern 2, CSV rollover)
   - Bug fixes: `#file:docs/prompts/bug-fix.md` (minimal fix, regression test)
   - Refactors: `#file:docs/prompts/refactor-module.md` (preserve DI contracts, backward-compatible constructors)
4. Follow project conventions (`#file:docs/conventions.md`):
   - `snake_case` for files/functions, `PascalCase` for classes
   - Relay GPIO inverted (`invert=True`)
   - All config in `DEVICE_CONFIG` with validation
   - Logging through injected `EventLogger` (never bare `print()` post-init)
   - Async loops use Pattern 1 (CancelledError + Exception)
   - Storage through `BufferManager.write(relpath, data)` with relative paths
5. Write tests alongside implementation — don't defer all tests to the end.
6. If you discover the plan needs adjustment, note it but keep implementing. Raise it at the Phase 4 checkpoint.

> **No checkpoint** — proceed directly to Phase 4 after implementation.

---

## Phase 4 — Verify (Act mode)

**Goal**: Run the full quality gate and auto-fix any failures.

**Agent instructions**:

1. Run lint: `ruff check .`
   - If errors: auto-fix and re-run (up to 3 iterations).
2. Run tests: `python -m pytest tests/ -v --tb=short --cov=lib --cov=config --cov-fail-under=88`
   - If failures: read the traceback, fix the issue, re-run (up to 3 iterations).
   - If coverage below 88%: add missing tests for uncovered lines.
3. Run host-sim smoke: `python main.py` — verify it starts without error (Ctrl+C after 5 seconds).
   - The host shims simulate hardware; errors here indicate wiring or import problems.
4. Check markdownlint on any new/changed `.md` files.

**Self-healing loop** (max 3 iterations):

```text
Run gate → failures? → read errors → fix → re-run gate → still failing? → fix → re-run → still failing? → report to human
```

> **CHECKPOINT** (only if unresolvable failures remain): Present the remaining failures with diagnosis and wait for guidance. If all gates pass, proceed directly to Phase 5.

---

## Phase 5 — Review (Plan mode — handoff back)

**Goal**: Present a summary of all changes for human review before commit.

**Agent instructions**:

1. List all files changed, created, or deleted.
1. Summarise the key changes per file (1–2 lines each).
1. Report test results: total tests, new tests added, coverage percentage.
1. Report lint status: clean or note any suppressed warnings.
1. Suggest a commit message following Conventional Commits format: `<type>(<scope>): <description>` with bullet points per significant change.
1. Note any follow-up work identified during implementation (e.g., "OLED integration would benefit from this new module").

**Output format**:

Present a markdown summary with these sections:

- **Changes summary** — table with columns: File, Action, Description
- **Test results** — total passed/failed, new tests added, coverage percentage
- **Suggested commit** — Conventional Commits format with scope and bullet points
- **Follow-up** — any identified future work

> **CHECKPOINT**: Human reviews the summary, then commits (or requests changes — return to Phase 3).

---

## Quick reference — Phase ↔ Mode mapping

| Phase | Mode | Agent action | Checkpoint? |
| ----- | ---- | ------------ | ----------- |
| 1. Brainstorm | Plan | Research + propose approaches | Yes — pick approach |
| 2. Design | Plan | Detailed step plan | Yes — approve plan |
| 3. Implement | Act | Write code + tests | No — flows into verify |
| 4. Verify | Act | Run gates + auto-fix | Only if failures remain |
| 5. Review | Plan | Present summary + commit msg | Yes — approve or revise |
