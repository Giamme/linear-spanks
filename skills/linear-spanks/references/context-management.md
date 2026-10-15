# Context Management

Treat the execution envelope as a hard input contract. Build a JSON context packet with `items`
(the exact text sent to the agent) and `metrics` (arrays of selected entity IDs or raw-log
fragments keyed by the profile limit), then run `linear_spanks_cli.py context packet <namespace> <command>
<packet.json>`. The tool measures UTF-8 text and every metric array itself; do not hand-enter
counts for a real run.
If a limit is exceeded, return `CONTEXT_OVERFLOW`, identify the overflowing section, and reduce or
shard it before continuing. Never silently omit required evidence.

## Retrieval order

1. Read compact identity, state, revision, and relation fields first.
2. Fetch full text only for the selected target and entities whose state or contract can change the
   command result. For missing native prerequisites after milestone prune, follow the managed
   milestone/dependency archive reference and use `context archived-task` for selected terminal
   outcome rows before workflow/graph selection. Missing IDs without that binding remain errors;
   never infer completion or load the whole archive into dispatch context.
3. For a consolidated task, read its canonical per-type comments and any later changes; do not
   load the task archive or obsolete snapshot Documents by default. The archive is historical,
   expanded only for a named source/section when needed.
   Read the authoritative current plan; do not load superseded plan revisions into active context.
   Each managed type owns one comment slot. Resolve it with `context task-comment-slots` and write
   through `context task-comment-slot`, which returns an in-place update for an occupied slot and a
   create only for an empty one. Slots are keyed by the managed marker, never by comment position:
   human comments and thread replies interleave with managed ones. Two comments claiming one type
   return `TASK_SLOT_AMBIGUOUS`; run `task checkpoint` to consolidate them. Each edit keeps a
   bounded superseded-revision summary in the comment, and the exact prior bodies stay in the task
   archive. If comment updates are unavailable, append a revision marker containing revision and
   superseded comment ID, select the highest valid revision from compact comment metadata, and
   expand only that comment.
4. Select siblings only when they share an input, output, dependency, or touched interface.
5. Select learning entries by matching tag and impacted area. Respect the envelope limit.
6. Summarize raw verification logs as command, exit status, short diagnostic, and artifact link.

When an `Active Project Context` document exists, use it as a retrieval index. Select only the
target's Active Frontier row, relevant decisions, resource links, and resume provenance. Do not
inject the whole document into every task. If the connector cannot project the needed sections,
count the full document against the command token and full-entity limits.

If the connector cannot project compact fields, use an isolated read worker when the runtime
supports one and return only the normalized contract row. Otherwise count the full entity against
`max_full_entities` or the corresponding full-entity limit and stop on overflow.

For blocker traversal, compact status rows count toward `max_blocker_nodes`. Fetch full blocker text
only for unfinished blockers or blockers whose output contract is consumed by the target. Stop at
`max_blocker_depth`; if correctness requires going beyond a limit, report overflow instead of
guessing.

## Planning and worker handoffs

For optimized task commands, compile `execution-brief`. Fast/balanced use its self-contained
runtime card instead of injecting overlapping references. Strict restores the full reference
packet. Keep `execution-envelope` for full diagnostics.

The planner has a separate repository-read budget under `orchestration.planner.context`. Validate
it with `context-packet --scope planner`; it does not borrow unused tokens or entity counts from
the command context. Return only the structured plan packet to the coordinator.

The executor receives the current plan/source revisions, stable task contract, relevant blocker
outputs, selected skills, repository evidence pointers, acceptance criteria, required verification,
selected tier, and replan conditions. Do not copy raw planner exploration, superseded plans, or
unrelated Linear threads into the worker context.

For `project run`, construct four distinct packets and validate every transfer with
`role-handoff-check`:

- project orchestrator: project spec, compact milestone ledger, selected documents and indexed
  learnings, capped at 60,000 input tokens and containing no repository evidence
- milestone orchestrator: one milestone contract, compact task matrix, dependency graph, current
  plans, selected decisions/learnings, and bounded source-read evidence, capped at 100,000 tokens
- task executor: one task, compact milestone objective, current plan, blocker outputs, assigned
  worktree, latest verifier findings, and verification commands, capped at 120,000 tokens
- task verifier: one task, compact milestone criteria, current plan, exact candidate diff,
  completion handoff, verification ledger, and verification commands, capped at 120,000 tokens

Every role ceiling is the authority in `project-orchestration-contract.json`; these figures track it.

Do not forward raw role transcripts. Persist compact handoffs and verifier ledger updates, then
release the role context at the event boundary.

For `milestone run --mode loop`, construct only the milestone orchestrator and scoped task-pair packets;
validate each transfer with `role-handoff-check --orchestration milestone` and keep the project
receipt/document index out of worker context.

Fast uses compact briefs and direct caps. Balanced requires exact measurement for repository
batches, large matrices, and near-limit packets. Strict preserves exact command, planner, and
repository packets. Repository scans are always exactly measured under every assurance profile.

## Milestone reviews

