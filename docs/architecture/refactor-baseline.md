# Refactor baseline

> Status: read-only architecture and quality baseline, reviewed 2026-07-30 against
> `develop@3a37900`. Findings and candidates in this document are not approved architecture
> decisions and do not authorize refactoring.

## Scope and method

This baseline covers the FastAPI Server, React Web client, generated API contract, migrations,
tests, repository scripts, and CI verification routes. The audit began from a clean worktree; the
only later changes visible while writing this document belong to the approved Skill and
verification-entry task.

Measurements use physical lines plus language-specific static analysis:

- `.agents/skills/architecture-audit/scripts/source_inventory.py` inventories fixed repository
  source areas, Python function spans, a deterministic decision-point heuristic, Python layer
  edges, and Python static import cycles.
- Ruff's opt-in `C901` check supplies the Python McCabe values below; `C901` is not part of the
  current Server lint configuration.
- The Web audit counts physical and effective TypeScript/TSX lines and uses an AST heuristic for
  conditions, loops, `catch`, `case`, ternaries, logical operators, and nesting. These values are
  comparative signals, not compiler metrics.
- Static import graphs cannot prove the absence of runtime string imports. All cycle claims below
  are limited to resolved static imports.

No production data, remote service, deployment, migration, test database, build output, or
browser session was changed during the audit.

## Current architecture

**Fact.** The accepted design is a monorepo and one FastAPI modular monolith backed by PostgreSQL
and private local storage. The React application consumes an OpenAPI-derived client.
LinguaSpindle and the Provider Relay are private translation boundaries; Novel Platform owns its
Run state and HTTP contract, not LinguaSpindle's database, identity, or Artifact volume.

```text
apps/web (React/Vite)
  -> packages/api-client (generated contract)
  -> apps/server/api
       -> application use cases and policy
       -> domain rules and enums
       -> infrastructure repositories, ORM, storage, and HTTP adapters
  -> PostgreSQL + private library volume
  -> optional private LinguaSpindle -> Relay -> approved Provider
```

Server entry points are `main.py`, `relay.py`, and `cli.py`. There is deliberately no queue,
worker, scheduler, public object store, public registration, or browser-direct Provider call.

**Fact.** Server Domain imports only Domain. Application currently imports concrete Infrastructure
models and repositories; the codebase is therefore layered but not a strict dependency-inverted
hexagon.

**Inference.** Direct concrete coupling increases the setup cost of service-level unit tests and
the blast radius of persistence refactors. It is not itself evidence that the modular monolith
should be split into services.

## Verification baseline

### Commands actually executed during the audit

| Command | Result and exact boundary |
| --- | --- |
| `cd apps/server && .venv/bin/ruff check .` | Passed |
| `cd apps/server && .venv/bin/ruff format --check .` | Passed; 161 files already formatted |
| `cd apps/server && .venv/bin/mypy` | Passed; 138 source files |
| `cd apps/server && .venv/bin/pytest tests/unit` | Passed 112 cases; emitted one duplicate-ZIP-entry warning from a deliberate malformed EPUB fixture |
| `cd apps/server && .venv/bin/pytest --collect-only -q tests/integration` | Collected 34 cases; tests were not run |
| `cd apps/server && .venv/bin/alembic heads` | One head: `20260727_0009` |
| `pnpm lint` | Passed for Web |
| `pnpm test` | Passed 60 Web cases across 12 files |
| `pnpm build` | Passed; Vite retained its existing chunk-size advisory |
| `pnpm acceptance -- --list` | Passed command discovery; default target is `v0100`; no acceptance scenario ran |
| `apps/server/.venv/bin/python .agents/skills/architecture-audit/scripts/source_inventory.py --root .` | Passed after selecting the repository Python 3.12+ environment |

The first inventory attempt with macOS system Python 3.9 stopped because it cannot parse the
Server's Python 3.12 `type` syntax. A subsequent `uv run --no-sync` attempt was blocked by local uv
cache permissions. Neither result indicates a repository defect; the successful command above
uses the existing repository interpreter and installs nothing.

