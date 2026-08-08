# Incremental refactor plan

> Approved execution scope: the user's 2026-08-08 request explicitly authorizes audit,
> planning, tests, incremental refactoring, verification, review, and documentation. This plan
> therefore proceeds without a second implementation approval checkpoint.

## Objective

Reduce two proven P1 responsibility/duplication hotspots without changing observable behavior:

1. make Translation Run control eligibility one pure domain policy consumed by Application and API;
2. make Provider credential form transitions and derived decisions one deterministic Web model
   while retaining secret lifecycle and async effects in the Page.

No feature, schema, migration, dependency, route, protocol, UI redesign, or deployment change is
part of this plan.

After both refactor slices were complete, the user separately authorized committing the verified
tree, promoting `develop` to the repository's existing `release` branch, pushing both branches,
and deploying the exact release commit through the maintained single-host runbook. That delivery
phase does not add another refactor slice or relax any completion criterion in this plan.

## Dependency graph and order

```text
Read-only audit and current quality baseline
  -> Slice S1 characterization tests
     -> Slice S1 domain policy extraction
        -> Server verification + review + baseline tightening
           -> Slice W1 characterization tests
              -> Slice W1 deterministic form-model extraction
                 -> Web verification + review + baseline tightening
                    -> final all-applicable verification and documentation
```

The slices are technically independent but will be executed serially so the shared quality
baseline and progress files have one writer.

## Slice S1 — Translation control-action domain policy

**Current problem.** Application control validation and API `available_actions` projection encode
the same `TranslationRunStatus -> pause/resume/cancel/retry` matrix independently. A future edit can
make advertised and accepted behavior diverge.

**Files and callers.**

- `apps/server/src/novel_platform/application/translations/service.py`
- `apps/server/src/novel_platform/api/translation_responses.py`
- `apps/server/src/novel_platform/domain/translations/models.py`
- new focused policy module under `domain/translations/`
- new/focused Server unit tests; existing `test_translation_runs.py` integration scenarios

**Single responsibility to extract.** Ordered control actions permitted for one local Translation
Run status. The API-only `sync` and `cleanup` projection conditions remain in the API adapter.

**Public interfaces to preserve.**

- `TranslationRunService.control(scope, run_id, action: str)`
- four HTTP control routes and their response schemas
- exact action ordering in `available_actions`
- `translation_control_conflict`, Chinese message, and HTTP 409
- remote LinguaSpindle action strings and idempotency behavior

**Compatibility strategy.** Introduce a pure domain function/type; both existing callers consume
it in the same slice. No external compatibility shim, re-export, or migration is required.

**Characterization tests before movement.**

- Parameterize all `TranslationRunStatus` values and assert the existing API-projected control
  action list and order with no remote IDs.
- Assert `sync` and `cleanup` ordering/conditions when remote IDs and terminal cleanup state exist.
- Run the focused characterization test against the unchanged implementation.

**Implementation steps.**

1. Add and pass characterization tests against current `_available_actions` behavior.
2. Add a specifically named domain control-policy module with immutable action sequences.
3. Replace the Application-local matrix with the domain policy.
4. Replace only the API control-action branches with the policy, then append existing `sync` and
   `cleanup` conditions unchanged.
5. Review imports, action order, error paths, and diff scope.

**Verification.**

- focused new unit test before and after movement;
- `uv run ruff check .` and `uv run ruff format --check .` from `apps/server`;
- `uv run mypy` and `uv run pytest tests/unit`;
- targeted `test_translation_runs.py` with a safe isolated `TEST_DATABASE_URL` if available;
- `pnpm verify` through `$code-change-verification`;
- direct quality guard after any `TIGHTEN`/`CLEANUP`, followed by reviewed baseline update and rerun.

**Rollback.** Restore the two callers, remove the new policy/test files, and restore only the
baseline entries tightened by this slice. No destructive Git command is needed.

**Completion criteria.** Every status maps to the same ordered controls; service acceptance and
API advertisement use one policy; all selected checks pass; no new metric, cycle, boundary edge,
schema diff, or API behavior appears.

**Explicitly out of scope.** Translation create/sync/retry implementation, remote protocol,
ingestion, cleanup, persistence, schemas, migrations, Web controls, and LinguaSpindle changes.

## Checkpoint after Slice S1

- Focused behavior is green before and after movement.
- Quality baseline is unchanged or strictly tightened.
- Independent five-axis review has no unresolved Critical/Required item.
- Progress document contains commands, results, compatibility, rollback, and next slice.

