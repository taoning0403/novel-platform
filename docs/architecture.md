# Architecture

漫读 (`novel-platform`) v0.9.0 remains a modular monolith: one React client, one FastAPI process,
PostgreSQL, and a private local library volume. Optional novel translation crosses one explicit
boundary to a separately deployed LinguaSpindle v0.3.1 service. The product remains a personal
non-commercial reading and collection-management site, not a public platform or distribution
service.

```text
Browser
  │ same-origin HTTPS in deployment
  v
Nginx (static SPA, bounded upload proxy, header hardening)
  │ controlled proxy network
  v
FastAPI modular monolith
  ├── authentication / credential capabilities / WebAuthn / administration / audit
  ├── contributor-attributed Books / Editions / imports / files / Series
  ├── actor-scoped Translation Run orchestration
  ├── safe Reader Projection / progress / settings / preferences
  ├── PostgreSQL
  ├── private Novel Platform library volume
  └── private HTTP (Server only)
       └── LinguaSpindle v0.3.1
            ├── independent SQLite + Artifact volume
            └── Provider configuration and secret
```

Novel Platform and LinguaSpindle share no identity, database, volume or domain model. Browser,
Web, migrate and PostgreSQL never join the translation network. There is no Redis, worker, queue,
public object store, external identity provider, analytics service, mail/SMS dependency, or
Cloudflare requirement. Cloudflare Access may be an optional outer layer, but application
authentication and authorization stand alone.

## Web component and route boundary

The Web client retains the v0.7.0 漫读 Quiet Trace system and v0.6.0 Ant Design component
foundation. v0.9 navigation/routes project server-returned capabilities and permission flags:

```text
AppProviders
  ├── Chinese ConfigProvider + Quiet Trace Design Tokens
  └── Ant Design App context
       └── AuthProvider + BrowserRouter
            ├── AppShell (non-Reader routes)
            │    ├── grouped desktop sidebar + account actions
            │    ├── mobile top bar + frequent bottom navigation
            │    ├── capability-aware full-navigation More Drawer
            │    └── logout, recovery confinement, version footer
            └── lazy page routes + accessible Suspense fallback
                 ├── BrandMark / InterfaceIcon / shared interaction components
                 ├── Login / Library / contribution / administration layouts
                 ├── Translation launch modal + actor-scoped master-detail workspace
                 ├── page and feature CSS Modules
                 └── Reader full-screen shell
                      ├── dedicated theme and publication typography
                      └── edge progress + TOC/settings + recoverable quiet chrome
```

Pages import named Ant Design components. They do not call static message, notification, or Modal
APIs outside provider context, depend on generated Ant Design class names, or introduce a second
general-purpose component library. Route-level dynamic imports keep Reader, Upload, administration,
Status, and other pages out of the synchronous application entry.

Product-owned fallback branding uses 漫读, while an explicitly configured site name, purpose,
privacy statement, and real ICP record remain part of the public entry. Desktop navigation is
grouped by reading, curation, and personal tasks; mobile promotes frequent destinations and keeps
the full role-aware route set in a `更多` Drawer. Recovery Sessions remain confined to Passkey
registration. Hiding or regrouping a route never replaces server authorization.

Library keeps search visible and moves secondary filters into a Drawer. Reader administration
uses master-detail and moves dangerous operations into consequence-aware menus and confirmations.
The global stylesheet remains limited to reset, root typography/background, accessibility helpers,
focus treatment, and reduced-motion behavior; layout, feature, and page styles use CSS Modules.
Reader retains its independent light/dark/sepia layer and renders only server-sanitized publication
markup inside the existing projection boundary. Its edge progress, TOC, settings, and auto-hiding
chrome do not change Edition selection, private settings, or optimistic progress synchronization.

## Trust and public boundary

Anonymous access is limited to the SPA shell, safe public site settings, credential/Passkey login
preparation, and minimal health endpoints. All Books, Editions, Series, covers, reader sections,
resources, files, preferences, progress, devices, Sessions, reader administration, site
administration, and audit endpoints authenticate independently.

The production SPA contains no preloaded catalogue data. Its public entry shows configurable site
name, non-commercial purpose, privacy text, unified login, and only an actually configured ICP
record. Production disables OpenAPI and both Nginx and FastAPI apply
`X-Robots-Tag: noindex, nofollow, noarchive`; robots directives are never treated as access
control.

In the two-hop staging topology the Compose Nginx restores the real client IP with the realip
module, trusting only the measured host-edge bridge address (default `172.30.19.1/32`, substituted
at image build, fail closed on empty or wildcard values) and resolving `X-Forwarded-For`
recursively. It then overwrites `X-Forwarded-For`, `X-Real-IP`, and `Forwarded` with that single
address before proxying. Uvicorn accepts proxy headers only from the fixed Nginx network address.
Direct local development does not trust forwarding headers. IP and bounded User-Agent summaries
are audit data, never device identity.

