# ADR 0010: Local library storage and atomic import

- Date: 2026-07-13
- Status: Accepted

## Context

v0.3.0 must attach EPUB/TXT content to the accepted BookEdition model without turning an
Edition into a path or overwriting its identity. Files must remain private, survive container
replacement, tolerate failed imports/replacements, migrate from v0.2.0 in place, and participate
in a complete backup. This milestone explicitly excludes object storage, queues, workers, and a
reader.

## Decision

Keep `books` and `book_editions` as the product model. Add owner-scoped `stored_files`, append-only
`edition_files` revisions with one database-enforced current row per Edition, and auditable
`library_imports`. Existing Editions may remain without a file after migration.

Use a two-step synchronous workflow. Inspection streams into private temporary storage while
hashing and enforcing limits, validates EPUB/TXT content, and returns editable metadata. Commit
moves random-key assets into sharded permanent storage and creates Book/Edition/file records in
one database transaction. A failed transaction moves newly committed files back to temporary
storage. Replacement locks the Edition row and changes only the current file revision; Edition ID,
source/supersedes links, and preferences stay unchanged. Historical file revisions are retained
until their Edition is deleted.

Point framework multipart spooling at the same private temporary directory and cap the complete
inspect request at the ASGI boundary, including requests without `Content-Length`. Keep the
separate file-stream limit because multipart framing is not part of the stored file.

Expose files only through owner-authenticated streaming endpoints. Never return storage keys,
hashes, or absolute paths. Covers use the same storage boundary. Compose and staging mount a
dedicated `/data/library` volume or host directory owned by the unprivileged API UID. Complete
backup stops writers briefly, dumps PostgreSQL, archives the library root, records both hashes,
rejects database/archive object mismatches, and verifies restore in an isolated database and
volume before any intentional live restore.

## Consequences

- v0.1.0/v0.2.0 IDs, Edition semantics, ownership, and legacy no-file rows remain compatible.
- The application coordinates filesystem compensation with database transactions; PostgreSQL
  cannot atomically commit a filesystem rename.
- Old file revisions consume storage but make replacement rollback-safe and auditable.
- Manual cleanup expires stale previews and failed-upload temp references without deleting temp
  objects still referenced by another import, and can remove reported permanent orphans.
  Scheduling is deferred until a later milestone has a justified worker/scheduler.
- A future object-storage backend can implement the storage protocol without changing routes or
  the Edition domain, but it requires a new operational decision and migration plan.
