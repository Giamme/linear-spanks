# Milestone Commands

## Planning stages

1. `milestone clarify`: gather objective, assumptions, constraints, non-scope, measurable success
   criteria, risks, and open questions. Draft `milestone-spec.md`; gate before saving.
2. `milestone design`: use `architectural-options.md` for genuinely different designs. Select one
   with the user, then produce the milestone spec.
3. `project review`: complete project-level review before task creation. The standalone command is
   read-only; inside `milestone run --mode step`, validate and persist the `project review` transition only
   after the findings are clean or explicitly accepted.
4. `milestone create-tasks`: read applicable project learnings, decompose without duplication, order hard
   dependencies, and gate before bulk creation. Create every new task in `Unplanned`.
5. `milestone plan`: run the deterministic risk screen, then use the assurance decision. Balanced may
   group up to four dependency-adjacent tasks in a bounded planner run; strict uses one high
   planner per task; fast lets the coordinator plan eligible deterministic low-risk work. In every
   mode, the coordinator persists one authoritative `Implementation Plan` per task containing evidence, source
   revision, executor tier, reviewer policy, exact steps, verification, and replan conditions. Do
   not code. Balanced/fast reconcile the bulk phase once and target reads at mismatches; strict
   retains per-task read-back. Move each successfully reconciled task from `Unplanned` to
   `Backlog`. Every plan binds trace-only source HEAD, target-file hashes, consumed-surface hashes
   with file fallback, selected dependency receipt/output hashes, acceptance-contract hash, and
   execution footprint. After each durable plan read-back, refresh the managed milestone dependency graph
   with current Linear blockers and plan execution footprints. Estimates are optional.
   With `--next-wave`, plan only the next live executable frontier. Keep later tasks `Unplanned`
   with `plan_revision: 0`; zero-revision graph nodes conservatively serialize until planned.
6. `milestone review`: build the compact task-contract matrix, then deep-review
   dependency-adjacent batches within the execution envelope. Check duplicate work, relation gaps,
   scope, testability, verification, downstream contracts, execution footprints, graph hashes,
   cycles, deterministic waves, and objective fit. Mark the graph reviewed only after it matches
   live relations and current plan revisions. Reduce batch findings
   with source revisions; do not load every full task and comment thread together. The initial
   `--next-wave` review validates the complete stable task/dependency contract plus the first wave.
   Later incremental reviews cover changed tasks, direct dependency neighbours, overlapping
   footprints, and final sinks, recording changed/adjacent/unchanged counts and hashes. A selected
   wave must have current review coverage. `--repair-safe` may apply only contract-whitelisted safe
   refreshes; material findings still stop for `milestone fix-review`.
7. `milestone fix-review`: draft exact fixes, obtain approval, apply them, then return to planning and run a
   fresh review.

## Execution and verification

`milestone run --mode step` resolves the next required stage, executes at most that one stage, persists a
checkpoint, and returns `next_command`. A later agent run resumes from validated state rather than
starting over or carrying the entire milestone in one context. `milestone verify` runs only after
all required tasks are Done and checks the milestone objective and every success criterion using
fresh evidence. Resolve final human-verification policy before counting tasks and filter the
managed gate by marker. When disabled, preserve the existing result and return `milestone wrap`.
When enabled, move the managed gate to In Progress, append the current revision-bound checklist,
stop at `milestone-verified`, and return `verification confirm`.

`milestone run --mode step --isolated-worktree` is conditional: resolve the next stage without mutation, accept
the flag only for `start-implementation`, and then use the optional single-task isolation flow.
For every other resolved stage, stop with `ISOLATION_NOT_APPLICABLE` before any stage write.

Inside `project run`, exactly one logical high-strength milestone orchestrator owns each milestone
across fresh events. It receives the milestone contract, compact task matrix, dependency graph,
current plans, selected project decisions/learnings, and bounded source-read evidence. It may plan,
dispatch fixed isolated task frontiers, validate executor/verifier handoffs, preview and perform
approved integration, verify the milestone, and wrap it. It never edits tracked source directly.
Independent milestone orchestrators may advance concurrently when their dependencies and project
contracts do not conflict; the project orchestrator resolves cross-milestone conflict.

