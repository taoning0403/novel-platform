# Module map

Use this map to choose a narrow inspection path, then verify behavior against current code,
migrations, and tests.

## Repository entry points

| Path | Responsibility |
| --- | --- |
| `README.md`, `README.zh-CN.md` | English and Simplified Chinese project overview, local start, CLI initialization, security configuration, checks, and release gate. |
| `LICENSE`, `NOTICE`, `SECURITY.md`, `SECURITY.zh-CN.md` | Apache-2.0 project license, Psycopg LGPL third-party notice, and bilingual private vulnerability-reporting policy. |
| `AGENTS.md`, `.agents/skills/repo-context/` | Required repository workflow and context-first navigation. |
| `.agents/skills/novel-platform-design-system/` | Approved 漫读 Quiet Trace tokens, layout, interaction, accessibility, and verification constraints for Web UI work. |
| `docs/PROJECT_STATE.md` | Current v0.9.0 capability, verification, omissions, and deployment state. |
| `docs/architecture.md`, `docs/data-model.md` | Boundaries, flows, relationships, and invariants. |
| `docs/DECISIONS.md`, `docs/adr/0012-*` through `0018-*` | Authentication, capability/contributor library, Quiet Trace, proxy hardening and private translation decisions. |
| `compose.yaml` | Isolated local PostgreSQL, migration, API, library volume, and Web topology. |
| `compose.staging.yml`, `.env.staging.example`, `compose.translation.yml` | HTTPS/WebAuthn single-host contract plus optional Server-only external `linguaspindle-private` overlay with no host port. |
| `scripts/acceptance-v090.mjs`, `acceptance-v090.database.yml` | Current release gate: applicable 84-core + 9-hardening replay and 11 v0.9 capability/contributor/translation/operations criteria in isolated resources. |
| `scripts/acceptance-v080.mjs` | Historical v0.8 gate, parameterized only so v0.9 can replay it into new evidence without overwriting historical artifacts. |
| `scripts/acceptance-v080.chain.yml`, `acceptance-v080-edge.conf` | Isolated two-hop chain (simulated host edge → staging Nginx → API) with fixed test addresses used only by the v0.8.0 gate. |
| `scripts/acceptance-v070.mjs` | Historical 105-criterion v0.7 gate retained with its evidence. |
| `scripts/acceptance-v060.mjs` | Historical 100-criterion v0.6 compatibility gate retained with its evidence. |
| `scripts/acceptance-v050.mjs` | Parameterized v0.5 core retained as historical evidence and replayed by current gates. |
| `scripts/acceptance-v010..v040.mjs` | Historical gates retained for evidence; password/ownership assertions are superseded. |
| `scripts/report-web-bundle.mjs` | Current production chunk inventory, route-scope comparison, accepted baseline sizes, and unchanged 200 kB entry gzip budget. |
| `scripts/deploy-staging.sh` | Backup, Alembic, explicit auth conversion, volume audit, and safe service start. |
| `scripts/backup-library.sh`, `restore-library.sh` | Coordinated Novel Platform database/library backup and isolated v0.9 restore verification; explicitly excludes LinguaSpindle resources. |
| `scripts/acceptance-staging-persistence.sh` | Sanitized table/fingerprint persistence across service/database/Compose recreation. |
| `scripts/{report-staging-resources,scan-staging-artifacts,generate-staging-deployment-report}.sh` | v0.5 resource, leak, and deployment evidence without credentials or host paths. |
| `docs/staging-deployment.md` | HTTPS, v0.9 destructive migration/reset approval, private translation network, backup/restore, verification and rollback runbook. |

## Server (`apps/server`)