### Not executed

- PostgreSQL integration test bodies because no isolated `TEST_DATABASE_URL` was provided.
- `pnpm api:check`, bundle report, or full Playwright acceptance.
- Alembic upgrade against an isolated database.
- Deployment, backup, restore, Relay, LinguaSpindle, or real Provider verification.

Therefore the audit establishes a green local static, Server-unit, Web-unit, and Web-build
baseline, not PostgreSQL integration, migration-upgrade, browser acceptance, or external-service
proof.

### Tooling validation after baseline creation

The approved Skill/tooling task then ran the finished entry points against the unchanged product
tree:

| Command or probe | Result and exact boundary |
| --- | --- |
| `pnpm verify -- --quality-only --all` | Passed; scanned 6,807 metrics, accepted 211 reviewed historical violations without growth, found zero Python/TypeScript cycles and zero boundary violations, validated all 5 repository Skills, and passed 38 verifier self-tests |
| verifier mutation and routing probes | Passed; same-change baseline rewrites or policy loosening, metric worsening, stale `TIGHTEN`/`CLEANUP` entries, ahead-plus-dirty history, deletion/rename/unusual-name routing, unsafe database targets, malformed config, missing Git provenance, clean unpublished branches, and inconsistent initial/new-branch push history all block rather than self-approve |
| `pnpm verify -- --config-only` | Passed; checked Git whitespace plus 12 detected workflow, root/acceptance-support Compose, Dockerfile, and workspace-config routes |
| `TEST_DATABASE_URL=.../novel_platform_test pnpm verify` | Passed the selected quality, Skill, verifier, config, Server, Web, PostgreSQL integration, migration, and default `v0100` acceptance routes against a loopback-only tmpfs database; API contract was correctly reported `SKIPPED` because the API surface was unchanged |
| repository Skill validation | The official `quick_validate.py` accepted all 3 new Skills; the repository validator accepted all 5 local Skills |
| `pnpm api:check` | Passed deterministic OpenAPI/client regeneration comparison |
| `pnpm lint` | Passed |
| `pnpm test` | Passed 60 Web cases across 12 files; React Router printed its existing v7 future-flag advisories |
| `pnpm build` | Passed; entry gzip was 198.27 kB and Vite printed its existing 500 kB chunk advisory |
| Server Ruff check and format check | Passed; 161 Server files already formatted |
| Server mypy | Passed for 138 source files |
| Server unit tests | Passed 112 cases; one deliberate duplicate-ZIP fixture warning |
| PostgreSQL integration and migration tests | Passed 27 non-migration integration cases and all 7 migration cases against the isolated test database |
| `pnpm acceptance` | Passed the current `v0100` gate and its inherited regression chain |

The direct historical `pnpm acceptance -- v090` command still defaults to Alembic revision
`20260723_0006`, while the current repository head is `20260727_0009`. That historical standalone
default therefore does not represent the current release gate. The current default `v0100` route
supplies its inherited revision contract and passed the full chain; the tooling task did not relax
or rewrite historical acceptance criteria.

### Existing repository gates

- Server: Ruff check, Ruff format check, strict mypy, unit tests; PostgreSQL integration requires
  an isolated `TEST_DATABASE_URL`.
- Web: generated API check, ESLint, Vitest, and production build.
- End to end: `pnpm acceptance` with the Compose stack.
- Unified entry: `pnpm verify`, implemented by the repository-local
  `code-change-verification` Skill.

Integration fixtures skip when `TEST_DATABASE_URL` is absent. Any verification entry that requests
integration coverage must fail before pytest when that variable is missing; a successful run with
skips is not integration proof.

## Source-size baseline

At audit start, the deterministic inventory reported 18,656 lines in 125 Server source files,
7,970 lines in 24 Server test/fixture files, 15,733 lines across 65 Web source files including CSS,
and 3,104 lines across 13 Web test files. The final tooling snapshot reports 8,012 Server
test/fixture lines because the integration fixture gained the database-target guard; production
source counts are unchanged.

