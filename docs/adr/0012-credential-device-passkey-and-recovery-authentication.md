# ADR 0012: Credential, device, Passkey, recovery, and session authentication

- Status: accepted
- Date: 2026-07-15
- Supersedes: ADR 0005 for interactive login and account recovery

## Context

The v0.2.0-v0.4.0 local username/password flow makes the persistent reader identity itself a
reusable login credential. That does not fit a closed personal reading site where one
administrator invites a small number of readers, rotates their access without replacing their
reading data, and uses phishing-resistant authentication for daily administration. A
client-generated instance ID also cannot prove that a browser previously consumed a device slot.

ADR 0005's short Access Token, database Session checks, hashed rotating Refresh Tokens, and replay
revocation remain useful. Its password login, Web setup token, password reset, and device
re-enablement decisions are replaced by this ADR.

## Decision

Keep `User` as the persistent identity and separate authentication into four layers:

1. A reader has at most one non-revoked high-entropy access credential. Only a domain-separated
   keyed digest and a non-secret hint are stored. Reissue creates a new credential for the same
   User and terminally revokes the old credential, its devices, Sessions, and Refresh Tokens.
2. A successful credential login authorizes a browser Device using a server-generated high-entropy
   secret in an HttpOnly Cookie. The database stores only its domain-separated digest. The
   client-provided instance ID remains a hint and is never sufficient to reuse an authorization.
   Locking the credential row serializes new-device counting.
3. An AuthSession is bound to its User, Device, and the reader credential, administrator Passkey,
   or one-time recovery credential that established it. Every protected request reloads and
   validates the current database state. Reader Session expiry is capped by credential expiry.
4. The single administrator uses discoverable Passkeys with required user verification for daily
   login. WebAuthn challenges are short-lived, single-use, Origin/RP-bound rows. A server CLI can
   issue a single-use, 15-minute recovery credential that creates only a restricted recovery
   Session until a Passkey is registered or reset.

Access credentials, device secrets, and recovery credentials use at least 256 random bits and a
role-neutral `npa_` format. Their full values are returned exactly once and never stored or logged.
The keyed-digest secret is independent from JWT and Refresh hashing secrets, with purpose strings
providing domain separation. Unknown and known credentials receive the same authentication error
and participate in both client-IP and credential-digest throttles.

Access Tokens remain browser-memory-only. Refresh Tokens remain rotating HMAC digests delivered in
an HttpOnly Cookie. Refresh and protected requests reject a disabled identity, suspended/expired/
revoked reader credential, revoked Device, revoked/expired Session, revoked Passkey, recovery-mode
scope violation, or administrator emergency lock before JWT natural expiry.

## Consequences

- Credential rotation preserves reader progress, settings, and preferences because those remain
  keyed to User rather than credential or Device.
- Clearing browser state consumes a new Device authorization; copying an instance ID does not.
- Passkey production operation requires HTTPS, a stable RP ID, and exact allowed Origins. Local
  automated acceptance may use localhost and a virtual authenticator.
- The old username/password and browser setup routes must not authenticate after conversion.
- Recovery credentials are deliberately not general-purpose administrator Sessions; server access
  remains necessary to recover from losing every Passkey.

