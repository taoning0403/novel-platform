# ADR 0013: Single-administrator library ownership and invited-reader visibility

- Status: accepted
- Date: 2026-07-15
- Extends and supersedes: ADR 0007 for read authorization

## Context

ADR 0007 gives every User a separate private Book collection and lets even administrators see only
their own content. The v0.5.0 product is instead one personal site library maintained by one
administrator and read by a small set of invited readers. Weakening every owner predicate to "any
authenticated user" would expose drafts, failed imports, raw files, storage metadata, and future
management surfaces.

Existing Book, Edition, file-revision, series, preference, progress, and storage identifiers and
relationships must survive the transition. A database with multiple administrators or content
owners cannot be converted safely by guessing which identity owns the site library.

## Decision

Retain explicit non-null ownership on Books, Series, StoredFiles, LibraryImports, and related
content. `site_settings.library_owner_user_id` identifies the sole administrator library owner
after an explicit conversion. The system keeps separate query boundaries:

- **manageable**: only the administrator owner can inspect or mutate all content states, imports,
  file revisions, covers, series metadata, and raw source downloads;
- **readable**: an invited reader can see only Books with at least one `ready` Edition backed by a
  current file, only those qualifying Editions, series filtered to visible Books, protected cover
  and reader projections, and that reader's own preferences/progress/settings.

Reader API shapes omit owner IDs, storage keys, paths, hashes, import audit details, and raw file
download links. Reader content mutations and direct management-route calls are rejected by the
backend. Cross-identity private state continues to return 404; role-based denial of a management
surface may return 403.

Migration is an operator command after coordinated database-and-library backup. A read-only
preflight reports administrator and owner cardinality plus relevant state counts. If there is more
than one administrator or content owner, conversion requires an explicit target administrator and
explicit handling of every non-target administrator. Conversion updates only owner foreign keys,
clears password hashes, revokes legacy Devices/Sessions/Refresh Tokens, and records completion; it
does not regenerate credentials or rewrite content IDs, Edition relationships, file revisions,
preferences, progress, or storage keys.

## Consequences

- ADR 0007 remains historical evidence for the v0.2.0-v0.4.0 private-per-user model, but its
  "administrators see only their own Books" read rule no longer describes v0.5.0.
- Every new content endpoint must choose manageable or readable semantics explicitly.
- Reader progress and settings remain private per User even though all readers share one library.
- Rollback is a coordinated verified backup restore; automatic Alembic downgrade is not the
  production recovery mechanism.

