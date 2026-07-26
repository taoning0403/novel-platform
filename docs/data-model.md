# Data model

```text
SiteSettings ── library owner ──> User(admin)
User
├── ReaderAccessCredential ──> ReaderCredentialCapability
│                            └── Device ──> AuthSession ──> RefreshToken
├── AdminRecoveryCredential ─────────────> AuthSession
├── AdminPasskey ────────────────────────> AuthSession
├── WebAuthnChallenge
├── ProviderCredentialVersion ──> ProviderUsageRecord
├── ReaderSettings
├── ReadingProgress ──> BookEdition
└── UserBookPreference ──> Book / BookEdition

User(admin, library owner) + User(actual creator)
├── Book ──> BookEdition ──> EditionFile ──> StoredFile
│              └── EditionTranslationRun
│                    ├── exact ProviderCredentialVersion
│                    └── optional generated BookEdition
├── BookSeries ──> SeriesMembership ──> Book
└── LibraryImport ──> StoredFile

AuthAuditEvent ── optional references to User / Credential / Device / Session / Passkey
```

## Site and persistent identity

`site_settings` is a singleton row (`id = 1`). It stores public site name, purpose and privacy
statements, optional real ICP number/link, default reader device limit, audit retention days,
the unique library-owner User, administrator lock time, and authentication-migration completion
time. Cookie, JWT, WebAuthn, CORS, proxy, database, and upload-limit configuration remains in the
server environment.

`users` remains the persistent identity anchor so historical progress and preference foreign keys
do not need rebuilding. Product roles are `admin` and `reader`; the PostgreSQL enum keeps the
historical value `member` internally for readers. A v0.4 username can remain as an internal
migration/audit identifier, but it is not accepted by an authentication route and is not exposed
in ordinary API responses. `password_hash` is nullable and conversion clears every legacy hash.

Exactly one logical administrator is selected in `site_settings.library_owner_user_id`. Multiple
Passkeys provide administrator device/recovery redundancy; a second administrator User cannot be
created through the application.

## Reader credential and device chain

`reader_access_credentials` separates a durable invited identity from a rotatable secret. It
stores only a domain-separated HMAC, a safe hint, lifecycle status (`active`, `suspended`, or
`revoked`), expiry, `allow_new_devices`, positive `max_devices`, use/lifecycle timestamps,
administrator attribution, and an optional replacement link. A partial unique index permits at
most one non-revoked current credential per reader while retaining revoked history.

```text
reader User 1 ── * credential history
                    └── at most 1 current non-revoked credential
```

The effective state is revoked, suspended, expired, or active in that order. Revocation is final.
Suspension and expiry revoke Sessions but preserve authorized Devices. Reissue revokes the old
credential, all its Devices and Sessions, then creates a new credential for the same User.

`reader_credential_capabilities` is keyed by `(credential_id, capability)` and permits exactly
`library.read`, `library.upload`, or `translation.use`. Every credential must include
`library.read`; create/reissue rejects missing-read, unknown or duplicate input. Rows are an
immutable issuance snapshot. Capability is not stored on User and is not trusted from JWT. The
foreign key cascades only with credential history deletion; normal reissue retains revoked
credential/capability history.

`devices` stores an HttpOnly device-secret HMAC plus the credential that authorized a reader
device. The browser `client_instance_id`, name, platform, app version, IP fields, and User-Agent
summary are descriptive only. Device identity is proven by the server-issued secret, never by IP
or the client hint. Revoked rows are retained and never silently reactivated; a later login may
create a new row if capacity allows.

`auth_sessions` binds User + Device to exactly one authentication basis:

- reader access credential;
- administrator Passkey; or
- administrator recovery credential with `recovery_mode=true`.

Every protected request reloads the User, Device, Session, and authentication basis. The Session
expiry for a reader is capped by credential expiry. `refresh_tokens` stores only HMACs, rotation,
replacement, use, expiry, and revocation state; replay revokes the owning Session.

## Administrator Passkeys and recovery

`admin_passkeys` stores WebAuthn credential ID, public key, signature counter, display name,
transports, device/back-up metadata, timestamps, and revocation time. Private-key material never
reaches the server. Normal operation must retain at least one active Passkey.

`webauthn_challenges` stores a one-time random challenge, purpose, User, expected Origin, RP ID,
expiry, and use time. Verification requires the same User, purpose, Origin, RP, unexpired unused
row, and user verification. A challenge becomes used before cryptographic verification is
committed, preventing replay even after an invalid response.

`admin_recovery_credentials` stores only a domain-separated HMAC and safe hint, purpose
(`initialize`, `recovery`, or `credential_reset`), expiry, use, revocation, and creation time. The
CLI displays a new raw value once. Login consumes it and creates a restricted recovery Session;
successful Passkey registration revokes old administrator Sessions and creates a normal Session.

