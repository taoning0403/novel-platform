# Incremental refactor progress

> Started 2026-08-08 on `develop@8c1f098`. This file is the restart point for a later Codex
> session. Status labels are literal: `PASS`, `FAIL`, `BASELINE FAILURE`, `SKIPPED`, `BLOCKED`.

## Scope status

| Item | Priority | Status | Next action |
| --- | --- | --- | --- |
| Read repository rules, context, Skills, baseline, Git state | required | complete | none |
| Refresh read-only architecture audit | required | complete | preserve evidence in audit |
| Translation control-action domain policy | P1 selected | complete | none |
| Provider credential deterministic form model | P1 selected | complete | none |
| Other P1/P2/P3 candidates | deferred | not started | use `refactor-plan.md`; do not expand this run |
| Commit, promote to `release`, push and guarded single-host deployment | added delivery scope | in progress | verify the exact release merge commit before deployment |

## Baseline before implementation

- Branch/upstream: `develop` / `origin/develop`; ahead 0, behind 0.
- Worktree before documentation: clean.
- Source inventory: Server 125 files/18,656 lines; Server tests 24/8,013; Web source
  65/15,733; Web tests 13/3,104; migrations 10/2,555; API contract 4/25,975.
- Dependency inventory: 125 Python modules, 483 edges, 0 Python cycles; 0 TypeScript cycles;
  0 configured boundary violations.
- Quality: 6,807 metrics; 211 reviewed historical violations; no pre-task `TIGHTEN`/`CLEANUP`.
- Collected only: 112 Server unit, 34 Server integration, 60 Web tests. Product test bodies were
  not run during audit.
- No safe `TEST_DATABASE_URL` is present in the environment. Docker client exists, but sandboxed
  access to the Docker socket is blocked; an isolated local database requires an approved
  out-of-sandbox command.

## Command ledger