Build one compact task-contract matrix containing task ID, state, blockers, inputs, outputs,
acceptance digest, plan revision, and verification digest. Run deep review in dependency-adjacent
batches no larger than `deep_review_batch_size`. Reduce batch findings into the final milestone
review and retain source IDs and revisions so stale findings can be detected.

When `max_tasks` is exceeded, split the milestone review into deterministic batches ordered by the
milestone task list, then Linear priority, dependency fan-out descending, creation time ascending,
and issue ID ascending.

Validate review batches against `milestone-review-contract.json`: at most 16 tasks, 8 model
turns, 200k active context, telemetry-backed 4M cumulative input, and the scaled phase cap.
Persist a checkpoint after one batch and resume only in a fresh session. Missing native telemetry
is `unverified`, never invented. Re-read marker, matrix, dependency graph, coverage hash, and
task/plan revisions before finalization.

Incremental review expands from changed tasks only to direct dependency neighbours, overlapping
execution footprints, and final sinks. Keep unchanged tasks as compact hash/count evidence.

## Session boundaries

- `single-command`: finish the command, persist its receipt, and stop.
- `single-stage`: execute at most one milestone stage, persist a checkpoint, report `next_command`,
  and stop. Do not carry an entire milestone through one agent context.
- `single-task`: select or execute exactly one task, persist its completion or interruption receipt,
  and stop.
- `single-phase`: execute exactly one project rollover phase, persist and validate its receipt,
  report the next phase command, release raw inventory context, and stop.
- `single-event`: execute exactly one deterministic `project run` or `milestone run --mode loop` event,
  persist the validated matching receipt and role artifacts, report that command with
  `--resume <receipt-id>`, and stop. A fresh session restores the same logical role ID from the
  receipt and ledger.

The guarded milestone supervisor composes `single-event`; it does not weaken the boundary. Each
event gets a distinct session ID and a persisted/read-back receipt before the outer invocation
selects another event.

Every checkpoint or result receipt includes command, target IDs, source revisions, source hashes,
applied operation IDs, verification status, unresolved decisions, and `next_command`. Linear and
the repository are durable memory; the conversation is not.

Project inventory compaction additionally uses `project-epoch-contract.json`. Validate every
capsule with `context project-capsule`; reconcile expected, covered, and explicitly excluded source
IDs. Never describe an incomplete capsule as the complete project baseline.

Task-verifier memory is the bounded `verification-ledger.md`, not a growing chat transcript. Reuse
a live verifier session only when supported and within budget. Otherwise restore the same verifier
ID, acceptance states, open/resolved/regressed findings, reviewed commit, compact verification
results, exclusions, and next checks. Each raw-log summary is capped at 8,000 characters; raw
executor transcripts are forbidden.

## Repository scan checkpoints

Commands whose envelope contains `repository_scan` accept `--scan fast|medium|heavy`. Validate each
raw-code batch independently with `context-packet --scope repository --scan <tier>`. The tier raises
total scan breadth and checkpoint count more than working-context size. After each batch, persist
only validated evidence capsules and coverage, release raw source, and resume from those capsules.

Validate a durable checkpoint with `linear_spanks_cli.py context scan-checkpoint`. Source revision or
content-hash drift invalidates affected capsules and returns `REPOSITORY_DRIFT`; it never permits a
stale synthesis. `CONTEXT_OVERFLOW` reports the exact scan metric and requires a smaller tier scope,
additional project split, or explicit exclusion. Never call a partial scan exhaustive.

## Persistent budgets and approved checkpoints

The coordinator resolves the exact project, milestone, and task IDs before reading policies.
`context budget <project|milestone|task> <target> --tokens <integer>` authorizes exactly that
update. `--reset` stores a revisioned null override, restoring inheritance. An identical setting
is a no-op. Increases must exceed the currently effective allowance. Agent-proposed increases
require approval. A policy changes token ceilings only: entity counts, traversal, batches, raw
logs, capsule bytes, attempts, and cumulative run budgets remain unchanged.

Read scope-addressable project Linear Documents at `context/<project-id>/<scope>/<target-id>/budget`.
Resolve task, milestone, project, then built-in defaults; each token ceiling is the greater of
its existing default and the selected override. Pass a freshly read inventory to internal operations
using `--context-policy <json-path>`. The inventory contains `ancestry` (resolved IDs), `policies`
(the exact ContextBudgetPolicy documents), and optional `runtime` evidence with `model`, `harness`,
`input_capacity`, `reserved_tokens`, and `source`. Unknown input capacity is reported explicitly.
Refresh capacity evidence after any model or harness change. Never persist credential values.

`context budget-prepare` takes `{documents, request}` and produces an exact ordered write plan.
The request binds scope, target, ancestry, tokens/reset, default_tokens, expected_policy_hash, and
`authorization: {scope, target, tokens, reset}`. This internal operation is pure: its simulated
read-backs are **not evidence of Linear persistence**. The coordinator uses linear-workflow to:

