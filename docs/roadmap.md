# Roadmap

## Completed baselines

- v0.1.0: Book and independent Edition metadata, relationship rules, management UI,
  PostgreSQL migration, quality gates, Compose startup, and persistence acceptance.
- v0.2.0: local Users, Devices, revocable Sessions, rotating hashed Refresh Tokens, private
  Book ownership, preferred Edition, generated OpenAPI types, and browser isolation acceptance.
- v0.3.0: owner-scoped EPUB/TXT inspection/import, Edition file revisions, protected downloads,
  local file persistence, complete backup/restore, and browser upload/version acceptance.
- v0.4.0: safe Edition-local EPUB/TXT reader, synchronized per-Edition progress and user reader
  settings, recent/continue surfaces, private ordered series, partial-success series upload, and
  responsive browser acceptance.
- v0.5.0: one administrator-owned shared collection, invited-reader filtered access and private
  state, rotatable reader credentials, server-authorized devices, administrator Passkeys and
  restricted recovery, filing-friendly public entry, explicit migration, and v0.5 acceptance.
- v0.6.0: Ant Design 6 interaction foundation, project theme tokens, desktop/mobile App Shell,
  page-level lazy loading, CSS Module style boundaries, responsive page migration, preserved
  Reader presentation, and v0.6 visual/bundle acceptance.
- v0.7.0: formal 漫读 identity and Quiet Trace design system, simplified login, grouped
  desktop/mobile navigation, cover-led library and filter workflow, reader-management
  master-detail, restrained responsive Reader chrome, and v0.7 acceptance with preserved
  authentication, authorization, API, and data contracts.
- v0.8.0: trusted-edge real client IP restoration, public authentication-entry rate limiting,
  device-secret-bound refresh, allowlisted cookie-refresh Origin, bounded WebAuthn challenge
  cleanup and SameSite=Strict staging/production Cookies.
- v0.9.0: immutable invited credential capabilities, durable contributor attribution,
  creator-aware upload/delete policy, removal of fileless creation, and actor-scoped private
  LinguaSpindle v0.3.1 TXT translation into creator-preview/admin-publish generated Editions.
- v0.10.0: immutable AES-256-GCM-encrypted reader-owned OpenAI-compatible credential versions,
  exact Run-to-version binding, sanitized Provider token usage, opaque LinguaSpindle v0.3.2
  credential scopes, and a private Relay with no administrator/shared-key fallback.

## Current committed milestone

- Post-v0.10 Provider routing increment: one current immutable configuration per translating User,
  with OpenAI, DeepSeek, Kimi and operator-allowlisted custom OpenAI-compatible choices; v2
  authenticated routing metadata; live Provider model-catalogue selection without product
  defaults; and Relay selection from the exact Run-bound version.

The implementation, focused verification, revision-0008 migration and external deployment
verification must be consolidated before assigning the next release version.

## Committed boundary

ADR 0020 defines the current increment. Further durable behavior requires an explicit task,
incremental acceptance criteria, and any necessary ADR before implementation.

## Reserved future increments

Candidate later work, not committed:

1. Consider annotations/export and per-chapter translation review/editing in a later milestone.
2. Consider optional source comparison without making normal reading depend on a source link.
3. Evaluate object storage, a worker, and a queue only when measured workloads justify them.
4. Consider EPUB/manga translation, site-funded translation, per-Run Provider selection or
   automatic Provider failover only after explicit scope, threat-model and cost/data-egress
   review; keep upstream keys write-only/encrypted and out of Browser/LinguaSpindle public state.
5. Evaluate native clients only after their secure credential and offline synchronization model is
   designed.

Every increment must preserve the unique administrator owner, database-backed capability plus
resource-creator checks, invited-user/private-state isolation, independent Editions, no shared-key
fallback, and the private Server → LinguaSpindle → Relay boundary. Do not begin another milestone
without an explicit task and the necessary ADRs.
