# ADR 0016: Trusted-edge client IP, entry rate limiting, bounded challenge cleanup, and device-bound refresh

- Status: accepted
- Date: 2026-07-17
- Amends: ADR 0009 for the staging proxy header policy, ADR 0012 for the refresh contract

## Context

The v0.5-v0.7 staging chain runs host Caddy/Nginx on public 80/443, forwards to the loopback-only
Compose Nginx, and reaches Uvicorn on a private network. Compose Nginx overwrote
`X-Forwarded-For` with its own `$remote_addr`, which in this two-hop topology is the Docker bridge
gateway address. Every visitor therefore shared one application-visible IP: the login throttle
degraded into a site-wide lock anyone could trip, and audit rows and device records stored the
gateway address instead of the client.

Three further gaps shared the same theme of trusting the wrong thing. The unauthenticated Passkey
authentication-options endpoint inserted one challenge row per call while the expired-challenge
cleanup existed but was never invoked, and deleted row by row. Refresh required only the Refresh
Token: a stolen token could be rotated by a thief, and replaying it could revoke the victim Session
without proving possession of the authorized Device. Cookie-mode Refresh validated `Origin` only
when the header happened to be present.

## Decision

1. Compose Nginx restores the real client IP with the realip module. It trusts exactly one peer —
   the measured host-edge bridge address, default `172.30.19.1`, substituted at image build with a
   build-time fail-closed check that accepts only a single canonical IPv4 address and rejects
   empty, malformed, CIDR, or wildcard values — and resolves `X-Forwarded-For` recursively so
   client-forged entries never win. The build then runs `nginx -t` on the substituted
   configuration. The proxy forwards that single address as both `X-Forwarded-For` and
   `X-Real-IP`. Uvicorn keeps trusting only the fixed Nginx peer. Peers outside the single trusted
   address cannot influence the resolved client IP.
2. Entry rate limiting applies at Compose Nginx to exactly two unauthenticated endpoints —
   `POST /api/v1/auth/login` and `POST /api/v1/auth/passkeys/authentication/options` — keyed on the
   realip-restored `$binary_remote_addr`. Excess requests receive a stable JSON
   `auth_entry_rate_limited` 429 with `Retry-After` and `Cache-Control: no-store`, and never reach
   the application, so they write no throttle or audit rows. The application login throttle keeps
   its client-IP and credential-digest dimensions behind this first line.
3. Expired WebAuthn challenges are deleted on challenge issuance in set-based batches (default
   500) driven by the existing `expires_at` index. Valid challenges are untouched and verification
   remains strictly single-use under concurrency.
4. Refresh is bound to the Session's Device. The application service verifies the presented
   device-secret digest against `auth_session.device_id` before any rotation or replay-revocation
   side effect. A missing or mismatched secret receives the same uniform 401 as an unknown token
   and is audited as `refresh_device_binding_failed`; an attacker holding only a Refresh Token can
   neither rotate nor revoke the victim Session. Replaying a used token together with the correct
   device secret still revokes the entire Session.
5. Cookie-mode Refresh requires a present, allowlisted `Origin`. Staging and production require
   `SameSite=Strict` authentication Cookies; development may keep `lax`. The device Cookie has an
   independent, configurable lifetime (`AUTH_DEVICE_COOKIE_TTL_DAYS`, default 365 days), is
   re-issued when a successful login reuses an already-authorized Device, and is deliberately not
   bound to reader credential expiry. Error responses on `/api/v1/auth/refresh` clear the Refresh
   Cookie only for 401 outcomes, so a rejected Origin cannot force-logout a healthy browser.

## Consequences

- Audit rows, login throttles, and device IP records regain meaning in the two-hop staging
  topology; one visitor can no longer lock out every reader through the shared gateway address.
- `STAGING_REAL_IP_PEER` must remain the single measured host-edge address. The build contract
  accepts only one canonical IPv4 address; any CIDR or wildcard form is rejected at build time,
  and widening the trust requires a new ADR.
- Body-delivery (future native) clients must persist the device secret delivered as a Set-Cookie
  at login and present it at refresh; ADR 0006's reserved body-delivery path is narrowed
  accordingly without changing the Web contract.
- The real host-edge chain, real-domain Passkey flows, and production rate-limit thresholds remain
  `DEPLOYMENT_PENDING` items verified on the real HTTPS domain; local acceptance emulates the host
  edge with a second Nginx hop and fixed test addresses.
- `acceptance:v080` replays the 84-criterion v0.5 core unmodified and adds nine hardening
  criteria (106-114); historical gates v050-v070 remain untouched and runnable.
