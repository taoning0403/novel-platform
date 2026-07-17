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
| `docs/PROJECT_STATE.md` | Current v0.8.0 capability, verification, omissions, and deployment state. |
| `docs/architecture.md`, `docs/data-model.md` | Boundaries, flows, relationships, and invariants. |
| `docs/DECISIONS.md`, `docs/adr/0012-*` through `0016-*` | Current authentication, shared-library, Web component-foundation, Quiet Trace UI/UX, and proxy/refresh-hardening decisions. |
| `compose.yaml` | Isolated local PostgreSQL, migration, API, library volume, and Web topology. |
| `compose.staging.yml`, `.env.staging.example` | HTTPS/WebAuthn single-host contract: host TLS edge with loopback-only Compose Web ingress, single-trusted-peer real client IP restoration, and auth entry rate limiting. |
| `scripts/acceptance-v080.mjs` | Current release gate: 84 inherited v0.5 criteria plus 9 proxy-chain/auth-hardening criteria (106-114), entry-limit and real-IP evidence, and explicit DEPLOYMENT_PENDING items. |
| `scripts/acceptance-v080.chain.yml`, `acceptance-v080-edge.conf` | Isolated two-hop chain (simulated host edge → staging Nginx → API) with fixed test addresses used only by the v0.8.0 gate. |
| `scripts/acceptance-v070.mjs` | Historical 105-criterion v0.7 gate retained with its evidence. |
| `scripts/acceptance-v060.mjs` | Historical 100-criterion v0.6 compatibility gate retained with its evidence. |
| `scripts/acceptance-v050.mjs` | Parameterized v0.5 core retained as historical evidence and replayed by current gates. |
| `scripts/acceptance-v010..v040.mjs` | Historical gates retained for evidence; password/ownership assertions are superseded. |
| `scripts/report-web-bundle.mjs` | Current production chunk inventory, route-scope comparison, accepted baseline sizes, and unchanged 200 kB entry gzip budget. |
| `scripts/deploy-staging.sh` | Backup, Alembic, explicit auth conversion, volume audit, and safe service start. |
| `scripts/backup-library.sh`, `restore-library.sh` | Coordinated database/library backup and isolated restore verification. |
| `scripts/acceptance-staging-persistence.sh` | Sanitized table/fingerprint persistence across service/database/Compose recreation. |
| `scripts/{report-staging-resources,scan-staging-artifacts,generate-staging-deployment-report}.sh` | v0.5 resource, leak, and deployment evidence without credentials or host paths. |
| `docs/staging-deployment.md` | HTTPS setup, v0.4 data/auth upgrade, v0.6-to-v0.7 application upgrade, CLI, recovery, backup, restore, and rollback runbook. |

## Server (`apps/server`)

