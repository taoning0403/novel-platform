# ADR 0011: Safe reader projection, optimistic progress, and private series

- Status: accepted
- Date: 2026-07-14

## Context

v0.4.0 must read owner-scoped EPUB and TXT files without exposing private storage paths or
executing publisher-controlled markup. The same User may read one Edition from multiple Devices,
including intentionally returning to an earlier location. The library also needs user-created
series and per-file bulk-import results without weakening Book ownership or Edition independence.

Raw EPUB delivery would move archive traversal, HTML safety, and resource authorization into the
browser. A last-write-wins progress row would silently discard a Device's position, while a
monotonic-only percentage would reject legitimate backtracking. Encoding series only in Book
metadata would not provide ownership, ordering, or one-series-per-Book integrity.

## Decision

The server exposes an Edition-local reader projection instead of the raw file. OPF spine order is
canonical; EPUB navigation/NCX is optional and a stable fallback is generated. Sections and
declared raster resources use opaque identifiers. Section HTML is bounded and sanitized with an
allow-list, has no active/external content, and is fetched independently. TXT is read from the
upload-time normalized UTF-8 file and split into bounded stable sections/blocks.

Reading progress belongs to `(User, BookEdition)` and records the current Edition file revision,
opaque section/block location, percentages, status, last-read time, and an optimistic version.
Every write supplies `expected_version`; mismatches return HTTP 409 with the current location.
The caller may retry using that current version only through an explicit user choice, which also
permits intentional backward movement, restart, and manual finished state. Reader visual settings
belong to the User, not a Device or Edition.

A private `BookSeries` belongs to one User. `SeriesMembership.book_id` is unique, so a Book has at
most one series, and `(series_id, position)` provides stable append order. Series deletion removes
memberships only. A create-Book import may include an owned series ID and commits the membership
atomically; a Web multi-file upload remains a sequence of independent inspect/commit operations so
one invalid file cannot roll back successful files.

All reader, progress, setting, recent, and series access uses the existing database-backed
User/Device/Session dependency and owner-scoped repository queries. Invisible resources return
404, and no reader response exposes storage keys, archive paths, hashes, or public URLs.

## Consequences

- One broken EPUB section can be reported and retried without making other sections unreadable.
- The Web client renders trusted-by-contract sanitized markup, but must still fetch every image
  through an authenticated opaque resource endpoint and revoke its object URLs.
- Replacing an Edition file invalidates exact section/block restoration; percentage remains the
  safe fallback and saving an old revision returns 409.
- Concurrent Devices cannot overwrite one another silently. Conflict resolution is visible to the
  reader and may deliberately choose either the cloud location or the current Device location.
- Progress, settings, and series require PostgreSQL; no browser-only state is authoritative.
- Series cannot nest, share Books, infer order, or span owners in v0.4.0. Manual reorder is not part
  of this milestone.
- Bulk import is partial-success by design and must show a durable result for every selected file.
