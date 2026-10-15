# Core Policy

Read this reference for every linear-spanks command.

## Project resolution

Resolve the project before resolving milestones, issues, or documents. Prefer `--project-id`,
then `--project` scoped by `--team`. Use `list_issues` with project and team filters for task
discovery and `get_project(query, includeMilestones:true)` for milestone context. When assigning
a milestone, pass both the milestone and resolved project because Linear may reject milestone
membership without project membership.

If the target remains ambiguous, stop. With `--strict-project`, reject an entity outside the
selected project. `--include-cross-project-blockers` permits read-only external blocker context;
it never expands mutation scope.

## Approval and mutation protocol

The typed approval in the compiled execution envelope is authoritative; its description comes from
`commands.json`. Before a gated write:

1. Draft the exact proposed change.
2. Obtain approval for that mutation unless the user already approved it explicitly.
3. Re-read the logical target and compare its revision or relevant fields. Strict repeats this for
   every write; balanced/fast reuse the revision within the logical entity/phase unless drift is
   detected.
4. Validate the command and any state transition together with current and replacement markers
   using `scripts/linear_spanks_cli.py state advance`.
5. Use an idempotency key derived from project, entity, command, and current revision. For each
   operation in a bulk command, also include its stable operation ID and canonical payload hash.
   Generate the latter with `scripts/linear_spanks_cli.py state payload-hash`; bulk commands reject a
   weaker command-level key.
6. Apply only intended fields; omit empty optional fields.
7. Read back the saved entity or document. Plan every read-back with
   `scripts/linear_spanks_cli.py runtime readback-plan`: declare `written_fields` per operation and
   read back only those fields plus identity and revision. A full entity read is never required to
   prove a write landed, and pulling whole issues or documents back is the largest avoidable cost
   in a mutation-heavy command. Balanced/fast may trust mutation responses as immediate
   acknowledgement, but still require one explicit final read. Bulk phases reconcile once
   and perform targeted reads for failures, missing entities, or stale revisions. Strict reads back
   every write, still projected to the written fields.
8. Report the artifact title, status, and Linear link.

Never mutate during a read-only/report request. Routine status updates and comments are allowed
inside an already approved task, but scope expansion, bulk creation, review fixes, learning
artifact persistence, archival, splitting, promotion, and conflict resolution require the
manifest's explicit gate.

## Storage model

- Project description: living `project-spec.md`, including vision, architecture, success
  criteria, naming conventions, and Future Blueprint.
- Active Project Context document: bounded, revision-linked retrieval index for the current
  baseline, delivered outcomes, active frontier, resource map, and exact resume command. It never
  overrides current entity state or replaces the Project Spec.
- Milestone description: objective, assumptions, scope/non-scope, success criteria, task list,
  human-readable stage, the machine-readable state marker, and optional compact learning index.
- Task description: stable goal, scope, acceptance criteria, dependencies, and milestone.
- Issue readiness: Human-authored drafts move `Human draft -> Unplanned` only after refinement;
  refined tasks move `Unplanned -> Backlog` only after an authoritative plan is persisted.
- `Implementation Plan` comment: plan revision, trace-only source HEAD, target-file hashes,
  consumed-surface hashes with file fallback, dependency receipt/output hashes,
  acceptance-contract hash, assurance-selected planner evidence, validated
  complexity assessment, executor tier, reviewer requirement, exact steps, affected interfaces,
  selected skills, verification commands, risks, and stop/replan conditions.
- Drift authority: run `plan-drift-check` before turning repository movement into a workflow
  decision. A changed repository revision alone refreshes trace fields in preflight and orchestration
  receipts and never invalidates the plan. `valid` continues; `safe-refresh` persists/read-backs only the
  affected execution-evidence receipt and recompiles inside the current run; `material` returns to planning for the affected impact closure. Exact
  parent HEAD and integration-preview bindings are unchanged.
- Completion comment: changes, files/modules, decisions, verification evidence, limits,
  follow-ups, newly unblocked issues, and the actual harness/model-routing and review receipt.
- Project Orchestration Receipt Linear Document: one active `project run` state machine per project
  revision, including logical role IDs, milestone/task-loop states, approval hashes, context
  budget, event pointers, source/dependency hashes, timestamps, and failure state.
- Milestone Runtime Linear Document: one current revisioned projection titled
  `Linear Spanks Milestone Runtime — <milestone-id>` with storage source, guarded policy binding,
  active wave, plan validity, incremental review coverage, human-repair state, and last event.
  Fall back to one managed comment when Documents are unavailable. Live issues and immutable event
  receipts remain authoritative; conflicting projections stop.
- Milestone Orchestration Receipts: immutable single-event evidence containing milestone role,
  task-pair bindings, project/milestone revisions, graph/source hashes, approvals, and bounded
  event state.
- Human verification policy: one exact-title project Document for the default plus one optional
  managed milestone-description override. Project and milestone receipts bind the resulting
  source, revisions, and hash.
- Human verification gate: one marked issue per enabled active milestone. Exclude it by marker
  from planning, dependency graphs, waves, execution, and regular task totals. Preserve its
  revision-bound checklist history when it is canceled or reactivated.
- Verification context: an approved task snapshot plus evidenced delta Documents linked from
  marked Verification Result comments. Preserve legacy ledgers as addressable source artifacts.
  Retain exact reviewed commits, acceptance states, unresolved findings, verification, exclusions,
  next checks and live-session state. Never embed accumulated history in each attempt comment.
- Completion Handoff and Verification Result comments: executor/verifier append-only capability
  outputs marked `linear-spanks:completion-handoff` and `linear-spanks:verification-result`.
- Linear Documents: project learning index, learning entries, retrospectives, and other durable
  project memory when the active toolset supports them.

## Naming

Read the project's naming-conventions paragraph before proposing milestones or issues. Apply it
strictly. During audit or onboarding, report a missing convention and ask for the preferred
format before saving one.

## Recovery

- Interrupted pipeline: parse the state marker, run status and sync, then continue from the
  validated stage.
- Failed verification: do not mark Done. Add a `Verification Failure` comment and keep or move
  the task In Progress.
- Project-loop interruption: validate exactly one active receipt and resume one deterministic
  event. Multiple receipts return `PROJECT_ORCHESTRATION_RECEIPT_AMBIGUOUS`; revision or source
  drift returns `PROJECT_ORCHESTRATION_DRIFT`.
- Milestone-loop interruption: validate the matching milestone receipt and project scope fence;
  ambiguity returns `MILESTONE_ORCHESTRATION_RECEIPT_AMBIGUOUS`, and project-scope conflict returns
  `ORCHESTRATION_SCOPE_CONFLICT`.
- Human-verification drift: stop with `HUMAN_VERIFICATION_POLICY_DRIFT`, resolve precedence again,
  reconcile affected receipts and gate state, then recompute the next event.
- Four failed automatic task rounds: return `MODEL_SELECTION_REQUIRED`. Run only one explicitly
  selected stronger repair, then return to the same gate after any further failure.
- External mutation: compare with current plans. Ask before reconciling conflicts.
- Changed task plans or dependencies: classify bound drift. Safe-refresh only whitelisted plan
  evidence; material changes expire guarded policy. Review affected acceptance checks and the material impact closure; preserve unrelated coverage.
- Failed write: read back to determine whether it applied. Retry once only when safe, then stop.
- Project rollover drift: stop with `ROLLOVER_DRIFT`, refresh inventory and preview, and never
  complete the source project from a stale receipt.
- Missing blocker: stop and ask for a valid issue identifier.
- Missing document capability: return the draft and capability gap; do not claim persistence.
