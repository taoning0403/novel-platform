---
name: code-change-verification
description: Verify novel-platform changes with diff-routed Web, Server, API, PostgreSQL, migration, acceptance, quality-ratchet, dependency-cycle, and architecture-boundary checks. Use after implementing, refactoring, reviewing, or preparing CI for changes in this repository. This Skill reports evidence; it does not fix failures, tamper with baselines, install dependencies, or deploy.
---

# Code Change Verification

Verify the changed surface without weakening tests or treating an unavailable prerequisite as a
pass.

## Run the verifier

Run from the repository root:

```bash
pnpm verify
```

Use the narrowest explicit override that still proves the requested outcome:

```bash
pnpm verify -- --quality-only
pnpm verify -- --config-only
pnpm verify -- --all
pnpm verify -- --user-visible
pnpm verify -- --base origin/develop
```

`--quality-only` runs the quality/dependency guard plus repository Skill validation; it skips
product lint, tests, builds, database checks, and acceptance. It also runs the verification
tooling's stdlib regression suite.

`--config-only` validates all current repository configuration routes plus changed/deleted routes.
It parses Compose and workflow YAML, checks required structure, runs Docker Compose configuration
validation when the CLI is available, and skips every product runtime gate.

Treat the result labels literally:

- `PASS`: the check ran and succeeded.
- `FAIL`: the check ran and found a new defect or a worsened metric.
- `SKIPPED`: the check was not selected for this change.
- `BASELINE FAILURE`: an unchanged historical metric remains above its target and is contained by
  the reviewed baseline.
- `BLOCKED`: a selected check could not run because a prerequisite is unavailable.

Never report `SKIPPED` or `BLOCKED` as passing. `BASELINE FAILURE` is neutral in the overall exit
status but remains visibly distinct from `PASS`.

Before PostgreSQL integration or migration checks, provide a `TEST_DATABASE_URL` whose normalized
database name contains a standalone `test` segment. Local hosts are accepted; a remote host also
requires `ALLOW_REMOTE_TEST_DATABASE=1`. Query parameters may not override the connection target;
encoded, repeated, or case-varied target keys are rejected without printing the URL or credentials.

## Maintain the ratchet

Run the quality guard directly when diagnosing a baseline failure:

```bash
uv run --project apps/server python \
  .agents/skills/code-change-verification/scripts/quality_guard.py
```

Regenerate the baseline only after reviewing why every remaining violation is historical:

```bash
uv run --project apps/server python \
  .agents/skills/code-change-verification/scripts/quality_guard.py --write-baseline
```

Review the JSON diff. Do not add an exclusion or raise a threshold to make a failure pass. Remove
stale baseline entries when the guard prints `CLEANUP`; lower stored values when it prints
`TIGHTEN`. Both are failures until the checked-in baseline is updated. The guard compares current
sources and any proposed baseline to a trusted Git revision, so rewriting the baseline in the same
change cannot bless a new metric regression or reverse dependency. `--write-baseline` also refuses
those regressions. A historical `BASELINE FAILURE` is non-blocking, but it is not evidence that the
metric meets the target.

The baseline provenance commit must exist, be an ancestor of the trusted comparison revision, and
carry that commit's exact Git `%cI` date. Local work, whether dirty or clean, uses the
tracking-upstream merge-base and combines committed plus worktree changes; without a trustworthy
upstream it is `BLOCKED` until `--base` is supplied. Pull requests use the base merge-base and
ordinary pushes use a valid nonzero `before`. For a new-branch zero `before`, the verifier requires
the complete push sequence and requires its `after` revision to equal `HEAD`, then uses the parent
of the oldest pushed commit. A truncated or inconsistent event and initial history are `BLOCKED`.

Thresholds, exclusions, allowed dependency edges, and monitored reverse-edge sets are also
compared with the policy stored at the trusted revision. A same-change threshold increase,
exclusion addition, or allowed-edge addition therefore fails even if the current baseline is
edited with it. The initial introduction is restricted to the reviewed bootstrap commit and
policy digest.

## Validate Skill metadata

After changing any project Skill, run:

```bash
uv run --project apps/server python \
  .agents/skills/code-change-verification/scripts/validate_skills.py
```

Read [references/verification-matrix.md](references/verification-matrix.md) when changing routing,
thresholds, exclusions, dependency rules, or the interpretation of a result.
