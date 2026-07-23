# 漫读 (novel-platform)

**English** · [简体中文](README.zh-CN.md)

漫读 v0.9.0 (`novel-platform`) is a private, self-hosted digital reading and
collection-management site designed for a personal, non-commercial deployment. One administrator
owns a shared EPUB/TXT collection. A small number of invited people can read published Editions;
selected credentials may also upload file-backed contributions or request TXT novel translation.
Each person keeps independent progress, settings, preferences, devices, and Sessions.
The current Web interface is Chinese-localized.

It intentionally has no public registration/catalogue, public raw download, username/password
login, comments, social features, payments, advertising, or public publishing.

The v0.9.0 milestone adds immutable `library.read`, `library.upload`, and `translation.use`
credential capabilities, durable creator attribution and creator-aware deletion rules. Novel
translation is orchestrated by the Server through a separately deployed LinguaSpindle v0.3.1
service on a private network; Provider secrets never enter Novel Platform or the browser. Verified
successful TXT artifacts become creator-owned draft generated Editions, and only the administrator
can publish them.

The current repository version is v0.9.0 and remains pre-1.0 software. Review the
[current project state](docs/PROJECT_STATE.md) and [deployment runbook](docs/staging-deployment.md)
before exposing an installation to the Internet.

## Highlights

- Import EPUB and TXT files through an inspect-preview-commit workflow with append-only file
  revisions and coordinated database/library backups.
- Read through a bounded, sanitized Reader Projection instead of exposing raw source files to
  invited readers.
- Use resident, user-verified Passkeys for administrator login and high-entropy, rotatable,
  one-time-displayed credentials with explicit capability snapshots for invited people.
- Attribute uploaded/generated Books, Editions, files, imports, and Translation Runs to the
  durable User while retaining one administrator-owned library and creator-aware mutation rules.
- Translate readable TXT Editions through Server-only private LinguaSpindle HTTP with persisted,
  idempotent Runs, bounded artifact ingestion, creator draft preview, and administrator publish.
- Bind Sessions to server-authorized Devices, rotate refresh tokens, revalidate authorization on
  every protected request, and retain structured security audit events without raw secrets.
- Keep progress, Reader settings, preferred Editions, Devices, and Sessions private to each
  reader while sharing one administrator-owned collection.
- Run a responsive React/Ant Design Web client with the Quiet Trace design system and a dedicated
  distraction-reduced Reader shell.
- Verify releases through unit, PostgreSQL integration, Web, browser, persistence, backup/restore,
  and leak-scanning acceptance gates.

## Architecture

```text
Browser
  -> same-origin Nginx Web entry
      -> React 18 + TypeScript + Ant Design 6
      -> FastAPI modular monolith
          -> PostgreSQL
          -> private local EPUB/TXT library volume
          -> optional private HTTP -> LinguaSpindle v0.3.1
                                      -> its own SQLite/artifact volume/Provider secret
```

The production boundary contains no public catalogue, public object store, external identity
provider, analytics service, worker, queue, or Redis requirement. See [architecture](docs/architecture.md),
[data model](docs/data-model.md), and the [decision index](docs/DECISIONS.md) for the durable
boundaries.

## Repository layout

| Path | Purpose |
| --- | --- |
| `apps/web` | React/TypeScript single-page application and Web tests |
| `apps/server` | FastAPI application, domain/application layers, migrations, CLI, and tests |
| `packages/api-client` | Generated OpenAPI contract and TypeScript schema |
| `scripts` | Acceptance, backup/restore, deployment, rollback, and evidence tooling |
| `docs` | Current state, architecture, data model, ADRs, and deployment runbook |
| `artifacts` | Sanitized acceptance and bundle evidence for reviewed milestones |

## Requirements

- Docker Engine with Compose v2
- Node.js 18.18+ and pnpm 10.33.2 for local Web checks
- Python 3.12+ and uv 0.8.x for local server checks
- Chromium for the complete acceptance gate

## Local start

Clone the repository and copy the non-secret configuration template:

```bash
git clone https://github.com/taoning0403/novel-platform.git
cd novel-platform
cp .env.example .env
```

Before using anything beyond disposable development, run the following command three separate
times and assign one result to each authentication-secret placeholder in `.env`:

```bash
openssl rand -hex 32
```

Then start the local stack:

```bash
docker compose up --build --detach
```

