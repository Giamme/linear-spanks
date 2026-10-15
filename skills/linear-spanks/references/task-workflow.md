# Bounded task workflow

The default balanced path for a localized, deterministic, evidenced low-risk change is inspect,
edit, focused checks, and one final self-review. The coordinator records a compact plan if missing;
otherwise reuse the current material plan. Explicit planning commands remain planning-only.
Strict or risk-triggered independent review remains required. Optional cleanup never blocks work.

## Current task comments

After `task checkpoint`, read the canonical `linear-spanks:task-comment` per-type comments
and new comments since consolidation. These hold the current structured plan, review and
handoff bindings. Do not fetch the task archive or old context snapshots unless a specific
missing fact requires expansion. Append-only archives are historical, never another active
plan. Subsequent checkpoints merge new passes into the same comment types and same archive.

For a missing prerequisite referenced by an archived-dependencies comment or milestone summary,
use `context archived-task` with a fresh matching archive hash and confirmed native absence.
Use its terminal outcome row in the compact dependency matrix; do not fetch a deleted issue
repeatedly, silently drop a missing blocker, or infer success from its title. Revalidate consumed
outputs for the current candidate; archival never grants execution/review/integration approval.
The coordinator restores scoped archived outcomes before calling runtime task-next or parent
event/graph selectors. Keep unresolved native tasks; strip archived terminal nodes only from
the executable frontier, preserving their outcome references as dependency evidence.

## Compile before dispatch

Use `runtime task-next [JSON-path]` for standalone tasks and each child of a milestone/project run.
It is read-only and supplies the same decision used by `runtime inspect-state`. Feed its inputs as
`task_workflows` into the project/milestone event selectors; completed tasks produce no new dispatch.

The input has `schema_version: 1`, `task_id`, `candidate_commit`, `roles` (bound executor and verifier
IDs), the existing `routing decide` input in `decision`, `approval_satisfied`, `blockers`, and the
current required `verification_commands` list. Use execution/next/verification commands here;
explicit planning uses its planning contract. Set `candidate_ready: true` after reading back the
completion handoff for this exact candidate to select verification without another execution.
Provide these evidence sections:

- `plan_drift`: the existing `reviews plan-drift` input (`plan`, `current`, `changed_plan_fields`),
  or `null` when a plan must first be recorded. Material drift returns to planning. Target evidence,
  trace HEAD and unchanged dependency outputs do not themselves change the material plan revision.
- `progress`: all consumed attempt records, including result, fingerprint, acceptance states and
  executor strength. New work starts with `{"attempts": []}`. Keep this bounded to the task's
  attempt allowance, with original evidence referenced in delta Documents.
- `observations`: an object keyed by observation. Each entry contains `previous` and `current`
  reuse bindings: source hashes, worktree, contracts, toolchain, dependencies and selection.
  `previous: null` means new analysis is needed. A changed observation does not invalidate others.
- Optional `refresh`: the read-back result of the evidence-refresh protocol below.
- Optional `verification`: the current verification ledger. A pass must bind this task, plan,
  exact candidate and the required review role. Optional `integration` is the validated isolation
  receipt for that candidate. New ledgers store the returned `verification_binding` as
  `execution_binding` after executing the required checks. Changed checks/toolchain evidence
  invalidate reuse; trace-only HEAD and unchanged dependency outputs do not. Legacy unbound
  verification remains readable and requires current verification before reuse.

The result reports the execution policy and reasons, next action, dispatch readiness, workflow hash,
material/evidence bindings, stale/reusable observations, and planned role counts. Counts describe
the compiled action; actual model invocations and timings must be recorded separately.

New task handoffs use schema 2 with `execution_policy` and `workflow_hash`. Include the full measured
packet and `workflow` input in `context dispatch-check`; bind its canonical hash as `task_workflow`
in packet bindings. The check recomputes readiness, role and policy before dispatch. Controllers
retain Linear writes, status changes, integration and final read-back. Task workers return results.

## Refresh inside the authorized run

`reviews refresh-prepare` accepts a `documents` inventory and `request` containing `project_id`,
`source` (the fresh plan-drift Document), `expected_source_hash`, `expected_receipt_hash`, and
`authorization` (`task_id` plus material binding hash). It prepares the exact guarded write to the
task's execution-evidence Document. It does not activate evidence or claim persistence.

The coordinator refreshes sources, applies the guarded write and reads it back through the
DocumentStore adapter (`reviews.refresh_evidence`). Recompile `runtime task-next` with that result.
The receipt preserves the material plan revision, stores separate evidence bindings, and resumes
idempotently after interrupted writes. Failed read-back or source drift prevents dispatch.

## Findings and repairs

New attempts use schema 2 with the execution policy, durable progress, and exact verification ledger
for a pass. New verification ledgers use schema 2. Findings include `classification` (`blocking` or
`suggestion`), `evidence`, and `requirement` (a cited correctness/acceptance/repository requirement
for blockers; `null` for suggestions). Legacy unclassified findings remain blocking. Classified
milestone findings follow the same rule; suggestions alone do not reopen tasks or invalidate plans.

Repair blocking defects within the current plan. Review changed areas and affected acceptance
checks; preserve unrelated coverage. Supply full `plan_changes` to incremental milestone coverage
so evidence refresh does not trigger dependency-wide review. Required final milestone verification
still checks the integrated result.

After two identical failures without acceptance improvement, `context repair-next` returns
`diagnose` and a diagnosis binding. Record diagnosis with `failure_binding`, `after_attempt`,
`new_approach`, and `new_evidence`. The same unchanged state cannot repeatedly start diagnosis.
Another execution requires a changed approach or new evidence; otherwise report `REPAIR_STALLED`.
Environment failures select prerequisite recovery. Four automatic executions remain the ceiling;
diagnosis, evidence refresh and replanning never reset counts or authorize a stronger executor.

Load selected skills fully once per session/source hash. Use code review and verification as the
current task's completion phase, not requests for extra agents. Re-run affected checks after edits
and all required final checks on the candidate; never relabel old results as freshly verified.

Pass the current `workflow` into role capability checks: diagnosis, review, refresh and blocked
actions cannot mutate source. For recovered environmental failures, record `prerequisite_recovery`
with the failure fingerprint and evidence references; reverify the same candidate without spending
a new executor attempt.

For a standalone task whose resolved Git strategy does not require isolated integration, pass
`integration_required: false`. A current pass selects `finalize-task`; the coordinator follows the
existing completion/status read-back protocol. Supply the existing routing completion receipt with
its `task_completion` binding to resume as completed: schema version 1, task ID, candidate commit,
material binding, policy hash, Done status, issue revision, completion reference, and read-back true.
Project/milestone task loops always retain isolated integration; their completed integration receipt
is still required. No isolation strategy is changed by choosing the short path.

After automatic exhaustion, optional `model_selection` contains the consumed `attempt_index` and
the existing approved model-escalation `request`. Validate it against current failures before one
`user-selected-repair`. The requested configured route overrides the baseline executor only for
that approved attempt. Another failure requires a new selection bound to the new attempt count.
