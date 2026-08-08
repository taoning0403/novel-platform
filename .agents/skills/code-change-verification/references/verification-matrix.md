# Verification matrix

## Result contract

| Label | Meaning | Successful overall run |
| --- | --- | --- |
| `PASS` | Selected check executed successfully | Yes |
| `FAIL` | Selected check found a new defect or worsened quality metric | No |
| `SKIPPED` | Check was not selected for the changed surface | Neutral |
| `BASELINE FAILURE` | Reviewed historical debt still exceeds its target without worsening | Neutral |
| `BLOCKED` | Selected check lacked a required executable, service, or environment value | No |

Never collapse `SKIPPED` or `BLOCKED` into `PASS`.

## Diff routing

`verify.py` combines unstaged, staged, untracked, deleted, and commit-range paths. An explicit
`--base` takes precedence. GitHub pull requests use the base-branch merge-base; pushes use the
validated nonzero event `before` commit. For a new-branch all-zero `before`, the parent of the
oldest complete pushed commit is used after verifying `after == HEAD`, the final listed commit is
`HEAD`, and the listed commits belong to that history in order. Missing, truncated, duplicated, or
inconsistent event history is `BLOCKED`. All local work uses its tracking-upstream merge-base and
combines the entire commit range with staged, unstaged, untracked, renamed, and deleted paths.
Local work without that trustworthy upstream and initial history without an explicit base are
`BLOCKED`. Rename/copy and untracked-path parsing use NUL delimiters, including for unusual
filenames. `--all` selects every surface,
`--quality-only` selects the deterministic quality guard, repository Skill metadata, and
verification-tool selftests, and `--config-only` selects only configuration validation.

| Changed surface | Selected checks |
| --- | --- |
| Python, TypeScript, or TSX | quality ratchet, local import cycles, Python layer boundaries |
| `.agents/skills/**` | repository Skill structure and metadata |
| root `compose*.yml`/`compose*.yaml`, acceptance-support Compose YAML, `Dockerfile*`, or `.github/workflows/**` | Git whitespace plus deterministic configuration structure checks |
| `apps/web/**` or `packages/api-client/**` | Web lint, tests, production build |
| Server source or Server unit tests | Ruff lint, Ruff format check, mypy, unit tests |
| API routes, schemas, serializers, OpenAPI, or generated client schema | `pnpm api:check` |
| Server application/domain/infrastructure/API or integration tests | PostgreSQL integration |
| SQLAlchemy models, Alembic configuration/versions, or migration tests | migration integration |
| user-visible Web source, acceptance scripts, or `--user-visible` | acceptance |

PostgreSQL integration and migration checks parse `TEST_DATABASE_URL` without printing
credentials. After lowercasing, replacing hyphens with underscores, and splitting on underscores,
the database name must contain an independent `test` segment. Hosts `localhost`, `127.0.0.1`,
`::1`, and an empty host are local. Any other host additionally requires
`ALLOW_REMOTE_TEST_DATABASE=1`. Percent-decoded, case-insensitive query keys that can replace the
connection target—including `host`, `hostaddr`, `port`, `dbname`, `database`, `service`, and
`servicefile`—are rejected even when repeated. A missing or unsafe value is `BLOCKED`. Acceptance
is not inferred from a Web build.

Compose and GitHub workflow files are parsed as YAML and must have mapping roots plus their
required `services`, `on`, and `jobs` structures. Workflow parsing preserves GitHub's unquoted
`on` key despite PyYAML's YAML 1.1 boolean rules. When Docker Compose is installed, Compose files
also pass `docker compose config --quiet --no-interpolate`; root overlays are checked with
`compose.yaml`, while isolated acceptance-support Compose files are checked standalone. CI can run
this deterministic surface independently with `pnpm verify -- --config-only`.

## Quality ratchet

| Metric | Python | TypeScript / TSX |
| --- | ---: | ---: |
| File effective lines | 400 | 300 |
| Function effective lines | 60 | 60 |
| Cyclomatic complexity | 10 | 10 |
| Control-flow nesting depth | 4 | 4 |

Effective lines exclude blanks and comments. A violation is identified by
`path + symbol + metric`. The checked-in baseline records the current value:

- a new above-threshold key is `FAIL`;
- a value above its stored value is `FAIL`;
- an unchanged historical key is reported as non-blocking `BASELINE FAILURE`;
- a lower above-threshold value is `TIGHTEN` and blocks until the baseline is lowered;
- a removed or now-within-threshold key is `CLEANUP` and blocks until the stale entry is removed.

Normal checks compare the current tree and checked-in baseline independently against the trusted
Git revision. A baseline changed in the same pull request therefore cannot bless a new or worsened
metric. `--write-baseline` refuses the same regressions and records the trusted commit's timestamp,
so repeated generation from the same revision does not drift with wall-clock time. Normal checks
also require `generated_from.commit` to exist, be an ancestor of the trusted revision, and carry
its exact Git `%cI` timestamp.

The enforced thresholds, exclusions, allowed dependency edges, and reverse-edge categories are
separately compared with the policy recorded at the trusted revision. Raising a threshold, adding
an exclusion, adding an allowed edge, or dropping a monitored category is a failure even when the
current baseline is changed in the same commit. Policy tightening is allowed. The first checked-in
policy is restricted to one reviewed bootstrap commit and canonical digest.

## Explicit metric exclusions

Exclusions are metric-scoped and carry reasons in `quality-baseline.json`. Tests are not excluded
as a directory.

- Alembic version scripts: generated/linear migration shape; all four metrics excluded.
- `packages/api-client/src/schema.d.ts`: generated OpenAPI declaration; all four metrics excluded.
- SQLAlchemy `infrastructure/database/models.py`: file-length metric only.
- Pydantic `api/schemas.py`: file-length metric only.

Functions inside the two declarative Python modules still obey function length, complexity, and
nesting limits.

## Dependency gates

Python and TypeScript local import graphs must each contain zero cycles. Cycles are hard failures,
not ratcheted debt.

The Python domain may import only the domain or external packages; it must not depend on
application, infrastructure, API, worker, or composition modules. Infrastructure may not depend
on application except for this reviewed storage-port edge:

```text
novel_platform.infrastructure.storage.local
  -> novel_platform.application.library.storage
```

That edge lets the local adapter implement the application-owned storage protocol. Any other
infrastructure-to-application edge, every infrastructure-to-API edge, and every
application-to-API edge is a hard failure.

The accepted baseline records the exact sorted resolved `application -> infrastructure` and
`API -> infrastructure` edge sets. A newly added edge therefore cannot be hidden by deleting a
different edge. Removed edges require baseline cleanup before the check passes.

Sibling imports between Python scripts inside each `.agents/skills/*/scripts` directory participate
in the Skill cycle graph. They are deliberately kept separate from the Server graph and do not
change Server boundary or reverse-edge accounting.