The development defaults use `http://localhost:3000`, `WEBAUTHN_RP_ID=localhost`, non-Secure
Cookies, and OpenAPI enabled. `compose.yaml` also publishes the Web, API, and PostgreSQL ports to
the host by default. These defaults are for local development only and must not be exposed directly
to the Internet; use the controlled staging configuration and deployment runbook for a public host.

Initialize the only administrator from the server CLI:

```bash
docker compose run --rm --no-deps --entrypoint novel-platform server \
  admin init --display-name '站点管理员'
```

The command prints a single-use, short-lived administrator credential once. Do not redirect it to
a file, paste it into chat, store it in an environment variable, or include it in shell history.
Open `http://localhost:3000/login`, enter the credential, and immediately register the first
Passkey. The recovery Session cannot access the library or administration pages before this step.

Afterward, use “使用安全设备登录” for daily administrator access. Create invited people under
“管理 → 阅读者与凭证”, select upload/translation capabilities as needed, and store the new
credential immediately; each complete value is displayed only once. Capability changes require
reissue and revoke the old credential, Devices, Sessions, and Refresh Tokens immediately.

Stop without deleting PostgreSQL or library data:

```bash
docker compose stop
```

Only an explicit disposable reset removes both named volumes:

```bash
docker compose down --volumes
```

## Authentication model

- Reader identity is durable; credential reissue preserves progress/settings/preferences.
- Every invited credential always includes `library.read`; optional `library.upload` and
  `translation.use` are immutable database-backed snapshots. JWT or UI state is never the
  authorization authority.
- Reader access credentials and administrator recovery credentials contain at least 256 bits of
  randomness. PostgreSQL stores only domain-separated HMACs and safe hints.
- Device authorization uses a server-generated HttpOnly device-secret Cookie. IP and
  `client_instance_id` are not authentication factors.
- Access JWTs live only in browser memory. Refresh tokens rotate through an HttpOnly Cookie and
  are stored as HMACs. Replay revokes the Session.
- Every protected request reloads User, Session, Device, and credential/Passkey state, so expiry,
  suspension, revocation, reset, and emergency lock are immediate.
- Administrator daily authentication uses resident, user-verified WebAuthn Passkeys. Recovery is
  CLI-generated, one-time, and restricted to Passkey registration/reset.

The three server secrets must be random, at least 32 bytes, and mutually distinct:

- `AUTH_JWT_SECRET`: access-JWT signatures;
- `AUTH_HASH_SECRET`: refresh/throttle hashes;
- `AUTH_CREDENTIAL_HASH_SECRET`: reader/recovery/device credential hashes.

Never commit `.env` or expose any secret, credential, token, Cookie, WebAuthn challenge, database
password, storage key/path, or book content in logs or reports.

## Required deployment configuration

Production requires:

- same-origin HTTPS;
- `AUTH_COOKIE_SECURE=true`;
- stable `WEBAUTHN_RP_ID` matching the registrable host;
- an explicit HTTPS JSON list in `WEBAUTHN_ORIGINS`;
- explicit `CORS_ORIGINS` and `TRUSTED_HOSTS`;
- `OPENAPI_ENABLED=false`;
- the three independent secrets above;
- controlled reverse proxying that overwrites forwarding headers.

`compose.staging.yml` publishes only Nginx. API and PostgreSQL stay on private networks. Nginx
restores the real client IP from the single trusted host-edge peer, rate-limits the public
authentication entries, and the Uvicorn process trusts only Nginx's fixed internal address.
When translation is enabled, add `compose.translation.yml`; it joins only `server` to the existing
external `linguaspindle-private` network and adds no host port. Provider keys remain exclusively in
LinguaSpindle. See [the deployment runbook](docs/staging-deployment.md).

## Security

Security-sensitive configuration is fail-closed in staging and production, but the repository is
not a substitute for deployment review or an independent security assessment. Before Internet
exposure, replace every development secret, use same-origin HTTPS, keep PostgreSQL and the API on
private networks, validate the trusted proxy peer, disable production OpenAPI, and test backup and
restore.

Report suspected vulnerabilities privately according to [SECURITY.md](SECURITY.md). Do not include
live credentials, tokens, Cookies, private data, storage paths, or imported book content in a public
Issue.

## Server CLI

Run a command against the configured Compose environment with:

```bash
docker compose run --rm --no-deps --entrypoint novel-platform server COMMAND
```