### Server production Python

| File | Physical lines | Classification |
| --- | ---: | --- |
| `infrastructure/database/models.py` | 1,254 | Declarative SQLAlchemy schema; report separately |
| `application/reader/content.py` | 872 | Cohesive but security-sensitive EPUB/TXT parser and sanitizer |
| `application/translations/service.py` | 833 | Translation Run orchestration |
| `api/schemas.py` | 829 | Declarative public Pydantic contract; report separately |
| `application/auth/service.py` | 821 | Login, refresh, context, Session and Device behavior |
| `infrastructure/integrations/linguaspindle.py` | 711 | Private translation HTTP adapter |
| `application/provider_credentials/service.py` | 673 | Credential crypto, routing, model discovery and lifecycle |
| `application/library/commit_service.py` | 586 | Import transaction, operation dispatch and compensation |

### Web TypeScript/TSX

| File | Physical / effective lines | Primary responsibility |
| --- | ---: | --- |
| `pages/AdminReadersPage.tsx` | 1,028 / 1,017 | Reader list plus credential/detail administration |
| `pages/ReaderPage.tsx` | 851 / 820 | Publication loading, navigation, settings and progress |
| `pages/ProviderCredentialPage.tsx` | 775 / 758 | Provider catalogue, credential lifecycle, usage and form state |
| `pages/TranslationsPage.tsx` | 621 / 600 | Run lists, detail, polling and control |
| `pages/UploadPage.tsx` | 602 / 583 | Inspect/commit upload workflow |
| `api/client.ts` | 576 / 566 | Shared transport plus endpoint adapters |
| `features/editions/EditionCard.tsx` | 385 / 382 | Edition projection and contextual actions |
| `pages/AdminSecurityPage.tsx` | 324 / 312 | Security administration |
| `pages/LibraryPage.tsx` | 322 / 318 | Library discovery |
| `pages/BookDetailPage.tsx` | 312 / 304 | Book and Edition details |

Large files are inventory signals, not automatic split requirements. In particular, declarative
models/schemas and cohesive parsers require responsibility and compatibility evidence before any
move.

### Large tests and generated files

- `tests/integration/test_translation_runs.py`: 1,715 lines.
- `tests/integration/test_migrations.py`: 1,193 lines.
- `tests/unit/test_provider_credentials.py`: 1,010 lines.
- `apps/web/tests/UploadPage.test.tsx`: 475 lines.
- `apps/web/tests/ProviderCredentialPage.test.tsx`: 439 lines.
- `apps/web/tests/AuthFlow.test.tsx`: 381 lines.
- Generated `packages/api-client/openapi.json`: 14,906 lines.
- Generated `packages/api-client/src/schema.d.ts`: 11,059 lines.

Tests participate in the same language thresholds so newly introduced or worsened test debt is
visible. Existing oversized tests remain explicit historical baseline entries. Do not split a
test mechanically if doing so obscures one scenario's setup and invariant matrix.

## Complexity hotspots

### Server

The opt-in Ruff command

```bash
cd apps/server
./.venv/bin/ruff check src tests/unit --select C901 \
  --config 'lint.mccabe.max-complexity=10'
```

reported 19 existing functions above 10:

- 23: `Settings.validate_auth_configuration`.
- 18: `GeneratedTranslationIngestionService.ingest`.
- 16: EPUB sanitizer `handle_starttag`.
- 15: reader administration `update_reader`.
- 14: auth `active_context`, translation `create`, translation `control`, CLI `run`, and Relay
  `chat_completions`.
- 13: import `commit`, import `_validate_actor_command`, and `inspect_epub`.
- 12: translation `sync` and `_ensure_remote`.
- 11: `delete_book`, `detect_text_encoding`, `save_progress`, site `update`, and LinguaSpindle
  `_json`.

