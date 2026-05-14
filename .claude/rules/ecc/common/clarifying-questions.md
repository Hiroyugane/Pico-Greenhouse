# Clarifying Questions Routine

> Loaded automatically into every Claude session. Treat these as
> mandatory steps, not suggestions.

## Rule

At the **start of every session** and at the **start of every new user
prompt that requests work** (a feature, a fix, a refactor, a research
task, a doc update, etc.), Claude MUST ask the user **3–4 clarifying
questions** before producing a plan, writing code, or running
non-trivial tool calls.

Use the `AskUserQuestion` tool so the user gets a structured picker.
Group the questions into a single `AskUserQuestion` call (1–4 questions
per call, per the tool contract).

## Purpose

- Increase the accuracy of Claude's understanding of the user's intent.
- Surface hidden constraints (scope, target surface, edge cases,
  acceptance criteria) before they are baked into wrong code.
- Reduce rework caused by assumptions Claude would otherwise make
  silently.

## When to ask

**MANDATORY** at the top of:

- a new session, on the first work-shaped prompt,
- any new work-shaped prompt within an existing session that opens a
  fresh thread of work (new feature, new bug, new investigation, new
  refactor scope).

**Skip** for:

- Pure mechanical follow-ups inside an already-clarified task
  ("continue", "now run the tests", "commit that", "fix the typo on
  line 42").
- Questions that are purely informational and have no implementation
  surface ("what does this function do?", "explain X").
- Cases where the user has **explicitly** said "just do it", "no
  questions", "skip clarifying", or equivalent — honor that for the
  rest of the session unless they re-enable it.
- Cases where the user's prompt is already fully specified and there
  is no meaningful ambiguity left to resolve (rare — when in doubt,
  ask).

## How to ask

Pick questions that actually change what gets built. Good axes to
probe, in rough priority order:

1. **Scope** — which surface, which files, which user flow, which
   platform (web / Android / iOS / desktop / CLI).
2. **Acceptance** — what does "done" look like; what's the smallest
   demonstrable success.
3. **Constraints** — backward-compatibility, performance budget,
   migration story, hardware vs host-side verification.
4. **Trade-offs** — speed vs. polish, prototype vs. production,
   bundled PR vs. split PRs, library vs. hand-rolled.

Each question must:

- Be answerable with one of 2–4 short options (plus the auto-provided
  "Other" escape hatch).
- Materially change the implementation if answered differently. If
  every option leads to the same code, don't ask it.
- Have a **recommended** option listed first when Claude has a
  defensible default, with `(Recommended)` appended to the label.

## Workflow integration

1. User sends a work-shaped prompt.
2. **Before** any planning, file reads beyond a quick orientation, or
   code edits: call `AskUserQuestion` with 3–4 questions per the rules
   above.
3. Wait for the answers.
4. Proceed with the work using those answers as ground truth. If the
   answers reveal a decision worth remembering, follow
   [documentation-routine.md](./documentation-routine.md) and append
   to `docs/notes/chat-log.md` as a `decision` entry.

## Honoring opt-out

If the user says any of:

- "skip questions",
- "no clarifying questions",
- "just do it",
- "stop asking, go",

…then for the **remainder of the current session** Claude skips this
routine and proceeds directly. The opt-out resets at the next session
unless the user makes it durable (e.g. saved into memory or a project
rule).

## Why this exists

Most rework on this project comes from Claude guessing about scope or
acceptance criteria and being wrong. Three to four targeted questions
up front cost ~30 seconds of the user's time and routinely save an
entire wrong implementation pass. The structured-picker format also
gives the user a fast way to redirect without typing.
