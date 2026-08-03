# Repository guidance

## Project profile

- This is a pnpm workspace with a React 18, TypeScript, Vite, Vitest, ESLint, and
  Ant Design Web application under `apps/web`, plus the generated API client under
  `packages/api-client`.
- The Server is a Python 3.12+ FastAPI modular monolith under `apps/server`, managed
  with uv and checked by Ruff, strict mypy, pytest, Alembic, and PostgreSQL integration
  tests.
- Preserve the API/application/domain/infrastructure responsibilities documented in
  `docs/architecture.md`. The current application layer deliberately uses concrete
  repositories; do not redesign the whole repository into a new architecture during
  an incremental task.

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

## Mandatory skill usage

- Use `$architecture-audit` before repository-wide refactoring, module-boundary changes,
  dependency-direction changes, or splitting large legacy modules.
- Use `$incremental-refactor` before moving responsibilities, extracting modules,
  replacing internal architecture, or restructuring legacy code.
- Run `$code-change-verification` whenever runtime code, tests, build configuration,
  dependencies, migrations, or user-visible behavior changes.
- Use `$agent-skills:planning-and-task-breakdown` for changes spanning multiple modules.
- Use `$agent-skills:test-driven-development` for behavior changes and bug fixes.
- Use `$agent-skills:code-review-and-quality` before declaring a substantial code change complete.
- Use `$agent-skills:code-simplification` only after behavior is verified and when complexity can be
  reduced without changing behavior.

## Compatibility and refactoring constraints

- Preserve public API paths, schemas, stable error codes, authentication and authorization
  semantics, Reader projections, translation state, Provider/Relay secret boundaries, and
  generated-client compatibility unless the user explicitly changes the requirement.
- Treat `packages/api-client/openapi.json` and `packages/api-client/src/schema.d.ts` as generated
  outputs; use `pnpm api:check` for contract consistency.
- Treat migrations as durable history. Use an isolated database for migration checks and
  never assume downgrade is supported.
- Move one cohesive responsibility per refactoring slice. Add characterization tests first
  when existing behavior lacks focused protection, and keep every slice independently
  verifiable and reversible.
- Do not combine refactoring with features, dependency upgrades, or repository-wide
  formatting. Do not mechanically split files only to satisfy a size threshold.
- Do not create vague catch-all modules such as `utils`, `helpers`, `common`, `misc`, or
  `shared2`; every new module needs one explicit business or technical responsibility.
- Never weaken, skip, ignore, or narrow a failing check merely to make verification pass.
- Do not use production data, staging services, paid Provider calls, or remote deployment
  as a local refactoring verification shortcut.

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

- Change-aware entry: `pnpm verify`; run `pnpm verify -- --quality-only --all` for
  the repository-wide quality ratchet without runtime tests.
- Web: `pnpm lint`, `pnpm test`, and `pnpm build`.
- Server, from `apps/server`: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy`, and `uv run pytest tests/unit`.
- PostgreSQL integration: run `uv run pytest tests/integration` with
  `TEST_DATABASE_URL` pointing at an isolated database whose underscore/hyphen-delimited
  name contains a distinct `test` segment. A non-local host additionally requires
  `ALLOW_REMOTE_TEST_DATABASE=1` after its isolation has been verified. Target-overriding
  URL query parameters such as `host`, `hostaddr`, `dbname`, `database`, `port`, or
  `service` are forbidden.
- End to end, with the Compose stack running: `pnpm acceptance`.

Do not weaken tests or alter the acceptance workflow merely to make a failure pass.
Change acceptance criteria only when the user explicitly changes the requirement.
