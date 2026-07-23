# Project state

Last reviewed against the repository on 2026-07-23. The current milestone is v0.9.0, developed
incrementally from the accepted v0.8.0 authentication-hardening and v0.7.0 Quiet Trace releases.

## Current milestone

漫读 remains a private, non-commercial, self-hosted reading and collection-management site with
one logical administrator and no public registration/catalogue. Invited access is no longer
equivalent to permanently read-only access: every current reader credential has an immutable
`library.read` capability and may optionally carry `library.upload` and/or `translation.use`.
Authorization now requires both the current database-backed credential capability and the
resource's durable creator policy. The unique administrator remains the library owner.

v0.9.0 also integrates standalone LinguaSpindle v0.3.1 for TXT novel translation. Only Novel
Platform Server may call it over private HTTP. The two services share no database, volume,
identity, credential or domain model. LinguaSpindle retains its own Provider secret, SQLite and
Artifact volume; Browser/Web never receives its base URL or Provider configuration.

## Implemented

### Credential capabilities and contributor library

- `reader_credential_capabilities` stores the immutable capability snapshot for each credential.
  `library.read` is mandatory; unknown, duplicate or missing-read sets are rejected. Capability
  changes use reissue, which immediately revokes the old credential, Devices, Sessions and
  Refresh Tokens while retaining the same durable User and attribution.
- Every protected request reloads the credential capability rows. JWT claims, cached Web state,
  role labels and client-submitted fields cannot grant capability. Restricted recovery Sessions
  receive no library or translation authority.
- `books.created_by_user_id`, `book_editions.created_by_user_id`,
  `stored_files.created_by_user_id` and `library_imports.requested_by_user_id` distinguish the
  actual contributor from the single `owner_user_id`. Safe responses expose only contributor
  display names plus server-computed permission flags.
- `library.upload` permits file-backed create/add and management of the actor's own uploaded
  resources. `translation.use` independently permits readable-TXT translation and management of
  the actor's own Runs/generated Editions. Series, raw downloads, generated publication and all
  user/site/security administration remain administrator-only.
- A contributor cannot delete a Book that contains another User's Edition or retained Run. Source,
  supersedes, active Import/Run and current file dependencies remain fail-closed. Deleting a ready
  Edition clears affected preferences/progress and precisely removes only unreferenced files.
- Public metadata-only Book/Edition creation and the two legacy Web Collapse surfaces are removed.
  New content comes only from a validated file import or verified generated Artifact.

### Translation orchestration

- `edition_translation_runs` persists actor, fixed source EditionFile/revision/SHA-256, target,
  non-secret configuration snapshot/fingerprint, deterministic client idempotency, remote
  correlation IDs, status/progress, retry and cleanup state, and an optional generated Edition.
- The narrow `LinguaSpindleClient` validates health, version `>=0.3.1,<0.4.0`, mandatory
  idempotency, `novel_txt_v1`, configured Provider and same-origin fixed endpoints. It disables
  redirects, bounds streaming downloads, verifies format/size/checksum, maps remote errors to
  sanitized stable failures, and never accepts an arbitrary download URL.
- Create/sync/pause/resume/cancel/retry/cleanup are actor-scoped and recoverable. A stable
  `(actor, client_request_id)` prevents duplicate Runs; active equivalent work, Project, Job,
  Artifact and generated Edition IDs are also unique. Cleanup targets only the persisted Project.
- Only a complete verified TXT Artifact is ingested. File compensation plus one database
  transaction prevents partial/corrupt/failed work from creating a readable Edition or orphan.
- Successful output is `draft + ai + generated`, linked to the fixed source and creator. The
  creator may preview the draft, other invited people receive 404, and only the administrator may
  publish `ready`. Retranslation keeps the old Edition, files, preferences and progress intact.
- Translation availability is independent of `/health/ready`; disabled/unavailable/incompatible
  LinguaSpindle disables only translation. Upload, login, library and Reader remain operational.

### Web, API and operations

- Admin reader create/reissue exposes mandatory read plus optional upload/translate choices,
  capability summaries and one-time credential invalidation consequences.
- AppShell routes/navigation and Book/Edition actions use server-projected capabilities and
  permission flags. The Quiet Trace translation workspace provides service status, actor-scoped
  master-detail Runs, controls, source/config snapshots, redacted errors, creator preview and
  administrator publication. It polls only the selected visible active Run with single-flight and
  bounded backoff.