| Path | Responsibility |
| --- | --- |
| `src/novel_platform/config.py` | Independent secrets, Cookies (SameSite=Strict enforced for staging/production, independent device-Cookie lifetime), WebAuthn RP/origins, CORS/proxy, OpenAPI, limits. |
| `src/novel_platform/main.py` | FastAPI/OpenAPI construction, middleware, routing, and noindex policy. |
| `src/novel_platform/cli.py` | Administrator, migration, integrity-audit, and retention-cleanup CLI. |
| `api/dependencies/auth.py` | Database-backed User/credential/device/Session/Passkey checks and recovery restriction. |
| `api/routes/auth.py` | Unified credential login, Passkey registration/authentication, device-bound refresh with fail-closed Origin, logout, Sessions. |
| `api/errors/handlers.py` | Stable error contract; clears the Refresh Cookie only for 401 refresh outcomes. |
| `api/routes/readers.py`, `site.py`, `audit.py` | Administrator reader/credential, site-setting, and audit adapters. |
| `api/routes/users.py`, `devices.py` | Self display-name and self device management; no password or user-creation routes. |
| `api/routes/books.py`, `editions.py`, `series.py` | Admin mutation and authenticated readable queries. |
| `api/routes/imports.py`, `files.py` | Admin-only imports/raw downloads and protected readable cover delivery. |
| `api/routes/reader.py`, `preferences.py` | Safe publication projection and viewer-private reading state. |
| `api/schemas.py`, `api/serializers.py`, `api/errors/` | Strict non-secret contracts, reader projections, and stable errors. |
| `application/access.py` | Separates site library owner from the authenticated viewer. |
| `application/auth/security.py` | Domain-separated HMACs, high-entropy credentials/device secrets, JWT and refresh tokens. |
| `application/auth/service.py` | Credential/device/Session login, throttle, device-bound rotation/replay, state revalidation. |
| `application/auth/webauthn_service.py` | UV/resident Passkeys, origin/RP/single-use challenge validation, and bounded expired-challenge cleanup on issuance. |
| `application/auth/admin_service.py` | CLI-only initialization, recovery/reset, Session revocation, lock/unlock/status. |
| `application/auth/migration_service.py` | Read-only preflight, explicit conversion, and database-volume integrity audit. |
| `application/auth/audit_service.py` | Filtered reads and retention-based manual cleanup. |
| `application/readers/service.py` | Persistent reader identity and one-current-credential lifecycle. |
| `application/site/service.py` | Limited public/site-security settings and change audit. |
| `application/books/`, `editions/`, `series/` | Manageable/readable library orchestration. |
| `application/library/` | Admin-only EPUB/TXT inspect/commit/revision and safe storage lifecycle. |
| `application/reader/` | Safe EPUB/TXT projection, protected resources, progress/settings/recent state. |
| `infrastructure/repositories/credentials.py` | Credential, Passkey, challenge, and device-secret lookups/counting plus set-based bounded challenge deletion. |
| `infrastructure/repositories/{books,editions,series,reader}.py` | Explicit owner and viewer query boundaries. |
| `infrastructure/database/models.py` | Identity, credential, device, Session, site, audit, library, and reader mappings. |
| `infrastructure/storage/local.py` | Random-key private local storage with checksum and bounded-path enforcement. |
| `migrations/versions/20260715_0005_private_reading_access.py` | v0.5.0 authentication/site schema. |
| `tests/integration/test_auth_and_isolation.py` | Credential state, device concurrency, recovery/reset/lock, and private isolation. |
| `tests/integration/test_auth_hardening.py` | Device-bound refresh, uniform failure, replay revocation, fail-closed Origin, and device-Cookie renewal. |
| `tests/integration/test_challenge_cleanup.py` | Bounded expired-challenge deletion, valid-row preservation, and concurrent single-use verification. |
| `tests/unit/test_auth_cookies.py` | Device-Cookie issuance, renewal, and independent lifetime. |
| `tests/integration/test_api_workflow.py` | Shared library visibility and direct API RBAC. |
| `tests/integration/test_migrations.py` | Empty/v0.4 upgrades, explicit mapping, preservation, and volume audit. |

## Web and shared client