Compose Nginx also applies entry rate limiting to the two unauthenticated authentication endpoints
(`POST /api/v1/auth/login` and `POST /api/v1/auth/passkeys/authentication/options`), keyed on the
restored client address. Excess requests receive a stable JSON 429 with `Retry-After` and
`no-store` and never reach the application, so they produce no throttle or audit writes.

## Identity and authentication flow

One durable User is the logical administrator and content owner. Historical ordinary Users become
durable reader identities. The PostgreSQL enum may retain internal `member`; APIs and product UI
expose `reader`.

Reader login:

```text
raw high-entropy credential
  -> domain-separated HMAC lookup + IP/credential-dimension throttle
  -> lock current credential row
  -> validate User, lifecycle, expiry, migration state
  -> validate HttpOnly device-secret Cookie
       existing authorized Device: reuse
       new Device: enforce allow_new_devices + locked max_devices count
  -> revoke prior active Session on that Device
  -> short Access JWT + rotating Refresh Cookie + optional new device Cookie
```

The browser keeps the Access Token only in React memory. Refresh and device secrets use HttpOnly,
appropriate SameSite, production-Secure Cookies. The database stores only keyed hashes. A copied
`client_instance_id` cannot prove authorization; clearing browser Cookies creates a new Device.

Every protected request decodes the JWT only as a lookup hint, reloads Session/User/Device, and
then reloads the current reader credential or administrator Passkey. Revocation, suspension,
expiry, device revocation, administrator lock, and Passkey reset therefore beat the JWT TTL.

Refresh tokens rotate once. Every refresh first proves possession of the Session's device secret:
the application verifies the presented device-secret digest against the Session's Device before any
rotation or replay-revocation side effect, so a stolen Refresh Token alone can neither rotate nor
revoke the victim Session. Replay with the correct device secret still revokes the entire Session.
Cookie-mode refresh requires a present, allowlisted `Origin`; staging and production require
`SameSite=Strict` authentication Cookies. The device Cookie has an independent configurable
lifetime and is re-issued when a login reuses an authorized Device. Reader Session and refresh
expiry never exceed credential expiry. An explicit login on one authorized Device replaces its
prior active Session instead of accumulating Sessions.

## Administrator Passkey and recovery flow

The server CLI initializes the single administrator and prints a 256-bit one-time recovery
credential once. The same credential entry on `/login` creates a short restricted recovery
Session. That Session can request and verify only Passkey registration (plus logout); ordinary
library, reader-management, site, audit, and Passkey-list routes reject it.

Passkey registration requests resident credentials and required user verification. Challenge
rows are short-lived, single-use, and bind purpose, User, Origin, and RP ID. Expired rows are
deleted on issuance in set-based batches bounded by a fixed batch size and driven by the
`expires_at` index. The server stores only WebAuthn public credential material. Completing
recovery registers the Passkey, revokes all old administrator Sessions, clears the emergency
lock, and creates a normal Passkey-backed Session.

Daily administrator login uses the same `/login` page and a Passkey assertion. A normal
administrator can register multiple Passkeys and cannot revoke the last one. CLI recovery,
credential reset, lock/unlock, and all-Session revocation never expose an existing credential.

Production requires HTTPS, Secure Cookies, a stable RP ID, and an explicit HTTPS Origin list.
Local automated acceptance uses `localhost` and Chromium's virtual WebAuthn authenticator.

## Authorization and library visibility

The application separates three subjects:

- `library_owner_user_id`: the unique administrator used for site-library containment, Series,
  storage integrity and backup;
- `actor_user_id`: the durable User attributed to uploaded/generated resources and Runs;
- `viewer_user_id`: the authenticated identity used for progress, settings, preferences, devices,
  and Sessions.

Invited authority is stored on the current credential, not the User or JWT. `library.read` is
mandatory; `library.upload` and `translation.use` are optional immutable snapshots. Every
protected request reloads Session, credential and capability rows. Route dependencies first check
administrator/capability/recovery confinement; application services then check the actor, library
owner, resource creator, state and dependencies. Admin cannot bypass integrity constraints.

```text
administrator          read-only            library.upload             translation.use
-------------          ---------            --------------             ---------------
all content states     ready/current-file   ready/current-file         ready/current-file
all library resources  no content mutation  own uploaded resources     own Runs/generated Editions
Series/publish/raw      none                 none                       none
all Runs/control       none                 none                       own Runs/control
own reading state      own reading state    own reading state          own reading state
security/site admin    none                 none                       none
```

Upload and translation do not imply each other. A combined credential receives the union but
never another actor's resource authority. A contributor-created Book containing another User's
Edition/Run returns `409 book_contains_other_contributions` for contributor Book deletion. Active
Import/Run and source/supersedes/file dependencies remain blocking. Cross-identity private
Import/Run/draft resources retain 404 hiding; visible-but-forbidden writes use stable 403. UI
visibility remains presentation only.

## Reader projection and private state

The accepted v0.4 Reader architecture remains:

- EPUB parsing follows the OPF spine and bounded TOC, rejects unsafe ZIP/XML/image structures,
  sanitizes active/external content, and serves protected declared resources only.
- TXT keeps original bytes and a normalized UTF-8 StoredFile, then streams deterministic bounded
  sections rather than loading an entire novel into browser state.