| Path | Responsibility |
| --- | --- |
| `src/novel_platform/config.py` | Auth/WebAuthn/CORS/proxy/storage limits plus fail-closed, non-secret LinguaSpindle origin/version/provider/time/size settings. |
| `src/novel_platform/main.py` | FastAPI/OpenAPI construction, middleware, routing, and noindex policy. |
| `src/novel_platform/cli.py` | Administrator, migration, integrity-audit, and retention-cleanup CLI. |
| `api/dependencies/auth.py` | Database-backed User/credential capability/device/Session/Passkey checks and recovery restriction. |
| `api/routes/auth.py` | Unified credential login, Passkey registration/authentication, device-bound refresh with fail-closed Origin, logout, Sessions. |
| `api/errors/handlers.py` | Stable error contract; clears the Refresh Cookie only for 401 refresh outcomes. |
| `api/routes/readers.py`, `site.py`, `audit.py` | Administrator reader/credential, site-setting, and audit adapters. |
| `api/routes/users.py`, `devices.py` | Self display-name and self device management; no password or user-creation routes. |
| `api/routes/books.py`, `editions.py`, `series.py` | Capability/creator-aware Book/Edition mutation, admin-only Series, and authenticated readable queries. |
| `api/routes/imports.py`, `files.py` | Actor-isolated admin/`library.upload` imports, admin raw downloads and protected cover delivery. |
| `api/routes/translations.py` | Actor-scoped Translation Run status/create/list/control/sync/preview plus administrator publish. |
| `api/routes/reader.py`, `preferences.py` | Safe publication projection and viewer-private reading state. |
| `api/schemas.py`, `api/serializers.py`, `api/errors/` | Strict non-secret contracts, reader projections, and stable errors. |
| `application/access.py` | Separates site library owner, authenticated actor, current credential capabilities and resource creator policy. |
| `application/auth/security.py` | Domain-separated HMACs, high-entropy credentials/device secrets, JWT and refresh tokens. |
| `application/auth/service.py` | Credential/device/Session login, throttle, device-bound rotation/replay, state revalidation. |
| `application/auth/webauthn_service.py` | UV/resident Passkeys, origin/RP/single-use challenge validation, and bounded expired-challenge cleanup on issuance. |
| `application/auth/admin_service.py` | CLI-only initialization, recovery/reset, Session revocation, lock/unlock/status. |
| `application/auth/migration_service.py` | Read-only preflight, explicit conversion, and database-volume integrity audit. |
| `application/auth/audit_service.py` | Filtered reads and retention-based manual cleanup. |
| `application/readers/service.py` | Persistent invited identity and one-current-credential capability snapshot/reissue lifecycle. |
| `application/site/service.py` | Limited public/site-security settings and change audit. |
| `application/books/`, `editions/`, `series/` | Readable, owner/creator-aware library orchestration and deletion dependencies. |
| `application/library/` | Actor-attributed EPUB/TXT inspect/commit/revision, generated ingestion reuse and safe storage lifecycle. |
| `application/translations/` | Run state machine/orchestration, deterministic remote correlation, sync/control/cleanup and atomic generated ingestion. |
| `application/reader/` | Safe EPUB/TXT projection, protected resources, progress/settings/recent state. |
| `infrastructure/repositories/credentials.py` | Credential capability, Passkey, challenge and device-secret lookups/counting plus bounded challenge deletion. |
| `infrastructure/repositories/{books,editions,series,reader,translations}.py` | Explicit library owner, actor creator and viewer query boundaries. |
| `infrastructure/integrations/linguaspindle.py` | Narrow, same-origin, no-redirect, bounded-streaming v0.3.1 private HTTP client. |
| `infrastructure/database/models.py` | Identity/capability, creator-attributed library, Translation Run, auth and reader mappings. |
| `infrastructure/storage/local.py` | Random-key private local storage with checksum and bounded-path enforcement. |
| `migrations/versions/20260715_0005_private_reading_access.py` | v0.5.0 authentication/site schema. |
| `migrations/versions/20260723_0006_capabilities_contributors_translations.py` | Destructive fileless cleanup, creator/capability backfill and Translation Run schema; no downgrade. |
| `tests/integration/test_auth_and_isolation.py` | Credential capabilities/state, device concurrency, recovery/reset/lock and private isolation. |
| `tests/integration/test_auth_hardening.py` | Device-bound refresh, uniform failure, replay revocation, fail-closed Origin, and device-Cookie renewal. |
| `tests/integration/test_challenge_cleanup.py` | Bounded expired-challenge deletion, valid-row preservation, and concurrent single-use verification. |
| `tests/unit/test_auth_cookies.py` | Device-Cookie issuance, renewal, and independent lifetime. |
| `tests/integration/test_api_workflow.py`, `test_contributor_library.py` | Legacy API removal, shared visibility, attribution and contributor permission/deletion matrix. |
| `tests/integration/test_migrations.py` | Empty/v0.4/v0.9 upgrades, destructive count/preservation, capability/creator backfill and fail-closed preflight. |
| `tests/unit/test_linguaspindle_client.py`, `tests/integration/test_translation_runs.py` | Private client hardening plus Run idempotency/control/cleanup/ingestion/draft/retranslation behavior. |

## Web and shared client