## Login throttles and audit

`login_throttles` contains only keyed hashes for client-IP and submitted-credential dimensions,
failure window/count, and block expiry. It does not store a submitted credential or a combined
raw IP/credential value.

`auth_audit_events` records event/outcome, optional actor/subject/credential/device/Session/
Passkey IDs, bounded IP and User-Agent summary, non-secret JSON metadata, and time. Raw access or
recovery credentials, WebAuthn challenges, access/refresh tokens, Cookies, authorization headers,
database/storage paths, hashes used as login secrets, and book content are forbidden. Rows older
than the configured retention period are removed only by the explicit cleanup CLI, which records
its own summary event.

## Shared content ownership and readable visibility

Every `books`, `book_series`, `stored_files`, `library_imports`, and `edition_translation_runs`
row keeps a non-null owner FK. All site library owners equal the unique administrator. Creator
attribution is separate and non-null:

| Table | Actor field | Meaning |
| --- | --- | --- |
| `books` | `created_by_user_id` | User whose first file import created the Book |
| `book_editions` | `created_by_user_id` | User who uploaded or generated the Edition |
| `stored_files` | `created_by_user_id` | User whose operation introduced the object |
| `library_imports` | `requested_by_user_id` | User who owns the inspect/commit workflow |
| `edition_translation_runs` | `created_by_user_id` | User who requested translation/retranslation |

This preserves one library containment boundary without claiming the administrator performed
every contribution. Credential rotation does not change attribution. API projections expose only
a safe display-name summary and computed permissions, never these IDs to another invited person.

A reader-visible Book has at least one `ready` BookEdition with a current EditionFile. A visible
Series contains only visible Books and is omitted when empty. Readers never receive owner IDs,
storage keys, filesystem paths, file hashes, incomplete imports, or raw download URLs.

## BookEdition and file revisions

`book_editions` preserves independent-version semantics:

```text
Book 1 ── * BookEdition
               ├── optional source_edition_id (same Book, source role)
               └── optional supersedes_edition_id (same Book, not itself)
```

A historical translation may remain valid without a source. New generated v0.9 translations keep
the fixed source link and optional valid same-Book supersedes link. Edition identity, Book, role,
translation origin, creation method, revision, relationships, status and metadata remain stable.

`stored_files` holds owner and creator, random storage key, original filename,
media/format/purpose, size, SHA-256, and time. `edition_files` is append-only by
`(edition_id, revision)` with one current revision. Replacement creates a new EditionFile and
preserves BookEdition identity and historical file rows. Cover/thumbnail references remain
protected StoredFiles.

`library_imports` records bounded inspect/commit state, actor and temporary references. Admin sees
all; a current uploader sees only their own row; other actors receive 404. It is never included in
reader projections.

## Provider credentials and usage

`provider_credential_versions` retains immutable OpenAI-compatible credential versions for one
User. `(user_id, version)` is unique and a partial unique index permits at most one current
non-retired/non-revoked version across OpenAI, DeepSeek, Kimi and custom Provider kinds. Each row
stores:

- random UUID used as the opaque integration scope;
- owner User, Provider kind, optional custom display name, normalized base URL, model,
  `thinking_enabled` defaulting to false, and positive per-User version;
- `aes-256-gcm-v2` for new rows, a 12-byte random nonce and authenticated ciphertext; and
- creation, retirement and revocation times.

The AES key is environment-only. v2 authenticated data binds User, credential UUID, version,
Provider kind/name, base URL, model and thinking state, so moving ciphertext or changing its
routing metadata fails decryption. Existing `aes-256-gcm-v1` OpenAI-compatible rows retain their
original fixed-upstream/model behavior, force thinking off and are not re-encrypted by migration.
No raw key, suffix, plaintext hash or upstream authorization value has a column. Rotation,
switching Provider or changing thinking state retires the prior current row and creates another;
removal revokes all non-revoked history. Retired ciphertext remains usable only through an
eligible Run that already references it. Revocation is final.

Preset routes are Server-normalized. A custom base URL must exactly match the deployment
allow-list when saved and again when used by the Relay; staging/production custom routes use
HTTPS. Thinking is false by default: DeepSeek requires exact equivalence with
`deepseek-reasoner`; Kimi permits true only for `kimi-k2.5` and then receives an explicit
enabled/disabled request field; OpenAI and custom routes cannot enable the generic switch. The
non-secret self-status projection may return Provider kind/name, base URL, model, thinking state,
version and lifecycle time but never the credential scope or encrypted fields.

