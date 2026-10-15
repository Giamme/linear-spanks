# Parallel milestone execution

Parallel execution is an explicit two-command workflow. Linear `blockedBy` relations remain the
authority for business dependencies. The managed milestone graph is a revision-bound projection
that adds plan-derived serialization edges; it never writes synthetic blockers back to Linear.

`project run` composes this authority rather than creating a second scheduler. Each milestone
orchestrator selects one fixed reviewed ready frontier, uses isolated worktrees, defaults to two
workers, and enforces the shared hard maximum of eight. Multiple milestone orchestrators may run
independent frontiers concurrently, but a task belongs to only one frontier and active receipts
reserve every selected issue. Newly unblocked tasks wait for a later project event.

## Optional single-task isolation

`task run` and `task next --isolated-worktree` use the same isolation authority as waves for
one issue. `milestone run --mode step --isolated-worktree` is valid only when its resolved next stage is
`start-implementation`; reject it with `ISOLATION_NOT_APPLICABLE` before any other stage mutation.
`wave implement` is always isolated, so the flag is an idempotent assertion. Reject it for every
other command, including `wave reconcile`.

Run `isolation preflight` before claims or Git writes. Require `.linear-spanks-git.yml`, an
absolute safe `parallel-worktree-root` outside the repository, a clean attached current branch, a
current plan, and unused branch/path targets. Only one active receipt may exist for an issue and
plan revision. The same flagged command resumes one receipt automatically; multiple receipts stop
with `ISOLATION_RECEIPT_AMBIGUOUS` and their IDs.

Claim serially, persist `prepared`, move In Progress, then create
`linear-spanks/run-<run-id>/<issue-id>` from the exact parent HEAD with a clean worktree below the
configured root. The executor writes, verifies, and commits only there. Persist receipt transitions
through `prepared`, `executing`, `verified-pending-integration`, `integrating`, and `integrated`, or
`failed`. Bind command, issue, plan revision, trace source hash, parent branch/baseline, worktree paths,
child branch/commit, verification, preview approval, integrated HEAD, completion read-back, and
timestamps.

After child verification, show one exact preview with current parent HEAD, child commit, `--no-ff`
merge, verification, cleanup, and Linear completion writes. A decline or interruption retains the
worktree and leaves the receipt pending. Re-read every binding after approval. Same-branch parent
advancement requires a fresh preview; plan revision or material consumed-surface/dependency drift
returns `REPLAN_REQUIRED`, while trace source drift does not. Conflicts and failed integration
verification preserve the parent, receipt, child, and Linear In Progress state.

Merge in a temporary integration worktree, rerun required verification, then fast-forward the
clean parent. Only afterward persist completion, mark Done, read the issue and newly unblocked
relations, and record `integrated`. Remove the worktree only after that receipt is durable; preserve
the child branch without pushing or opening a PR. If the child is already an ancestor of the
current parent, verify ancestry and the current parent, rerun verification, and record recovered
integration before Linear completion.

## Persistent dependency graph

After `task plan`, every successfully reconciled task in `milestone plan`, and `task replan`, rebuild
the milestone graph with `dependency-graph-build`, render it with `dependency-graph-render`, and
replace the one managed `## Dependency graph` block. Preserve all other milestone text and the
separate workflow-state marker. Re-read the milestone immediately before the write. On revision
drift, re-read and re-derive once; a second mismatch returns `DEPENDENCY_GRAPH_DRIFT`.

Every plan supplies an execution footprint: repository identity, canonical repository-relative
write scopes, exclusive resources, a `parallel_safe` decision, and a serialization rationale.
Unknown scopes, repository mismatches, unsafe tasks, overlapping paths, or shared exclusive
resources create deterministic dashed serialization edges. `milestone review` validates live
blockers, plan revisions, footprints, cycles, source hashes, and graph hashes before changing the
graph from `unreviewed` to `reviewed`.
Until a task is planned, represent it with plan revision zero and an unknown empty write scope so
the incremental graph remains conservative and serializes it. A reviewed graph requires every
task to have a positive current plan revision.

## `wave implement`

Require a current reviewed graph, milestone stage `milestone-reviewed` or `implementing`, current
plans, live blocker readiness, at least two compatible ready tasks, harness capacity of at least
two, and a clean current branch. Default to two workers; accept `--max-parallel 2..8` and clamp to
the ready frontier and reported capacity. Select with `wave-select` using the validated graph, a
complete freshly read Linear status matrix, and issue IDs already reserved by active receipts;
persist a validated wave
receipt before any claims or Git writes.

The clean current branch and HEAD are the immutable wave parent and baseline. Create every child
as `linear-spanks/wave-<wave-id>/<issue-id>` from that exact HEAD, with one new clean worktree per
task under the absolute safe sibling root configured by `parallel-worktree-root` in
`.linear-spanks-git.yml`. Bind the root in the receipt and reject any worktree or cleanup target
outside it. Claim selected issues serially and read the claims back.
A lost claim is skipped without replacement. Launch one executor per remaining worktree. Executors
may edit and commit only inside their assigned worktree; they never merge and never mark issues
Done. Successful tasks end as `verified_pending_integration`. Let independent siblings finish
after a failure, retain their evidence, and block another wave until failures are resolved.

One invocation executes one fixed frontier. Do not add newly unblocked downstream tasks to the
same run. If capacity is below two, return `PARALLEL_CAPACITY_UNAVAILABLE`. If fewer than two
compatible tasks are ready, return `NO_PARALLEL_WAVE` and recommend `task next`.

## `wave reconcile`

Re-read the graph, plans, receipt, child heads, and clean current parent. Present the exact ordered
integration set, parent HEAD, planned merge commits, cleanup, and verification, then obtain one
approval. Any bound drift invalidates that approval.

Create a temporary clean integration branch/worktree from the parent. For each child in stable
order, create a candidate from the current integration head, merge the child with `--no-ff`, and
run that plan's required verification. Advance the integration head only for a clean candidate.
Preserve conflicts or failures and continue with independent siblings. Run combined verification,
then fast-forward the parent only if it passes; otherwise leave the parent unchanged and retain a
resumable receipt.

After parent integration, write completion receipts, mark only integrated issues Done, read them
back, and read newly unblocked relations. Then remove successful clean task worktrees. Preserve
child branches by default. `--delete-merged-branches` permits deletion only after ancestry and
receipt checks. Always retain failed branches and worktrees.

Inside `project run`, the milestone orchestrator performs the same preview, drift re-read,
temporary-worktree merge, verification, parent advancement, Linear completion, and cleanup
sequence. Task executors and task verifiers never integrate or mark Done. Failed execution,
verification, merge, or combined verification leaves the parent and Linear Done state unchanged.
