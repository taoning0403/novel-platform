# v0.8.0 single-host deployment

This runbook describes a private single-host deployment, the guarded v0.4.0-to-v0.5.0 data/auth
upgrade, the historical application-only v0.5.0-to-v0.6.0 foundation and v0.6.0-to-v0.7.0 Quiet
Trace upgrades, and the current v0.7.0-to-v0.8.0 authentication-hardening upgrade. It is not a
production, high-availability, disaster-recovery, or filing-approval claim. No real server is
changed by repository acceptance.

## Required HTTPS topology

```text
Internet TCP :80/:443
        |
        v
Host Caddy/Nginx (certificate, HTTP-to-HTTPS redirect)
        |
        v
127.0.0.1:8080 -> Compose Nginx Web/proxy :8080
                         |
                         v
                   FastAPI/Uvicorn :8000 (private fixed proxy network)
                         ├── PostgreSQL :5432 (private database network)
                         └── /data/library (private mode-700 bind mount)
```

The external edge may be a host Nginx/Caddy instance, load balancer, tunnel, or Cloudflare proxy,
but the application does not depend on any vendor. On the single-host topology, host Caddy/Nginx
owns public ports 80/443 and forwards to `127.0.0.1:8080`. `compose.staging.yml` binds its only
published service to that loopback address by default; it does not provide a public HTTP login
entry. The external edge must terminate a valid certificate, redirect HTTP to HTTPS, preserve the
public Host/scheme, and forward only to the Web container. Do not expose host ports 8080, 8000,
5432, or `/data/library` publicly.

A minimal Caddy virtual host is:

```caddyfile
reading.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
}
```

When another site already uses the host proxy, add a validated virtual host instead of replacing
the existing configuration.

`compose.staging.yml` makes Nginx restore the real client IP before proxying: the realip module
trusts only the measured host-edge bridge address (`STAGING_REAL_IP_PEER`, default
`172.30.19.1`, baked into the image at build; the build accepts only a single canonical IPv4
address, rejects empty, malformed, CIDR, or wildcard values, and then runs `nginx -t`) and
resolves `X-Forwarded-For` recursively, so client-forged entries never win. Nginx then
overwrites the forwarding headers with that single address. Uvicorn accepts forwarded headers only
from Nginx's fixed internal IP. Nginx additionally rate-limits `POST /api/v1/auth/login` and
`POST /api/v1/auth/passkeys/authentication/options` at the edge; excess requests receive a stable
JSON 429 with `Retry-After` and `no-store` without reaching the application. Access logs are
disabled. Nginx and FastAPI return noindex headers, OpenAPI is disabled, and standard
OpenAPI/documentation paths return an explicit 404 instead of falling through to the SPA. The Web
CSP permits Ant Design's runtime-injected styles while keeping inline scripts prohibited.
Uploaded files are never served as a static directory.

Passkey production use requires a stable DNS name. An IP/HTTP deployment cannot complete v0.7.0
administrator acceptance and must be reported `DEPLOYMENT_PENDING`.

## Host directories

```text
/srv/novel-platform/
├── app/                 # clean committed checkout
├── config/              # mode-600 environment only
├── data/
│   ├── postgres/        # PostgreSQL bind mount
│   ├── library/         # mode 700, UID/GID 10001
│   └── backups/         # mode 700; backup files mode 600
└── reports/             # sanitized reports and preflight summaries, mode restricted
```

Bootstrap scripts may prepare the deploy user, Docker, firewall, swap, and these paths. Verify
key-only deploy login before changing SSH policy. The public firewall needs only the actual SSH
port and the HTTPS edge ports.

## Environment

Generate a new mode-600 environment only for a new host:

```bash
cd /srv/novel-platform/app
./scripts/create-staging-env.sh https://reading.example.com
```

The command generates independent database, JWT, refresh/throttle-hash, and credential/device
hash secrets without printing their values. It does not generate an administrator password,
Setup Token, recovery credential, or Passkey.

For an existing environment, merge names from `.env.staging.example` manually and preserve
existing values until the coordinated upgrade reaches the secret-rotation step. Required v0.5
settings include:

```text
STAGING_HTTP_PORT=8080
AUTH_CREDENTIAL_HASH_SECRET
AUTH_DEVICE_COOKIE_NAME
AUTH_DEVICE_COOKIE_TTL_DAYS=365
ADMIN_RECOVERY_TTL_MINUTES
WEBAUTHN_RP_ID
WEBAUTHN_RP_NAME
WEBAUTHN_ORIGINS
WEBAUTHN_CHALLENGE_TTL_SECONDS
OPENAPI_ENABLED=false
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=strict
STAGING_REAL_IP_PEER=172.30.19.1
```