## `milestone run --mode loop`

`milestone run --mode loop <milestone> [--max-parallel <2..8>] [--resume <receipt-id>]` preserves the
legacy one-event controller when no loop flags are supplied. Add
`--until approval-required,blocked,milestone-done --max-events 20 --repair-safe` to supervise
fresh receipt-backed events. Use `milestone run --mode loop`; the removed v1 `--autopilot`
spelling is rejected with its exact replacement.
The event ceiling defaults to 20 and cannot exceed 100. Each event runs in a fresh bounded
session, persists and reads back its receipt and runtime projection, then reevaluates policy and
drift. `--isolated-worktree` is an idempotent assertion because loop task execution is isolated.
Repository HEAD/source-hash changes are trace-only in loop receipts. Before selecting an event,
classify each affected current plan with `plan-drift-check`; continue on `valid`, perform only the
task-scoped refresh on `safe-refresh`, and stop/replan only the material impact closure. A trace
refresh does not require a new approval preview. Dependency graphs, plan revisions, policy
bindings, task-loop bindings, and integration previews remain authoritative gates.
The controller reuses the isolated task-wave,
executor/verifier, integration, and model-escalation rules from `project run` without changing the
legacy single-stage `milestone run --mode step` command. It may create and plan tasks, dispatch work, verify,
integrate, verify the milestone, and persist milestone retrospective evidence.

Guarded policy persists across sessions but expires on scope, acceptance, dependency,
authorization, migration-policy, or project-policy drift. Safe plan refreshes, routine Linear
comments/statuses, bounded active-task repairs, tests, disposable local migration runs, and
unambiguous cache reconciliation may be automatic. New tasks; scope, dependency, product,
authorization, migration/schema-source changes; irreversible external writes; model selection;
integration; merge; and push remain gated.

Run `orchestration-scope-check` before creating or resuming the receipt. An active project loop or
cross-milestone/project-level dependency returns a safe stop; do not use the milestone loop to
change project scope, curate project learnings, or settle project conflicts.

## Testing-session findings

`milestone report-findings <milestone> --session-id <id> --finding <text>...` submits one
idempotent batch. Reopen one unambiguous owning task; otherwise preview and create exactly one
managed repair task for the complete batch. Preserve gate/checklist history, return the runtime to
`implementing`, and require machine verification plus a fresh human checklist. Invalidate only
unfinished plans that consume provided surfaces changed by the repair.

## Wrapping

`verification confirm` is separate from wrapping. It requires explicit human confirmation of the
current pending checklist, marks the gate Done, reads native Linear milestone completion back,
advances to `human-verified`, and then returns `milestone wrap`.

`verification fail` requires a reason and an exact approved preview. Record the failure
beneath the checklist, create exactly one marked Unplanned repair task for that failure revision,
keep the gate open, and return to `implementing`; the next completion attempt must rerun machine
verification.

`milestone wrap` is optional and starts after machine verification when policy is disabled, or
after `human-verified` when enabled. Generate the
retrospective, candidate learnings, milestone learning appendix, project learning index changes,
and learning-entry drafts. Obtain approval before saving learning artifacts.

After approval, attempt every approved write and read back each artifact. Return a checklist with
links for the retrospective, milestone appendix, project learning index, every learning entry,
and status update. If no reusable learning exists, still persist the retrospective and status
update with `No reusable project learnings identified`; do not create empty entries.

## Review checklist

- Missing, incorrect, or transitive blockers
- Same work planned more than once
- Cross-milestone conflicts or unformalized dependencies
- Wrong milestone membership
- Oversized or vague tasks
- Untestable acceptance criteria
- Weak or missing verification plans
- Plans that conflict with the objective or sibling contracts

Classify review output before selecting repairs. Structured findings contain summary, classification,
requirement and evidence. Suggestions-only batches have no repair or plan-invalidation action;
legacy plain-text findings remain blockers. Preserve the required final milestone verification.
