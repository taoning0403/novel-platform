# Project state

Last reviewed against the repository on 2026-07-17. The current milestone is v0.8.0, developed
incrementally from the accepted v0.7.0 Quiet Trace Web release and the v0.5.0 authentication,
ownership, and private-library release.

## Current milestone

v0.8.0 is 漫读, a private, non-commercial digital reading and collection-management site. One
logical administrator owns and manages the shared collection. A small number of invited readers
can read only published, file-backed Editions while retaining private progress, settings,
preferred Editions, devices, and sessions. There is no public registration, public catalogue,
username or password login, social surface, sales flow, advertising, or reader upload path.

This milestone is authentication hardening (ADR 0016). It restores the real client IP across the
two-hop staging proxy chain from a single trusted host-edge peer, adds Nginx entry rate limiting
for the two unauthenticated authentication endpoints, deletes expired WebAuthn challenges in
bounded batches, binds refresh rotation to the Session's device secret, requires an allowlisted
Origin for cookie-mode refresh, and enforces SameSite=Strict authentication Cookies outside
development. It changes no persistent entity, migration, permission, or library contract.

## Implemented

- A single `/login` accepts high-entropy reader access credentials and one-time administrator
  initialization/recovery credentials. Administrator daily authentication uses resident,
  user-verified Passkeys.
- Reader identity, rotatable access credential, server-authorized device, session, and refresh
  token are separate persistent concepts. Raw credentials appear only in one successful response;
  the database stores domain-separated HMACs and safe hints.
- Device authorization uses an HttpOnly device-secret Cookie. `client_instance_id` is only a hint;
  IP and User-Agent are audit attributes, not device identity. Credential rows are locked while a
  new device is counted, so concurrent requests cannot exceed `max_devices`.
- The staging Compose Nginx restores the real client IP with the realip module, trusting only the
  measured host-edge bridge peer (build-time default `172.30.19.1`; the build accepts only a
  single canonical IPv4 address and fails closed otherwise) and resolving `X-Forwarded-For`
  recursively. Untrusted peers cannot inject a forged source, and Uvicorn keeps trusting only the
  fixed Nginx peer.
- Nginx entry rate limiting covers `POST /api/v1/auth/login` and
  `POST /api/v1/auth/passkeys/authentication/options`, keyed on the restored client address.
  Excess requests receive a stable JSON `auth_entry_rate_limited` 429 with `Retry-After` and
  `no-store` and never reach the application, so they write no throttle or audit rows.
- Refresh is bound to the Session's device secret. The application verifies the presented secret
  against the Session's Device before any rotation or replay-revocation side effect: a stolen
  Refresh Token alone can neither rotate nor revoke the victim Session, while replay with the
  correct device secret still revokes the entire Session. Binding failures use the uniform
  invalid-token 401 and are audited.
- Cookie-mode refresh requires a present, allowlisted `Origin`. Staging and production require
  `SameSite=Strict` authentication Cookies. The device Cookie has an independent configurable
  lifetime (`AUTH_DEVICE_COOKIE_TTL_DAYS`, default 365 days), is re-issued when a login reuses an
  authorized Device, and is cleared only on 401 refresh outcomes.
- Expired WebAuthn challenges are deleted on issuance in set-based batches (default 500) driven by
  the existing `expires_at` index; valid challenges are untouched and verification remains
  single-use under concurrency.
- Credential expiry, suspension, revocation, reissue, device revocation, Session revocation,
  Passkey revocation, administrator lock, and credential reset take effect before an old JWT
  naturally expires because every protected request reloads current database state.
- Recovery credentials are single-use and short-lived. Their Session is restricted to Passkey
  registration; completing recovery revokes old administrator Sessions and creates a normal
  Passkey-backed Session.
- Explicit `manageable` and `readable` boundaries preserve the administrator as Book, Edition,
  StoredFile, LibraryImport, and Series owner. Readers see only Books with at least one `ready`,
  current-file-backed Edition and only visible Books inside Series.
- Readers use the safe EPUB/TXT Reader Projection and protected covers/resources, but the backend
  rejects raw file downloads, imports, uploads, and Book/Edition/Series mutations. They may write
  only their own reading progress, settings, preferences, device names, and revocations.
- The public page exposes configurable site name, purpose, privacy statement, unified login, and
  only a real configured ICP record. Production can disable OpenAPI and all non-health responses
  receive `noindex, nofollow, noarchive`.
- The administrator UI manages invited readers, one-time credential issuance, credential state,
  devices, Sessions, Passkeys, the limited public site settings, and filtered security events.
- The server CLI provides administrator initialization/recovery/reset/lock/status, all-Session
  revocation, migration preflight/conversion, database-volume integrity audit, and audit cleanup.
- Migration `20260715_0005` adds site settings, reader credentials, administrator recovery
  credentials, Passkeys, WebAuthn challenges, and expanded device/Session/audit links. Explicit
  conversion preserves BookEdition IDs, file revisions, source/supersedes links, Series,
  preferences, settings, and progress while consolidating content ownership and invalidating the
  old password/session system.
- Complete backups include every authentication and site table plus the coordinated library
  archive. Isolated restore validates revision, database-referenced permanent checksums, and
  referenced temporary files before any live restore can be authorized.
- The Web application uses one Chinese-localized Ant Design 6 provider and a centralized Quiet
  Trace token layer: graphite text, cool canvas, white paper, index blue, semantic teal/coral, and
  a compact three-line reading-trace mark. The formal product name is 漫读.
- Login is a single centered task surface. `AppShell` owns grouped desktop navigation, a mobile
  top bar and bottom quick navigation with a More Drawer, account/logout controls,
  recovery-Session confinement, and the version footer. Reader routes retain a separate
  full-screen shell.
