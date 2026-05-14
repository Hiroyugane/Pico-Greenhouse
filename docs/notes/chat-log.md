# Chat log

> Decisions, spec clarifications, deviations, issues, and non-obvious
> notes from Claude sessions. See
> [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md)
> for the entry format. Newest topic on top.

## 2026-05-14 · Commit-on-stop enforcement

### decision · Stop hook blocks turn-end while tracked tree is dirty

Extended `commit-granularity.md` with a "Commit before ending the
turn" section: when Claude finishes a task, all of its work must
already be committed. Enforced by `.claude/hooks/check-clean-tree.ps1`,
wired as a `Stop` hook in `.claude/settings.json`. The hook runs
`git status --porcelain`, ignores untracked entries (`??`), and
returns `{"decision":"block","reason":"..."}` if any tracked file is
modified or staged — re-prompting Claude with the dirty file list
and a pointer to the rule.

### deviation · Hook scope limited to tracked changes

User chose "any tracked changes Claude touched" over "entire working
tree must be clean" for the scope. Practical consequence: if Claude
creates a brand-new file and forgets to `git add` it, the hook
**will not catch it** — only the rule does. The hook is a backstop
for the common case (modifying tracked files); Claude is still
expected to follow the rule's letter for new files. This was the
explicit trade-off to avoid blocking on user-vintage untracked junk
(scratch files, build artifacts, `docs/notes/` before it was
committed).

### decision · Per-turn opt-out via sentinel file

When the user says "leave it uncommitted" / "don't commit yet" /
equivalent, Claude creates `.claude/.skip-commit-check`. The hook
consumes and deletes the sentinel on next Stop, allowing one turn to
end uncommitted. The opt-out is per-turn, not per-session — each
subsequent dirty Stop needs its own sentinel. This keeps the default
("commit before done") strict and makes the escape hatch feel
deliberate.

### note · `.claude/` is gitignored on this repo

The new rule file, hook script, and settings change all live under
`.claude/` which is in `.gitignore` (line 21). They exist only on
this machine and won't propagate via `git pull`. Other contributors
who want the same enforcement need to add the same files locally.
Promoting any of this to checked-in territory would require either
unignoring `.claude/` or moving the rule/hook to a tracked location
(e.g. `docs/` for the rule, a top-level `hooks/` for the script).

## 2026-05-14 · Commit granularity rule

### decision · One logical change per commit, with refactor/behavior split

Added [.claude/rules/ecc/common/commit-granularity.md](../../.claude/rules/ecc/common/commit-granularity.md)
as a third load-bearing rule alongside `clarifying-questions.md` and
`documentation-routine.md`. Sizing is "one logical change per commit"
regardless of file count — a coherent change can span multiple files
when they form one indivisible unit (e.g. a config key + its validator
+ its test row), but a refactor and a behavior change in the same
working tree must split into two commits. Banned patterns:
`wip`/`checkpoint`/`misc` messages, refactor mixed with behavior change,
tests bundled with unrelated code, and squash-merging into `main`.
Rationale: future AI sessions read `git log` to reconstruct intent;
construction-site commits force them to diff a swamp.
