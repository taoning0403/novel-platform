# ADR 0008: Preferred Edition

- Status: accepted
- Date: 2026-07-11

## Context

A user may prefer a human translation while still needing an AI translation, original, or mixed
revision to remain independently available.

## Decision

Represent preferred and last-opened Edition IDs as a per-user, per-Book preference record. A
selected Edition must belong to the same owned Book. Selection changes only the preference row;
it does not mutate, supersede, archive, or delete an Edition.

## Consequences

Source, AI, human, mixed, and unknown-origin translations continue to coexist. UI language must
describe preference rather than replacement. Reader-driven last-opened updates remain outside
v0.2.0.
