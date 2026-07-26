# Project state

Last reviewed against the repository on 2026-07-26. The current target is the v0.10.0 release
candidate, developed incrementally from the v0.9.0 capability, contributor and private-translation
baseline. Package/API metadata targets 0.10.0; final release-gate and external deployment evidence
remain pending consolidation.

## Current milestone

漫读 remains a private, non-commercial, self-hosted reading and collection-management site with
one logical administrator and no public registration/catalogue. Every invited credential has
immutable `library.read` and may also carry `library.upload` and/or `translation.use`.
Authorization requires the current database-backed capability plus durable resource-creator
policy; the administrator remains the unique library owner.

v0.10.0 changes who supplies and pays for real TXT translation. Each translating actor owns
versioned encrypted OpenAI-compatible Provider credentials in Novel Platform. A Run binds one
exact version and sends only its opaque UUID4 scope to standalone LinguaSpindle
`>=0.3.2,<0.4.0`. LinguaSpindle calls a separate private Relay, which validates the service,
scope, Job, model and fixed upstream before decrypting that actor's key. There is no administrator
or shared-key fallback.

## Implemented candidate surface

### Capability, contributor and translation baseline

- `reader_credential_capabilities` stores immutable capability snapshots. Every protected request
  reloads the current credential and capability rows; restricted recovery Sessions have no
  library or translation authority.
- Books, Editions, StoredFiles, imports and Translation Runs retain the unique administrator
  owner while recording their actual creator/requester. Upload and translation contributors may
  manage only their own permitted resources; Series, raw downloads, publication and
  site/security administration remain administrator-only.
- Translation Runs retain the fixed source file/revision/checksum, actor, target, configuration,
  deterministic idempotency, remote Project/Job/Artifact IDs, control/recovery state and optional
  generated Edition. Only a verified complete TXT Artifact can become a creator-previewed draft;
  only the administrator may publish it.
- Main readiness does not depend on LinguaSpindle or the Relay. Translation failure or disabled
  configuration must leave login, upload, library and Reader available.

### Encrypted reader-owned Provider credentials

- `provider_credential_versions` stores immutable per-User `openai_compatible` versions encrypted
  with AES-256-GCM. Each row has a random nonce; authenticated data binds User, credential UUID,
  Provider and version. The API never returns a key, suffix, hint, hash, ciphertext, nonce or
  credential scope.
- `PROVIDER_CREDENTIAL_MASTER_KEY` is strict Base64 decoding to exactly 32 bytes. It is injected
  into Server and Relay, never stored in PostgreSQL, an image, source control, logs, reports or
  coordinated backups.
- A `translation.use` actor can inspect non-secret status/usage, PUT a new key, rotate to a new
  version, or DELETE all usable versions under `/api/v1/me/provider-credential`. Rotation retires
  the previous version; already-bound Runs may keep using it. Removal revokes every version and
  causes later calls for affected Runs to fail closed.
- Translation launch requires both current `translation.use` and a current personal credential.
  Missing, revoked, undecryptable or mismatched credentials never fall back to an administrator
  key. Feature-disabled status remains a distinct translation-availability outcome.
- `provider_usage_records` stores only successful Relay request time, credential version, bounded
  model, optional LinguaSpindle Job correlation and nonnegative integer prompt/completion/total
  tokens. Monthly/all-time totals are Provider-reported usage, not prices or billing estimates;
  prompts, translations and raw Provider responses are absent.

### Opaque scoped execution and private Relay

- Every new `edition_translation_runs` row has a non-null
  `provider_credential_version_id`. The credential UUID enters Novel Platform configuration
  fingerprinting and LinguaSpindle request/execution fingerprinting, preventing work funded by
  different versions from coalescing.
- LinguaSpindle v0.3.2 privately persists only the opaque scope needed for restart/retry. Scoped
  OpenAI-compatible execution sends the fixed credential-scope and Job-ID headers to the Relay;
  the scope remains absent from Novel Platform public Run snapshots and LinguaSpindle public
  responses, logs, errors and Artifacts.
- The dedicated Relay accepts only the fixed Chat Completions path, a constant-time-checked
  service Bearer, canonical scope, required LinguaSpindle Job ID, an operator-allowlisted model,
  and one fixed HTTPS upstream. It disables redirects, bounds bodies/timeouts, normalizes Provider
  errors, rejects successful responses that reflect the decrypted key, and never logs bodies,
  authorization, scope or decrypted keys. A partial unique Run index plus row lock atomically
  claims the first authenticated Job ID during the creation race; later calls require the exact
  persisted correlation.
- `PROVIDER_RELAY_SERVICE_SECRET` is independent of the vault/authentication secrets and is shared
  only with the Relay and LinguaSpindle. At the upstream boundary the Relay replaces this internal
  Bearer with the decrypted actor key.
