# ADR 0004: Reader and editing model

- Status: accepted
- Date: 2026-07-10

## Decision

Normal reading will operate on one Edition and must not require its source link.
Progress, annotations, and exports attach to the selected Edition. Side-by-side
comparison and local retranslation are optional capabilities enabled only when a
valid source is linked.

Edits that materially change content will create traceable Editions instead of
overwriting history; `supersedes_edition_id` expresses product replacement without
deleting the older version.