- Shared `PageHeader`, `AsyncPanel`, `StatusTag`, and `DestructiveAction` components centralize
  page hierarchy, accessible async state, status language, and consequence-specific confirmation.
- All page routes use `React.lazy` and an accessible `Suspense` fallback. CSS Modules now separate
  layout, account, library, upload, administration, forms, and Reader styles; the former
  2,252-line global stylesheet has been removed.
- Upload still uses the existing inspect-preview-commit API state machine. Ant Design Dragger
  only selects a local File and never starts its own request.
- The library prioritizes recent reading and cover-led discovery, with search, sorting, a filter
  Drawer, and removable active filters. Reader administration uses task-focused master-detail
  presentation while preserving one-time credential and destructive-action safeguards.
- Reader keeps its safe projection, dedicated typography, three themes, synchronization, and
  conflict choices while adopting a progress trace, compact table-of-contents rail, and
  auto-hiding responsive controls.

## Verification state

- The pre-open-source v0.4.0 baseline gate passed: 65 Python unit tests, 14 PostgreSQL
  integration tests, 28 Web tests, Chromium reader/series acceptance, restart persistence,
  backup/restore, and leak scans.
- The v0.8.0 directed checks pass: Ruff, Ruff format, mypy, 67 Python unit tests, 20 PostgreSQL
  integration tests, ESLint, 37 Web tests, TypeScript, and the Vite production build. New
  integration coverage proves device-bound refresh (uniform 401, no attacker-triggered revocation,
  replay-with-secret still revokes), fail-closed cookie Origin, device-Cookie renewal, and bounded
  challenge cleanup with concurrent single-use verification.
- `acceptance:v050` passes all 84 criteria with real Chromium virtual WebAuthn, four independent
  reader browser contexts, direct RBAC checks, credential/admin recovery controls, restart
  persistence, coordinated backup, isolated database/volume restore, and leak scanning. The
  sanitized evidence is `artifacts/acceptance-v050.{md,json}`.
- `acceptance:v070` passes all 105 criteria: the 84 inherited v0.5.0 criteria and 21 UI criteria
  comprising the 16 retained v0.6.0 checks plus five Quiet Trace task-path checks. It records 30
  sanitized, capture-only desktop/mobile screenshots in `artifacts/visual-v070/` and reports to
  `artifacts/acceptance-v070.{md,json}`.
- `acceptance:v080` replays the 84 v0.5.0 criteria unmodified and adds 9 hardening criteria
  (106-114): real client IP across a simulated host-edge → staging Nginx → API chain, forged
  `X-Forwarded-For` rejection, untrusted-peer confinement, login and Passkey-options entry rate
  limits with stable 429 JSON/`Retry-After`/`no-store` and no downstream audit or challenge
  writes, fail-closed refresh Origin, device-secret-bound refresh semantics through the chain, and
  enforced SameSite=Strict cookies. Evidence is `artifacts/acceptance-v080.{md,json}` with the
  inherited core in `artifacts/acceptance-v080-core.json`.
- The v0.7.0 production entry is 595,455 bytes raw / 197,625 bytes gzip and passes the unchanged
  200,000-byte gzip budget. Route chunks are recorded in `artifacts/bundle-v070.{md,json}`.
- `acceptance:v080` is the v0.8.0 release gate and the default `pnpm acceptance` target.
  `acceptance:v050` through `acceptance:v070` remain immutable historical commands; their scripts,
  criteria, and evidence are neither weakened, skipped, nor rewritten by this milestone.
- Local acceptance never changes real staging or production data. Real-domain HTTPS/RP-ID checks
  remain deployment actions and must be reported as `DEPLOYMENT_PENDING` until explicitly run.

## Deliberately not implemented

- Public registration, email/phone/OAuth login, usernames as credentials, passwords, Web Setup
  Token, or a second administrator identity.
- Highlights, annotations, bookmarks, comments, forums, messaging, sharing, ranking, payments,
  advertising, public publishing, or a download centre.
- Reader upload, raw EPUB/TXT download, metadata editing, deletion, archiving, or publication.
- LLM calls, provider credentials, Redis, workers, queues, scheduled jobs, or external analytics.
- Tauri or other native applications, object storage, public file URLs, Series nesting, or
  automatic Series inference/reordering.
- Sliding session renewal, out-of-band security-event notification, and a production kill switch
  for body-delivery Refresh Tokens remain deferred decisions (ADR 0016 scope), not gaps.

## Deployment state

The repository supplies HTTPS/WebAuthn configuration and guarded v0.4.0-to-v0.5.0 upgrade,
backup, isolated restore, and rollback instructions. v0.8.0 adds no database migration, API
contract, permission, topology, or data-conversion change; application rollback to the accepted
v0.7.0 build requires no Alembic downgrade or database restore. The single-host staging contract
reserves public 80/443 for host Caddy/Nginx and binds the Compose Web proxy only to
`127.0.0.1:8080`. v0.8.0 tightens the staging environment: the configuration validator now
requires `SameSite=Strict` authentication Cookies in staging/production, and the Compose Web image
build accepts `STAGING_REAL_IP_PEER` (default `172.30.19.1`) plus `AUTH_DEVICE_COOKIE_TTL_DAYS`
(default 365). Real host-edge client-IP restoration, real-domain Passkey ceremonies, and
production rate-limit thresholds remain `DEPLOYMENT_PENDING` until verified under explicit
deployment authorization. No real server was deployed or migrated by this milestone implementation.

## Update triggers

Update this file when milestone scope, capability, omission, verification, or deployment state
changes. Put durable rationale in ADRs and module navigation in `docs/MODULE_MAP.md`.