`provider_usage_records` contains one sanitized successful Relay call record: credential version,
bounded model name, optional LinguaSpindle Job correlation, nonnegative prompt/completion/total
token counts and time. It contains no User-supplied prompt, translated output, Provider response,
key, scope header or price estimate. User totals are derived by joining through the credential
owner; current-month totals use UTC month boundaries.

## Translation Runs

`edition_translation_runs` is durable orchestration state, not a queue or LinguaSpindle mirror.
It stores:

- library owner, actor, Book, fixed source Edition + EditionFile + revision + SHA-256 + `txt`;
- exact non-null Provider credential-version foreign key;
- target language, requested title, optional same-Book generated Edition to supersede;
- non-secret configuration fingerprint/snapshot (service/pipeline/provider/profile/model IDs,
  bound Provider routing/thinking metadata and safe credential version number);
- actor-scoped `client_request_id` and remote Project/Job/Artifact/request IDs;
- local/remote status, progress, sanitized error, retry, cleanup and timestamps;
- optional generated Edition ID (`ON DELETE SET NULL`) so Run history survives Edition deletion.

`(created_by_user_id, client_request_id)` is unique. The configuration fingerprint includes the
credential UUID even though API snapshots expose only its version. A partial unique index prevents
an equivalent active source-file/target/configuration/credential Run; remote
Project/Job/Artifact and generated Edition IDs are unique when present. Status and cleanup values
use checked strings so service changes do not silently expand the local state machine.
A second partial unique index permits only one `preparing` Run with no remote Job ID per credential
version. This makes the Relay's first authenticated Job-ID claim unambiguous; after that atomic
bootstrap, every Provider call must match the persisted Job correlation.

The source snapshot never follows a later file replacement. Only a verified successful Artifact
can create one `draft + ai + generated` Edition and file relation. That Edition's creator is the
Run actor; its owner remains the site owner. Creator/admin may see the draft; only admin changes it
to `ready`. Partial/failed/corrupt output leaves `generated_edition_id` null.

## Private reading state

`user_book_preferences` is unique by `(user_id, book_id)` and stores optional preferred and
last-opened Edition IDs. Both must belong to the same readable Book for a reader. Changing a
preferred Edition never replaces, archives, or deletes another Edition.

`reader_settings` is one row per User and stores bounded font size, line height, content width,
font family, and theme. It is created lazily.

`reading_progresses` is unique by `(user_id, edition_id)` and stores reading status, stable
section/block location, section/overall percentages, Edition-file revision, optimistic version,
last writing Device, and timestamps. Writes lock the row and require `expected_version`; a stale
write receives 409 plus the current row. Two readers and the administrator therefore have
independent state over the same Edition.

## Series

`book_series` is administrator-owned. `series_memberships.book_id` is the primary key, so a Book
belongs to at most one Series; `(series_id, position)` provides stable append order. Deleting a
Series removes memberships only. Reader queries filter members through Book readability and hide
an empty result.

## v0.5, v0.9 and v0.10 migrations

Migration `20260715_0005` adds the site/credential/Passkey/challenge schema and expands
User/Device/Session/audit rows without deleting content or private reading state. The separate
conversion command requires an explicit target when administrators or content owners are
ambiguous, consolidates all content-owner FKs, maps every non-target administrator explicitly to
a reader, clears password hashes, and revokes all legacy Devices, Sessions, and Refresh Tokens.
It never generates reader plaintext credentials.

After conversion, `auth migration audit` compares database permanent-file references and SHA-256
values with the library volume, checks referenced temporary files, and reports counts only—never
storage keys or paths.

Migration `20260723_0006` requires either a pristine database or a completed, unambiguous v0.5
conversion. Its count-only preflight rejects owner mismatch, active imports, missing/mismatched
file references and invalid current-file cardinality. It deletes Edition rows with no EditionFile,
clears their preferences/progress/source/supersedes references, and deletes Books left without an
Edition. It then backfills all creator fields to the unique owner, inserts only `library.read` for
every retained credential, and creates Translation Run storage. Notices/reporting contain counts,
not titles, filenames, paths, IDs or content. Destructive cleanup makes downgrade unsupported;
restore the matching coordinated PostgreSQL + library backup.

Migration `20260726_0007` creates encrypted credential-version and usage storage and makes every
new Translation Run bind one credential version. A historical v0.9 Run has no truthful payer/key
version; the migration therefore fails closed if any Run exists instead of deleting it or
fabricating attribution. The operator must retain the pre-upgrade backup, explicitly clean/reset
those orchestration rows under the approved deployment procedure, and rerun. A direct
v0.8-to-v0.10 upgrade first creates an empty Run table in `0006`, so `0007` is non-destructive for
that path.