Since v0.8.0 the server refuses to boot in staging/production unless authentication Cookies are
`SameSite=Strict`. `STAGING_REAL_IP_PEER` must stay the single measured host-edge bridge address
seen by the Compose Web container; widening it re-opens forged-source injection.

`PUBLIC_BASE_URL`, `CORS_ORIGINS`, and `WEBAUTHN_ORIGINS` must contain the exact HTTPS origin.
`WEBAUTHN_RP_ID` is the stable hostname without scheme or path. `TRUSTED_HOSTS` is an explicit
allow-list. The three authentication secrets must be distinct, random, and at least 32 bytes.
Keep `STAGING_HTTP_PORT` on an unused loopback port; 8080 is the documented default and must not be
opened by the host or cloud firewall.

Validate without printing the resolved Compose environment:

```bash
docker compose --env-file /srv/novel-platform/config/.env.staging \
  -f compose.staging.yml config --quiet
```

Never run `docker compose config` with environment expansion into a report. Never paste or export
CLI-generated credentials into `.env`, shell history, a command line, chat, or an acceptance
artifact.

For CLI commands while the staging Server is running, execute the command inside that existing
container:

```bash
docker compose --env-file /srv/novel-platform/config/.env.staging \
  -f compose.staging.yml exec -T server novel-platform COMMAND
```

The staging services use fixed private IP addresses. Do not use `docker compose run server` while
the Server container is running; a one-off Server would try to claim the same address and fail
before the CLI starts. Repository deployment and backup scripts stop the conflicting service
before their own one-off operations.

## New database initialization

Build and deploy:

```bash
./scripts/deploy-staging.sh
```

On a fresh database, deployment deliberately leaves the administrator pending. Generate the
single-use initialization credential in a trusted interactive terminal:

```bash
docker compose --env-file /srv/novel-platform/config/.env.staging \
  -f compose.staging.yml exec -T server novel-platform \
  admin init --display-name '站点管理员'
```

Enter the printed value once on `/login`, register a Passkey, log out, and use the Passkey to log
back in. The recovery Session must be unable to open the library, reader management, site
settings, or audit pages before Passkey registration.

Create reader identities in the administrator UI. Deliver each one-time reader credential through
an appropriate private channel. The UI cannot retrieve it again.

## Upgrade from v0.7.0 to v0.8.0

v0.8.0 is authentication hardening (ADR 0016). It adds no Alembic revision, API contract,
permission, persistent-entity, or data-conversion change. It does change the Compose Web image
content (real client IP restoration and auth entry rate limiting) and one boot-time validation.

1. Require `pnpm acceptance:v080` to pass on the exact reviewed commit. Record
   `artifacts/acceptance-v080.{md,json}` and `artifacts/acceptance-v080-core.json`.
2. Create and isolated-restore-test the normal coordinated backup as an operational precaution.
3. Set `AUTH_COOKIE_SAMESITE=strict` in the mode-600 environment. The server refuses to boot in
   staging/production without it.
4. Measure the source address that the Compose Web container actually sees from the host edge
   (with the loopback-published topology this is the edge bridge gateway `172.30.19.1`). Set
   `STAGING_REAL_IP_PEER` only if the measured value differs, and keep it a single address.
5. Build and deploy the reviewed v0.8.0 images with the existing environment and topology.
6. Verify on the real HTTPS origin: an externally visible client address appears in audit rows
   (not the gateway), a forged `X-Forwarded-For` probe still records the real address, repeated
   failed logins return the JSON 429 without locking out other readers, administrator Passkey
   login and reader credential login still succeed, and cookie-mode reload/refresh works with
   SameSite=Strict cookies. These checks remain `DEPLOYMENT_PENDING` until run under explicit
   deployment authorization.
7. If application rollback is needed, redeploy the accepted v0.7.0 application image or commit.
   Do not run Alembic downgrade or restore database/library data solely for this rollback.

## Upgrade from v0.6.0 to v0.7.0

v0.7.0 changes the Web design system, interaction layout, static assets, and application version
only. It adds no Alembic revision, API contract, authentication or authorization protocol,
permission, persistent entity, or topology change.

