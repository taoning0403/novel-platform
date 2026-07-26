# Project state

Last reviewed against the repository and staging deployment on 2026-07-26. v0.10.0 is deployed
from Novel Platform commit `b8c84c92eb7e2af367ec3bc4d58b97a84635e736` with LinguaSpindle
commit `1eeb5b029703c941c2fb4052d79e72767142cd19`. Package/API metadata, the final
release gate and the staging runtime all report v0.10.0.

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

The current source branch contains an unversioned post-v0.10 Provider-routing increment governed
by ADR 0020. It keeps package/API metadata at v0.10.0 while adding OpenAI, DeepSeek, Kimi and
operator-allowlisted custom configurations plus a default-off thinking switch. Candidate and
deployment evidence use a distinct Provider-routing tag so archived v0.10 evidence remains
unchanged.

## Implemented v0.10 surface

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

## Implemented post-v0.10 Provider-routing increment

- One current immutable credential version now binds Provider kind, optional custom name, exact
  normalized base URL, model and thinking state. New ciphertext uses `aes-256-gcm-v2` authenticated
  data that binds those routing fields; legacy v1 ciphertext retains its original upstream/model
  behavior with thinking forced off.
- OpenAI, DeepSeek and Kimi use fixed official base URLs. Custom OpenAI-compatible routes require
  an exact operator allow-list match both when saved and at Relay call time; redirects remain
  disabled. The legacy upstream setting is not reused for new v2 OpenAI credentials.
- Thinking defaults off. DeepSeek enables it only through exact `deepseek-reasoner` equivalence;
  Kimi injects an explicit enabled/disabled field only for `kimi-k2.5`; OpenAI, custom and
  unsupported Kimi models cannot enable the generic switch.
- The personal credential page configures Provider/model/custom metadata and exposes only
  non-secret status. Translation launch and task detail show the bound Provider/model/thinking
  snapshot without allowing per-Run switching.
- Alembic `20260726_0008` adds the routing/thinking columns, one current version and one monotonic
  per-User version sequence. Backup manifests declare the custom-route allow-list as an external
  configuration dependency, and isolated restore verifies the 0008 constraints and invariants.

## Verification state

- Archived outputs are `artifacts/acceptance-v0100.{md,json}`. The v0.10 gate passed on commit
  `b8c84c9`,
  replaying 84 core, 9 proxy-hardening and 11 v0.9 criteria before passing all 6 v0.10
  BYOK/Relay criteria.
- Server lint, formatting, strict typing, 86 unit tests and 29 PostgreSQL integration tests passed.
  Web lint, 52 tests and production build passed. LinguaSpindle passed 252 tests plus lint,
  formatting, strict typing, package and schema-migration checks.
- The offline full chain from Novel Platform through real LinguaSpindle v0.3.2 and the private
  Relay to a fake Provider passed with sanitized usage persistence. Staging secret injection,
  private DNS, authenticated no-upstream probing, HTTPS, restart/recreate persistence, topology,
  coordinated backup and isolated restore checks also passed.
- A real OpenAI-compatible Provider remains outside the verification boundary: no reader key,
  paid request or user-content egress was used.
- Historical acceptance scripts/evidence remain intact. v0.10 does not rewrite v0.9 evidence to
  claim that operator-funded/shared-key translation remains supported.
- The Provider-routing increment passes Server lint/format/type checks, 101 unit tests and 31
  PostgreSQL integration tests plus Web lint, 56 tests, production build, generated-contract
  refresh, Compose validation and script syntax checks. Its exact-commit
  `acceptance-v0100-provider-routing*` gate and external 0008 deployment verification remain
  pending until the candidate is committed.

## Deliberately not implemented

- Public registration/catalogue, email/phone/OAuth/password login, a second administrator, public
  publishing/downloads, social/comment/messaging/ranking/payment/advertising features.
- EPUB, manga or arbitrary-document translation; per-chapter review/editor workflows;
  per-Run Provider/model/profile/URL selection; arbitrary or unallowlisted custom destinations;
  browser-direct Provider calls; arbitrary Artifact downloads; Redis, workers, queues or scheduled
  polling.
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

Staging at `https://novel.mine-novel.top` deployed Novel Platform v0.10.0 commit `b8c84c9` on
2026-07-26T10:18:43Z. Alembic migrated transactionally from `20260715_0005` through
`20260723_0006` to `20260726_0007`. LinguaSpindle v0.3.2 runs at schema 5. The archived v0.8
release, pre-migration backup and protected old configuration remain available; no Alembic
downgrade was performed or enabled.

The post-v0.10 Provider-routing increment and Alembic `20260726_0008` are not yet deployed.
Staging remains on the clean revision-0007 baseline while the exact candidate commit, coordinated
backup/isolated restore and external verification are prepared.

The deployment created a revision-0007 coordinated backup
`novel-platform-v0100-20260726T100151Z` and passed its isolated database/library restore. It also
passed API, PostgreSQL, Compose stop/start and application-recreate persistence checks. The
sanitized deployment evidence is `deployment-v0100-report.md` in the protected staging report
directory.

Runtime inspection confirms:

- Server joins proxy, database and `linguaspindle-private`; Relay joins only database and
  `linguaspindle-private`; LinguaSpindle joins only `linguaspindle-private`; Web and PostgreSQL do
  not join translation.
- Only Web publishes `127.0.0.1:8080`; PostgreSQL, Server, Relay and LinguaSpindle publish no host
  port.
- Server and Relay share the protected vault key; only Relay and LinguaSpindle share the
  independent service Bearer. HMAC challenges proved runtime/host equality without printing the
  values.
- Current secret values were absent from deployment logs, reports, image configuration and image
  history. The authenticated absent-scope probe stopped at Relay's expected sanitized 404 and did
  not contact the fixed upstream.
- Existing 2 Users, 1 Book and 1 Edition remain. Provider credential versions, usage records,
  Translation Runs and LinguaSpindle Projects/Jobs are all empty.

No Provider key has been submitted and no real Provider request has been made. Real translation
requires a `translation.use` actor to configure a personal key; paid/content-egress verification
remains explicitly pending.

## Update triggers

Update this file when milestone scope, capability, omissions, verification or deployment state
changes. Put durable rationale in ADRs and module navigation in `docs/MODULE_MAP.md`.
