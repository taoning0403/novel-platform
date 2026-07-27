# Project state

Last reviewed against the repository and staging deployment on 2026-07-27. Staging runs the
unversioned post-v0.10 Provider-routing increment from Novel Platform commit
`93675b9198e99e9078baafd32cb6800af18cdd82` with LinguaSpindle commit
`1eeb5b029703c941c2fb4052d79e72767142cd19`. Package/API metadata remains v0.10.0 and
the staging database is at Alembic `20260726_0008`.

## Current milestone

漫读 remains a private, non-commercial, self-hosted reading and collection-management site with
one logical administrator and no public registration/catalogue. Every invited credential has
immutable `library.read` and may also carry `library.upload` and/or `translation.use`.
Authorization requires the current database-backed capability plus durable resource-creator
policy; the administrator remains the unique library owner.

v0.10.0 changes who supplies and pays for real translation. Each translating actor owns
versioned encrypted OpenAI-compatible Provider credentials in Novel Platform. A Run binds one
exact version and sends only its opaque UUID4 scope to standalone LinguaSpindle
`>=0.3.2,<0.4.0`. LinguaSpindle calls a separate private Relay, which validates the service,
scope, Job, model and fixed upstream before decrypting that actor's key. There is no administrator
or shared-key fallback.

The deployed post-v0.10 Provider-routing increment is governed by ADR 0020. It keeps package/API
metadata at v0.10.0 while adding OpenAI, DeepSeek, Kimi and operator-allowlisted custom
configurations plus a default-off thinking switch.

The current source branch adds the unversioned EPUB-translation increment governed by ADR 0021.
It extends the same private scoped execution from TXT to common valid, unencrypted EPUB 2/3,
using LinguaSpindle's native structure-preserving Pipeline and Alembic `20260727_0009`. This
increment has not been deployed; staging remains at the Provider-routing baseline and database
revision `20260726_0008`.

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
- The personal credential page loads the selected Provider's live `/models` catalogue with the
  write-only key through POST `/api/v1/me/provider-credential/models`, requires a model selection
  from that transient list, and maintains no product-selected model default. It exposes only
  non-secret saved status. Translation launch and task detail show the bound
  Provider/model/thinking snapshot without allowing per-Run switching.
- Alembic `20260726_0008` adds the routing/thinking columns, one current version and one monotonic
  per-User version sequence. Backup manifests declare the custom-route allow-list as an external
  configuration dependency, and isolated restore verifies the 0008 constraints and invariants.

## Implemented EPUB-translation increment

- A readable `ready` source Edition with a current EPUB or TXT file can launch a Run. Translation
  availability is queried for that exact format, and the Run snapshot fixes the format, Pipeline
  key/version, EditionFile revision and SHA-256.
- The private client maps TXT to `novel_txt_v1` / `novel_export_txt` and EPUB to
  `novel_epub_v1` / `novel_export_epub`. EPUB keeps its original filename and
  `application/epub+zip` media type through Project upload.
- Successful EPUB output must be the single format-matching Artifact for the exact Project/Job,
  pass bounded download and SHA-256 checks, reopen through Novel Platform's EPUB safety inspector,
  and declare the Run target language. It creates one EPUB StoredFile and no normalized TXT.
- EPUB uses the same reader-owned credential version, opaque LinguaSpindle scope, private Relay,
  idempotency/control/cleanup, creator-previewed draft and administrator-only publication rules as
  TXT. Partial, corrupt, ambiguous or locally invalid output creates no Edition.
- Alembic `20260727_0009` permits only `epub | txt` Run sources, preserves existing TXT rows and
  refuses downgrade while EPUB Run history exists.
- The Web launch modal requests format-specific capability and explains structure-preserving EPUB
  output; the task workspace shows the fixed format, Pipeline and output contract.

## Implemented Scheme C Web interaction refresh

- The authenticated Web shell now uses the approved Scheme C compact white sidebar, unified blue
  reading-trace mark and smaller page-heading hierarchy. Mobile keeps the existing top bar,
  bottom navigation and overflow drawer.
- Library browsing is cover-led with a compact recent-reading strip, search/filter toolbar,
  five-column desktop grid and two-column mobile layout. Book detail uses a cover-led hero and
  compact Edition cards; edit, upload, replace, translate, download and destructive actions move
  into contextual menus, Drawers and explicit confirmation dialogs without changing permission
  checks.
- Upload uses one focused work surface beside a vertical five-step rail, with operation cards,
  local drag-and-drop and metadata confirmation shown only after safe inspection. Translation
  tasks are grouped into active and completed/attention-needed lists, while source snapshots,
  Provider bindings and task controls remain available in a detail Drawer.
