# Repository guidance

## Start here

For implementation, debugging, planning, review, refactoring, or repository
documentation work, use the repository-local `repo-context` skill first.

Before broad source inspection:

1. Read `docs/PROJECT_STATE.md` for the current milestone and deliberate omissions.
2. Use `docs/MODULE_MAP.md` to locate the responsible module and nearby tests.
3. Read only the relevant parts of `docs/architecture.md` and `docs/data-model.md`.
4. Consult `docs/DECISIONS.md` and its linked ADRs before changing durable design.
5. Inspect `git status --short`, recent commits, and files directly related to the task.

Treat context documents as navigation aids, not substitutes for current code. Verify
relevant claims against implementation, migrations, and tests. Do not recursively read
the entire repository unless the maintained context is missing, stale, or inconsistent.

## Keep context current

After a change, update only the context whose facts changed:

- `docs/PROJECT_STATE.md` for milestone, capability, scope, or known-gap changes.
- `docs/MODULE_MAP.md` for new, removed, renamed, or repurposed modules and entry points.
- `docs/architecture.md` for boundary, dependency, deployment, or data-flow changes.
- `docs/data-model.md` for persistent entities, relationships, or invariant changes.
- `docs/DECISIONS.md` plus a new ADR for durable technical or product decisions.

Keep these documents concise and factual. Do not copy large source excerpts into them.

## Verification

Run the checks that cover the changed surface. The full local quality gates are:

- Web: `pnpm lint`, `pnpm test`, and `pnpm build`.
- Server, from `apps/server`: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy`, and `uv run pytest tests/unit`.
- PostgreSQL integration: run `uv run pytest tests/integration` with
  `TEST_DATABASE_URL` pointing at an isolated test database.
- End to end, with the Compose stack running: `pnpm acceptance`.

Do not weaken tests or alter the acceptance workflow merely to make a failure pass.
Change acceptance criteria only when the user explicitly changes the requirement.
