---
name: repo-context
description: Orient work in the novel-platform repository through maintained context documents before implementing, debugging, planning, reviewing, refactoring, or documenting changes. Use at the start of repository development tasks, when locating responsible modules, checking architecture or data-model constraints, and when refreshing repository context after a change.
---

# Repository context

Use maintained context to avoid broad repository scans while still verifying task-relevant
facts against current implementation.

## Orient

1. Read the root `AGENTS.md` completely.
2. Read `docs/PROJECT_STATE.md` for the current milestone, implemented capabilities, and
   deliberate omissions.
3. Use `docs/MODULE_MAP.md` to select the responsible code, tests, migrations, and commands.
4. Read only the relevant sections of `docs/architecture.md`, `docs/data-model.md`, and
   `docs/DECISIONS.md`; follow a linked ADR when the task touches its decision.
5. Inspect `git status --short`, recent commits, and the directly responsible files.
6. Verify context claims against current code, tests, and migrations before relying on them.
7. Expand the search only when context is missing, inconsistent, or insufficient to trace the
   affected behavior.

Avoid loading generated lockfiles, full stylesheets, or unrelated modules unless the task
requires them.

## Work and verify

- Follow the layer boundaries, invariant ownership, and verification commands in `AGENTS.md`.
- Preserve unrelated user changes and reconcile documentation with current code when they
  disagree.
- Inspect the matching tests before changing behavior and run the checks proportional to the
  changed surface.
- Compare the final diff with the context documents before declaring completion.

## Refresh context

Update only documents whose facts changed:

- Update `docs/PROJECT_STATE.md` when milestone, scope, capabilities, omissions, or committed
  direction changes.
- Update `docs/MODULE_MAP.md` when modules, entry points, ownership, or verification routes
  change.
- Update `docs/architecture.md` or `docs/data-model.md` when boundaries, flows, storage,
  relationships, or invariants change.
- Add a new ADR and update `docs/DECISIONS.md` for a durable decision; do not rewrite an
  accepted ADR to hide a reversal.
- Skip context edits when the implementation does not change any documented fact.

Keep context concise, factual, and free of large source excerpts or transient task notes.
