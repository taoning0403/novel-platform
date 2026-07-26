# Decisions

This is the index for durable product and technical decisions. Read the linked ADR before
changing a constraint it owns; use `docs/architecture.md` and `docs/data-model.md` for the
current consolidated design.

| ADR | Status | Decision and practical effect |
| --- | --- | --- |
| [0001 — Monorepo and modular monolith](adr/0001-monorepo-and-modular-monolith.md) | Accepted | Keep server, web, shared packages, infrastructure, scripts, and records together; retain explicit API/application/domain/infrastructure boundaries inside one API deployment. |
| [0002 — Edition versioning](adr/0002-edition-versioning.md) | Accepted | Treat every source or translation as an independent Edition; keep source links optional and mutable, and represent semantic replacement with a new Edition plus `supersedes_edition_id`. |
| [0003 — Client-supplied LLM credentials](adr/0003-client-supplied-llm-credentials.md) | Superseded by 0019 | Keep the historical v0.1 omission; 0019 now supplies the explicit encrypted lifetime, redaction and private-relay rules required before managed BYOK. |
| [0004 — Reader and editing model](adr/0004-reader-and-editing-model.md) | Accepted | Make normal reading Edition-local and source-independent; attach progress and any future annotations to an Edition, and create traceable Editions for material edits. |
| [0005 — Local accounts and session authentication](adr/0005-local-accounts-and-session-authentication.md) | Superseded in part by 0012 | Retain short-lived JWTs, database Session checks, rotating Refresh Tokens, and replay revocation; username/password and Web setup are historical only. |
| [0006 — Web token storage](adr/0006-web-token-storage.md) | Accepted | Keep Access Tokens in memory, use an HttpOnly Refresh Cookie, and reserve OS secure storage for future native clients. |
| [0007 — Book ownership and isolation](adr/0007-book-ownership-and-isolation.md) | Superseded in part by 0013 | Retain explicit Book ownership and 404 isolation; 0013 adds invited-reader filtered read access while reserving mutation for the owner. |
| [0008 — Preferred Edition](adr/0008-preferred-edition.md) | Accepted | Store selection as a user preference; never replace, archive, or delete other Editions when preference changes. |
| [0009 — Single-host staging topology](adr/0009-single-host-staging-topology.md) | Accepted | Deploy staging as PostgreSQL + one-shot migration + one API worker + unprivileged Nginx; publish only the proxy and never couple application rollback to an automatic database downgrade. |
| [0010 — Local library storage and atomic import](adr/0010-local-library-storage-and-atomic-import.md) | Superseded in part by 0017 | Keep Edition identity, append-only file revisions, atomic import/compensation, and coordinated backup; v0.9 removes compatibility for fileless Book/Edition placeholders. |
| [0011 — Safe reader projection, optimistic progress, and private series](adr/0011-reader-progress-and-series.md) | Accepted | Expose bounded sanitized Edition-local sections, synchronize per-Edition progress with optimistic versions and explicit conflict choice, and model private series as one optional ordered membership per Book. |
| [0012 — Credential, device, Passkey, recovery, and session authentication](adr/0012-credential-device-passkey-and-recovery-authentication.md) | Extended by 0017 | Retain rotatable credentials, server-secret-backed Devices, administrator Passkeys, restricted recovery, and database-checked Sessions; credential snapshots now also carry invited capabilities. |
| [0013 — Single-administrator library ownership and invited-reader visibility](adr/0013-single-admin-library-and-reader-visibility.md) | Superseded in part by 0017 | Keep the unique administrator library owner and filtered readable projection; selected invited credentials may now contribute under capability plus creator policy. |
| [0014 — Ant Design component foundation](adr/0014-ant-design-component-foundation.md) | Superseded in part by 0015 | Retain Ant Design 6, project tokens, CSS Modules, route-level dynamic imports, and the Reader's dedicated publication layer; only its warm visual-language clause is superseded. |
| [0015 — Quiet Trace UI/UX system](adr/0015-quiet-trace-ui-ux-system.md) | Accepted | Adopt 漫读 Quiet Trace branding, tokens, grouped responsive navigation, task-oriented Library and administration, and restrained Reader chrome without changing v0.5/v0.6 behavior contracts. |
| [0016 — Trusted-edge client IP, entry rate limiting, bounded challenge cleanup, and device-bound refresh](adr/0016-trusted-edge-rate-limit-and-device-bound-refresh.md) | Accepted | Restore the real client IP from the single trusted host edge, rate-limit the two public auth entries at Nginx, delete expired challenges in bounded batches, and require the device secret plus an allowlisted Origin for refresh. |
| [0017 — Credential capabilities and contributor-attributed library](adr/0017-credential-capabilities-and-contributor-library.md) | Accepted | Keep one library owner, attach immutable read/upload/translation capabilities to each invited credential, attribute durable content to its actual User, enforce creator-aware mutation, and remove fileless public creation. |
| [0018 — Private LinguaSpindle translation orchestration](adr/0018-private-linguaspindle-translation-orchestration.md) | Superseded in part by 0019 | Retain private HTTP orchestration, recoverable actor-scoped Runs and verified generated-Edition ingestion; 0019 replaces the operator-owned Provider-secret boundary. |
| [0019 — Reader-owned Provider credentials and private relay](adr/0019-reader-owned-provider-credentials-and-private-relay.md) | Superseded in part by 0020 | Retain encrypted reader-owned credential versions, exact Run binding, the private scoped Relay and no shared-key fallback; 0020 replaces the single fixed upstream and credential kind. |
| [0020 — Versioned reader-selected Provider routing](adr/0020-versioned-provider-routing.md) | Accepted | Let one current immutable reader credential version select OpenAI, DeepSeek, Kimi or an operator-allowlisted custom route and a live Provider-catalogue model while preserving scoped Relay authorization and exact Run binding. |

## Recording a decision

1. Add the next numbered file under `docs/adr/` (currently `0020`).
2. Record date, status, context, decision, and consequences.
3. Add a concise row to this index and update consolidated architecture or data-model docs.
4. Supersede an accepted ADR with a new ADR when reversing it; do not rewrite history to
   conceal the old decision.

Record decisions that constrain future work. Keep temporary implementation notes, task
progress, and code-level mechanics out of ADRs.
