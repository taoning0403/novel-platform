# ADR 0020: Versioned reader-selected Provider routing

- Status: accepted
- Date: 2026-07-26
- Supersedes in part: ADR 0019's single fixed upstream and fixed credential-kind clauses
- Extends: ADR 0019's reader-owned credential, scoped Relay and no-fallback boundary

## Context

ADR 0019 deliberately introduced reader-owned BYOK with one fixed OpenAI-compatible upstream.
That boundary establishes safe encryption, exact Run-to-version binding and a private Relay, but
it cannot represent readers who use DeepSeek, Kimi or another OpenAI-compatible service. Merely
labelling keys differently in the Web client would be misleading because every request would
still go to the operator's fixed upstream and model.

Allowing an arbitrary browser-supplied URL on each request would create a Server-side request
forgery and credential-exfiltration path. Letting a current setting mutate an existing Run would
also violate the exact payer, key and recovery snapshot introduced by ADR 0019.

## Decision

Each translating User has exactly one current Provider configuration. Saving a key creates a new
immutable credential version containing the non-secret Provider kind, display name, normalized
base URL, model and thinking-mode state together with the encrypted key. Switching Provider or
changing its model or thinking mode is a normal credential rotation: new Runs use the new version
and existing Runs remain bound to the version selected at creation.

The supported Provider kinds are:

- `openai_compatible`, presented as OpenAI, with new v2 versions fixed to
  `https://api.openai.com/v1`;
- `deepseek`, with the fixed `https://api.deepseek.com/v1` base URL;
- `kimi`, with the fixed `https://api.moonshot.cn/v1` base URL; and
- `custom`, with a reader-supplied display name, model and base URL.

Preset base URLs are not browser-editable. A custom base URL must be a normalized HTTP(S) base
URL, must use HTTPS in staging/production, and must exactly match an operator-configured Relay
allow-list. The Server validates this before saving and the Relay validates it again before every
upstream call. Redirects remain disabled. Adding an allowed custom destination is therefore an
explicit deployment decision, not authority for a reader to make the Relay contact an arbitrary
host.

Thinking mode defaults to disabled and is never inferred from a generic browser boolean:

- DeepSeek enables thinking exactly when the bound model is `deepseek-reasoner`; disabled
  configurations cannot use that model.
- Kimi `kimi-k2.5` receives an explicit `thinking.type` of `enabled` or `disabled`. Other Kimi
  models may be saved only with thinking disabled and receive no injected thinking field.
- OpenAI and custom OpenAI-compatible routes reject an enabled value because their reasoning
  controls are model-specific and cannot be represented truthfully by one portable boolean.

LinguaSpindle remains configured with one identity-free OpenAI-compatible adapter pointing to the
private Relay. The Relay first authenticates LinguaSpindle, scope and Job correlation and checks
the adapter's inbound model against its operator allow-list. Only after resolving the exact bound
credential version does it replace the outbound base URL and model with that version's immutable
configuration. It replaces the internal service Bearer with the decrypted reader key only at that
selected upstream boundary.

New ciphertext uses an AES-256-GCM authenticated-data format that binds User, credential UUID,
version, Provider kind, display name, base URL, model and thinking-mode state. The previous format
remains decryptable only for existing OpenAI-compatible versions and always keeps thinking
disabled. Migration adds their historical fixed routing metadata without decrypting or rewriting
their ciphertext. API responses may return Provider kind, display name, base URL, model, thinking
state, version and timestamps because these are configuration, but they continue to omit the key,
ciphertext, nonce, scope and any key derivative.

`PROVIDER_RELAY_UPSTREAM_BASE_URL` remains the legacy v1 destination so an existing deployment
with a non-OpenAI compatible upstream cannot silently redirect its old key or Run. New v2 OpenAI
versions ignore that legacy setting and bind the official URL; other compatible destinations must
use `custom` and the explicit allow-list.

Usage remains aggregated for the User across Provider versions. A Provider change does not create
a shared/site-funded fallback and does not grant translation authority.

## Consequences

- OpenAI, DeepSeek and Kimi work as first-class choices while custom OpenAI-compatible services
  require an explicit operator allow-list entry.
- One User cannot keep several simultaneously current keys or choose a different Provider per Run;
  selecting another Provider rotates the current configuration.
- Thinking remains off unless a supported DeepSeek/Kimi configuration is explicitly saved; an
  unsupported or inconsistent Provider/model/thinking combination fails closed.
- A Run remains recoverable against the exact Provider route, model and key version it originally
  bound, subject to credential revocation and continued custom-destination allow-list approval.
- Database backups now contain non-secret Provider routing metadata alongside ciphertext. A
  matching vault key remains independently required, and custom allow-list configuration remains
  a separate deployment input.
- Supporting a browser-direct Provider call, arbitrary custom destination, site-funded key,
  automatic Provider failover or per-Run Provider picker requires another explicit decision.