Six Python functions exceed 100 physical lines: translation ingestion `ingest` (220),
`book_summaries` (144), translation `create` (129), translation `control` (121), import `commit`
(105), and import `_apply_operation` (101).

### Web

The Web AST heuristic found 25 production functions over 60 lines, 26 over complexity 10, and no
function deeper than 4. The highest signals are:

| Function/component | Lines | Complexity | Max depth |
| --- | ---: | ---: | ---: |
| `ProviderCredentialPage` | 659 | 66 | 4 |
| `TranslationsPage` | 470 | 47 | 3 |
| `AdminReadersPage.ReaderDetail` | 526 | 44 | 2 |
| `EditionCard` | 336 | 43 | 2 |
| `UploadPage` | 531 | 35 | 4 |
| `TranslationLaunchModal` | 255 | 32 | 4 |
| `AppShell` | 205 | 29 | 3 |
| `BookDetailPage` | 290 | 25 | 2 |
| `ReaderPage` | 758 | 24 | 2 |

These numbers mix rendering and state branching. A recommendation must identify a stable state,
action, or presentation responsibility rather than extract JSX by line range.

## Dependency baseline

### Server static imports

The inventory resolved 125 modules and 483 internal edges with zero cycles:

| Direction | Edges |
| --- | ---: |
| `api -> application` | 52 |
| `api -> domain` | 21 |
| `api -> infrastructure` | 23 |
| `application -> domain` | 41 |
| `application -> infrastructure` | 74 |
| `infrastructure -> application` | 1 |
| `infrastructure -> domain` | 18 |

The single `infrastructure -> application` edge is `LocalFileStorage` using the
application-owned `FileStorage` contract and is intentional dependency inversion. Domain has no
outward dependency to API, Application, or Infrastructure.

### Web static imports

Resolved relative static and dynamic imports contain zero cycles. `api/client.ts` and
`api/types.ts` each have fan-in 23; `AsyncState` and `PageHeader` each have fan-in 17.

**Inference.** The API adapter and shared UI are high-blast-radius compatibility boundaries.
Their fan-in is not evidence of a defect, but any split requires stable re-exports or a complete
caller migration in one independently verifiable slice.

Before this tooling task, CI did not enforce Web dependency direction or import-cycle absence.
The new repository quality guard now enforces zero resolved TypeScript/TSX import cycles in CI;
broader Web dependency-direction policy remains a reviewed refactoring constraint rather than a
hard-coded layer rule.

## Test-protection baseline

**Facts.**

- Server collected 112 unit and 34 integration cases. Unit tests concentrate on Provider
  credentials, parsers, security primitives, storage, and the LinguaSpindle client.
- `AuthService`, `ImportCommitService`, and Translation Run orchestration are protected mainly by
  broad PostgreSQL/API scenarios rather than narrow service-level characterization tests.
- Web has 19 page modules; 7 have direct page-level specs. `AdminReadersPage` has 3 direct cases,
  `TranslationsPage` 2, and `ReaderPage` 4.
- Many `api/client.ts` endpoints are protected indirectly through page tests.
- Neither toolchain has a configured coverage threshold. Mypy excludes Server integration tests.

**Inference.** Existing behavior coverage is broad but some refactor seams are expensive to
localize. Add characterization tests before moving state transitions, compensation logic,
security ordering, or shared API exports. Do not equate the absence of a coverage percentage with
the absence of tests.

## Exclusions and special handling

- Exclude lockfiles, installed dependencies, caches, build output, coverage output, artifacts,
  binary fixture output, and `*.tsbuildinfo` from source-size and complexity gates.
- Exclude generated OpenAPI JSON and `schema.d.ts` from manual size/complexity judgments; require
  deterministic regeneration and `pnpm api:check`.
- Treat Alembic versions separately. Continue Ruff/format checks and require a single head,
  isolated upgrade, and migration tests. Do not require universal downgrade: revision
  `20260723_0006` is intentionally irreversible and later downgrades are data-guarded.
