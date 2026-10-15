# Project Commands

## `project create`

Run a collaborative product and architecture discovery rather than jumping to a finished plan.

1. Product discovery: ask one or two questions at a time about audience, value, constraints,
   business rules, and edge cases. Continue until the user explicitly says the product direction
   is ready for architecture.
2. Architecture: present at least two viable high-level options and trade-offs. Align on stack,
   data model, boundaries, and interactions incrementally. Prefer a durable foundation without
   overbuilding the first release.
3. Synthesis: render `project-spec.md`, including naming conventions.
4. Gate: show the spec and exact project creation before writing.
5. Roadmap: propose foundational milestones and a final Future Blueprint milestone. Gate before
   creating the roadmap.

## `project update`

Read the current project description and relevant roadmap context. Identify the requested product
or architecture pivot, show the changed sections, and obtain approval before replacing the living
project spec. Preserve still-valid decisions and record newly invalidated roadmap assumptions.

## Codebase analysis and import

- `codebase analyze`: perform source-read-only repository analysis using the selected `--scan`
  tier. Invocation permits only checkpoint artifacts inside the repository. Execute one scan stage,
  validate and persist the checkpoint, report coverage and the next command, then release raw batch
  context. Never mutate Linear.
- `codebase import`: run or resume the same checkpointed analysis, synthesize an evidence-linked
  project baseline, and propose three to seven historical outcome milestones plus a separate future
  roadmap. Invocation permits local checkpoints; show `codebase-import-proposal.md` and obtain
  preview approval before any Linear creation. Read back every approved artifact.

Historical outcomes must remain classified as `verified-delivered`, `implemented-unverified`, or
`historical-inferred`. Code existence alone is not completion evidence.

## Review and onboarding

- `project review`: read all milestones and report overlap, deprecation, ordering, dependency,
  ownership, and objective conflicts using `project-review-findings.md`.
- `project audit`: perform the same structural diagnosis without mutation. Check project spec,
  naming conventions, milestone objectives, measurable success criteria, task acceptance
  criteria, plans, dependencies, and state markers.
- `project onboard`: run the audit, draft normalization, obtain approval, apply only approved
  changes, and read them back.
- `project normalize`: require existing onboarding findings and approval; do not invent additional
  changes during application.

Project review findings block task creation until resolved or explicitly accepted.

## `project run`

Use `project run <project> [--max-parallel <2..8>] [--resume <receipt-id>]` to advance the entire
staged project pipeline without collapsing project, milestone, task implementation, and task
verification into one context. It is opt-in and does not replace the individual commands.

Follow `project-orchestration.md`. Persist exactly one active project receipt per project revision,
select one event with `project-loop-next`, invoke only the role named by that event, validate every
handoff and capability, persist the transition, and stop at the `single-event` boundary. Native
delegation may schedule the next fresh invocation. Multiple active receipts return
`PROJECT_ORCHESTRATION_RECEIPT_AMBIGUOUS`; bound revision or hash drift returns
`PROJECT_ORCHESTRATION_DRIFT`.

The one logical project orchestrator owns the project spec, compact milestone ledger, selected
documents and learnings, cross-milestone conflicts, and strategic approval gates. It never receives
repository code, diffs, paths, or source-reading tools. It creates and coordinates milestone work
through handoffs to the one logical orchestrator assigned to each milestone.

## Human verification policy

- `verification policy-set <project> --default enabled|disabled` updates the singleton
  project Document only after an exact preview of every active inheriting milestone and its gate,
  checklist, and orchestration receipt effects.
- `verification policy-set <milestone> --override enabled|disabled|inherit` updates exactly
  one revisioned milestone-description marker after the same scoped preview.
- `verification status` is read-only and reports stored sources, the effective precedence
  result, gate/checklist state, and receipt drift. Missing project policy reports the disabled
  system default.

Follow `human-verification.md`. Project mutation fails with
`HUMAN_VERIFICATION_POLICY_UNAVAILABLE` when Document persistence is unavailable; milestone
overrides remain independently available because they use the milestone description.

## Checkpoints and release rollovers

- `project checkpoint`: build a bounded project inventory and render one authoritative `Active
  Project Context` document using `project-context-capsule.md`. Validate its body, coverage,
  batches, revisions, and source snapshot with `context project-capsule`; preview-gate the exact
  document mutation and read it back. Never rewrite historical entities during compaction.
- `project rollover`: follow `project-epoch.md` and the validated receipt one phase at a time. A
  rollover prepares a release capsule, creates a successor project with inherited Initiative
  membership when available, creates three-to-seven approved outcome milestones, recreates only
  selected issues in `Unplanned`, resolves every approved source disposition, and completes the
  source project only after final read-back and zero unresolved items.

Use a checkpoint for a smaller context reset inside the same active release. Use a rollover only
for a major release boundary where the source project is ready to close. `milestone wrap` remains
the source of milestone-level retrospectives and reusable learnings; it is not replaced by either
project command.
