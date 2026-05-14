# Documentation routine

> Loaded automatically into every Claude session. Treat these as
> mandatory steps, not suggestions.

## Two rolling logs to keep current

| File | Purpose |
| --- | --- |
| [`docs/test/hw-test-log.md`](../../../../docs/test/hw-test-log.md) | Every change that needs to be verified on real hardware (Keystore, biometric, FLAG_SECURE, notification scheduling, camera, foreground service, sensor permissions, DB encryption work factor, anything else that can't be exercised by `flutter test` or a host-side run). |
| [`docs/notes/chat-log.md`](../../../../docs/notes/chat-log.md) | Decisions, spec clarifications, deviations from `docs/superpowers/specs/`, open issues, and non-obvious notes that arise from Claude conversations. |

## When to append to `hw-test-log.md`

**MANDATORY** after any session that:

- adds or changes user-visible behavior,
- changes anything inside `android/`, `ios/`, native-channel code, or
  permissions-manifest entries,
- touches database encryption, key storage, biometrics, or secure
  storage,
- changes notification scheduling, foreground-service config, or
  alarm/exact-alarm code,
- modifies camera, photo storage, or any other hardware-backed API,
- updates a flutter plugin that mediates any of the above.
- updates anything that the user interacts with

**Skip** for: doc-only edits,
test-only edits, and dead-code removal.

### Entry shape

```markdown
## YYYY-MM-DD · <short title>

**Branch:** `<branch name>`
**Why hardware-only:** <one sentence: what can't be tested on host/CI>
**Pre-flight:** <wipe DB / reinstall / etc — what state the device should start in>

### <section per concern>

- [ ] <specific, observable step + expected outcome>
- [ ] <another step>

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.
```

Newest entry on top. Use `[ ]` for pending, `[x]` passed, `[!]` failed,
`[~]` partial/blocked. Each checkbox must be a concrete user-visible
verification — not a unit-test substitute.

## When to append to `chat-log.md`

**MANDATORY** after any session that produces:

- a **decision** between two or more viable approaches,
- a **spec** clarification that wasn't in
  `docs/superpowers/specs/2026-05-05-myco-app-design.md`,
- an intentional **deviation** from the original spec,
- an **issue** worth tracking (open question, known limitation,
  follow-up task),
- a **note** about non-obvious context future-Claude will need.

**Skip** for: trivial implementation choices that any reader would make
the same way, pure mechanical work.

### Entry shape

```markdown
## YYYY-MM-DD · <topic>

### <type> · <one-line headline>

<2-5 sentences: what was decided/clarified/observed, and the reason.>
```

`<type>` is one of: `decision`, `spec`, `deviation`, `issue`, `note`.
Newest topic on top; multiple subsections under one date are fine when
they share a theme.

## Workflow integration

1. Implement the change as normal.
2. Before reporting the session as complete:
   - append an entry to `hw-test-log.md` if the change is hardware-
     verifiable (per the criteria above),
   - append an entry to `chat-log.md` if the session produced a
     decision / spec / deviation / issue / note (per the criteria
     above).
3. Mention the appended log files in the end-of-turn summary so the
   user can spot-check them.

Do not batch documentation across sessions. Every applicable session
appends its own entries the same turn the code lands.

## Why this exists

The hardware test log makes the unverified surface area visible — the
user runs it on the Pixel between commits and we don't lose track of
what still needs eyes-on verification. The chat log is the project's
decision memory: months from now, "why is the pepper a per-user random
and not a build-time constant?" should be answerable in 10 seconds, not
by re-reading conversation transcripts.
