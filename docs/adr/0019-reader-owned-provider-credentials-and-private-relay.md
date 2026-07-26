# ADR 0019: Reader-owned Provider credentials and private relay

- Status: accepted
- Date: 2026-07-26
- Supersedes: ADR 0018's operator-owned Provider-secret and no-Provider-key-in-Novel-Platform clauses
- Extends: ADR 0017 for invited capabilities and ADR 0018 for recoverable Translation Runs

## Context

The v0.9 translation boundary authorizes an invited actor with `translation.use`, but every real
LinguaSpindle Job still uses one operator-configured Provider key. Capability checks therefore
separate who may translate without separating who pays for Provider usage. A software quota over
the shared key cannot move billing to the reader.

The selected product direction is bring your own key (BYOK): each translating actor supplies and
pays for their own OpenAI-compatible Provider credential. LinguaSpindle must remain standalone and
must not gain a User, tenant, owner, permission or quota model. Browser-direct Provider calls,
plaintext database storage, a key in LinguaSpindle Job snapshots, and silent fallback to an
administrator key would each break an existing trust or recoverability boundary.

## Decision

Novel Platform owns a versioned encrypted Provider-credential vault and a separately deployed
private LLM Relay:

```text
Browser
  -> Novel Platform Server (identity, capability, Run and encrypted credential ownership)
  -> LinguaSpindle (identity-free Job + opaque credential_scope)
  -> Novel Platform LLM Relay (scope authorization and decryption)
  -> fixed OpenAI-compatible Provider (the actor's key)
```

### Credential ownership and lifecycle

- A normal authenticated actor with translation authority may configure, rotate or remove only
  their own Provider credential. The API returns configured state, Provider kind, version,
  timestamps and sanitized usage totals; it never returns a key, suffix, hash or reversible
  derivative.
- Credential versions are immutable rows. The raw key is encrypted with AES-256-GCM and unique
  random nonce; authenticated data binds its credential ID, User, Provider kind and version.
  The 32-byte vault master key is injected independently into Server and Relay, never stored in
  PostgreSQL, an image, source control, logs, reports or coordinated backups.
- Rotation creates a new current version and retires the old version. A Run binds the exact
  version selected at creation, so rotation cannot switch the payer or key midway through a Job.
  A retired version is usable only for a Run already bound to it. Removal revokes all usable
  versions for that actor; affected work fails closed.
- `translation.use` alone is insufficient to launch work. The actor must also have a current
  credential. There is no administrator/shared-key fallback. A future site-funded mode requires a
  separate capability and decision.

### Scoped execution without a LinguaSpindle identity

`EditionTranslationRun` stores a foreign key to the exact credential version. The version's random
UUID is sent to LinguaSpindle as an opaque `credential_scope`; it is not a User ID, tenant,
permission, quota or Provider secret. The scope participates in both Novel Platform's Run
configuration fingerprint and LinguaSpindle's Job request/execution fingerprints so active work
funded by different credential versions cannot coalesce.

LinguaSpindle persists the opaque scope only as private execution state needed after restart. It
omits the value from public Job responses, logs, errors and Artifacts. On a scoped
OpenAI-compatible execution it adds fixed scope and Job-correlation headers to its request to the
Relay. Unscoped standalone LinguaSpindle operation keeps its existing caller/environment key
behavior.

### Private Relay

The Relay is a separate FastAPI process built from the Novel Platform Server package. It has no
public or proxy-network port. It joins only the Novel Platform database network and the external
`linguaspindle-private` network. Web, PostgreSQL, migration and public ingress do not join the
translation network.

Every Relay request must:

1. use the single fixed OpenAI-compatible Chat Completions path;
2. present a constant-time-checked service Bearer secret shared only with LinguaSpindle;
3. present a strictly validated credential scope;
4. present a LinguaSpindle Job ID already bound to that Run, or atomically claim the first Job ID
   during the narrowly serialized `preparing` bootstrap race;
5. resolve an active credential version or a retired version still bound to permitted work;
6. request exactly an operator-allowlisted upstream HTTPS origin and model; and
7. remain within configured request, response and timeout bounds with redirects disabled.

The Relay replaces the service Bearer value with the decrypted actor key only at the upstream call
boundary. It never logs request/response bodies, authorization/scope headers or decrypted keys.
Unexpected exceptions are reduced to a fixed response and exception-type-only log entry. Provider
errors are normalized and bounded, and a nominally successful response that reflects the
decrypted key anywhere in its JSON value is rejected before projection or persistence. Successful
integer
`prompt_tokens`/`completion_tokens`/`total_tokens` values are recorded with credential version,
model, time and optional LinguaSpindle Job correlation; prompts, translations and raw Provider
responses are not usage data.

LinguaSpindle v0.3.2 is the minimum compatible service because earlier versions neither retain nor
forward `credential_scope`. Translation availability requires the Relay and compatible
LinguaSpindle to be healthy. Their failure must not change Novel Platform's main readiness.

## Consequences

- Reader billing is enforced by the key used at the upstream boundary, not by an advisory quota.
- PostgreSQL backups contain ciphertext, metadata and token counts. Restoring usable credentials
  also requires the separately protected matching vault master key; losing that key is
  intentionally unrecoverable.
- Server compromise can access the master key used for new credential encryption, and Relay
  compromise can decrypt in-scope credentials. Container/network isolation, least configuration,
  secret rotation, bounded transport and log suppression are therefore deployment obligations,
  not claims that application-level encryption defeats a fully compromised host.
- Rotation of the vault master key needs an explicit re-encryption procedure and is not performed
  by ordinary reader-key rotation.
- LinguaSpindle remains independently deployable, identity-free and unaware of Novel Platform
  domain objects. The opaque execution scope is an integration contract rather than an account
  model.
