# ADR 0018: Private LinguaSpindle translation orchestration

- Status: superseded in part by ADR 0019 and ADR 0021
- Date: 2026-07-23
- Supersedes: ADR 0003's proposed client-supplied credential direction for this integration
- Extends: ADR 0002 for generated translation Editions and ADR 0009 for staging topology

## Context

LinguaSpindle v0.3.1 is an independently versioned, headless translation service with a durable
SQLite-backed asynchronous Job runner, immutable Artifacts, server-side idempotency, request
correlation, and TXT/EPUB/manga pipelines. Novel Platform needs a narrow novel-translation workflow
without importing LinguaSpindle's database, identity, provider configuration, or execution model
into the modular monolith.

Browser access, shared databases or Volumes, public service ports, caller-supplied Provider keys,
and a second queue/worker would broaden the trust boundary and create conflicting durability. A
remote success followed by a local crash also requires a recoverable local record before any HTTP
side effect occurs.

## Decision

Integrate the two applications only through a versioned private HTTP contract:

```text
Browser -> Novel Platform Web -> Novel Platform FastAPI -> LinguaSpindle v0.3.1
```

Only Novel Platform Server joins the external `linguaspindle-private` network. Web, PostgreSQL,
migration containers, and public ingress do not join it. LinguaSpindle publishes no host port and
keeps its own SQLite database, Artifact Volume, identity-free instance scope, and runtime Provider
secret. Novel Platform accepts, stores, displays, and logs no Provider key and the browser never
submits a service URL, Provider/Profile/Pipeline, model parameter, or Artifact URL.

The initial product scope is whole-book asynchronous translation of a currently readable,
`ready`, current-file-backed TXT Edition through the fixed `novel_txt_v1` pipeline. It excludes
EPUB/manga/segment translation, editing, terminology, streaming UI, WebSocket/SSE, scheduled
reconciliation, automatic publication, and automatic preference/archive changes.

Persist an `EditionTranslationRun` before external I/O. It records the library owner and actor,
Book/source Edition, immutable source EditionFile revision/format/hash snapshot, target language,
output title, optional superseded Edition, non-secret versioned configuration snapshot and
fingerprint, actor-scoped client request UUID, exact remote Project/Job/Artifact/request IDs,
progress/status/error/cleanup state, and at most one generated Edition. Active equivalent work is
unique by source snapshot, target, and configuration; terminal work permits retranslation.

Run state transitions belong to the domain/application layer. Long HTTP operations do not hold a
database transaction. Creation uses deterministic external idempotency keys derived from the local
Run ID and stage, persists every exact remote identifier, and can replay after a remote-success /
local-crash window. GET operations never create remote work; an explicit actor-authorized sync
polls state and imports success. A row lock permits only one terminal importer. Network ambiguity
is recoverable and is not immediately converted to a terminal failure.

Use a dedicated strongly typed `LinguaSpindleClient` with a server-configured base origin and
predefined paths. It rejects redirects, cross-origin download locations, malformed remote IDs,
unsupported versions outside `>=0.3.1,<0.4.0`, oversized responses, invalid JSON, unexpected media
types, and unsafe error details. Uploads and downloads stream with bounded connect/read timeouts and
a local byte ceiling. Safe `X-Request-ID` correlation is forwarded; request bodies, multipart data,
Artifact bytes, raw idempotency keys, and Provider secrets are never logged.

Translation availability checks health, version, required idempotency mode, `novel_txt_v1`, and the
configured Provider. Failure disables translation only; Novel Platform readiness, authentication,
library, upload, and Reader remain healthy. Real paid/provider-backed calls require separate
operator configuration and explicit authorization. Mock-provider evidence is labelled as Mock.

Only a fully successful Job with one verified `novel_export_txt` Artifact may be ingested. Download
origin/path, Project/Job/Artifact linkage, filename, media type, byte size, SHA-256, and TXT safety
are validated while streaming to temporary storage. A dedicated generated-content service reuses
the import validation, atomic publish, and compensation core without invoking the public upload API
or fabricating an uploaded LibraryImport. It commits a new Edition with:

```text
content_role = translation
translation_origin = ai
creation_method = generated
status = draft
source_edition_id = run.source_edition_id
supersedes_edition_id = run.supersedes_edition_id
created_by_user_id = run.created_by_user_id
```

The creator and administrator may preview the draft; only the administrator may publish it as
`ready`. Partial/failed jobs produce no Edition. Retry stays within one Run; retranslation creates a
new Run and draft without changing the old Edition, file, preference, or progress. Cleanup uses only
the persisted exact Project ID. Cleanup failure after a successful local commit is recorded and
retryable but never rolls back the Edition.

## Consequences

- LinguaSpindle remains a reusable standalone engine and Novel Platform remains the identity,
  authorization, attribution, publication, and local-ingestion authority.
- PostgreSQL provides recoverable caller orchestration without introducing Redis, Celery, or a
  second Job runner.
- Translation UI polls visible active Runs only and can recover after navigation or process restart.
- Provider configuration and costs remain an explicit operator concern; `translation.use` grants
  product use, not secret or service administration.
- Deployment must validate the private network, exact tag/image, no host port, backup/restore, and
  main-site independence. Branch publication, migration, network mutation, Provider setup, paid
  calls, and remote cleanup remain separately authorized effects.
