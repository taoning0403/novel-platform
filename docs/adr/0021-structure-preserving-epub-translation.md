# ADR 0021: Structure-preserving EPUB translation

- Date: 2026-07-27
- Status: Accepted
- Extends: ADR 0018 for private LinguaSpindle orchestration
- Preserves: ADRs 0019 and 0020 for reader-owned credentials, scoped Relay execution and
  version-bound Provider routing

## Context

ADR 0018 deliberately limited the first Novel Platform translation surface to current-file TXT
sources even though LinguaSpindle already had a bounded, structure-preserving EPUB 2/3 Pipeline.
The private Relay and opaque credential-scope work now provide the same per-Run Provider boundary
for any LinguaSpindle Pipeline containing Provider Steps. Adding EPUB does not require another
task system, Provider path or third-party EPUB translation service.

Flattening EPUB to TXT would lose package structure and make links, navigation and resources
impossible to verify. Importing a remote EPUB without local validation would also bypass Novel
Platform's existing archive, XML and DRM checks.

## Decision

Novel Platform supports whole-book asynchronous translation of a readable, `ready`, current-file
source Edition when that file is either TXT or a common valid, unencrypted EPUB 2/3.

The LinguaSpindle contract is selected from one format mapping:

| Source | Upload media type | Pipeline | Required final Artifact |
| --- | --- | --- | --- |
| TXT | `text/plain` | `novel_txt_v1` | `novel_export_txt` / `text/plain` / `.txt` |
| EPUB | `application/epub+zip` | `novel_epub_v1` | `novel_export_epub` / `application/epub+zip` / `.epub` |

The Run fixes the source format alongside its EditionFile, revision and SHA-256. Its non-secret
configuration snapshot and fingerprint include the selected Pipeline version and source format.
EPUB keeps its original filename for the private Project upload. TXT retains the deterministic
revision filename.

The browser still calls only Novel Platform. The Server still creates one identity-free
LinguaSpindle Project and Job using the exact Run-bound opaque credential scope. LinguaSpindle
still calls only the private Relay, and the Relay still resolves the reader-owned credential
version and exact Provider route. No raw key, User identity or Novel Platform domain object enters
LinguaSpindle.

Only a succeeded Job with exactly one format-matching final Artifact may be ingested. Novel
Platform checks Project/Job association, kind, media type, extension, nonzero size, bounded
download size and SHA-256. EPUB output is then reopened with the existing bounded EPUB inspector;
unsafe archives, unsupported encryption/DRM, invalid package structure and a target-language
mismatch are rejected. A valid EPUB produces one `edition_source` StoredFile and no normalized
TXT file. A valid TXT continues to retain the downloaded source plus normalized UTF-8 file.

Successful output creates a new creator-previewed `draft + translation + ai + generated` Edition.
It never overwrites its source, an earlier translation or reading progress. Only the administrator
may publish it. Partial, failed, ambiguous, corrupt or locally invalid output creates no Edition.

Alembic `20260727_0009` widens the Run `source_format` check from TXT to `epub | txt` without
rewriting existing rows. Downgrade refuses while any EPUB Run exists rather than deleting or
mislabeling durable orchestration history.

## Consequences

- EPUB preserves LinguaSpindle's spine, navigation, links and non-text resources instead of
  creating a flattened derivative.
- Translation availability is format-specific; the Web asks for the current source format and
  displays the selected Pipeline and output contract.
- Existing capability, creator, idempotency, retry, cleanup, credential, Relay and publication
  rules apply unchanged to TXT and EPUB.
- Novel Platform adds no Calibre runtime, GUI plugin, external EPUB service, second Job model or
  additional Provider-key path.
- DRM bypass, broad invalid-publisher repair, chapter selection, proofreading/editing, bilingual
  output, terminology memory, manga and other document formats remain out of scope.
