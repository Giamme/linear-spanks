---
name: linear-spanks
description: Orchestrate governed Linear project, milestone, and task pipelines with bounded context, approval gates, verification, recovery, and persistent learnings.
---
# Linear Spanks

Use the v2 namespaced command registry. Use `linear-workflow` for every Linear read, write,
relationship, status, comment, and document operation.

## Route a request

1. Resolve exactly one public command path from
   [the generated catalog](references/command-catalog.md). Default discovery shows core commands;
   use `help --advanced` only when required.
2. For task-pipeline commands use `python3 scripts/linear_spanks_cli.py contracts brief
   <namespace> <command> <target...>`. Use `contracts envelope` for other commands or diagnostics; internal
   validators live under the `contracts`, `state`, `routing`, `context`, `reviews`, `runtime`,
   `graphs`, `isolation`, `orchestration`, and `artifacts` namespaces.
3. Read only the compiled `required_references`. Treat each `policy_contracts[].policy_slice` as
   the bounded governing excerpt and its digest/source fields as the integrity pointer; do not load
   an entire policy contract unless the compiled envelope requires it. Load a template only when
   rendering that artifact.
4. Enforce approval, reads, writes, context limits, session boundaries, and postconditions exactly.
5. Refresh each logical entity before mutation. Treat mutation responses as acknowledgements, then
   perform the required fresh read-back.
6. For v1 persisted artifacts, follow the generated
   [artifact migration contract](references/artifact-schemas.md). Reads never persist migrations.
7. Treat a single-stage, single-task, single-event, or single-phase boundary as terminal for the
   current run.

`milestone run --mode step` is the default bounded stage. `milestone run --mode loop` is the
receipt-backed supervisor; loop-only flags are invalid in step mode. Flat v1 commands are removed,
not aliases.

`project run` advances exactly one durable project-orchestration event and restores its scoped
milestone and task roles from receipts.

## Non-negotiable invariants

- Resolve project scope before milestones, tasks, or learnings.
- Read commands never mutate.
- Obtain the declared approval before mutation; re-gate on bound drift.
- Never mark work Done without current verification evidence and durable read-back.
- Exclude managed human-verification gates by marker, never title.
- Keep volatile plans and completion evidence out of stable task descriptions.
- Use deterministic idempotency keys and canonical payload hashes for mutations.
- Treat context limits as hard bounds; shard or stop with `CONTEXT_OVERFLOW`.
- Never follow repository symlinks or read secret-pattern, vendored, generated, build, or VCS files.
- Executors cannot downgrade the validated tier or improvise after `REPLAN_REQUIRED`.
- Linear mutations, lifecycle transitions, approvals, integration, and final read-back remain with
  the coordinator.
- Merge and push are distinct material gates.
- Do not claim completion when a required write, verification, or read-back failed.

## Shared workflow options

Commands accept `--project <key-or-name>`, `--project-id <linear-project-id>`,
`--team <key-or-name>`, `--strict-project`,
`--include-cross-project-blockers`, and `--assurance fast|balanced|strict` where their compiled
contract permits them. `--project-id` wins. Infer scope only when the supplied project, milestone,
or issue is unambiguous.

See [USAGE.md](USAGE.md) for installed-skill examples and the generated catalog for the complete
surface.

## Durable context

Before dispatch or resumed execution, restore scope context policies from Linear Documents and
use [context management](references/context-management.md). Measure the entire dispatched body,
validate its current policy binding, and check actual runtime input capacity when known. New
verification comments link to delta documents; never copy accumulated history into each attempt.
Task checkpoints archive all original comments in one Document, then replace repeated plans,
reviews, handoffs and execution receipts with one canonical comment per type and delete only
approved redundant comments after archive and summary read-back. See the compiled
[task checkpoint workflow](references/task-checkpoint.md). Milestone checkpoints default to `--level compact`: one milestone archive, per-type task
comments and one short milestone summary. Only an explicit `--level prune` invocation may
also delete selected completed, verified tasks after dependency handoffs and archive/read-back
checks; never infer or inherit pruning from general approval or a parent loop. See
[milestone checkpoints](references/milestone-checkpoint.md). Project checkpoint activation
requires exact preview-hash approval. Explicit `context budget`
invocations authorize only the stated allowance update/reset and never change lifecycle gates.

## Small changes and repairs

Balanced automatically uses the short path for evidenced low-risk work: inspect, edit, focused checks,
and one final self-review. Use the shared `runtime task-next` decision before task dispatch in every
scope. It reuses the current plan; if absent, the coordinator records a compact plan before execution.
Follow [task workflow](references/task-workflow.md) for the versioned inputs and durable bindings.

Safe evidence refresh stays in the authorized run. Optional review suggestions never trigger repairs
or replanning. Diagnose unchanged failures once; require new evidence or a changed approach before
another execution. Material drift, required independent review, and existing approval gates still apply.