| Path | Responsibility |
| --- | --- |
| `packages/api-client/openapi.json`, `src/schema.d.ts` | Generated FastAPI contract and TypeScript schema. |
| `apps/web/nginx.staging.conf`, `apps/web/nginx/staging-*.conf`, `apps/web/Dockerfile.staging` | Staging proxy: single-trusted-peer realip restoration, auth entry rate limits with stable JSON 429, and shared upstream-header snippets (no per-location proxy drift). |
| `apps/web/src/api/{types,client}.ts` | Generated v0.9 aliases, in-memory access token, refresh, library and Translation Run calls. |
| `apps/web/src/ui/{AppProviders,theme,tokens}.ts*` | Chinese Ant Design provider and the single Quiet Trace token source. |
| `apps/web/src/ui/components/` | Quiet Trace BrandMark/icons plus shared page hierarchy, async state, status language, and destructive confirmation. |
| `apps/web/src/layouts/AppShell.tsx` | Grouped desktop sidebar, mobile top/bottom navigation and `更多` Drawer, account/logout, recovery confinement, and footer. |
| `apps/web/src/styles/globals.css` | Minimal Quiet Trace reset, typography/background foundation, focus, and reduced-motion behavior. |
| `apps/web/src/**/*.module.css` | Component/page style boundaries for shell, account, library, upload, administration, forms, and Reader chrome/publication. |
| `apps/web/src/App.tsx` | Existing route contract with page-level lazy imports and accessible route fallback. |
| `apps/web/src/auth/AuthProvider.tsx` | Public config, unified credential/Passkey login, memory token, device hint. |
| `apps/web/src/auth/webauthn.ts` | Browser option conversion and credential serialization. |
| `apps/web/src/auth/ProtectedRoute.tsx` | Authentication/admin/capability checks and recovery-Session confinement. |
| `apps/web/src/pages/LoginPage.tsx` | Compact 漫读 credential/Passkey entry with quiet configurable purpose, privacy, and real-filing disclosure. |
| `apps/web/src/pages/AdminDashboardPage.tsx` | Administrator landing page. |
| `apps/web/src/pages/AdminReadersPage.tsx` | Invited-user master-detail, capability create/reissue, one-time credentials, lifecycle, Devices, Sessions and events. |
| `apps/web/src/pages/AdminSecurityPage.tsx` | Passkey registration/management, recovery upgrade, and admin Sessions. |
| `apps/web/src/pages/AdminSitePage.tsx`, `AdminAuditPage.tsx` | Limited public settings and filtered security events. |
| `apps/web/src/pages/LibraryPage.tsx`, `BookDetailPage.tsx` | Collection discovery plus server-projected creator/capability actions and translation launch. |
| `apps/web/src/features/editions/EditionCard.tsx` | Reader-safe actions plus projected upload/generated mutation and translate/retranslate controls. |
| `apps/web/src/features/translations/`, `pages/TranslationsPage.tsx` | Narrow launch modal and Quiet Trace actor-scoped master-detail workspace with polling and draft publish. |
| `apps/web/src/pages/Series*.tsx`, `UploadPage.tsx` | Readable Series/admin Series mutation plus capability-aware file-backed imports. |
| `apps/web/src/pages/ReaderPage.tsx` | Responsive safe Reader with edge progress, TOC/settings, recoverable quiet chrome, restore, synchronization, conflict, and Edition switch. |
| `apps/web/src/pages/{Devices,Sessions,Profile}Page.tsx` | Viewer-private identity, device, and Session controls. |
| `apps/web/tests/` | Public/auth/RBAC and responsive navigation, filters, master-detail, imports, one-time credentials, confirmations, Reader, and Edition tests. |

## Task routing

| Change | Start with | Then verify |
| --- | --- | --- |
| Credential/device/Session state | auth service + credential repository | auth integration tests, acceptance device contexts |
| Credential capability/reissue | reader service + auth dependency | capability integration/Web tests and direct API denial |
| Passkey/recovery | WebAuthn + admin service + auth routes | virtual-authenticator acceptance and ADR 0012 |
| Reader management/audit/site | matching service/route/admin page | PostgreSQL + Web tests and non-secret contracts |
| Library visibility/contributor policy | access service + repository query | contributor matrix, direct API isolation and browser flow |
| Book/Edition/file/Series mutation | matching domain service | admin regression plus reader-denial tests |
| Reader projection/private state | reader service/repository/route | parser/unit, conflict/integration, browser acceptance |
| Translation Run/private service | translation service/repository + Lingua client | client unit, PostgreSQL Run tests, Web polling and exact cleanup |
| Persistence schema | models plus migration | empty/v0.4 migration and isolated restore tests |
| HTTP contract | schema/serializer/route | `pnpm api:generate`, Web typecheck, integration tests |
| Web layout/component system | design-system skill + provider + AppShell + shared UI | Web tests, production build, bundle report, inherited v0.6 browser acceptance, v0.7 task paths and capture-only browser evidence |
| Deployment/upgrade | settings, Compose overlays, staging scripts | config validation, count preflight, coordinated backup/restore, network/port audit |
| Durable design | current code and consolidated docs | new ADR and decision-index entry |
