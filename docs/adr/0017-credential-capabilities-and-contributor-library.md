# ADR 0017: Credential capabilities and contributor-attributed library

- Status: accepted
- Date: 2026-07-23
- Extends: ADR 0012 for invited-reader authorization
- Supersedes in part: ADR 0010 for fileless compatibility and ADR 0013 for reader mutation

## Context

The v0.5.0-v0.8.0 shared-library model deliberately made every invited identity read-only. That
is too coarse for a small private site whose administrator may trust selected people to contribute
validated EPUB/TXT files or use a separately controlled translation service. A durable reader
identity must keep its attribution when its login credential is rotated, while the administrator
must be able to remove access immediately without rewriting content ownership.

The existing `owner_user_id` fields identify the one site library owner and are required for
isolation, backup, Series, and file integrity. They cannot also describe the person who uploaded or
generated a specific resource. Existing public metadata-only Book and Edition creation also permits
rows that cannot be read and complicates contributor and deletion rules. The site has not reached
1.0 and has no production user data that requires preserving that placeholder contract.

## Decision

Keep `site_settings.library_owner_user_id` and the existing content `owner_user_id` fields as the
single administrator library boundary. Record the durable contributor separately:

- `books.created_by_user_id` is the User that performed the first file-backed import;
- `book_editions.created_by_user_id` is the uploader or translation initiator;
- `stored_files.created_by_user_id` is the User that introduced the physical object;
- `library_imports.requested_by_user_id` is the User that initiated inspect/commit; and
- translation runs record their own `created_by_user_id` as defined by ADR 0018.

Responses expose only a safe contributor display name. They do not expose contributor User IDs,
usernames, credential hints, administrator notes, storage identifiers, or hashes. Book and Edition
responses include server-computed permission flags; clients never reconstruct authorization from a
role or contributor identifier.

Store invited-reader capabilities as an immutable snapshot attached to each
`ReaderAccessCredential`:

- `library.read` is mandatory for every issued invited-reader credential;
- `library.upload` permits validated file-backed contribution and management of the actor's own
  uploaded resources; and
- `translation.use` permits translation of a readable TXT source and management of the actor's own
  translation runs and generated Editions.

Capabilities are normalized rows keyed by credential and capability. They are neither User roles,
JWT claims, raw-credential encodings, nor frontend state. Every protected request reloads the
current Session, authentication basis, and capability rows. The sole administrator receives the
full effective capability set without a ReaderAccessCredential. Recovery Sessions receive none.
Capability changes require credential reissue, which immediately revokes the replaced credential,
Devices, Sessions, and Refresh Tokens while leaving User-keyed attribution intact. Existing
credentials migrate with `library.read` only; unknown, duplicate, or read-less capability sets are
rejected.

Authorization has two mandatory layers: the current Session must be the administrator or hold the
required capability, and the application service must enforce library owner, contributor, state,
dependency, active-operation, and file-reference rules. A visible resource denied for mutation
returns a stable 403; an invisible private resource remains 404.

The v0.9 resource policy is:

- `library.upload` may create a Book through a validated import, add an Edition to a visible Book,
  and replace/edit/delete only the actor's uploaded resources;
- `translation.use` does not imply arbitrary upload and may manage only the actor's generated
  resources and runs;
- Series, raw downloads, publication state, and management of another contributor remain
  administrator-only;
- a contributor may delete a Book only while every retained Edition and translation run belongs to
  that User and no active import, run, source/supersedes dependency, or file-reference conflict
  exists; and
- deleting a ready Edition clears all users' preferences/progress that reference it before precise
  unreferenced-file cleanup. Translation-run history is retained when a generated Edition is
  removed.

Remove the public metadata-only Book and Edition POST routes, request schemas, Web client methods,
and legacy forms. Internal Book/Edition creation remains reusable by atomic import and generated
ingestion. New product content must originate from a validated EPUB/TXT import or a verified
LinguaSpindle artifact.

The v0.9 migration backfills contributor fields from the unique library owner, grants retained
credentials only `library.read`, deletes Editions with no `edition_files`, and then deletes Books
with no file-backed Edition. It must first report counts without content or paths and fail closed
unless v0.5 conversion is complete, exactly one owner exists, no active import exists, and file
references are consistent. Physical files are never deleted by SQL path matching. Production
recovery after this destructive migration is a coordinated PostgreSQL and library restore, not an
automatic downgrade.

## Consequences

- Invited contribution is explicit, revocable, least-privilege, and independent of credential
  rotation.
- Library ownership, backup, Series, and storage isolation remain single-administrator concerns.
- Upload and translation are independent capabilities; holding both grants their union, never
  access to another contributor's resources.
- Fileless Book/Edition compatibility is intentionally removed and historical acceptance remains
  immutable evidence of the superseded contract.
- Tests and acceptance must cover capability forgery, reissue invalidation, actor isolation,
  cross-contributor deletion conflicts, destructive migration preflight, and orphan-free cleanup.
