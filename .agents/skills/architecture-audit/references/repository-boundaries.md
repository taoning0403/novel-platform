# Novel Platform repository boundaries

Use this reference to route an audit. Verify it against current code before relying on it.

## Repository topology

- `apps/server` is the FastAPI modular monolith. `main.py`, `relay.py`, and `cli.py` are separate
  composition or process entry points from the same package.
- `apps/web` is the React browser client. It consumes the generated API client and must not
  replace Server authorization with route visibility.
- `packages/api-client/openapi.json` and `packages/api-client/src/schema.d.ts` are generated
  contract artifacts. Regenerate and diff them through the repository command; do not edit them
  directly.
- `scripts` owns acceptance, staging, backup, restore, deployment, and reporting workflows.
- PostgreSQL migrations live under `apps/server/migrations/versions`. Several migrations have
  fail-closed or intentionally irreversible behavior, so an audit must not assume downgrade is a
  valid verification step.
- LinguaSpindle is an external private service. Novel Platform owns its HTTP boundary and local
  Run state, not LinguaSpindle identity, database, Artifact volume, or internal domain model.

## Server layers

| Layer | Current responsibility | Dependency expectation |
| --- | --- | --- |
| `api` | FastAPI dependencies, routes, schemas, serializers, middleware, stable errors | May adapt HTTP to application/domain behavior. Direct infrastructure reads exist and must be recorded rather than denied. |
| `application` | Use cases, authorization policy, orchestration, storage port, transaction and compensation flow | May depend on domain. Current services also depend directly on concrete repositories and ORM models; treat that as measured coupling, not an imaginary clean boundary. |
| `domain` | Stable enums, value models, state rules, and domain errors | Must not depend on API, application, or infrastructure. |
| `infrastructure` | SQLAlchemy models/repositories, local storage, LinguaSpindle and Provider HTTP adapters | May depend on domain and implement application-defined ports. Must not depend on API. |

The accepted architecture is a modular monolith, not a set of independently deployed internal
services. Do not recommend service extraction merely to eliminate in-process imports.

`infrastructure/storage/local.py` importing the application-owned `FileStorage` contract is an
intentional dependency-inversion edge. Verify cycles and responsibility before calling it a
violation.

## Web boundaries

- Route pages belong in `apps/web/src/pages`; reusable domain UI belongs in the matching feature
  or shared component area.
- `apps/web/src/api` owns browser-to-Server request adaptation. Components must not invent
  backend enums, authorization rules, or secret-bearing contracts.
- `apps/web/src/auth/AuthProvider.tsx` owns authenticated-session state and
  `apps/web/src/ui/AppProviders.tsx` composes application-wide providers. Avoid making feature
  modules depend on page implementations.
- Reader publication rendering is a distinct safety and presentation boundary. Preserve
  server-sanitized content assumptions and its dedicated tests.
- Ant Design, project tokens, CSS Modules, route-level lazy loading, and the Quiet Trace design
  system are accepted UI constraints, not refactoring opportunities by default.

Verify actual aliases, imports, and exports from `tsconfig`, Vite configuration, source files, and
tests before asserting a Web dependency direction.

## Compatibility boundaries

Preserve these surfaces unless the user explicitly changes the requirement:

- FastAPI routes, status codes, stable error codes, cookie behavior, and generated OpenAPI schema.
- Database entities, constraints, migration history, creator/owner attribution, and immutable
  credential/Run binding.
- `FileStorage` behavior, atomic import compensation, append-only Edition file revisions, and
  protected storage identifiers.
- Credential capability checks, administrator/recovery confinement, session replay revocation,
  and 404 isolation behavior.
- LinguaSpindle version, Pipeline, MIME, Artifact, idempotency, request-correlation, and private
  credential-scope contracts.
- Reader-safe publication projection, progress conflict semantics, and private per-user state.
- Web route behavior, generated API types, accessibility contracts, and acceptance scenarios.
- Operational backup, migration, restore, topology, and rollback requirements.

## Evidence routing

| Surface | Primary source | Protection |
| --- | --- | --- |
| Architecture and omissions | `docs/PROJECT_STATE.md`, `docs/architecture.md`, ADRs | Verify against entry points and Compose |
| Server modules | `docs/MODULE_MAP.md`, `apps/server/src` | Ruff, mypy, unit and targeted integration tests |
| Persistence | ORM models plus Alembic versions | Single-head check, isolated upgrade and migration tests |
| HTTP contract | Server schemas/routes plus generated client | `pnpm api:check` and integration tests |
| Web behavior | Pages, features, providers, API adapter | ESLint, Vitest, build and targeted acceptance |
| Operations | Compose and `scripts` | Syntax/config checks plus protected-environment procedures |

## Inventory exclusions

Keep exclusions narrow and explicit:

- Exclude lockfiles, caches, build output, artifacts, installed dependencies, and binary fixture
  output from source-size and complexity thresholds.
- Treat generated OpenAPI and TypeScript schema as contract artifacts: exclude them from manual
  complexity judgments but verify regeneration.
- Treat Alembic versions, declarative ORM models, Pydantic schemas, fixtures, and tests as separate
  categories. Continue linting them; do not apply ordinary behavior-file size limits blindly.
- Keep large cohesive parsers and adapters visible in the report. Exclusion from an absolute line
  gate is not exclusion from responsibility, complexity, security, or test review.