That one-off form is for local development or a stopped stack. On a running staging stack, the
services use fixed private IP addresses, so starting a second `server` container would collide
with the live Server address. Use the staging runbook's `docker compose ... exec -T server
novel-platform COMMAND` form instead.

Available command groups:

```text
admin init --display-name NAME
admin recovery create
admin credentials reset
admin sessions revoke-all
admin status
admin lock
admin unlock
auth migration preflight
auth migration convert [--target-admin-id UUID] [--map-admin-to-reader UUID ...]
auth migration audit
auth audit cleanup
```

`admin init`, `admin recovery create`, and `admin credentials reset` emit a new raw one-time
credential. Existing Passkeys or credentials are never printed. All other output is deliberately
sanitized and contains no token or storage key/path.

Use `admin lock` for an immediate administrator stop. It revokes administrator Sessions; only the
server CLI can unlock. `admin credentials reset` revokes Passkeys and all administrator Sessions,
then emits a recovery credential for registering a new Passkey.

## Shared library and contributor boundary

The unique administrator remains the explicit owner of Books, Editions, StoredFiles, imports,
Translation Runs, and Series. Resource attribution is separate: every Book, Edition, StoredFile,
Import, and Run records the durable User that created/requested it. Invited people receive a
filtered readable projection:

- only Books with a `ready`, current-file-backed Edition;
- only `ready`, current-file-backed Editions;
- only Series containing visible Books;
- protected covers and safe EPUB/TXT Reader sections/resources.

Read-only credentials may update only their own progress, status, Reader Settings,
preferred/last-opened Edition, device names, and Session/device revocations. `library.upload`
permits file-backed create/add plus management of that User's own uploaded resources;
`translation.use` independently permits readable-TXT translation and management of that User's
own Runs/generated Editions. Neither grants Series, raw download, publish, reader/site/audit, or
Passkey administration. A Book creator cannot delete a Book containing another User's
contribution. Backend checks capability and resource creator; hiding buttons is not security.

The accepted v0.4 Reader, file-revision, Edition-identity, source/supersedes, progress-conflict,
and Series invariants remain unchanged.

## Public page and indexing

The anonymous page reads only `/api/v1/site` and shows site name, non-commercial purpose, privacy
text, unified login, and an optional real ICP record. An empty ICP number renders nothing. No
catalogue metadata is embedded in the SPA build or requested anonymously.

FastAPI applies `X-Robots-Tag: noindex, nofollow, noarchive` to non-health responses. Nginx applies
the same policy to HTML/static responses. This complements authentication; it is not access
control.

## v0.8.0 to v0.9.0 capability and translation upgrade

v0.9.0 adds Alembic `20260723_0006`. It deletes fileless placeholder Editions and Books, clears
their dependent preferences/progress/links, backfills retained content attribution to the unique
library owner, grants existing invited credentials only `library.read`, and creates Translation
Run storage. The migration refuses an incomplete v0.5 conversion, ambiguous owner, active Import,
or inconsistent file references. It has no downgrade; rollback restores the matching coordinated
PostgreSQL + library backup.

Before migration, record sanitized counts, stop writers, create `scripts/backup-library.sh` output,
and pass `scripts/restore-library.sh --test`. Actual server migration or a disposable reset requires
explicit approval for the exact target. Never delete/rebuild LinguaSpindle SQLite, artifact volume,
container, or network. After the database upgrade, configure the non-secret `LINGUASPINDLE_*`
values, verify v0.3.1/private DNS/no host port/mandatory idempotency, and add
`compose.translation.yml` only to the Server deployment when translation is ready.

## v0.7.0 to v0.8.0 security upgrade

v0.8.0 adds authentication and trusted-proxy hardening without a database migration or a change to
the accepted API, role, library, file-revision, or Reader-state contracts. Staging and production
must use `AUTH_COOKIE_SAMESITE=strict`; the staging Web image must be built with the measured single
host-edge peer in `STAGING_REAL_IP_PEER`, and operators may configure the independent device-Cookie
lifetime through `AUTH_DEVICE_COOKIE_TTL_DAYS`.

Deploy through the guarded workflow in the [staging runbook](docs/staging-deployment.md) and verify
the real HTTPS proxy chain, Passkey ceremony, authentication entry limits, and Cookie attributes.
Application rollback to the accepted v0.7.0 build needs no Alembic downgrade or database/library
restore.

## v0.6.0 to v0.7.0 application upgrade

v0.7.0 changes the Web design system, interaction layout, static assets, and application version
only. It adds no API, database, authentication, authorization, permission, or deployment-topology
migration. Deploy the reviewed v0.7.0 application image through the existing workflow and verify
the real HTTPS login, role navigation, library filtering, reader administration, Upload, Reader,
noindex, and health surfaces.

Application rollback is to redeploy the accepted v0.6.0 commit or image. Do not run Alembic
downgrade or restore PostgreSQL/library data solely for this application rollback.

## v0.5.0 to v0.6.0 historical application upgrade

v0.6.0 changes the Web component foundation and application static bundle without adding an API,
database, authentication, or deployment-topology migration. Deploy the reviewed v0.6.0
application image through the existing workflow and verify the real HTTPS login, role
navigation, Upload, Reader, administration, noindex, and health surfaces.

Application rollback is to redeploy the accepted v0.5.0 commit or image. Do not run Alembic
downgrade or restore PostgreSQL/library data solely for this UI rollback.

## v0.4.0 to v0.5.0 upgrade

Do not run Alembic against live data without a coordinated PostgreSQL + library backup and a
successful isolated restore test.

1. Stop Web/API writers and create `scripts/backup-library.sh` output.
2. Run the isolated `scripts/restore-library.sh --test BACKUP_DIRECTORY` check.
3. Upgrade schema to Alembic `20260715_0005`.
4. Run `auth migration preflight`.
5. If administrators or content owners are ambiguous, choose `--target-admin-id` and explicitly
   pass every non-target administrator through `--map-admin-to-reader`. Conversion refuses to
   guess.
6. Run `auth migration convert ...`; this consolidates content ownership, preserves content and
   reading IDs/state, clears legacy password hashes, and revokes legacy Devices, Sessions, and
   Refresh Tokens. It never creates reader plaintext credentials.
7. Run `auth migration audit` against the mounted library volume.
8. Rotate the old JWT, refresh-hash, and new credential-hash secrets independently; do not record
   values in a report.
9. Generate administrator recovery with the CLI, register a Passkey, then reissue reader
   credentials one identity at a time.

For a fresh database, skip conversion: `admin init` completes initialization and emits the only
raw initialization credential.

## Backup, restore, and rollback

Create a coordinated backup on the configured host:

```bash
./scripts/backup-library.sh
```

It briefly stops writers, produces a PostgreSQL custom dump plus library archive and manifest,
and rejects mismatched database/file references before publishing the backup directory. The dump
includes credentials and capability rows, Passkeys, devices, Sessions, site settings, audit rows,
Books, Editions, contributor attribution, Translation Runs, file revisions, Series, preferences,
settings, and progress. The manifest explicitly excludes LinguaSpindle data and resources.

Always restore-test into isolated resources first:

```bash
./scripts/restore-library.sh --test \
  /srv/novel-platform/data/backups/novel-platform-v090-TIMESTAMP
