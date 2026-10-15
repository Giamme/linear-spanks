# Codebase Analysis

Load this reference only when the compiled execution envelope contains `repository_scan`.

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

## Staged scan

Execute at most one stage per agent session:

1. `inventory`: collect compact language, manifest, directory, entry-point, test, documentation,
   and Git-history metadata. Select files deterministically by manifest/entry-point priority,
   dependency adjacency, tests, then normalized path. Create stable batch IDs.
2. `shard-analysis`: read one bounded subsystem or dependency-adjacent batch. Produce normalized
   evidence capsules, validate the checkpoint, persist it, and release raw code context.
3. `synthesis`: reduce capsules into a current architecture and capability model. When capsules
   exceed one working-context packet, reduce deterministic capsule batches into a compact index and
   merge those indexes while retaining the original capsule IDs and pointers. Never load all
   capsules at once or replace evidence with an uncited summary of a summary.
4. `preview`: render `codebase-import-proposal.md` with the exact proposed Linear project and
   milestone operations. Stop for approval.
5. `apply`: re-read the repository revision and Linear target, reject drift, apply only approved
   operations with per-operation identity, then read back every artifact.
6. `complete`: report links, coverage, confidence gaps, source revision, and the next command.

Use `scan-checkpoint` before every resume. If the current revision differs from the checkpoint,
return `REPOSITORY_DRIFT`; reuse only capsules whose source hashes and dependency inputs are still
valid, then rescan changed and dependency-affected shards. Resume with
`codebase analyze <repository-path> --resume <checkpoint> --scan <tier>`; the tier must match the
checkpoint unless the command starts a new run and reports the changed scope.

## Evidence capsules

Each capsule uses the contract schema and contains responsibilities, public interfaces,
dependencies, implemented capabilities, tests/verification, known gaps, evidence pointers, source
hashes, and confidence. Store conclusions and pointers, never raw source or secrets. Evidence
pointers should identify a repository-relative path plus a symbol or line, or an exact commit.
Completion findings are stored separately in every checkpoint with classification, verification
evidence, pointers, and confidence so historical status cannot drift during resume or synthesis.

## Import synthesis

Reconstruct the project description as a current-state product and architecture baseline. Propose
three to seven outcome-oriented historical milestones rather than milestones per file, module, or
commit. Keep future roadmap milestones separate.

Classify every historical outcome:

- `verified-delivered`: current code plus fresh successful verification supports completion.
- `implemented-unverified`: implementation evidence exists but fresh verification is absent or
  failed.
- `historical-inferred`: Git or documentation suggests the outcome, but current behavior is not
  established.

Only `verified-delivered` outcomes may be proposed as completed, and never save that status without
explicit approval. Preserve the other classifications in the milestone description and leave them
open or unstarted according to the approved preview.
