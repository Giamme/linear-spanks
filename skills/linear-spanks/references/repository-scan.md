# Repository scan evidence

Bounded repository resolution, scan tiers, and evidence capsules for commands that read a
working tree. Staged scans and import synthesis belong to the `codebase` namespace; see
[codebase analysis](codebase-analysis.md).

## Repository resolution and safety

Resolve one repository root and its current Git revision before reading source. If Git is absent,
derive a stable source revision from the selected file paths and content hashes. Never follow
symlinks, read outside the resolved root, or read secret-pattern files. Respect `.gitignore` and
the contract exclusions for dependency, generated, build, cache, binary, and VCS content. Report
every exclusion class and any unreadable paths in coverage; never silently count them as analyzed.

Checkpoint artifacts may be written only below the resolved repository, defaulting to
`.linear-spanks/checkpoints/codebase/<run-id>/`. `codebase analyze` invocation authorizes these
artifacts but no source or Linear mutation. For `codebase import`, invocation authorizes checkpoint
artifacts; the rendered project and milestone preview requires a separate approval before Linear
writes.

## Scan tiers

Compile the selected tier into the execution envelope with:

```bash
python3 scripts/linear_spanks_cli.py contracts envelope <namespace> <command> --scan <fast|medium|heavy>
```

- `fast`: inventory plus high-signal manifests, docs, entry points, interfaces, representative
  tests, and recent history. It is intentionally partial.
- `medium`: dependency-aware coverage of every major subsystem with broader tests, configuration,
  and sampled history across bounded batches.
- `heavy`: deterministic coverage of every eligible file that fits the heavy total-scan limits,
  deeper history, and resumable evidence capsules. Return `CONTEXT_OVERFLOW` when eligible evidence
  exceeds the heavy cap; do not imply exhaustive coverage.

The tier raises total coverage, batch count, history, and capsule budgets. It may modestly raise
working context, but raw evidence from multiple batches must never accumulate in one prompt. Build
the exact packet and validate it with `context-packet --scope repository --scan <tier>`.

For orchestrated planning or execution commands, repository scanning is a preprocessing stage.
The planner receives evidence capsules and pointers within its independent planner budget; it does
not inherit the scan tier's raw-source allowance. Temporary context-packet files may contain raw
batch text for measurement and must be released with that batch. Only capsules and checkpoints are
durable.

## Evidence capsules

Each capsule uses the contract schema and contains responsibilities, public interfaces,
dependencies, implemented capabilities, tests/verification, known gaps, evidence pointers, source
hashes, and confidence. Store conclusions and pointers, never raw source or secrets. Evidence
pointers should identify a repository-relative path plus a symbol or line, or an exact commit.
Completion findings are stored separately in every checkpoint with classification, verification
evidence, pointers, and confidence so historical status cannot drift during resume or synthesis.
