# Refactor audit

> Status: read-only audit refreshed on 2026-08-08 against `develop@8c1f098`.
> Facts below preserve the pre-refactor repository snapshot used to select this run's slices.
> Inferences and recommendations are proposals, not new architecture decisions; completed work
> and final measurements are recorded in `refactor-progress.md`.

## Scope and method

This audit covers the FastAPI Server, React Web application, generated API-client boundary,
migrations, tests, verification tooling, repository scripts, and maintained architecture
documents. It follows the repository-local `repo-context` and `architecture-audit` Skills.

Evidence was collected from current source, tests, Git history, the deterministic source
inventory, the quality guard, Ruff's opt-in McCabe diagnostic, and test collection. Generated
contracts and accepted migrations were inspected as compatibility boundaries, not ordinary
refactoring targets.

No production data, migration, deployment, package dependency, generated contract, external
service, or business source was changed during the audit. Product test bodies, PostgreSQL
integration tests, browser acceptance, and paid Provider calls were not run in this read-only
phase. Their absence is not a pass.

## Revision and worktree

- **Fact.** Current branch is `develop`; `HEAD` and `origin/develop` both resolve to
  `8c1f09802af104323b4bddd9cbb397d3ba90d713`.
- **Fact.** `git status --short` was empty before the audit.
- **Fact.** The existing quality baseline was generated from `3a37900` and is protected by Git
  provenance and same-change policy checks.
- **Fact.** The previous baseline document reports 8,012 Server test/fixture lines; the current
  inventory reports 8,013. This is a one-line measurement drift, not a quality regression.

## Current architecture and responsibilities

### Repository and entry points

- **Fact.** `apps/server` is one FastAPI modular monolith with three process/composition entry
  points: `main.py`, `relay.py`, and `cli.py`.
- **Fact.** `apps/web/src/main.tsx` composes providers and routing. All 19 page modules are lazy
  imports in `apps/web/src/App.tsx`; Reader, Upload, administration, and translation pages do not
  enter the synchronous application entry.
- **Fact.** `packages/api-client/openapi.json` and `src/schema.d.ts` are generated contracts.
  Browser transport and authentication behavior remain in `apps/web/src/api/client.ts`.
- **Fact.** PostgreSQL and private library storage are owned by Novel Platform. LinguaSpindle and
  the Provider Relay are private integration boundaries with separate identity/storage rules.

### Server dependency direction

The current static Python graph resolves 125 modules and 483 internal edges with zero cycles.

| Direction | Edges | Assessment |
| --- | ---: | --- |
| `api -> application` | 52 | Accepted HTTP-to-use-case adaptation |
| `api -> domain` | 21 | Accepted contract/domain use |
| `api -> infrastructure` | 23 | Existing measured coupling; ratcheted against growth |
| `application -> domain` | 41 | Expected direction |
| `application -> infrastructure` | 74 | Existing concrete repository/model coupling; ratcheted |
| `infrastructure -> application` | 1 | Intentional `FileStorage` dependency inversion |
| `infrastructure -> domain` | 18 | Expected adapter/domain use |

- **Fact.** Domain has no outward dependency to API, Application, or Infrastructure.
- **Fact.** Infrastructure has no dependency on API.
- **Inference.** The 74 Application-to-Infrastructure and 23 API-to-Infrastructure edges increase
  refactoring setup cost, but do not justify converting the modular monolith into services.
- **Recommendation.** Preserve the current concrete repository architecture during incremental
  work. Reduce one proven responsibility or duplicate policy at a time rather than introducing a
  repository-wide port abstraction.

### Web dependency direction

- **Fact.** The current TypeScript graph has zero resolved static cycles.
- **Fact.** Pages do not issue direct `fetch` calls; network access is concentrated in
  `apps/web/src/api/client.ts`.
- **Fact.** No Feature, Shared, or Layout module imports a Page implementation.
- **Fact.** `api/client.ts` has 23 production callers and its mutable `api` object is used by
  `vi.spyOn` in many tests.