1. Refresh all ancestry policies and compare the compiled policy hash.
2. Serialize writes for the scope; refresh the exact document immediately before each mutation.
3. Persist the operation receipt, then the policy, verifying each document through a fresh read.
4. Restore policies from Linear on every resume; local files are disposable inventories.
5. Recompile packets after policy changes. Preserve factual evidence, task progress and all lifecycle gates.

Public commands compile governance envelopes; they do not independently connect to Linear.
`context inspect <scope> <target>` and `runtime inspect <scope> <target>` are read-only.
Their internal projections are `context inspect-state` and `runtime inspect-state`; the latter
uses execution's project/milestone event selectors and the task repair selector. Report active
scope, next command, blockers, approval state, stale evidence, effective budgets and unavailable
capabilities from refreshed evidence, with no inferred approvals or verification successes.

## Snapshot and delta lifecycle

`task checkpoint` uses [task comment consolidation](task-checkpoint.md): one archive Document
and one current comment per selected type, with approved redundant-comment deletion. Existing
task snapshot Documents remain historical; do not create new snapshot/manifest/active Documents
for this command.

`milestone checkpoint` uses [milestone consolidation](milestone-checkpoint.md): compact by
default, prune only via the explicit command argument. Both update one archive and one summary
paragraph; task entities survive compact mode.

`project checkpoint` prepares a snapshot preview.
Keep project objectives, decisions, constraints, frontier and cross-milestone blockers; milestone
criteria, outcomes, dependencies, findings and integration; task plan bindings, acceptance,
findings, verification, attempted fixes and next checks. Preserve original artifacts indefinitely (task comments may be removed from the issue only
after their exact originals are preserved in the single scope archive; milestone prune may
remove selected completed tasks only after verified archival and consumer handoffs).

`context checkpoint-preview` takes resolved scope IDs, revision, original `sources`, compressed
`narrative`, `default_tokens`, and the `previous_active` reference. Each source supplies ID,
revision and hash plus authoritative `facts` and narrative. Facts include IDs, revisions,
requirements, constraints, dependencies, approvals, commits, verification, findings, acceptance,
next action and plan binding. The deterministic fact projection preserves source disagreements;
a compressor can shorten narrative but cannot change these facts or infer resolution.

The preview includes exact writes, source bindings, historical manifest references, before/after
measurements and a canonical preview hash. Obtain approval for this hash. Refresh every original
source before applying `context activate-prepare`. Write and read back manifest pages and the
snapshot, then the receipt, then the small active reference. On interruption, resume the same
operation hash. Earlier active snapshots and all originals remain available. Never treat a failed
read-back as completed activation; use the receipt's previous_active reference for recovery.
A stale source or changed policy requires a new preview and approval.

New attempts persist `ContextDelta` documents through `context delta-prepare`; comments contain
links and current changes, never the accumulated ledger. A delta carries only changed fact fields,
source evidence, previous hash and policy hash. `context assemble` loads the approved snapshot
and subsequent deltas, applying only explicit evidenced changes. It does not recursively summarize
narrative summaries. Historical manifests have at most 50 entries per page; follow pages only
through bounded, resumable reads during an approved checkpoint. No bulk migration is authorized.

At durable boundaries use `context inspect-state`. Suggest compaction at the lesser of 70% of the
effective budget and 21,000 tokens, over 4,000 history tokens, or after three repair/handoff events.
Target the lesser of 50% and 15,000 tokens; partition or stop if required facts exceed the target.
The absolute caps keep persisted snapshots small when a scope raises its token ceiling. Store a declined suggestion hash without activating its
candidate, suppress unchanged suggestions, and continue only while hard limits permit.
`context expand` requires source, section, reason and max_bytes; retrieve only that section.
Tasks receive relevant parent facts; parents consume structured child outcomes and references.

Use `context compressor` to select fast for ordinary narrative, strong for project synthesis,
conflicts or ratios above 4:1. One strong retry is allowed after validation failure. Missing slots
report active-agent fallback without claiming an independent or stronger model. External slots
require a configured endpoint and data-sharing authorization. Provider failures retain the prior
active snapshot; retry within the same allowance or stop for prerequisite recovery.

## Measured dispatch and repair

`context compile` serializes the full dispatch body: instructions, selected skill contents, plan,
evidence and bindings. Measurement covers all serialized bytes, including policy/runtime bindings.
`context validate` verifies the measurement/hash and current policy; UTF-8/4 is an estimate, not
native token telemetry. `context dispatch-check` additionally binds the packet to its exact role
handoff and enforces the role ceiling. Legacy handoff readers remain readable, but all new dispatches
require this measured packet. Do not dispatch extra text outside the measured body.

Record failure fingerprints and acceptance states with each attempt. `context repair-next` returns
prerequisite recovery for environment failures, diagnosis/replanning after two unchanged failures,
and model-selection approval after at most four automatic executions. Pass progress into the
existing attempt validator so execution and inspection use the same decision. Stronger execution
still requires explicit approval; compaction or a budget increase never grants it.

`context reuse` binds repository observations, dependency outputs and skill selection to source
hashes, worktree identity, contracts, toolchain, dependencies and selection. Reuse only a matching
binding. Always verify the actual candidate and integrated result, even when analysis is reused.