## Slice W1 — Provider credential deterministic form model

**Current problem.** `ProviderCredentialPage` interleaves deterministic Provider/model/thinking
decisions with API-key lifecycle, catalogue race handling, network calls, usage display, and JSX.
The deterministic decisions are repeated across handlers and derived render variables.

**Files and callers.**

- `apps/web/src/pages/ProviderCredentialPage.tsx`
- new `apps/web/src/features/provider-credentials/credentialFormModel.ts`
- existing `apps/web/tests/ProviderCredentialPage.test.tsx` plus a focused catalogue-safety spec
- nearby regression tests for translation launch and API client

**Single responsibility to extract.** Pure form decisions: provider presentation/base URL,
catalogue invalidation state, model/thinking transitions, load/save eligibility, and credential
payload construction/validation.

**Public interfaces to preserve.**

- `/provider-credential` route and named `ProviderCredentialPage` export
- visible Chinese text, accessible labels, roles, and control behavior
- API method calls and exact payloads
- catalogue request-id stale-response protection
- clearing the only React API-key copy before save begins and never restoring it on failure

**Compatibility strategy.** The Page remains the effect owner and calls a new internal pure model.
No API client, generated type, Server rule, CSS, route, or public package export changes.

**Characterization tests before movement.**

- Add invalid custom Base URL coverage proving catalogue/save API is not called.
- Add a deferred-promise race proving an older catalogue response cannot overwrite the current
  Provider/key catalogue.
- Run all existing Provider page cases against the unchanged implementation.

**Implementation steps.**

1. Add and pass the two missing page-level characterization cases.
2. Define explicit form state/derived decision inputs and outputs in the focused feature module.
3. Move deterministic transitions and payload/eligibility decisions only.
4. Keep request IDs, all asynchronous calls, `setApiKey("")` ordering, and notices in the Page.
5. Review for new invalid intermediate states, duplicate rules, secret retention, and accessibility
   changes.

**Verification.**

- focused Provider page, TranslationLaunchModal, and API-client Vitest specs;
- `pnpm lint`, `pnpm test`, and `pnpm build`;
- `pnpm verify` through `$code-change-verification`;
- quality guard/baseline tightening if requested;
- follow change-aware verifier routing for browser acceptance and record `PASS`, `FAIL`, or
  `SKIPPED` literally.

**Rollback.** Restore the page-local deterministic expressions, remove the feature model and new
tests, and restore only slice-specific baseline tightening.

**Completion criteria.** Existing and new page behavior passes; API key/order and payloads are
unchanged; the Page's measured complexity/length does not worsen and should tighten; the new
module stays below all thresholds; no new import cycle or API/generated diff appears.

**Explicitly out of scope.** Translation workspace, Server Provider authority, API client split,
CSS/visual redesign, new Provider support, generated contract changes, or credential persistence.

## Checkpoint after Slice W1

- Focused and full Web checks are green.
- Quality baseline is unchanged or strictly tightened.
- Independent review has no unresolved Critical/Required item.
- Architecture/module context reflects only actual new ownership.

## Deferred executable follow-ups

These remain proposals and are not dependencies for the selected slices:

1. Translation ingestion download/prepare versus persistence/compensation, after narrow service
   characterization and an isolated database are available.
2. Translation workspace polling/action state, after adding action/backoff/concurrency tests.
3. Provider/Relay pure configuration policy, preserving error order and legacy v1 behavior.
4. Import Commit planning/persistence/compensation, after focused transaction tests.
5. Upload preview invalidation state, using its existing eight direct page cases.
6. API transport versus endpoint adapters only after Blob/XHR characterization; do not split the
   endpoint object merely to delete a size exception.

## Final verification and documentation

- Run `pnpm verify` for the combined diff and `pnpm verify -- --quality-only --all`.
- Run all direct language gates selected by the diff.
- Run `pnpm api:check` only if API/generated surfaces changed unexpectedly; otherwise report
  `SKIPPED` rather than pass.
- PostgreSQL integration is required for Slice S1 when an isolated test database is available;
  no production/shared database may be used.
- Acceptance/E2E is required only if the implementation or review identifies user-visible behavior
  risk. External/paid Provider calls, deployment, push, and release remain forbidden within the
  refactor verification phase; the separately authorized delivery phase is governed by the
  maintained deployment runbook.
- Update `docs/MODULE_MAP.md` only for new/repurposed module ownership. Update
  `docs/PROJECT_STATE.md`, `docs/architecture.md`, `docs/data-model.md`, and ADRs only if their
  facts actually change.