- **Inference.** The API client is a high-blast-radius compatibility surface. Its size alone is
  insufficient evidence for a first refactor because Blob/XHR paths are not narrowly protected.

## Current size and complexity

### Inventory

| Area | Files | Physical lines |
| --- | ---: | ---: |
| Server source | 125 | 18,656 |
| Server tests/fixtures | 24 | 8,013 |
| Web source, including CSS | 65 | 15,733 |
| Web tests | 13 | 3,104 |
| Server migrations | 10 | 2,555 |
| Generated API contract area | 4 | 25,975 |
| Repository scripts | 32 | 12,794 |

### Quality ratchet

- **Fact.** The guard scanned 6,807 metrics and reported 211 reviewed historical violations with
  no worsening: 134 Python and 77 TypeScript.
- **Fact.** The 211 entries comprise 29 file-size, 97 function-length, 80 complexity, and 5
  nesting violations.
- **Fact.** Product source accounts for 161 entries: 101 Server and 60 Web. Tests remain included
  in the ratchet.
- **Fact.** Current hard results are 0 Python cycles, 0 TypeScript cycles, and 0 configured
  boundary violations.
- **Fact.** The guard reported no stale `TIGHTEN` or `CLEANUP` item before this task.
- **Inference.** `BASELINE FAILURE` means historical debt is contained, not that the targets are
  met.

Reference thresholds remain: Python file 400 effective lines, TypeScript/TSX file 300, named
function 60, complexity 10, and nesting 4.

### Server hotspots

| Responsibility | Evidence | Test seam | Assessment |
| --- | --- | --- | --- |
| Translation Run orchestration | `service.py` 807 effective lines; `create`, `control`, `sync`, `_ensure_remote` exceed limits | Broad PostgreSQL/API scenarios | High value, split only after focused rules/tests |
| Generated translation ingestion | `ingest` 215 effective lines, heuristic complexity 25; download, parse, lock, storage, DB, compensation | Success/EPUB/corrupt integration cases; no direct unit | High benefit, high compatibility risk |
| Import commit | file 559 effective lines and 10 baseline entries; transaction and compensation concentrated | Three broad integration scenarios | High benefit, high rollback risk |
| Provider/Relay configuration | Server and Relay repeat secret/model/allow-list/upstream normalization | 26+ direct Provider unit cases | Suitable pure-policy extraction after the selected rules slice |
| Auth service | 821 physical lines; login, refresh, context, Session, Device | Broad security/integration tests | High impact and weak narrow seam; defer |
| Reader content | 872 physical lines, security-sensitive parser/sanitizer | Focused parser/content units | Cohesive despite size; do not split mechanically |

Ruff's opt-in C901 diagnostic found 19 functions above 10. The command exits 1 by design for the
historical diagnostic; normal Ruff configuration still passes. The highest values include
`Settings.validate_auth_configuration`, translation ingestion, Reader sanitization, translation
control/create, CLI dispatch, and Relay request orchestration.

### Web hotspots

| Responsibility | Current signals | Direct tests | Assessment |
| --- | --- | ---: | --- |
| Provider credential page | 758 effective lines; component 652/complexity 66; 3 commits and 1,077 churn lines | 9 | Strong first Web seam if API-key lifecycle and async ordering stay put |
| Translation workspace | 600 effective; component 461/47; 6 commits and 951 churn lines | 2 | High value but protection is too thin for the first slice |
| Upload workflow | 583 effective; component 522/35 | 8 | Good later state-boundary candidate |
| Admin readers | 1,017 effective; two large components | 3 | High compatibility risk; defer |
| Reader page | 820 effective; component 739/24 | 4 | High-risk side effects and publication boundary; defer |
| API client | 566 effective; `request` complexity 14; 23 callers | 5 direct transport cases | P2 until Blob/XHR behavior is characterized |

The current TypeScript guard records 24 production function-length violations, while the 2026-07-30
historical narrative recorded 25 under its earlier snapshot. The historical measurement is
retained; current reporting uses the guard's 24-entry result.