| Stage | Command | Result | Notes |
| --- | --- | --- | --- |
| audit | `source_inventory.py --root .` | PASS | current inventory recorded above |
| audit | `pnpm verify -- --quality-only --all` | BLOCKED then exit 0 | sandbox uv-cache denial; approved rerun |
| audit | quality ratchet | BASELINE FAILURE + PASS | 211 historical, no worsening; 0 cycles/boundary violations |
| audit | project Skill validation | PASS | 5 directories |
| audit | verifier self-tests | PASS | 38 tests |
| audit | opt-in Ruff C901 | BASELINE FAILURE diagnostic | 19 historical functions over 10 |
| audit | Server test collection | PASS | 112 unit, 34 integration; no bodies run |
| audit | Web test list | PASS | 60 listed; no bodies run |
| audit | product runtime gates | SKIPPED | implementation has not started |
| S1 pre-move | `pytest -q -p no:cacheprovider tests/unit/test_translation_control_actions.py` | PASS | 16 cases against the original duplicate matrices |
| S1 local | focused test after movement | PASS | 16/16 unchanged |
| S1 local | changed-file Ruff / format | PASS | 4 files |
| S1 first verifier | `pnpm verify` | FAIL + BLOCKED | expected `TIGHTEN` for 3 historical values; PostgreSQL URL absent; all executed Server/API checks passed |
| S1 baseline | `quality_guard.py --write-baseline` | PASS | strict 807→792, 22→21, 121→105; no threshold/exclusion change |
| S1 integration | `pytest tests/integration/test_translation_runs.py` | PASS | 7/7 against loopback-only tmpfs PostgreSQL |
| S1 verifier | `TEST_DATABASE_URL=... pnpm verify` | BASELINE FAILURE + PASS | 6,821 metrics/211 historical; 0 cycles/boundary violations; 128 unit and 27 PostgreSQL integration passed; API contract passed |
| S1 review | `$code-review-and-quality` independent review | REQUEST CHANGES | one Required: directly characterize the Application service contract |
| S1 review fix | focused test / Ruff / format | PASS | 20 tests; legal remote actions plus exact conflict error contract |
| S1 review fix | project-configured `mypy` | PASS | 140 source files; a direct single-test-file invocation was invalid because it bypassed package resolution |
| S1 final verifier | `TEST_DATABASE_URL=... pnpm verify` | BASELINE FAILURE + PASS | 6,833 metrics/211 historical; 0 cycles/boundary violations; 132 unit and 27 PostgreSQL integration passed; API contract passed |
| S1 follow-up review | `$code-review-and-quality` independent review | APPROVE | Critical/Required/Optional/Nit all 0; previous Required closed |
| W1 pre-change | focused Provider/launch/API-client Vitest | PASS | 3 files, 18/18 before characterization additions or implementation |
| W1 characterization | Provider Page Vitest against original Page | PASS | 11/11, including unsafe custom URL and stale catalogue response |
| W1 focused | Provider/safety/launch/API-client Vitest after extraction | PASS | 4 files, 20/20 |
| W1 first quality | `quality_guard.py` | FAIL | existing Provider test file worsened when two cases were appended; moved those cases unchanged into a focused below-threshold spec |
| W1 quality | `quality_guard.py` after test organization | expected TIGHTEN/CLEANUP only | no new/worsened metric; Page tightened three values and cleared two exceptions |
| W1 baseline | `quality_guard.py --write-baseline` | BLOCKED then PASS | sandbox could not create baseline temp file; approved rerun wrote 209 strict historical entries |
| W1 local | `pnpm lint` / Web build | PASS | ESLint zero warnings; TypeScript and Vite production build passed with existing large-chunk warning |
| W1 full Web first run | `pnpm test` | FAIL | 61/62; unrelated AuthFlow heading wait exceeded default timeout under parallel load |
| W1 failure triage | focused AuthFlow / AuthFlow file / full Web rerun | PASS | 1/1, 12/12, then 62/62; no code/test timeout change made |
| combined verifier | `TEST_DATABASE_URL=... pnpm verify` | BASELINE FAILURE + PASS | exit 0; 6,907 metrics/209 historical; 132 Server unit, 62 Web, 27 PostgreSQL, API contract, build and local acceptance passed |
| W1 review | `$code-review-and-quality` independent review | REQUEST CHANGES | one Required: lock failed-save Key clearing and Kimi true payload; two Optional test expansions |
| W1 review fix | safety spec / quality guard | PASS | 4/4; exact failed-save and Kimi-true payloads; 6,919 metrics/209 historical, no worsening |
| W1 concurrent full Web | `pnpm test` while review subagents also ran checks | FAIL | 62/64; two unrelated 5-second timeouts under measured shared-machine load |
| W1 timeout triage | two exact failed tests, then full Web without concurrent agents | PASS | 1/1 + 1/1, then 64/64; no timeout or test rule changed |
| W1 follow-up review | `$code-review-and-quality` independent review | APPROVE | Critical/Required/Nit 0; two non-blocking Optional test expansions recorded below |
| pre-final combined verifier | `TEST_DATABASE_URL=... pnpm verify` | BASELINE FAILURE + PASS | exit 0; 6,919 metrics/209 historical; 132 Server unit, 64 Web, 27 PostgreSQL, API contract, build and local v0.10 acceptance replay passed |
| pre-final quality-only verifier | `pnpm verify -- --quality-only --all` | BASELINE FAILURE + PASS | exit 0; 6,919 metrics/209 historical, no worsening; 0 Python/TypeScript cycles and 0 configured boundary violations; 5 Skills and 38 verifier self-tests passed |
| final migration integration routing | change-aware verifier | SKIPPED | no migration or schema surface changed |
| final configuration routing | change-aware verifier | SKIPPED | no configuration surface changed |
| final consistency review | independent `$code-review-and-quality` follow-up | REQUEST CHANGES | remove test `Any`/dynamic method replacement and account for the third dependency edge |
| type-safe test double, first attempt | focused tests / Ruff / format / mypy | FAIL | behavior 20/20 and Ruff passed; format requested one-file rewrite and mypy rejected method assignment, then an incomplete abstract Gateway |
| type-safe test double, final | focused tests / Ruff / format / mypy | PASS | explicit complete fail-fast `LinguaSpindleGateway`; 20/20 and strict mypy across 140 sources; no `Any`, ignore, or disabled rule |
| post-review quality guard | `quality_guard.py` | BASELINE FAILURE + PASS | 6,958 metrics/209 historical, no worsening; 0 cycles and 0 configured boundary violations |
| post-review combined verifier attempt | `TEST_DATABASE_URL=... pnpm verify` | FAIL | mypy caught the first method-replacement attempt; acceptance also exited 1; all other routed gates passed |
| acceptance failure diagnosis | report + exact BYOK Vitest command | FAIL then PASS | history replay passed; four 5-second Web waits failed under sustained local load, then the exact 32 cases passed 32/32 without timeout/test changes |
| complete local acceptance rerun | `pnpm acceptance -- v0100` | PASS | all 84 core + 9 hardening + 11 v0.9 criteria and five current v0.10 steps passed; report still names pre-commit HEAD, so it is not release-SHA evidence |
| final inventory | `source_inventory.py --root .` | PASS | Server source 126/18,653; Server tests 25/8,318; Web source 66/15,912; Web tests 14/3,311; generated contract, migrations and scripts unchanged |
| environment cleanup | stop exact temporary databases and inspect task processes/resources | PASS | removed `novel-platform-refactor-test-019fdf0f` and `novel-platform-refactor-final-019fdf0f`; no task Vitest/pytest/acceptance process or v0.10 network remained |

## Slice S1 — Translation control-action domain policy

- Status: complete; implemented, proportionally verified, and independently approved.
- Responsibility: ordered `TranslationRunStatus -> control actions` policy.
- Modified files: new `domain/translations/control.py`, Application service, API response adapter,
  new focused unit test, and the quality baseline.
- Tests added: `test_translation_control_actions.py`, covering all 11 statuses, five remote
  sync/cleanup combinations with exact action ordering, three legal Service-to-remote action
  calls, and the exact illegal-combination code/message/409 contract. The first 16 policy/projection
  cases passed against the original duplicate implementation before it moved.