- Reader responses never expose a storage key/path/hash or raw file URL.

Progress is per User + Edition with stable section/block anchors, file revision, percentages,
status, and optimistic version. A stale update returns 409 plus current state; the UI offers cloud
restore or intentional overwrite. Reader settings and preferred/last-opened Editions are also
viewer-private. The administrator participates as a viewer with state independent of each reader.

## Import, file revision, and Series boundaries

The administrator or a current `library.upload` credential runs inspect-preview-commit. Imports are
isolated by `requested_by_user_id`; the administrator sees all, while another actor receives 404.
Upload bytes are bounded and validated before one transaction creates/changes Book/Edition/file
relations. `owner_user_id` remains the administrator; creator columns record the actor. An invited
uploader may replace only a self-created Edition. Replacement appends a revision and preserves
Edition identity. Compensation is idempotent and precisely deletes only unreferenced objects.

Series remains an administrator-owned ordered grouping. A Book belongs to at most one Series;
deleting a Series retains Books, Editions, files, preferences, and progress. Reader Series
responses filter invisible Books and omit empty shells.

## Private translation boundary

Translation is synchronous HTTP orchestration from Server with persisted recovery state; React
never performs remote multi-step calls and the HTTP client never creates an Edition.

```text
actor + fixed readable TXT EditionFile
  -> create Run (actor/client UUID idempotency + source revision/SHA snapshot)
  -> Lingua status/version/pipeline/provider/idempotency checks
  -> deterministic Project + Job requests and stored correlation IDs
  -> on-demand selected-Run sync/control (no worker or scheduler)
  -> terminal successful Artifact metadata
  -> same-origin bounded streaming download + size/SHA/format validation
  -> shared generated-ingestion kernel + one DB transaction + file compensation
  -> draft/ai/generated Edition owned by library owner, attributed to actor
  -> creator-only preview -> administrator-only ready publication
```

Base URL, compatible version, Provider/Profile identity, timeouts and maximum download size are
operator configuration. Provider keys exist only inside LinguaSpindle. The browser submits no
Provider/model/profile/URL/download choice. The client follows no redirects, accepts only fixed
same-origin endpoints, does not propagate remote response bodies, and sanitizes error details.

The Run stores exact Project/Job/Artifact IDs. Retry recovers with deterministic idempotency;
cleanup may delete only that stored Project. A cleanup failure never rolls back an already
ingested Edition. Lingua availability is deliberately absent from main readiness, so disabling the
feature/network affects only translation.

## Auditing and retention

Authentication, credential/capability, device, Session, Passkey, recovery, contributor mutation,
translation control/publication, administrator-control, site setting, and important permission
events use bounded structured audit rows. Metadata never
contains raw credentials, tokens, Cookies, challenges, secrets, storage paths, or book content.
The configured default retention is 90 days. There is no scheduler; an operator runs
`auth audit cleanup`, which records a summary event after deletion.

Login failure throttling uses two keyed dimensions: the realip-restored client IP and the
submitted credential hash, behind the Nginx entry limit on the login route. Unknown credentials
receive the same generic response and throttle style as known unavailable credentials.
Device-limit errors are the one explicit non-enumerating operational response.

## Migration, backup, and failure posture

Alembic `20260723_0006` follows the completed v0.5 identity/owner conversion. Its internal
count-only preflight refuses a missing conversion, non-unique owner/admin, owner mismatch, active
Import, missing/mismatched file reference or invalid current-file set. It then clears private
state/links pointing at fileless placeholders, deletes those Editions and resulting empty Books,
backfills creator columns, grants every retained credential only `library.read`, and creates Run
storage. It cannot be downgraded because placeholder deletion is destructive.

Deployment order is:

```text
validate candidate/config/topology -> stop writers -> sanitized count preflight
-> coordinated database+library backup -> isolated restore
-> explicit approval for destructive migration/reset -> Alembic 20260723_0006
-> volume integrity audit -> API/Web health + credential capability matrix
-> optional Server-only translation network -> v0.3.1 Mock short TXT/retranslation/cleanup
-> restart persistence + before/after topology comparison
```

The library audit compares database permanent references/checksums and temporary references with
the mounted volume but reports only counts. A coordinated backup captures Novel Platform
PostgreSQL and library while writers are stopped, including capability/creator/Run state. Its
manifest excludes LinguaSpindle SQLite/Artifacts/containers/networks. Restore must first succeed
against a temporary database and temporary volume. Rollback restores matching code + database +
volume; a translation-only failure disables the feature/network without deleting generated
Editions. Remote Projects are never cleaned by pattern or inventory guess.

## Deliberate omissions

v0.9.0 does not add bookmarks, highlights, annotations, comments, social features, sharing,
public registration/catalogue, payments, advertising, public/raw downloads, native clients,
scheduled jobs, object storage, Series nesting/reordering, EPUB/manga translation, per-chapter
review, browser Provider configuration, client-supplied credentials or arbitrary Artifact URLs.
Adding any durable boundary requires a new explicit milestone and ADR.