## Duplicate rules, misplaced orchestration, and side effects

### Duplicate business/application rules

- **Fact.** Translation control eligibility is encoded independently in
  `application/translations/service.py` and `api/translation_responses.py`. Both currently map
  Run status to `pause`, `resume`, `cancel`, and `retry`.
- **Inference.** Two matrices can drift, causing an action to be advertised but rejected, or
  accepted but not advertised.
- **Recommendation.** Move only the control eligibility and ordering into a pure Translation
  domain policy; retain `sync`/`cleanup` projection conditions in the API adapter.

- **Fact.** Provider preset/thinking rules are represented in both Web form logic and Server
  authority. Web copies are presentation decisions, not authorization.
- **Recommendation.** Extract a client-only deterministic form model while keeping Server rules
  authoritative and leaving API-key lifecycle/API calls in the Page.

- **Fact.** Server and Relay settings repeat provider-secret, model-list, allow-list, and upstream
  normalization.
- **Recommendation.** Treat this as a later P1 pure configuration-policy slice with exact error
  message/order characterization.

### Business logic at boundaries

- **Fact.** `api/routes/books.py` coordinates pagination, access parameters, repositories, and
  summary assembly. `LibraryRepository.book_summaries` also combines visibility, preferences,
  progress, formats, and projection.
- **Fact.** `TranslationsPage` owns polling, visibility listeners, backoff, action serialization,
  selected Run state, and detail presentation.
- **Fact.** `ProviderCredentialPage` owns deterministic form decisions plus API-key lifecycle,
  catalogue request races, persistence calls, usage, and presentation.
- **Inference.** These are real responsibility concentrations, but moving their asynchronous or
  persistence behavior without focused tests would increase risk.

### Global state and implicit side effects

- **Fact.** `main.py` and `relay.py` create settings/engines/apps during import; `main.py` also sets
  `tempfile.tempdir`.
- **Fact.** `api/client.ts` has module-level access-token, refresh-flight, and auth-failure state.
- **Fact.** `ReaderPage`, `TranslationsPage`, and `ProtectedImage` intentionally manage timers,
  visibility events, Blob URLs, scroll restoration, or request queues.
- **Inference.** These effects are compatibility-sensitive. App-factory or generic-hook work is
  P2 until existing import/test and lifecycle contracts are characterized.

## Public and compatibility boundaries

The following must remain unchanged during the selected work:

- FastAPI paths, methods, response schemas, status codes, stable errors, cookies, and generated
  OpenAPI output.
- Translation `control(scope, run_id, action: str)` call shape, control-action order, conflict
  error `translation_control_conflict`, and HTTP 409 behavior.
- Translation status, remote protocol, persistence, idempotency, cleanup, credential scope, and
  LinguaSpindle action vocabulary.
- Web route and named component exports, accessible names/text, API payloads, model catalogue
  invalidation, request-id race behavior, and API-key clearing before save.
- Database schema, accepted migrations, persistent data, deployment topology, dependencies, and
  generated client files.
- `api/types.ts` compatibility adapters, including optional import payload fields restored over
  generated types.

No currently used legacy v1 Provider-credential path is deprecated for removal; it has explicit
unit coverage and remains a compatibility requirement.

## Test protection and weak seams

- **Fact.** Current collection finds 112 Server unit and 34 Server integration tests.
- **Fact.** Current Web collection lists 60 tests across 12 specs. Seven of 19 pages have direct
  page specs.
- **Fact.** There is no configured coverage threshold. Server mypy does not type-check integration
  tests.
- **Fact.** Translation action/ingestion behavior is primarily protected by broad PostgreSQL/API
  scenarios. Import Commit has the same weakness.
- **Fact.** ProviderCredentialPage has nine direct behavior tests covering catalogue invalidation,
  key clearing before save, DeepSeek/Kimi mapping, and revocation. Missing cases include stale
  concurrent catalogue responses and invalid custom URLs.
- **Recommendation.** Add passing characterization tests before each selected movement and assert
  projected actions/form behavior rather than file placement or private helper calls.

