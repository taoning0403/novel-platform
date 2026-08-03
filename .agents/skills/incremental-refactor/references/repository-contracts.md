# Novel Platform refactoring contracts

Use this reference for every incremental refactor in this repository. Verify its claims against
the current code and maintained context before relying on them.

## Repository and toolchain

- Treat the repository as a pnpm monorepo containing the React Web application, a generated API
  client package, the FastAPI modular monolith, migrations, deployment configuration, and
  acceptance tooling.
- Use pnpm for the root and `apps/web`; do not introduce npm or yarn lockfiles.
- Use uv from `apps/server`; do not introduce Poetry or a second Python environment workflow.
- Keep a refactor free of package upgrades unless the user authorizes a separate dependency task.

Applicable existing gates are:

```text
Web:       pnpm lint
           pnpm test
           pnpm build
Contract:  pnpm api:check
Server:    cd apps/server
           uv run ruff check .
           uv run ruff format --check .
           uv run mypy
           uv run pytest tests/unit
Database:  TEST_DATABASE_URL=<isolated database with a distinct test name segment>
           uv run pytest tests/integration
End to end:
           pnpm acceptance
```

Let `$code-change-verification` select and report the proportional subset. Do not substitute a
focused check for a required full gate in the final verification.

The integration harness destroys and recreates its target schema. Its underscore/hyphen-delimited
database name must contain a distinct `test` segment; a non-local host additionally requires
`ALLOW_REMOTE_TEST_DATABASE=1` after isolation has been verified. Never set that override for
production or shared staging infrastructure. Do not use URL query parameters that override the
connection target, including `host`, `hostaddr`, `dbname`, `database`, `port`, `service`, or
`servicefile`.

## Web and generated-client boundary

- Keep `apps/web/src/App.tsx` as the route contract and preserve route-level lazy loading. Moving a
  page must not pull Reader, Upload, administration, Provider, or Translation page code into the
  synchronous entry.
- Keep React pages and features responsible for presentation and interaction, not authorization or
  remote multi-step orchestration. Server-returned capabilities and permission flags remain
  presentation inputs, never the enforcement boundary.
- Preserve the single Ant Design/Quiet Trace provider, shared tokens, CSS Modules, accessible names,
  responsive navigation, and the Reader's independent publication layer.
- Keep access tokens in memory and refresh through the HttpOnly Cookie flow. Do not introduce
  browser persistence for access tokens, refresh tokens, raw Provider keys, or credential scopes.
- Treat `packages/api-client/openapi.json` and `packages/api-client/src/schema.d.ts` as generated.
  Do not hand-edit them. The contract flows from FastAPI schemas through `pnpm api:check`, then into
  `apps/web/src/api/types.ts` and the hand-written fetch adapter in `apps/web/src/api/client.ts`.
- Preserve `@novel-platform/api-client` exports and the Web adapter's path, method, error, refresh,
  and bounded-upload behavior while moving code. A public HTTP change is an API task, not an
  internal refactor.

## FastAPI modular-monolith boundary

- Keep API routes, dependencies, schemas, serializers, and error handlers as HTTP adapters.
- Keep use-case orchestration, access decisions, state transitions, and compensation in the
  matching `application` service.
- Keep persistence queries in infrastructure repositories, file behavior in infrastructure
  storage, and external protocol details in infrastructure integrations.
- Keep database mappings and Alembic migrations responsible for persistent constraints. Do not
  move a durable invariant into React, an API route, or an external client.
- Preserve stable 404 isolation, visible-but-forbidden 403 responses, conflict responses, and
  sanitized error details. UI hiding must never replace server authorization.

Before extracting across these layers, inspect the current constructor/call path and tests. Do not
infer a desired dependency direction only from directory names.

## Ownership and authorization invariants

- Preserve the distinction between the unique library owner, the actor attributed to an operation,
  and the viewer who owns private reading/authentication state.
- Reload current Session, credential, and capability rows for protected requests. Do not treat JWT
  claims or cached Web state as current authority.
- Keep `library.read`, `library.upload`, and `translation.use` checks plus creator-aware resource
  policy at their existing server boundaries.
- Preserve cross-identity 404 hiding and the administrator-only Series, raw-download, publication,
  and security/site administration rules.

## Provider and Relay safety boundary

- Preserve immutable, version-bound reader Provider credentials and the absence of an
  administrator/shared-key fallback.
- Keep raw Provider keys write-only, encrypted at rest, absent from API responses, logs, browser
  storage, generated artifacts, and error details.
- Preserve exact Provider/base URL/model/thinking binding, custom-destination allow-list checks,
  no-redirect bounded HTTP behavior, and reflected-secret rejection.
- Keep the opaque credential scope and LinguaSpindle Job correlation private. Do not expose them in
  public Run projections or move Relay authorization into the browser or LinguaSpindle.
- Preserve the Relay's service Bearer, first-Job atomic claim, exact later Job matching, sanitized
  token usage, private network placement, and lack of a public or host port.
- Keep translation failure independent of main application readiness.

Refactoring these paths requires characterization tests for secret containment, cross-user denial,
version binding, retry/cleanup behavior, and failure without fallback.

## Reader, import, and generated-Edition boundary

- Keep Reader content behind the safe projection: sanitize publication markup, serve only declared
  protected resources, and never expose storage paths, keys, hashes, or raw file URLs.
- Preserve per-User, per-Edition progress with optimistic versions and explicit stale-write
  conflict behavior. Do not collapse viewer-private settings or progress into shared Book state.
- Preserve EPUB/TXT bounded parsing and the Reader's Edition-local identity and file-revision
  semantics.
- Keep upload as inspect-preview-commit with actor isolation, append-only file revision, atomic
  persistence, and precise idempotent compensation.
- Keep translation orchestration on the Server. Only a complete, format-matching, bounded,
  checksum-verified and locally revalidated Artifact may create one draft generated Edition.
  Partial, corrupt, ambiguous, or mismatched output must create none.
- Preserve creator-preview and administrator-only publication behavior.

Characterize the failure and compensation paths before moving parser, storage, import, Reader, or
translation code.

## Migration and persistence boundary

- Never rewrite an accepted migration to make a new design appear historical.
- Treat `20260723_0006` as destructive and non-downgradable; rollback requires the matching
  coordinated PostgreSQL and library backup.
- Preserve `20260726_0007` fail-closed behavior for historical unscoped Translation Runs. Do not
  fabricate payer or credential attribution.
- Preserve legacy v1 Provider behavior through `20260726_0008`.
- Preserve existing TXT history and `20260727_0009` refusal to downgrade while EPUB Run history
  exists.
- Require an isolated PostgreSQL database for integration or migration verification. Never point a
  refactor check at production or shared staging data.

If a proposed extraction needs a new column, constraint, migration, downgrade, data rewrite, or
backup procedure, stop the refactor slice and request a separately scoped persistence change.

## Characterization and rollback checklist

Before editing:

- Identify direct and indirect callers, public exports/routes, tests, stored side effects, external
  calls, and cleanup paths.
- Add a focused test for every old behavior that cannot be confidently observed today.
- Define one responsibility, explicit exclusions, and a file-level rollback path.

After editing:

- Run `$code-change-verification`.
- Compare success, denial, error, retry, cleanup, and persistence behavior.
- Confirm generated files are either unchanged or intentionally regenerated through
  `pnpm api:check`.
- Check import cycles and layer crossings.
- Confirm the quality baseline did not worsen.
- Revert the slice through its isolated files or commit if verification fails; never use
  `git reset --hard`, `git clean -fd`, or broad checkout commands against a dirty worktree.
