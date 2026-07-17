# ADR 0005: Local accounts and session authentication

- Status: accepted
- Date: 2026-07-11

## Context

Private libraries and later multi-device synchronization need a revocable identity boundary.
An entirely stateless JWT cannot immediately invalidate access after a password change, user
disable, device revoke, or logout.

## Decision

Use local administrator-created accounts. Hash passwords with Argon2id. Sign short-lived JWT
Access Tokens with HS256, but verify the referenced active User, Device, and database Session on
every protected request. Persist rotating opaque Refresh Tokens only as HMAC-SHA256 hashes.
Replay of a used Refresh Token revokes its entire Session.

## Consequences

Authentication remains available with PostgreSQL alone and critical revocations take effect
immediately. Protected requests perform a database lookup, Refresh requires transactional row
locking, and signing/hash secrets must be independently generated and protected.
