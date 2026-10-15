# Project Orchestration Loop

`project run` is the opt-in portable controller for the existing project, milestone, task, wave,
isolation, verification, and learning commands. One invocation advances one bounded event and
persists a receipt. A harness with native delegation may immediately schedule the next fresh role
invocation; inherited or advisory harnesses return the validated resume command instead. The
conversation is never the system of record.

## Logical topology

- Create exactly one logical project orchestrator for the project. It owns the project spec,
  milestone creation and coordination, project documents, learning curation, and cross-milestone
  conflicts. It must never receive repository code, diffs, paths, or source-reading tools.
- Create exactly one logical milestone orchestrator per milestone. It owns only that milestone,
  its tasks, plans, dependency graph, dispatch, integration, verification, and wrap. It may read
  bounded source evidence for planning and may perform validated Git integration, but it must not
  edit tracked source.
- Reserve one logical task executor and verifier identity per task. Dispatch a separate verifier
  only when the shared task policy requires independent review. They retain the
  same IDs across retries and refreshed sessions. Different task pairs may run concurrently only
  in the isolated worktrees selected by a fixed reviewed dependency frontier.

Project coverage means a compact milestone ledger plus selective expansion, not every full
milestone history. Milestone coverage means a compact task matrix plus selective expansion, not
every full issue and comment thread. Run every handoff through
`role-handoff-check --receipt <project-receipt.json>` so the role ID and all bound revisions and
hashes are checked together.

## Event selection and receipts

Use `project-loop-next` with freshly read project, milestone, task, approval, and drift state. Its
precedence is project reconciliation, pending approval, active task execution, active task
verification, verified integration, pending human verification, ready task dispatch, milestone
wrap, eligible milestone work, project completion, then blocked. Do not improvise another order.
`await-human-verification` is a terminal automation stop for that event: do not wrap the enabled
milestone or dispatch its downstream milestones.

Persist one project-scoped `Project Orchestration Receipt` Linear Document from
`project-orchestration-receipt.md` and validate it with
`project-loop-receipt-check`. The same `project run --resume <receipt-id>` resumes one matching
active receipt. Multiple active receipts for the project revision stop with
`PROJECT_ORCHESTRATION_RECEIPT_AMBIGUOUS` and their IDs. Re-read all bound revisions and hashes
before `project-loop-transition`; drift stops with `PROJECT_ORCHESTRATION_DRIFT`.
The transition request carries the completed receipt event, freshly read current project,
source/graph, milestone, and task bindings, plus the next durable bindings, states, and monotonic
budget. Existing role IDs may not be removed or rebound. Any topology or bound-revision change
requires its approved preview. The receipt also binds one effective human-verification policy per
milestone, including source, project and override revisions, and hash. Any mismatch returns
`HUMAN_VERIFICATION_POLICY_DRIFT`; recompute before choosing the next event.

## Task execution and verification

Every task starts in its own isolated worktree. Task policy determines planning and review effort.

Use `runtime task-next` before dispatch. A low-risk task executes and self-verifies in one bounded
invocation. Other tasks retain the required independent reviewer. Repair only blocking findings and
verify affected areas; do not restart planning for routine implementation changes. Schema 2 attempts
bind the execution policy, exact candidate verification, and durable progress. Schema 1 readers
preserve the former fixed low/high pair.

Validate every attempt with `task-attempt-check`. Each executor attempt writes one idempotent
Completion Handoff comment marked `linear-spanks:completion-handoff`. Each verifier attempt writes
one idempotent `task-verification-result.md` comment marked `linear-spanks:verification-result`.
Only the milestone orchestrator changes task status or integrates commits.

After four failed automatic verifications, stop with `MODEL_SELECTION_REQUIRED`. Use
`model-escalation-check` only after showing the user the evidence and the configured enforceable or
advisory models. The selected-model record must confirm that the model is configured. One user
selection authorizes one medium or high executor repair. Every failure
after that returns to the same user gate; never retry a stronger model automatically. The user may
retry, select another model, request milestone replanning, or pause.

## Verifier continuity

The task verifier is a logical identity, not an indefinitely growing conversation. Reuse its live
session only while supported and inside the effective task context budget. Preserve legacy
`verification-ledger.md` artifacts and validate them with `verification-ledger-check` when read.
New Verification Result comments link to the approved ContextSnapshot and current evidenced
ContextDelta; never repeat accumulated attempt history. A fresh verifier restores its identity,
acceptance states, unresolved findings, reviewed commits and next checks from the snapshot plus
deltas. The coordinator writes and reads back all context Documents; roles provide bounded changes.

Before automatic repair, use `context repair-next` with failure fingerprints and acceptance states.
Two unchanged failures require diagnosis; only material plan drift requires replanning. Environment failures select prerequisite
recovery. Four attempts remain an upper bound, not a requirement to repeat an ineffective repair.

Never persist raw executor transcripts. Compact resolved findings, preserve open and regressed
findings, and cap each raw-log summary at 8,000 characters. A pass requires every criterion
passing, no open or regressed blocking findings, the exact candidate commit reviewed, and all required
verification freshly rerun.

## Capability and completion boundary

Run `role-capability-check` before every role mutation. Executors may edit and commit only in their
assigned worktree and may write only Completion Handoff comments. Verifiers may run checks and
write only Verification Result comments; they never edit tracked source. Orchestrators retain all
other Linear lifecycle and Git integration writes.

Use the existing exact wave or single-task integration preview. Mark a task Done only after the
verifier-approved commit is integrated, post-integration verification passes, the completion
receipt is durable, and the issue and newly unblocked relations are read back. Promote task
findings to milestone retrospective candidates first; only the project orchestrator curates
approved reusable project learnings.

## Optional repository discovery

Follow [Ripwire](ripwire.md) after each child resolves its repository. Carry only the compiled
`ripwire.child_arguments` into child invocations and role briefs; resolve saved preferences
against that child repository. Include advisory query evidence in the measured context packet.
