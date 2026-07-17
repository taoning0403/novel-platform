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

## Committed boundary

There is no committed post-v0.7.0 milestone. New durable behavior requires an explicit task,
incremental acceptance criteria, and any necessary ADR before implementation.

## Reserved future increments

Candidate later work, not committed:

1. Consider annotations/export and traceable editing/retranslation in a later milestone.
2. Consider optional source comparison without making normal reading depend on a source link.
3. Evaluate object storage, a worker, and a queue only when measured workloads justify them.
4. Add client-supplied LLM credentials only after a reviewed security model.
5. Evaluate native clients only after their secure credential and offline synchronization model is
   designed.

Every increment must preserve the unique administrator owner, invited-reader isolation,
independent translations, and normal use of a translation without a source link. Do not begin
another milestone without an explicit task and the necessary ADRs.