1. Require `pnpm acceptance:v070` to pass on the exact reviewed commit. Record
   `artifacts/acceptance-v070.{md,json}`, `artifacts/bundle-v070.{md,json}`, and the 30 sanitized,
   capture-only screenshots in `artifacts/visual-v070/`. There is no reviewed pixel baseline yet.
2. Create and isolated-restore-test the normal coordinated backup as an operational precaution;
   the UI release itself does not write migration data.
3. Build and deploy the reviewed v0.7.0 commit with the existing environment and topology.
4. Verify the real HTTPS origin: the focused `/login`, administrator and reader desktop/mobile
   navigation, library filters, reader master-detail, Passkey login, Upload inspect/commit, Reader
   themes/synchronization, noindex headers, and API health.
5. If application rollback is needed, redeploy the accepted v0.6.0 application image or commit.
   Do not run Alembic downgrade or restore database/library data solely for this UI rollback.

The historical v0.5.0-to-v0.6.0 upgrade was likewise application-only and added no Alembic, API,
authentication, persistent-entity, or topology change. Its release evidence remains available
through `pnpm acceptance:v060` and `artifacts/acceptance-v060.{md,json}`.

Repository acceptance is local evidence only. Until the real-domain checks run under explicit
deployment authorization, report `LOCAL_PASS / DEPLOYMENT_PENDING`.

## Upgrade from v0.4.0

Do not run this procedure without an explicit maintenance window. Do not clear the existing
PostgreSQL or library directory.

### 1. Pre-upgrade evidence

From a trusted local checkout, require the v0.4.0 release gate to pass. Record the current Git
commit, Alembic revision, service health, and a non-secret row-count summary. Confirm the library
directory is owned by UID/GID 10001 and mode 700.

### 2. Coordinated backup and isolated restore

With the v0.4-compatible code still checked out:

```bash
./scripts/backup-library.sh
./scripts/restore-library.sh --test BACKUP_DIRECTORY
```

`backup-library.sh` stops API/Web writers, creates a PostgreSQL custom dump and library archive,
checks permanent and temporary references, and publishes an atomic manifest. The restore test uses
a temporary database and temporary Docker volume, verifies revision and every referenced file,
and removes only those isolated resources.

Keep the resulting pre-upgrade directory unchanged. It is the rollback unit for database and
library together.

### 3. Install v0.5 configuration and code

Add the v0.5 environment names without logging values. Point the stable HTTPS hostname/certificate
to the Web service. Check out the reviewed v0.5 commit, then run:

```bash
./scripts/deploy-staging.sh
```

The deploy sequence is:

```text
validate config -> build immutable images -> stop writers -> coordinated backup
-> Alembic 20260715_0005 -> migration preflight -> explicit conversion
-> database/library integrity audit -> API/Web health
```

Any migration, conversion, or integrity failure leaves the public application stopped.

### 4. Resolve ambiguous administrators/owners

The deploy script writes a mode-600 preflight JSON under the reports directory. If the old
database has multiple administrators or content owners, conversion refuses to guess. Review the
IDs and rerun with the unique target and every non-target administrator explicitly listed:

```bash
V050_TARGET_ADMIN_ID=TARGET_UUID \
V050_MAP_ADMIN_TO_READER_IDS=OTHER_ADMIN_UUID,ANOTHER_ADMIN_UUID \
  ./scripts/deploy-staging.sh
```

These values are identifiers, not credentials. Conversion changes all content-owner FKs to the
target, maps every listed non-target administrator to a reader, clears all password hashes, and
revokes legacy Devices, Sessions, and Refresh Tokens. It preserves Book/Edition/file/Series IDs,
relations, progress, settings, and preferences and never creates reader plaintext credentials.

For manual review while the Server is running, use:

```bash
docker compose --env-file /srv/novel-platform/config/.env.staging \
  -f compose.staging.yml exec -T server novel-platform auth migration preflight
```

If a failed migration deliberately left the Server stopped, the same preflight may instead use a
one-off Server only after confirming the regular Server container is not running.

### 5. Rotate authentication secrets

After successful conversion, replace `AUTH_JWT_SECRET`, `AUTH_HASH_SECRET`, and
`AUTH_CREDENTIAL_HASH_SECRET` with three new independent random values. Recreate API/migrator
containers. Do not record values. Old JWTs, Refresh Tokens, device secrets, reader credentials,
and recovery credentials must no longer authenticate.

### 6. Recover administrator and readers

Because passwords are gone, use:

