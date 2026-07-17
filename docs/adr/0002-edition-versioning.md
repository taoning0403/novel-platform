# ADR 0002: Edition versioning

- Status: accepted
- Date: 2026-07-10

## Decision

Model every source or translation as an independent `BookEdition`. A translation's
source link is optional and mutable. Fundamental classification is immutable; a
new semantic version is another Edition linked with `supersedes_edition_id`.

## Consequences

Users can start with only a translation, link a source later, unlink it, keep
multiple same-language variants, and retain superseded history. Source-dependent
features must test capability rather than treating a missing source as invalid.

