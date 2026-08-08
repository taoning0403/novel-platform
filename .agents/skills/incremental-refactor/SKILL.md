---
name: incremental-refactor
description: Plan and execute behavior-preserving, reversible refactoring slices in novel-platform's React/pnpm Web, generated API client, or FastAPI/uv modular monolith. Use before moving responsibilities, extracting modules, changing internal dependency direction, splitting legacy files, or replacing internal architecture. Require characterization tests plus compatibility, rollback, and verification plans; do not use this Skill to add features, redesign schemas, upgrade dependencies, rewrite migrations, or silently change public contracts.
---

# Incremental refactor

Read [references/repository-contracts.md](references/repository-contracts.md) completely before
planning or editing a refactor slice.

## Orient the work

1. Invoke `$repo-context` and follow its narrow context-first inspection path.
2. Inspect the working tree and preserve every unrelated or pre-existing change.
3. Read the target module, its callers and dependents, its tests, and every public interface the
   slice could affect.
4. Invoke `$architecture-audit` first when the responsibility boundary, dependency direction, or
   proposed repository-wide split is not already established.
5. Separate observable behavior changes from internal restructuring. Move a behavior change or bug
   fix into a separately authorized task with its own tests.

## Define one reversible slice

Write down before editing:

- the single cohesive responsibility or dependency boundary to move;
- the observable behavior and compatibility interfaces that must remain unchanged;
- the files and callers expected to change;
- explicit out-of-scope work;
- the characterization and regression tests that protect the behavior;
- the smallest commands that verify the slice and the full applicable gate;
- a rollback path that does not rely on destructive Git commands.

Do not start with a desired file count. File length is a signal, not a responsibility boundary.
Prefer a narrow slice that can be reviewed, verified, and reverted independently.

## Establish behavior before movement

1. Trace both success and failure paths, including authorization, error mapping, cleanup, retries,
   and persisted side effects.
2. Reuse existing tests when they directly observe the contract.
3. Add characterization tests before moving code when the old behavior is weakly protected.
   Assert externally meaningful results instead of incidental implementation details.
4. Record any pre-existing failure or quality-baseline exception separately. Do not make the slice
   responsible for unrelated historical debt.

## Move one responsibility

- Move one cohesive responsibility at a time and keep each intermediate state runnable.
- Preserve routes, exported names, generated contracts, error/status semantics, persistence
  invariants, accessible names, and security boundaries unless a separately approved migration
  explicitly changes them.
- Give every new module a specific business or technical responsibility. Do not create catch-all
  `utils`, `helpers`, `common`, `misc`, `shared2`, or equivalent dumping grounds.
- Do not mechanically cut a file by line range, wrap old code only to satisfy a threshold, or
  spread one responsibility across arbitrary fragments.
- Keep a compatibility entry point when callers cannot move in the same slice. Otherwise provide
  an explicit caller migration and tests in that slice.
- Do not combine the refactor with feature work, framework or dependency upgrades, repository-wide
  formatting, generated-file hand edits, or unrelated cleanup.
- Do not rewrite accepted Alembic migrations or invent a downgrade. Stop and rescope if a schema
  change is required; it is not an ordinary behavior-preserving refactor.
- Preserve the repository-specific Web, Server, Provider/Relay, Reader, authorization, import, and
  generated-contract boundaries in the required reference.

## Verify and close the slice

1. Invoke `$code-change-verification` after implementation.
2. Run the characterization test before and after the movement when practical, then run every
   check selected for the changed surface.
3. Recheck dependency direction and local import cycles. Do not introduce a new quality-baseline
   exception or increase a grandfathered limit.
4. Compare externally observable behavior, generated API output when relevant, and persisted
   effects rather than relying only on a clean diff.
5. Report added, removed, moved, and responsibility-changed files; preserved interfaces; commands
   and results; skipped or blocked checks; and the concrete rollback path.
6. Update only architecture/context documents whose facts changed. Record a durable reversal as a
   separately approved ADR rather than hiding it inside a refactor.
7. Do not declare completion while an applicable check fails, a baseline regresses, or a required
   compatibility boundary remains unverified.