- The launch modal submits only source/target/title plus one stable client UUID; it cannot choose
  Provider, model, profile, service URL or download URL. UI copy discloses private external
  processing and possible Provider cost.
- OpenAPI and generated TypeScript describe the v0.9 capability/contributor/translation contract.
  The product and package/API versions are 0.9.0.
- Alembic `20260723_0006` performs a count-only, fail-closed preflight; deletes fileless placeholder
  Editions/Books and dependent private state/links; backfills creator fields to the unique owner;
  grants retained credentials read only; and creates Run storage. Because cleanup is destructive,
  downgrade is intentionally unsupported—restore the coordinated backup instead.
- `compose.translation.yml` adds only Server to the external `linguaspindle-private` network and
  publishes no port. Protected deployment configuration requires explicit non-secret
  `LINGUASPINDLE_*` values. Provider keys are not Novel Platform configuration.
- Coordinated backup/restore includes capability, attribution and Translation Run data with the
  Novel Platform library while explicitly excluding LinguaSpindle resources. Isolated restore
  verifies revision, database/file checksums, temporary references and v0.9 invariants.

## Verification state

- Focused Server unit/PostgreSQL integration coverage passes for capability snapshots and reissue,
  contributor isolation/deletion, legacy API removal, v0.9 migration, LinguaSpindle HTTP hardening,
  Translation Run idempotency/control/retry/cleanup, atomic ingestion, draft visibility,
  administrator publication, retranslation and corrupt/partial failure handling.
- Web ESLint and production build pass. All 47 Web tests pass, including capability projection,
  launch-payload narrowing, polling/backoff/single-flight, generated Edition controls and
  destructive confirmation. The existing >500 kB main-chunk warning remains non-fatal.
- Headed Chromium visual review passes at 1440 px and 320 px. The 320 px page has no horizontal
  overflow; the mobile More dialog exposes 小说翻译 with accessible names, while translation stays
  outside the high-frequency bottom navigation. Evidence is in `artifacts/visual-v090/`.
- `acceptance:v090` is the current release gate. It preserves applicable v0.5/v0.8 regression,
  adds 11 v0.9 criteria, uses synthetic/fake transport by default, and records real service/
  Provider work as `PENDING_OPERATOR_CONFIG`. Final full-gate evidence is written to
  `artifacts/acceptance-v090.{md,json}`.
- Historical acceptance scripts and evidence remain intact. v0.9 explicitly supersedes fileless
  creation; it does not rewrite old evidence to claim compatibility.

## Deliberately not implemented

- Public registration/catalogue, email/phone/OAuth/password login, a second administrator, public
  publishing/downloads, social/comment/messaging/ranking/payment/advertising features.
- EPUB, manga or arbitrary-document translation; per-chapter review/editor workflows; browser
  Provider configuration; Provider keys in Novel Platform; client-supplied model/profile/URL;
  arbitrary Artifact downloads; Redis, workers, queues or scheduled polling.
- Real OpenAI-compatible Provider configuration/calls and real user-content egress. A real paid
  call requires separate key configuration and explicit authorization for that call.
- Automatic cleanup of unknown LinguaSpindle resources or any ownership of LinguaSpindle SQLite,
  Artifact volume, schema, image, container or network.

## Deployment state

No remote database was reset or migrated, no remote credential was reinitialized, no Compose
network was changed, no LinguaSpindle Provider was configured/called, and no application was
deployed by this implementation. Local work is on `codex/v0.9.0-contributor-translation` and has
not been pushed.

Deployment requires a reviewed candidate SHA, migration-head and sanitized count preflight,
coordinated PostgreSQL+library backup with isolated restore, explicit approval for the destructive
migration/reset target, private network and v0.3.1 checks, capability identity matrix, synthetic
Mock short-TXT translation, exact cleanup, persistence/restart checks and before/after topology
comparison. Real HTTPS/Passkey and real Provider verification remain deployment/operator work.

## Update triggers

Update this file when milestone scope, capability, omissions, verification or deployment state
changes. Put durable rationale in ADRs and module navigation in `docs/MODULE_MAP.md`.