- Compatibility: keep routes, service signature, action order, error code/message/status, remote
  protocol, persistence, and generated schema unchanged.
- Verification: focused tests 20/20; Server Ruff/format/mypy; 132 unit tests; deterministic API
  contract; 7 targeted and 27 routed PostgreSQL integration tests all passed. Migration integration,
  Web gates, and acceptance were correctly `SKIPPED` for this surface. The initial review rejected
  the test boundary because it did not invoke the Application service; the four follow-up cases
  close that gap.
- Baseline exceptions removed/tightened: three values in Translation service: file effective lines
  807→792, `control` complexity 22→21, and `control` effective lines 121→105. Total historical
  entry count remains 211.
- Rollback: remove policy/tests and restore the two callers plus slice-specific baseline diff.
- Next step: none in this run; deferred Translation work remains separately prioritized in the
  audit and plan.

## Slice W1 — Provider credential deterministic form model

- Status: complete; implemented, proportionally verified, and independently approved.
- Responsibility: deterministic form transitions and derived decisions.
- Modified files: Provider page, new focused feature model, new focused catalogue-safety Page spec,
  quality baseline, and module map.
- Tests added: four page-level characterization cases. The first two passed against the original
  Page before extraction: unsafe custom URLs never reach catalogue/update APIs, and a deferred old
  Provider/key catalogue response cannot overwrite the current selection. Review then required two
  more exact contracts: update rejection never restores the Key and Kimi `kimi-k2.5` with the
  switch enabled saves `thinking_enabled: true`.
- Compatibility: preserve API-key clearing order, request-id race handling, API payloads, text,
  accessibility, route/export, and Server authority. API key state, request IDs, asynchronous API
  calls, notices, and `setApiKey("")` before update remain in the Page.
- Verification: final focused safety 4/4 and full Web 64/64; lint; TypeScript/Vite build; combined
  verifier exit 0 with Server/API/PostgreSQL checks and local v0.10 acceptance replay. Earlier
  unrelated UI waits failed once under parallel load and passed focused/full reruns without rule
  changes. No generated API diff appeared; migration integration was correctly `SKIPPED`.
- Baseline exceptions removed/tightened: Page file 758→624, component complexity 66→49, component
  length 652→565; removed `loadModelCatalog` complexity 11 and `saveCredential` length 67 entries.
  Total historical entries fell 211→209. The new model and safety spec introduce no exception.
- Rollback: restore page-local decisions and remove feature model/tests plus slice-specific baseline
  diff.
- Next step: none in this run. Review's two Optional test enhancements—parameterizing every custom
  URL rejection subcondition and isolating key-only/base-URL-only in-flight races—are non-blocking
  follow-ups and do not justify expanding this refactor slice.

## Compatibility-layer ledger

No temporary compatibility layer has been introduced. The Server policy migrated both internal
callers in one slice; the Web Page remains the existing public route/export.

## Final handoff snapshot

- Source inventory after both slices: Server source 126 files/18,653 lines; Server tests
  25/8,318; Web source 66/15,912; Web tests 14/3,311; migrations 10/2,555; generated API
  contract area 4/25,975; repository scripts 32/12,794.
- Quality scan: 6,958 metrics and 209 reviewed historical entries: 29 file-size, 96
  function-length, 79 complexity, and 5 nesting. Product source accounts for 21, 56, 77, and 5
  respectively.
- Dependency inventory: 126 Python modules, 486 edges and 0 cycles; TypeScript cycles remain 0.
  The new expected inward Domain uses make `api -> domain` 21→22 and
  `application -> domain` 41→42; the policy's import of the existing status model makes
  `domain -> domain` 9→10. Existing `application -> infrastructure` 74 and
  `api -> infrastructure` 23 coupling did not grow; the guard reports no configured boundary
  violation.
- Generated OpenAPI/schema, migrations, dependencies, lockfile, routes, CSS, database data, and
  deployment topology are unchanged.
- The exact temporary loopback PostgreSQL container was stopped and removed after final
  verification. Existing unrelated stopped Compose containers were not modified.
- At the refactor verification checkpoint no commit, push, deployment, publication, production
  mutation, or paid/external Provider call had been performed. The user subsequently authorized
  release promotion and guarded deployment; exact-commit and deployment evidence will be appended
  after that separate delivery phase.

## Remaining risks

- The routed local acceptance replay passed. Real Provider calls, paid/content egress, deployed
  browser and device behavior remain outside the local refactor proof.
- Historical quality debt remains `BASELINE FAILURE`; selected work must not create or relocate an
  exception.
- Review left two non-blocking test-depth opportunities for the Provider page: isolate every
  unsafe-URL subcondition, and separately cover key-only/base-URL-only in-flight catalogue races.
- Deferred P1 orchestration candidates remain audit-and-plan items only; none is partially moved.
- LinguaSpindle code/configuration and paid Provider calls remain outside scope. The existing
  single-host deployment may be health/topology checked, but this refactor does not alter its
  private integration protocol.