```

The test verifies manifest hashes, Alembic revision, permanent file checksums, temporary
references, capability/attribution/Translation Run tables, then removes only the temporary
database and volume. An
intentional live restore additionally requires `ALLOW_STAGING_RESTORE=1`, `--staging`, and exact
database-name confirmation. It never runs an automatic Alembic downgrade.

Rollback means stopping writers and restoring matching code + database + volume from the same
verified pre-upgrade backup. A failed migration/conversion/integrity audit must leave the public
application stopped.

## Development checks

Install locked dependencies:

```bash
pnpm install --frozen-lockfile
cd apps/server && uv sync --frozen && cd ../..
```

Web and generated contract:

```bash
pnpm api:generate
pnpm api:check
pnpm lint
pnpm test
pnpm build
pnpm bundle:report
```

Server:

```bash
cd apps/server
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest tests/unit
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost/ISOLATED_TEST_DB \
  uv run pytest tests/integration
```

Integration tests require PostgreSQL and never use SQLite or live data.

## Automated acceptance

The v0.9.0 release gate uses unique, disposable Compose projects and an isolated PostgreSQL
database. It replays applicable authentication/Reader/proxy behavior, then exercises the current
capability, contributor, migration, translation, Web, backup and leak contracts:

```bash
pnpm acceptance
# equivalent
pnpm acceptance:v090
```

The gate preserves the 84 applicable v0.5 core criteria and 9 v0.8 proxy/auth-hardening criteria,
then adds 11 v0.9 criteria: capability lifecycle, four-identity actor/resource policy, legacy API
removal and migration, private-service idempotency/control/atomic ingestion, retranslation and
draft publication, service isolation, leak resistance, coordinated backup/restore, desktop/320 px
visual evidence, and exact cleanup. Synthetic fake transport is mandatory. Real v0.3.1 + Mock
Provider and real OpenAI-compatible Provider remain `PENDING_OPERATOR_CONFIG` until configured;
the gate never presents fake/Mock output as a real AI translation.

Sanitized outputs are `artifacts/acceptance-v090.{md,json}`, inherited replay evidence is written
under `artifacts/acceptance-v090-regression*`, and visual evidence is under
`artifacts/visual-v090/`. Remote migration, network changes, HTTPS/Passkey, Provider, persistence,
and cleanup checks remain `DEPLOYMENT_PENDING` until separately authorized. Set
`KEEP_ACCEPTANCE_ENV=1` only when preserving a failed isolated environment for local diagnosis.

Historical gates `acceptance:v010` through `acceptance:v080` remain directly runnable with their
historical evidence and contracts. v0.9 does not rewrite them to claim fileless creation remains
supported.

## Superseded acceptance

v0.5.0 intentionally supersedes historical assertions that depended on:

- username/password or Web Setup Token authentication;
- administrator password changes/resets;
- Web creation of local username/password Users;
- each ordinary member owning and uploading to an isolated personal library;
- ordinary members downloading raw source files or mutating content.

v0.9.0 additionally supersedes public metadata-only Book/Edition creation and any assertion that
an invited credential can never write. New content must be file-backed or verified generated
output, and invited writes require both a current capability and creator-aware resource policy.

Those behaviors are not retained as compatibility backdoors. Still-valid BookEdition, file
revision, safe Reader, private-state, Series, persistence, backup/restore, and leak assertions are
replayed in the current gate.

## API groups

All API endpoints use `/api/v1`:

- `/site`: safe public site configuration;
- `/auth`: credential/Passkey login, registration, refresh, identity, logout, and Sessions;
- `/devices`, `/users/me`: viewer-private controls;
- `/admin/readers`, `/admin/site`, `/admin/audit`: administrator-only management;
- `/books`, nested `/editions`, `/series`: readable queries plus capability/creator-aware library
  mutations (Series remains administrator-only);
- `/imports`: administrator or `library.upload` inspect/commit/revision operations, actor-isolated;
- nested `/translation-runs` and `/translations`: actor-scoped TXT translation creation, listing,
  controls, synchronization, draft preview, and administrator publication;
- `/editions/{id}/file`: administrator-only raw download;
- protected Book cover endpoints and `/editions/{id}/reader/*`: safe readable assets;
- `/books/{id}/preferences`, `/reader/settings`, `/reader/recent`: viewer-private state;
- `/health`: minimal process/database probes.

See [architecture](docs/architecture.md), [data model](docs/data-model.md), and the
[decision index](docs/DECISIONS.md) for durable boundaries.

## Contributing

Issues and pull requests are welcome. Keep changes within the documented product and security
boundaries, add focused tests, and run the checks that cover the changed surface. Durable changes
to authentication, authorization, storage, deployment, or data invariants should include an ADR.

Use public Issues for ordinary bugs and proposals. Use the private process in
[SECURITY.md](SECURITY.md) for vulnerabilities.

## AIGC disclosure

This project was developed with assistance from the following large language models:

- OpenAI GPT-5.6;
- Moonshot AI Kimi K3.

The models assisted with code generation, review, documentation, and design discussion. Every
accepted model output was reviewed and selected by the human maintainer, who remains responsible
for the project's design, licensing, security decisions, and released artifacts. Listing these
models discloses tool use; it does not grant authorship or ownership to a model or imply endorsement
by a model provider.

## License and notices

The project source code is licensed under the [Apache License 2.0](LICENSE). The description
"non-commercial" refers to the current product scope and included features; it is not an additional
restriction on the rights granted by the Apache License 2.0.

Third-party components retain their own licenses. See [NOTICE](NOTICE) for the Psycopg 3
LGPL-3.0-only declaration. The project license does not grant rights to EPUB/TXT files, cover art,
metadata, or other content imported by an operator; operators are responsible for having the rights
to use that content.

Maintainer contact: [alnemark0403@gmail.com](mailto:alnemark0403@gmail.com).