- `compose.translation.yml` joins Server to the external `linguaspindle-private` network and runs
  the Relay on exactly the database and translation networks. Relay has no host/proxy port; Web,
  migrate and PostgreSQL do not join the translation network. LinguaSpindle keeps its independent
  SQLite and Artifact volume and gains no User, tenant, permission or quota model.

### Web, API, migration and operations

- The personal Provider-credential page supports configure/rotate/remove, never pre-fills or
  stores the raw key in browser storage, and shows only version/timestamps plus current-month and
  all-time request/Token totals.
- Translation launch and workspace surfaces require a configured personal credential and provide
  no browser choice of Provider URL, model, profile, credential scope or download URL.
- The v0.10 OpenAPI contract adds GET/PUT/DELETE
  `/api/v1/me/provider-credential` and GET `/api/v1/me/provider-credential/usage`; private
  credential/scope/Relay fields are not public schema.
- Alembic `20260726_0007` creates encrypted version and usage storage and makes every Translation
  Run bind one version. Existing v0.9 Runs have no truthful payer/key assignment, so migration
  fails with `v0100_preflight_unscoped_translation_runs` if any exist. It neither deletes them nor
  fabricates attribution; the operator must back up and explicitly remove/archive test Runs or
  reset/restore the exact disposable environment before retrying.
- Coordinated backups now include credential ciphertext, metadata and usage with the Novel
  Platform database/library, while excluding the master key, Relay service secret, LinguaSpindle
  SQLite/Artifacts/containers/networks and upstream keys. A usable credential restore requires
  the separately protected matching master key; losing it is intentionally unrecoverable.

## Verification state

- `scripts/acceptance-v0100.mjs` is the current release-candidate gate, selected by
  `pnpm acceptance` and `pnpm acceptance:v0100`. It replays the applicable v0.9 gate into
  `artifacts/acceptance-v0100-regression*` without rewriting historical evidence, then evaluates
  six v0.10 BYOK/Relay/Web/version/topology criteria.
- Candidate outputs are `artifacts/acceptance-v0100.{md,json}`. Synthetic/fake transport is the
  repository test boundary. Real LinguaSpindle v0.3.2 + Mock Provider, secret injection, private
  container chain, HTTPS/Passkey and restart/topology checks remain operator/deployment work.
- The final v0.10 full-gate result has not yet been recorded in this file. Do not interpret
  focused test reports or package metadata as a completed release or deployment.
- Historical acceptance scripts/evidence remain intact. v0.10 does not rewrite v0.9 evidence to
  claim that operator-funded/shared-key translation remains supported.

## Deliberately not implemented

- Public registration/catalogue, email/phone/OAuth/password login, a second administrator, public
  publishing/downloads, social/comment/messaging/ranking/payment/advertising features.
- EPUB, manga or arbitrary-document translation; per-chapter review/editor workflows;
  client-supplied Provider/model/profile/URL; browser-direct Provider calls; arbitrary Artifact
  downloads; Redis, workers, queues or scheduled polling.
- Administrator/shared/site-funded Provider fallback, software quota billed to an administrator
  key, price/currency estimation, or a LinguaSpindle User/tenant/quota model.
- Vault-master-key rotation/re-encryption automation. Ordinary reader-key rotation creates a new
  credential version and does not rotate the vault key.
- Real OpenAI-compatible Provider calls or real user-content egress. No paid Provider call has
  been executed for this candidate; it requires a reader-supplied key and separate explicit
  authorization.
- Automatic cleanup of unknown LinguaSpindle resources or ownership of its SQLite, Artifact
  volume, image, container or external network.

## Deployment state

No v0.10.0 deployment, migration 0007 application, Provider-key submission or real paid Provider
call is asserted by this document. Deployment remains candidate work until the exact reviewed
commits, backups, isolated restores, secret injection, migration, topology and post-deploy checks
are recorded by the root task.

Before migration, stop writers and create a coordinated PostgreSQL + library backup, then pass an
isolated restore. Preserve the matching vault master key separately. A v0.9 database with any
Translation Run must stop at the fail-closed 0007 preflight until the operator explicitly resolves
those unscoped test Runs. Deploy LinguaSpindle `>=0.3.2,<0.4.0`, share the Relay Bearer only with
LinguaSpindle/Relay, point LinguaSpindle's OpenAI-compatible base URL to the private Relay `/v1`,
and keep the model in the Relay allowlist. Verify Relay/LinguaSpindle have no host ports, Relay
joins only database + translation networks, and Web/PostgreSQL/migrate do not join translation.

Deployment verification may use synthetic or offline Mock content. Real Provider verification
must remain explicitly pending unless a reader key and paid/content-egress authorization are
provided.

## Update triggers

Update this file when milestone scope, capability, omissions, verification or deployment state
changes. Put durable rationale in ADRs and module navigation in `docs/MODULE_MAP.md`.
