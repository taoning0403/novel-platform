# ADR 0007: Book ownership and isolation

- Status: accepted
- Date: 2026-07-11

## Context

The v0.1.0 schema contains Books and Editions but no identity. Adding private libraries must not
discard or require re-importing those records.

## Decision

Every Book has one non-null owner. Editions inherit authorization from their Book. Ordinary Book
and Edition APIs, including those used by administrators, only expose the current user's Books;
invisible cross-user IDs return 404. Migration creates a fixed pending administrator UUID,
assigns historical Books to it, and setup converts that same row into the first administrator.

## Consequences

Existing Book and Edition IDs and relationships remain intact. Authorization queries must scope
Book ownership and must re-check Edition relationships server-side. Shared/public libraries
would require a future explicit model rather than weakening this boundary.