```bash
docker compose --env-file /srv/novel-platform/config/.env.staging \
  -f compose.staging.yml exec -T server novel-platform admin credentials reset
```

Use the one-time output to register a new Passkey. Reissue a new reader credential for each
retained reader identity in the UI; reissue preserves progress/settings/preferences.

### 7. Post-upgrade verification

```bash
./scripts/healthcheck-staging.sh
docker compose --env-file /srv/novel-platform/config/.env.staging \
  -f compose.staging.yml exec -T server novel-platform auth migration audit
```

Then verify on the real HTTPS origin:

- public page contains only configured purpose/privacy/login and real ICP data;
- OpenAPI is unavailable and noindex headers are present;
- administrator Passkey registration/login/recovery constraints;
- reader credential, three-device/default limit, fourth-device denial, and device revocation;
- reader can read and synchronize but cannot upload/mutate/download/administer through UI or API;
- restart persistence and a new coordinated backup + isolated restore.

Generate the current sanitized operational evidence after the functional checks:

```bash
./scripts/acceptance-staging-persistence.sh
./scripts/report-staging-resources.sh post-v050
./scripts/scan-staging-artifacts.sh
STAGING_LOCAL_ACCEPTANCE_JSON=/srv/novel-platform/reports/acceptance-v050.json \
STAGING_PASSKEY_RESULT=PASS \
  ./scripts/generate-staging-deployment-report.sh
```

The persistence state contains only row counts and hashes over stable database state. The
deployment report uses v0.5 filenames, omits credentials, IDs, storage keys, content, and absolute
host paths, and remains `DEPLOYMENT_PENDING` unless all required artifacts plus the real HTTPS
Passkey result are PASS.

Until these real-domain checks run under explicit server authorization, report
`LOCAL_PASS / DEPLOYMENT_PENDING`.

## Routine administrator CLI

Use the running-staging `exec` prefix shown above, followed by one of these commands:

```text
admin recovery create          # one-time restricted recovery credential
admin credentials reset        # revoke Passkeys/Sessions, emit one-time reset credential
admin sessions revoke-all      # immediately revoke every administrator Session
admin status                   # sanitized state only
admin lock                     # revoke Sessions and block normal admin access
admin unlock                   # CLI-only emergency unlock
auth audit cleanup             # apply configured retention, audit the cleanup
auth migration audit           # count/check database-volume consistency without keys/paths
```

`admin lock` is the emergency stop. After unlock, authenticate normally or create a recovery
credential. The Web application never generates a universal recovery value.

## Backup and isolated restore

Create regular coordinated backups:

```bash
./scripts/backup-library.sh
```

The v0.5 dump includes site settings, reader credential history, administrator recovery records,
Passkeys, WebAuthn challenge history, devices, Sessions, refresh rows, audit events, all content,
file revisions, Series, preferences, settings, and progress. Raw credentials are not present
because they are never stored.

Restore-test every backup:

```bash
./scripts/restore-library.sh --test \
  /srv/novel-platform/data/backups/novel-platform-v050-TIMESTAMP
```

An intentional live restore is destructive and needs separate authorization:

```bash
ALLOW_STAGING_RESTORE=1 \
  ./scripts/restore-library.sh --staging BACKUP_DIRECTORY --confirm novel_platform
```

It rejects a schema mismatch before destructive work, repeats the isolated restore, makes a new
safety backup, restores database and volume, recomputes permanent checksums, validates temporary
references, and starts the app only after all checks pass. It never runs Alembic downgrade.

## Rollback

Application-only rollback is valid only when the target code supports the current schema. The
normal v0.5 response is fix-forward. Returning to v0.4 requires separate destructive approval:

1. stop writers;
2. isolate-test the exact pre-upgrade coordinated backup;
3. restore its database and library together;
4. switch to the matching v0.4 code;
5. verify revision, references, health, and authentication behavior.

Do not run an automatic downgrade or restore a database and volume from different backups.

## Health and exposure checks

```bash
./scripts/healthcheck-staging.sh
```

The script verifies PostgreSQL/API/Web health, matching Alembic revision availability, and that
PostgreSQL/FastAPI publish no host ports. Also verify externally that ports 5432, 8000, and 8080
are closed, that the Web binding is `127.0.0.1:8080`, and that HTTP redirects to HTTPS.

Container logs are diagnostic only. Never enable request-body/header logging or include verbose
environment output in reports. Run the artifact leak scan after generating any deployment report.