- Treat ORM models and Pydantic schemas as declarative categories. Continue lint/type checks but
  do not force mechanical splitting at an ordinary behavior-file limit.
- Treat tests and fixture generators as separate categories; lint their source and exclude only
  generated outputs.
- Keep `api/client.ts`, parsers, protocol adapters, and large CSS files in reports. They are
  handwritten code and are not generated exclusions.

## Compatibility boundaries to preserve

- FastAPI route, status, stable error, cookie, and generated OpenAPI contracts.
- Database constraints, migration history, owner/creator attribution, Edition revisions, and
  immutable Provider credential/Translation Run binding.
- Credential capability, recovery confinement, Session replay, 404 isolation, audit, and secret
  redaction behavior.
- `FileStorage`, atomic import compensation, protected storage identifiers, and backup/restore
  topology.
- LinguaSpindle version, Pipeline, MIME, Artifact, idempotency, scope, Job correlation, and Relay
  boundaries.
- Reader-safe publication projection, progress conflicts, theme/settings, and private state.
- Web route behavior, API types, accessibility, responsive navigation, and acceptance scenarios.

## Recommended ratchet

These are proposed verification thresholds, not product architecture decisions:

- Python source files: report above 400 effective lines. TypeScript/TSX source files: report above
  300 effective lines. Record existing exceptions; fail only when an exception grows or a new file
  crosses its language threshold without explicit approval.
- Named functions/components: report above 60 lines and complexity above 10. Record current
  exceptions by path and symbol; prohibit new exceptions and metric growth.
- Nesting: report above 4 and prohibit new deeper functions.
- Static import cycles: hard limit zero.
- Domain outward edges and Infrastructure-to-API edges: hard limit zero.
- During pure refactoring, prohibit growth in measured `application -> infrastructure`,
  `api -> infrastructure`, and high fan-in Web boundary edges.
- Exclude generated contracts and migration history from all structural metrics. Exclude only the
  file-size metric for the declarative ORM model and Pydantic schema registries; their function
  metrics remain enforced. Tests are included. Continue all applicable semantic checks.

## Verification triggers

| Changed surface | Required route |
| --- | --- |
| Any Server Python | Ruff, format, mypy, unit tests, inventory/quality ratchet |
| Server application, repository, auth, storage, Reader, or translation behavior | Relevant PostgreSQL integration tests with an isolated `TEST_DATABASE_URL` |
| ORM model or Alembic version | Single head, isolated upgrade, migration tests, affected integration tests |
| Route, API schema, serializer, or OpenAPI export | Server checks plus `pnpm api:check` and Web type/lint/tests |
| Any Web TS/TSX | ESLint, TypeScript, Vitest, inventory/quality ratchet |
| User-visible Web or HTTP flow | Production build and targeted acceptance after lower-level checks |
| Dependency or lockfile | Frozen dependency validation plus all affected language gates |
| Compose, staging, backup, restore, or deployment script | Syntax/config validation and the relevant protected-environment procedure |

An unselected check must report `SKIPPED`; a selected check with a missing prerequisite must report
`BLOCKED`. Neither is a pass.

## Phase-two refactor candidates

The following three priorities are proposals only, not approved architecture decisions. Each must
become a separately approved, independently verifiable slice:

1. **Translation ingestion and Run orchestration.** First characterize artifact validation,
   storage compensation, idempotency, cleanup, and state transitions. Then separate one coherent
   download/prepare/persist responsibility while preserving `TranslationRunService`, error codes,
   Run invariants, and LinguaSpindle contracts.
2. **Provider/translation Web state orchestration.** First characterize catalogue invalidation,
   credential rotation/removal, polling, selected Run, and control behavior. Extract state/action
   ownership without merging Provider configuration and Run lifecycle into a generic hook.
3. **Import commit workflow.** Characterize its operation matrix, transaction, file moves,
   rollback, and error mapping before separating operation planning from persistence.

Large Reader parsing/rendering files and declarative Server schemas remain visible but are not
prioritized solely because of line count.
