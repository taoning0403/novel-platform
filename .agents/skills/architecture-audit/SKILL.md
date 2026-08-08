---
name: architecture-audit
description: Perform read-only architecture audits in novel-platform before repository-wide refactors, module splits, dependency-direction changes, large-file remediation, or boundary reviews. Use for planning, review, and version-controlled reporting across apps/server, apps/web, packages/api-client, migrations, tests, and generated contracts; inventory responsibilities, size, complexity, dependencies, cycles, test protection, and compatibility boundaries while separating facts, inferences, and recommendations. Do not implement refactors or change business behavior without an explicitly authorized implementation task.
---

# Architecture Audit

Audit the current repository before proposing structural change. Treat maintained documents as
navigation aids and verify every material claim against current code, configuration, tests, or
command output.

## Establish scope

1. Invoke `$repo-context` and follow `AGENTS.md`.
2. Read [repository-boundaries.md](references/repository-boundaries.md).
3. Inspect `git status --short`, the current branch, recent commits, and pre-existing changes.
4. Name the modules, interfaces, data, and test surfaces in scope.
5. State that the audit is read-only. Do not edit business code, move files, rename symbols,
   regenerate contracts, run migrations, or install dependencies.

Stop and report the limitation when required evidence depends on an unavailable service, isolated
database, or tool. Do not invent results or install a replacement during an audit.

## Collect evidence

Run the deterministic source inventory from the repository root:

```bash
apps/server/.venv/bin/python \
  .agents/skills/architecture-audit/scripts/source_inventory.py --root .
```

Use `--format json` when another tool must consume the output. The script reads source files only;
it does not modify the repository or enforce policy. On Windows, use
`apps\server\.venv\Scripts\python.exe`. If the existing environment is absent, use another
already-installed Python 3.12 or newer; do not create an environment or install dependencies
during a read-only audit.

Then inspect only the responsible modules and:

- trace entry points, callers, public exports, API contracts, persistence models, migrations, and
  nearby tests;
- identify module responsibilities and dependency directions before judging file placement;
- check static import cycles, cross-layer edges, duplicate implementations, long functions,
  complexity, file size, and test concentration;
- distinguish generated artifacts, declarative schemas, migrations, fixtures, and ordinary
  behavior code;
- run only existing, non-mutating static or collection checks needed to verify a claim;
- record the exact command, working directory, exit status, and boundary of every check.

Do not treat a successful test collection, a skipped integration suite, an old CI result, or a
maintained context document as proof that current runtime behavior passed.

## Assess responsibilities

Evaluate whether a file contains multiple independently changeable responsibilities, coordinates
too many boundaries, or lacks a testable seam. Do not infer that a file must be split merely
because it exceeds a line threshold. Large declarative models, schemas, parsers, and cohesive
protocol adapters may be valid; small files may still create damaging dependency direction or
duplication.

Prefer a responsibility boundary supported by callers, invariants, failure handling, and tests.
Reject mechanical extraction into vague `utils`, `helpers`, `common`, `misc`, or similarly
unowned modules.

## Separate findings

Label every material item:

- **Fact**: directly supported by a path and line, configuration value, generated inventory, or
  command result.
- **Inference**: a reasoned risk or likely responsibility boundary; state uncertainty and the
  facts it depends on.
- **Recommendation**: a candidate action with intended benefit, compatibility constraints,
  characterization tests, verification route, and rollback scope.

Never present an inference or recommendation as an accepted architecture decision. Consult
`docs/DECISIONS.md` and linked ADRs before recommending a durable boundary change.

## Report

Write or update a version-controlled report only when the task authorizes documentation changes.
Use `docs/architecture/refactor-baseline.md` for the repository-wide baseline. Include:

- audit scope, revision, method, exclusions, and unverified surfaces;
- current architecture and compatibility boundaries;
- actual validation commands and known failures or skips;
- file-size, function-length, complexity, dependency, and cycle evidence;
- test protection and weak seams;
- baseline thresholds that preserve existing exceptions without permitting new regressions;
- prioritized candidates explicitly marked as proposals, not approved decisions.

Preserve prior measurements when they remain useful and date new evidence. Do not replace
historical evidence with a stronger claim than the command actually proves.

## Stop boundary

End after delivering the audit unless the user explicitly authorizes an implementation task.
Do not begin refactoring, create compatibility shims, change quality rules, weaken tests, or
reinterpret acceptance criteria as part of the audit.