## Change-frequency evidence

The available 27-commit release-window history identifies relative hotspots, not proof of ongoing
instability. No product-source commit exists after 2026-07-28.

| Handwritten surface | Commits touched | Approximate churn lines |
| --- | ---: | ---: |
| `TranslationsPage.tsx` | 6 | 951 |
| Translation service | 4 | 903 |
| `ProviderCredentialPage.tsx` | 3 | 1,077 |
| Provider credential service | 3 | 761 |
| LinguaSpindle adapter | 3 | 739 |
| `EditionCard.tsx` | 4 | 455 |
| Translation ingestion | 2 | 394 |
| Import commit service | 2 | 106 |

Generated OpenAPI/schema churn and migration history are excluded from hotspot prioritization.

## Prioritized candidates

Scores use 1–5. Higher means more cost/frequency/impact/dependencies/difficulty/risk, while higher
test protection and benefit are favorable.

| Candidate | Priority | Maintain | Frequency | Impact | Tests | Dependencies | Difficulty | Compatibility risk | Benefit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Translation control-action domain policy | P1 | 3 | 4 | 4 | 3 | 2 | 1 | 2 | 4 |
| Provider credential form decision/state model | P1 | 5 | 4 | 5 | 4 | 2 | 3 | 3 | 5 |
| Translation Run/ingestion responsibility split | P1 | 5 | 4 | 5 | 3 | 5 | 4 | 5 | 5 |
| Translation workspace polling/action state | P1 | 5 | 5 | 5 | 2 | 3 | 4 | 4 | 5 |
| Import Commit planning/persistence/compensation | P1 | 5 | 3 | 5 | 3 | 5 | 4 | 5 | 5 |
| Provider/Relay pure configuration policy | P1 | 4 | 4 | 5 | 5 | 4 | 3 | 5 | 4 |
| Upload local inspect-preview-commit state | P1 | 4 | 4 | 4 | 5 | 3 | 3 | 3 | 4 |
| API transport versus endpoint adapters | P2 | 4 | 5 | 5 | 3 | 5 | 4 | 5 | 4 |
| Auth service responsibility split | P2 | 5 | 2 | 5 | 3 | 4 | 5 | 5 | 4 |
| Reader parsing/rendering and App factories | P2 | 4 | 2 | 5 | 3 | 4 | 5 | 5 | 3 |
| Declarative schema/model split by size | P3 | 2 | 2 | 5 | 4 | 5 | 5 | 5 | 1 |

### Priority conclusion

- **P0:** none established. There is no current cycle, configured boundary violation, quality
  regression, or demonstrated security blocker. Runtime surfaces not executed in this audit
  remain unverified rather than implicitly safe.
- **P1 selected for this run:** Translation control-action policy, followed by Provider credential
  form decisions. They are pure/deterministic seams, separately reversible, and precede high-risk
  orchestration work.
- **P1 deferred:** ingestion, workspace polling, Import Commit, provider configuration, and Upload
  state. Each requires its own focused characterization slice; deferral prevents scope expansion.
- **P2/P3:** do not process in this run.

## Audit command ledger

| Command | Result | Boundary |
| --- | --- | --- |
| `source_inventory.py --root .` | PASS | Static source/size/import inventory |
| `pnpm verify -- --quality-only --all` | Initial environment BLOCKED, then exit 0 | First sandbox run could not read existing uv cache; approved rerun produced 211 historical `BASELINE FAILURE`, quality PASS, 5 Skill PASS, 38 self-test PASS |
| Ruff opt-in `C901` diagnostic | Exit 1 / historical diagnostic | 19 existing functions over 10; not a new lint failure |
| Server unit/integration `--collect-only` | PASS: 112 / 34 collected | Test bodies not run |
| Web Vitest list | PASS: 60 listed | Test bodies not run |
| `git diff --check` | PASS | Audit-stage whitespace only |
| Product lint/test/build/API/integration/acceptance | SKIPPED | Run during proportional implementation verification, not claimed here |