- This refresh changes only React/CSS/test code under `apps/web`; Server behavior, API contracts,
  persistence, authentication, authorization and Reader publication chrome are unchanged.

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
- The Provider-routing increment passes Server lint/format/type checks, 111 unit tests and 32
  PostgreSQL integration tests plus Web lint, 59 tests, production build, generated-contract
  refresh, Compose validation and script syntax checks. The exact-commit
  `acceptance-v0100-provider-routing*` gate passed on `e91a41a` with all 6 criteria and 5 steps,
  including the inherited v0.8/v0.9 regressions.
- The source-only EPUB increment passes Server Ruff format/check, strict mypy, 112 unit tests and
  all 34 PostgreSQL integration tests; Web lint, all 60 tests and the production build; repeatable
  OpenAPI generation; translation Compose parsing; and deployment/restore script syntax checks.
  LinguaSpindle passes Ruff, strict mypy across 43 targets, compileall, dependency/Compose checks
  and all 253 tests. Its scoped EPUB regression uses a fake HTTP Provider, produces a re-openable
  target-language EPUB and proves scope/Job headers plus public/log/Artifact containment.
- The initial EPUB candidate `pnpm acceptance` advanced an empty database through Alembic
  `20260727_0009`, then stopped in the inherited v0.5 browser replay because its broad historical
  language locator matched two operation radios and the language textbox. The locator now targets
  the exact language textbox without changing the scenario or criterion; a complete candidate
  rerun is still required before any new full acceptance PASS, real-container LinguaSpindle chain
  or deployment is claimed.
- External verification on `e91a41a` passed revision-0008 deployment, HTTPS/API/container health,
  migration and library integrity audit, restart/stop-start/recreate persistence, topology and
  secret-agreement checks, sanitized resource reporting, artifact leak scanning, coordinated
  backup and isolated database/library restore.
- The Scheme C Web refresh passes Web lint, all 59 tests and the production build. The initial
  entry chunk remains within the 200 kB gzip budget at 198.26 kB. Mock-API visual checks at
  1440x900 and 390x844 cover Library, Book detail, Upload and Translations with no horizontal
  overflow.

## Deliberately not implemented

- Public registration/catalogue, email/phone/OAuth/password login, a second administrator, public
  publishing/downloads, social/comment/messaging/ranking/payment/advertising features.
- Manga or arbitrary-document translation; EPUB chapter selection or review/editor workflows;
  per-Run Provider/model/profile/URL selection; arbitrary or unallowlisted custom destinations;
  browser-direct Provider calls; arbitrary Artifact downloads; Redis, workers, queues or scheduled
  polling.
- Administrator/shared/site-funded Provider fallback, software quota billed to an administrator
  key, price/currency estimation, or a LinguaSpindle User/tenant/quota model.
- Vault-master-key rotation/re-encryption automation. Ordinary reader-key rotation creates a new
  credential version and does not rotate the vault key.
- Real OpenAI-compatible Provider calls or real user-content egress. No paid Provider call has
  been executed for this deployment; it requires a reader-supplied key and separate explicit
  authorization.
- Automatic cleanup of unknown LinguaSpindle resources or ownership of its SQLite, Artifact
  volume, image, container or external network.

## Deployment state

Staging at `https://novel.mine-novel.top` runs the post-v0.10 Provider-routing increment at exact
commit `93675b9198e99e9078baafd32cb6800af18cdd82`, deployed on 2026-07-26 at
15:48:57Z. This revision includes the Scheme C Web interaction refresh. The database remains at
Alembic `20260726_0008`; LinguaSpindle v0.3.2 remains at schema 5. No Alembic
downgrade was performed or enabled.

The source-only EPUB increment and Alembic `20260727_0009` are not deployed.

The protected pre-routing environment backup is
`.env.staging.pre-provider-routing-20260726T131839Z` with mode 0600. The migration preparation
backup `novel-platform-v0100-20260726T131906Z` passed isolated restore, and the initial routing
deployment created `novel-platform-v0100-20260726T132053Z`. The final `e91a41a` update created
`novel-platform-v0100-20260726T133652Z`; after all restart and external checks, the coordinated
backup `novel-platform-v0100-20260726T133950Z` passed a fresh isolated database/library restore.
The Scheme C Web deployment created the coordinated backup
`novel-platform-v0100-20260726T154811Z`; no database revision change was required.

The deployed custom-route allow-list is empty. OpenAI, DeepSeek and Kimi preset routes are
available, while custom Provider destinations fail closed until the operator adds an exact
reviewed HTTPS base URL.

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
- The Scheme C deployment script and post-deploy healthcheck passed. External checks returned
  HTTPS 200, HTTP-to-HTTPS 308 and `{"status":"ok"}` from API readiness; Web, Server, Relay and
  PostgreSQL are healthy, with only Web published on loopback `127.0.0.1:8080`.

No Provider key has been submitted and no real Provider request has been made. Real translation
requires a `translation.use` actor to configure a personal key; paid/content-egress verification
remains explicitly pending.

## Update triggers

Update this file when milestone scope, capability, omissions, verification or deployment state
changes. Put durable rationale in ADRs and module navigation in `docs/MODULE_MAP.md`.