| Path | Responsibility |
| --- | --- |
| `packages/api-client/openapi.json`, `src/schema.d.ts` | Generated FastAPI contract and TypeScript schema. |
| `apps/web/nginx.staging.conf`, `apps/web/nginx/staging-*.conf`, `apps/web/Dockerfile.staging` | Staging proxy: single-trusted-peer realip restoration, auth entry rate limits with stable JSON 429, and shared upstream-header snippets (no per-location proxy drift). |
| `apps/web/src/api/{types,client}.ts` | Generated aliases, in-memory access token, refresh, and v0.5 API calls. |
| `apps/web/src/ui/{AppProviders,theme,tokens}.ts*` | Chinese Ant Design provider and the single Quiet Trace token source. |
| `apps/web/src/ui/components/` | Quiet Trace BrandMark/icons plus shared page hierarchy, async state, status language, and destructive confirmation. |
| `apps/web/src/layouts/AppShell.tsx` | Grouped desktop sidebar, mobile top/bottom navigation and `更多` Drawer, account/logout, recovery confinement, and footer. |
| `apps/web/src/styles/globals.css` | Minimal Quiet Trace reset, typography/background foundation, focus, and reduced-motion behavior. |
| `apps/web/src/**/*.module.css` | Component/page style boundaries for shell, account, library, upload, administration, forms, and Reader chrome/publication. |
| `apps/web/src/App.tsx` | Existing route contract with page-level lazy imports and accessible route fallback. |
| `apps/web/src/auth/AuthProvider.tsx` | Public config, unified credential/Passkey login, memory token, device hint. |
| `apps/web/src/auth/webauthn.ts` | Browser option conversion and credential serialization. |
| `apps/web/src/auth/ProtectedRoute.tsx` | Authentication/admin checks and recovery-Session confinement. |
| `apps/web/src/pages/LoginPage.tsx` | Compact 漫读 credential/Passkey entry with quiet configurable purpose, privacy, and real-filing disclosure. |
| `apps/web/src/pages/AdminDashboardPage.tsx` | Administrator landing page. |
| `apps/web/src/pages/AdminReadersPage.tsx` | Reader master-detail, one-time credentials, lifecycle, devices, Sessions, and per-reader events. |
| `apps/web/src/pages/AdminSecurityPage.tsx` | Passkey registration/management, recovery upgrade, and admin Sessions. |
| `apps/web/src/pages/AdminSitePage.tsx`, `AdminAuditPage.tsx` | Limited public settings and filtered security events. |
| `apps/web/src/pages/LibraryPage.tsx`, `BookDetailPage.tsx` | Continue-reading, visible search, filter Drawer/chips, cover-led collection, and role-aware management controls. |
| `apps/web/src/features/editions/EditionCard.tsx` | Reader-safe read/preference actions and admin-only raw/mutation actions. |
| `apps/web/src/pages/Series*.tsx`, `UploadPage.tsx` | Readable Series plus admin-only mutations/imports. |
| `apps/web/src/pages/ReaderPage.tsx` | Responsive safe Reader with edge progress, TOC/settings, recoverable quiet chrome, restore, synchronization, conflict, and Edition switch. |
| `apps/web/src/pages/{Devices,Sessions,Profile}Page.tsx` | Viewer-private identity, device, and Session controls. |
| `apps/web/tests/` | Public/auth/RBAC and responsive navigation, filters, master-detail, imports, one-time credentials, confirmations, Reader, and Edition tests. |

## Task routing

| Change | Start with | Then verify |
| --- | --- | --- |
| Credential/device/Session state | auth service + credential repository | auth integration tests, acceptance device contexts |
| Passkey/recovery | WebAuthn + admin service + auth routes | virtual-authenticator acceptance and ADR 0012 |
| Reader management/audit/site | matching service/route/admin page | PostgreSQL + Web tests and non-secret contracts |
| Library visibility/RBAC | access service + repository query | direct API isolation tests and reader browser flow |
| Book/Edition/file/Series mutation | matching domain service | admin regression plus reader-denial tests |
| Reader projection/private state | reader service/repository/route | parser/unit, conflict/integration, browser acceptance |
| Persistence schema | models plus migration | empty/v0.4 migration and isolated restore tests |
| HTTP contract | schema/serializer/route | `pnpm api:generate`, Web typecheck, integration tests |
| Web layout/component system | design-system skill + provider + AppShell + shared UI | Web tests, production build, bundle report, inherited v0.6 browser acceptance, v0.7 task paths and capture-only browser evidence |
| Deployment/upgrade | settings, Compose, staging scripts | config validation, backup, preflight/convert/audit, restore |
| Durable design | current code and consolidated docs | new ADR and decision-index entry |
