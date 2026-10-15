# Command catalog

<!-- Generated from contracts/command-registry.v2.json; do not edit. -->

All commands emit the v2 JSON envelope by default. Add `--format text` for a compact
human-readable result. Shared workflow targeting options remain contract-defined.
Shared option: `--ripwire on|off|inherit` (default inherit); see [Ripwire](ripwire.md).

## Overview

| Namespace | Core | Advanced |
|---|---|---|
| `codebase` | `analyze`, `import` | — |
| `project` | `create`, `review`, `run` | `update`, `audit`, `onboard`, `normalize`, `checkpoint`, `rollover` |
| `milestone` | `clarify`, `design`, `create-tasks`, `plan`, `review`, `run`, `status`, `verify`, `wrap` | `report-findings`, `fix-review`, `pause`, `resume`, `sync`, `archive`, `blockers`, `diff`, `handoff`, `onboard`, `checkpoint` |
| `task` | `refine`, `plan`, `next`, `run` | `design`, `create-bug`, `organize`, `replan`, `scope`, `decompose`, `split`, `promote`, `verify`, `backfill`, `onboard`, `checkpoint` |
| `wave` | — | `implement`, `reconcile` |
| `verification` | — | `policy-set`, `status`, `confirm`, `fail` |
| `learning` | — | `review`, `apply`, `organize` |
| `context` | — | `budget`, `inspect` |
| `runtime` | — | `inspect` |

## Codebase

### `codebase analyze <repository-path> [--scan fast|medium|heavy] [--checkpoint-dir <path>] [--resume <checkpoint>] [project options]`

Analyze a repository in bounded resumable stages and produce evidence-linked current-state findings.

- Tier: `core`
- Access: `write`
- Approval: explicit invocation authorizes source-read-only analysis and local checkpoint artifacts; no Linear mutations
- Profiles: `invocation_write`, `project`
- Template: `codebase-analysis.md`
- Transitions: none
- Removed v1 names: `analyze-codebase`

### `codebase import <repository-path|checkpoint> [--scan fast|medium|heavy] [project options]`

Reconstruct a project and outcome-oriented historical milestones from codebase evidence, then create only the approved Linear artifacts.

- Tier: `core`
- Access: `write`
- Approval: invocation authorizes local scan checkpoints; preview required before Linear project and milestone creation
- Profiles: `staged_import`, `project`
- Template: `codebase-import-proposal.md`
- Transitions: none
- Removed v1 names: `import-codebase`


## Project

### `project create <idea> [project options]`

Run interactive product and architecture discovery, create a project spec, then propose the initial roadmap.

- Tier: `core`
- Access: `write`
- Approval: before project and roadmap creation
- Profiles: `preview_write`, `project`
- Template: `project-spec.md`
- Transitions: none
- Removed v1 names: `create-project`

### `project review <project> [project options]`

Review roadmap milestones for overlap, conflicts, ordering, and dependency gaps.

- Tier: `core`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `project`
- Template: `project-review-findings.md`
- Transitions: none
- Removed v1 names: `review-project`

### `project run <project> [--max-parallel <2..8>] [--resume <receipt-id>] [project options]`

Advance the durable project, milestone, and task orchestration loop by one fresh bounded event.

- Tier: `core`
- Access: `write`
- Approval: invocation covers autonomous progress inside approved scope; preview gates project or milestone scope changes, exact integration, and stronger executor selection
- Profiles: `staged_project_orchestration`, `project`
- Template: `project-orchestration-receipt.md`
- Transitions: none
- Removed v1 names: `run-project`

### `project update <project> [project options]`

Revise an existing project spec after a product or architecture pivot.

- Tier: `advanced`
- Access: `write`
- Approval: before updating the project description
- Profiles: `preview_write`, `project`
- Template: `project-spec.md`
- Transitions: none
- Removed v1 names: `update-project`

### `project audit <project> [project options]`

Produce a read-only compatibility diagnosis for a legacy project.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `project`
- Template: `project-onboarding-findings.md`
- Transitions: none
- Removed v1 names: `audit-project`

### `project onboard <project> [project options]`

Audit a legacy project and, after approval, normalize it for linear-spanks.

- Tier: `advanced`
- Access: `write`
- Approval: before applying normalization changes
- Profiles: `preview_write`, `project`
- Template: `project-onboarding-findings.md`
- Transitions: none
- Removed v1 names: `onboard-project`

### `project normalize <project> [project options]`

Apply approved structural fixes from onboarding findings.

- Tier: `advanced`
- Access: `write`
- Approval: before applying the proposed normalization
- Profiles: `preview_write`, `project`
- Template: `project-onboarding-findings.md`
- Transitions: none
- Removed v1 names: `normalize-project`

### `project checkpoint <project> [--label <name>] [project options]`

Compact the active project frontier into a bounded, revision-linked context capsule without rewriting history.

- Tier: `advanced`
- Access: `write`
- Approval: before creating or replacing the authoritative Active Project Context document
- Profiles: `preview_write`, `project_compaction`
- Template: `project-context-capsule.md`
- Transitions: none
- Removed v1 names: `checkpoint-project`

### `project rollover <project> --next-release <label> [--resume <receipt>] [--next-goal <text>] [--next-project-name <name>] [--initiative <id-or-name>] [project options]`

Create a clean successor release project from a verified source project using a resumable, approval-gated rollover.

- Tier: `advanced`
- Access: `write`
- Approval: at each previewed release phase, with a final gate before resolving source work and completing the source project
- Profiles: `staged_rollover`, `project_compaction`
- Template: `project-rollover-proposal.md`
- Transitions: none
- Removed v1 names: `rollover-project`


## Milestone

### `milestone clarify <idea> [project options]`

Clarify intent, assumptions, constraints, and success criteria.

- Tier: `core`
- Access: `write`
- Approval: before saving the milestone spec
- Profiles: `preview_write`, `milestone`
- Template: `milestone-spec.md`
- Transitions: `clarify`
- Removed v1 names: `clarify-milestone`

### `milestone design <idea> [project options]`

Explore multiple architectural options before producing a milestone spec.

- Tier: `core`
- Access: `write`
- Approval: before saving the selected design
- Profiles: `preview_write`, `milestone`
- Template: `architectural-options.md`
- Transitions: `clarify`
- Removed v1 names: `design-milestone`

### `milestone create-tasks <milestone> [project options]`

Decompose an approved milestone into ordered, dependency-aware tasks.

- Tier: `core`
- Access: `write`
- Approval: before bulk task creation
- Profiles: `preview_write`, `milestone`
- Template: `task-spec.md`
- Transitions: `create-tasks`
- Removed v1 names: `create-tasks`

### `milestone plan <milestone> [--next-wave] [--scan fast|medium|heavy] [project options]`

Plan all tasks, or only the next live executable frontier with --next-wave.

- Tier: `core`
- Access: `write`
- Approval: covered by the approved planning stage; --next-wave preserves later tasks as Unplanned revision zero
- Profiles: `invocation_write`, `milestone`, `planning`
- Template: `implementation-plan.md`
- Transitions: `plan-tasks`
- Removed v1 names: `plan-tasks`

### `milestone review <milestone> [--next-wave] [--repair-safe] [project options]`

Review the stable contract and first wave, then use impact-closed incremental coverage.

- Tier: `core`
- Access: `write`
- Approval: explicit invocation covers review persistence and safe repairs; material findings require fix-review approval
- Profiles: `invocation_write`, `milestone`
- Template: `milestone-review-findings.md`
- Transitions: `review-milestone`
- Removed v1 names: `review-milestone`

### `milestone run <goal|milestone> [--mode step|loop] [--isolated-worktree] [loop options] [project options]`

Resume one stage, or use --mode loop for guarded milestone orchestration.

- Tier: `core`
- Access: `write`
- Approval: at each gated mutation; --mode loop persists guarded policy and stops at material gates
- Profiles: `per_operation_write`, `milestone`
- Template: `milestone-spec.md`
- Transitions: `clarify`, `review-project`, `create-tasks`, `plan-tasks`, `review-milestone`, `fix-review`, `start-implementation`, `verify-milestone`, `wrap-milestone`
- Removed v1 names: `run-milestone`, `run-milestone-loop`

#### Mode override: `loop`

`milestone run <goal|milestone> --mode loop [--max-parallel <2..8>] [--resume <receipt-id>] [--until approval-required,blocked,milestone-done] [--max-events <1..100>] [--repair-safe] [--isolated-worktree] [project options]`

Supervise fresh receipt-backed single events until a configured stop or event ceiling.

- Approval: invocation covers guarded automatic operations inside the bound milestone policy; material change, integration, model selection, merge, and push remain gated
- Profiles: `staged_milestone_orchestration`, `milestone`, `planning`
- Template: `milestone-orchestration-receipt.md`
- Transitions: none

### `milestone status <milestone> [project options]`

Report runtime storage, policy binding, active wave, plan validity, review coverage, repair state, statuses, and dependencies.

- Tier: `core`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `lifecycle`
- Template: none
- Transitions: none
- Removed v1 names: `status-milestone`

### `milestone verify <milestone> [--scan fast|medium|heavy] [project options]`

Verify every milestone success criterion using fresh evidence.

- Tier: `core`
- Access: `write`
- Approval: covered by the approved milestone execution
- Profiles: `invocation_write`, `milestone`
- Template: `completion-handoff.md`
- Transitions: `verify-milestone`
- Removed v1 names: `verify-milestone`

### `milestone wrap <milestone> [project options]`

Persist the retrospective, approved learnings, indexes, and read-back evidence.

- Tier: `core`
- Access: `write`
- Approval: before saving retrospective and learning artifacts
- Profiles: `preview_write`, `milestone`
- Template: `milestone-retrospective.md`
- Transitions: `wrap-milestone`
- Removed v1 names: `wrap-milestone`

### `milestone report-findings <milestone> --session-id <id> --finding <text>... [project options]`

Submit one idempotent testing-session batch and require machine plus fresh human reverification.

- Tier: `advanced`
- Access: `write`
- Approval: invocation reopens one unambiguous owner; otherwise one exact managed repair-task preview is required
- Profiles: `conditional_proposal_write`, `milestone`
- Template: `milestone-review-findings.md`
- Transitions: none
- Removed v1 names: `report-milestone-findings`

### `milestone fix-review <milestone> [--incremental] [project options]`

Apply approved review fixes and require a fresh milestone review; incremental active repairs retain the implementing stage.

- Tier: `advanced`
- Access: `write`
- Approval: before applying review fixes
- Profiles: `preview_write`, `milestone`
- Template: `milestone-review-findings.md`
- Transitions: `fix-review`
- Removed v1 names: `fix-review`

### `milestone pause <milestone> [project options]`

Park a milestone while preserving its resumable state.

- Tier: `advanced`
- Access: `write`
- Approval: explicit command invocation required
- Profiles: `invocation_write`, `lifecycle`
- Template: none
- Transitions: `pause`
- Removed v1 names: `pause-milestone`

### `milestone resume <milestone> [project options]`

Synchronize and resume a paused milestone.

- Tier: `advanced`
- Access: `write`
- Approval: after status and synchronization checks
- Profiles: `preview_write`, `lifecycle`
- Template: none
- Transitions: `resume`
- Removed v1 names: `resume-milestone`

### `milestone sync <milestone> [project options]`

Detect external changes and reconcile only approved conflicts.

- Tier: `advanced`
- Access: `conditional`
- Approval: before resolving conflicting mutations
- Profiles: `conditional_write`, `lifecycle`
- Template: `sync-report.md`
- Transitions: none
- Removed v1 names: `sync-milestone`

### `milestone archive <milestone> [project options]`

Gracefully archive a milestone and resolve affected tasks.

- Tier: `advanced`
- Access: `write`
- Approval: before changing task dispositions
- Profiles: `preview_write`, `lifecycle`
- Template: `milestone-archive-notes.md`
- Transitions: `archive`
- Removed v1 names: `archive-milestone`

### `milestone blockers <issue|milestone> [project options]`

Report the transitive blocker chain and critical path.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `lifecycle`
- Template: none
- Transitions: none
- Removed v1 names: `trace-blockers`

### `milestone diff <milestone> [project options]`

Show milestone changes since a point in time or stage.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `lifecycle`
- Template: `milestone-diff-report.md`
- Transitions: none
- Removed v1 names: `diff-milestone`

### `milestone handoff <milestone> [project options]`

Generate a runtime-aware context package for another agent or human.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `lifecycle`
- Template: `milestone-handoff.md`
- Transitions: none
- Removed v1 names: `handoff-milestone`

### `milestone onboard <milestone> [project options]`

Normalize one legacy milestone.

- Tier: `advanced`
- Access: `write`
- Approval: before normalization
- Profiles: `preview_write`, `lifecycle`
- Template: `milestone-spec.md`
- Transitions: none
- Removed v1 names: `onboard-milestone`

### `milestone checkpoint <target> [--level compact|prune] [project options]`

Compact task comments into one milestone archive and summary; explicitly select prune to also delete verified completed tasks.

- Tier: `advanced`
- Access: `write`
- Approval: exact preview approval; task deletion additionally requires explicit --level prune in the invocation
- Profiles: `context_management`
- Template: none
- Transitions: none
- Removed v1 names: none


## Task

### `task refine <issue> [project options]`

Refine one Human draft issue into a stable task contract and move it to Unplanned after approval.

- Tier: `core`
- Access: `write`
- Approval: before replacing the human draft description and moving it to Unplanned
- Profiles: `preview_write`, `task`, `task-intake`
- Template: `task-refinement.md`
- Transitions: none
- Removed v1 names: `refine-task`

### `task plan <issue> [--scan fast|medium|heavy] [project options]`

Create one authoritative implementation plan for an Unplanned task and move it to Backlog.

- Tier: `core`
- Access: `write`
- Approval: explicit invocation covers persisting the approved plan and moving the issue to Backlog
- Profiles: `invocation_write`, `task`, `planning`
- Template: `implementation-plan.md`
- Transitions: none
- Removed v1 names: `plan-task`

### `task next <milestone> [--isolated-worktree] [--scan fast|medium|heavy] [project options]`

Select and run the next unblocked task using deterministic priority rules.

- Tier: `core`
- Access: `write`
- Approval: covered by the approved milestone execution
- Profiles: `invocation_write`, `lifecycle`, `task-execution`
- Template: `implementation-plan.md`
- Transitions: `start-implementation`
- Removed v1 names: `implement-next`

### `task run <issue> [--isolated-worktree] [--scan fast|medium|heavy] [project options]`

Plan, implement, verify, hand off, and complete one unblocked task.

- Tier: `core`
- Access: `write`
- Approval: covered by the approved task unless scope changes
- Profiles: `invocation_write`, `task`, `task-execution`
- Template: `implementation-plan.md`
- Transitions: `start-implementation`
- Removed v1 names: `run-task`

### `task design <idea> [project options]`

Design a small standalone task without creating a milestone.

- Tier: `advanced`
- Access: `write`
- Approval: before creating the issue
- Profiles: `preview_write`, `task`
- Template: `task-spec.md`
- Transitions: none
- Removed v1 names: `design-task`

### `task create-bug <bug-description> [project options]`

Create a bug task with reproduction, impact, and verification criteria.

- Tier: `advanced`
- Access: `write`
- Approval: before creating the issue
- Profiles: `preview_write`, `task`
- Template: `bug-task-spec.md`
- Transitions: none
- Removed v1 names: `create-bug-task`

### `task organize <issue...|project> [project options]`

Recommend standalone, existing-milestone, or new-milestone placement for refined Unplanned tasks and apply only approved changes.

- Tier: `advanced`
- Access: `conditional`
- Approval: before attaching tasks, creating a milestone, or creating complementary tasks
- Profiles: `conditional_proposal_write`, `intake`
- Template: `unplanned-work-grouping.md`
- Transitions: none
- Removed v1 names: `organize-unplanned`

### `task replan <issue> [--scan fast|medium|heavy] [project options]`

Append a plan revision while preserving the original plan.

- Tier: `advanced`
- Access: `write`
- Approval: covered unless scope or downstream contracts change
- Profiles: `invocation_write`, `task`, `planning`
- Template: `replan-task.md`
- Transitions: none
- Removed v1 names: `replan-task`

### `task scope <issue> [project options]`

Assess whether a task should remain a task, split, or become a milestone.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `task`
- Template: none
- Transitions: none
- Removed v1 names: `review-task-scope`

### `task decompose <issue> [project options]`

Recommend splitting or promoting an oversized issue.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `task`
- Template: `task-split-proposal.md`
- Transitions: none
- Removed v1 names: `decompose-task`

### `task split <issue> [project options]`

Split an approved oversized issue into smaller dependency-aware tasks.

- Tier: `advanced`
- Access: `write`
- Approval: before creating replacement tasks
- Profiles: `preview_write`, `task`
- Template: `task-split-proposal.md`
- Transitions: none
- Removed v1 names: `split-task`

### `task promote <issue> [project options]`

Promote an oversized issue into a milestone with child tasks.

- Tier: `advanced`
- Access: `write`
- Approval: before creating a milestone and tasks
- Profiles: `preview_write`, `task`
- Template: `task-promotion-proposal.md`
- Transitions: none
- Removed v1 names: `promote-task`

### `task verify <issue> [--scan fast|medium|heavy] [project options]`

Collect fresh evidence before marking a task Done.

- Tier: `advanced`
- Access: `write`
- Approval: covered by the approved task
- Profiles: `invocation_write`, `task`, `task-verification`
- Template: `completion-handoff.md`
- Transitions: none
- Removed v1 names: `verify-task`

### `task backfill <issue> [--scan fast|medium|heavy] [project options]`

Draft and save a clearly labeled reconstructed completion handoff.

- Tier: `advanced`
- Access: `write`
- Approval: explicit command invocation required
- Profiles: `invocation_write`, `task`
- Template: `reconstructed-completion.md`
- Transitions: none
- Removed v1 names: `backfill-completion`

### `task onboard <issue> [project options]`

Normalize one legacy task.

- Tier: `advanced`
- Access: `write`
- Approval: before normalization
- Profiles: `preview_write`, `lifecycle`
- Template: `task-spec.md`
- Transitions: none
- Removed v1 names: `onboard-task`

### `task checkpoint <target> [project options]`

Archive all original task comments in one document and consolidate repeated plans, reviews and handoffs to one comment per type.

- Tier: `advanced`
- Access: `write`
- Approval: exact preview approval for archive, canonical comments and redundant-comment deletion
- Profiles: `context_management`
- Template: none
- Transitions: none
- Removed v1 names: none


## Wave

### `wave implement <milestone> [--isolated-worktree] [--max-parallel <2..8>] [--resume <wave-id>] [--scan fast|medium|heavy] [project options]`

Execute one reviewed dependency-graph wave concurrently on isolated child branches and clean task worktrees.

- Tier: `advanced`
- Access: `write`
- Approval: explicit invocation covers preparing and executing one fixed wave
- Profiles: `invocation_write`, `lifecycle`, `parallel-execution`
- Template: `parallel-wave-receipt.md`
- Transitions: `start-implementation`
- Removed v1 names: `implement-wave`

### `wave reconcile <milestone> --wave <wave-id> [--delete-merged-branches] [--scan fast|medium|heavy] [project options]`

Reconcile verified wave branches with merge commits, combined verification, durable receipts, and safe cleanup.

- Tier: `advanced`
- Access: `write`
- Approval: one approval after an exact ordered integration preview
- Profiles: `preview_write`, `lifecycle`, `wave-reconciliation`
- Template: `parallel-wave-receipt.md`
- Transitions: none
- Removed v1 names: `reconcile-wave`


## Verification

### `verification policy-set <project|milestone> (--default enabled|disabled | --override enabled|disabled|inherit) [--reason <text>] [project options]`

Set the project default or one milestone override for final human verification.

- Tier: `advanced`
- Access: `write`
- Approval: one exact preview covering every affected active milestone, gate, checklist, and orchestration receipt
- Profiles: `preview_write`, `project`
- Template: none
- Transitions: none
- Removed v1 names: `set-human-verification-policy`

### `verification status <project|milestone> [project options]`

Report persisted and effective human-verification policy, gates, checklists, and drift without mutation.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `project`
- Template: none
- Transitions: none
- Removed v1 names: `status-human-verification`

### `verification confirm <milestone> [project options]`

Record final human confirmation, close the managed gate, and advance to human-verified.

- Tier: `advanced`
- Access: `write`
- Approval: explicit human confirmation of the current revision-bound checklist
- Profiles: `invocation_write`, `milestone`
- Template: `human-verification-checklist.md`
- Transitions: `confirm-milestone`
- Removed v1 names: `confirm-milestone`

### `verification fail <milestone> --reason <text> [project options]`

Record failed human verification, create one repair task, and return the milestone to implementation.

- Tier: `advanced`
- Access: `write`
- Approval: one exact repair-task preview
- Profiles: `preview_write`, `milestone`
- Template: `human-verification-checklist.md`
- Transitions: `fail-milestone-verification`
- Removed v1 names: `fail-milestone-verification`


## Learning

### `learning review <project|milestone> [project options]`

Summarize reusable learnings by tag and impacted area.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `learning`
- Template: none
- Transitions: none
- Removed v1 names: `review-learnings`

### `learning apply <milestone|idea> [project options]`

Return relevant, cited lessons before planning.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `read_report`, `learning`
- Template: none
- Transitions: none
- Removed v1 names: `apply-learnings`

### `learning organize <project> [project options]`

Draft cleanup for duplicate, stale, or low-signal learning entries.

- Tier: `advanced`
- Access: `conditional`
- Approval: before changing learning documents
- Profiles: `conditional_write`, `learning`
- Template: `project-learning-index.md`
- Transitions: none
- Removed v1 names: `organize-learnings`


## Context

### `context budget <project|milestone|task> <target> (--tokens <integer> | --reset) [project options]`

Persist an inherited, raise-only context token allowance.

- Tier: `advanced`
- Access: `write`
- Approval: explicit invocation authorizes exactly the selected budget update or reset; agent-proposed increases require approval
- Profiles: `context_management`
- Template: none
- Transitions: none
- Removed v1 names: none

### `context inspect <project|milestone|task> <target> [project options]`

Inspect scope, effective context limits, and resumable state without mutations.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `context_management`
- Template: none
- Transitions: none
- Removed v1 names: none


## Runtime

### `runtime inspect <project|milestone|task> <target> [project options]`

Inspect scope, effective context limits, and resumable state without mutations.

- Tier: `advanced`
- Access: `read`
- Approval: none
- Profiles: `context_management`
- Template: none
- Transitions: none
- Removed v1 names: none

## Removed v1 command mapping

Flat commands are rejected and never executed as aliases.

| Removed command | Exact replacement |
|---|---|
| `analyze-codebase` | `codebase analyze` |
| `apply-learnings` | `learning apply` |
| `archive-milestone` | `milestone archive` |
| `audit-project` | `project audit` |
| `backfill-completion` | `task backfill` |
| `checkpoint-project` | `project checkpoint` |
| `clarify-milestone` | `milestone clarify` |
| `confirm-milestone` | `verification confirm` |
| `create-bug-task` | `task create-bug` |
| `create-project` | `project create` |
| `create-tasks` | `milestone create-tasks` |
| `decompose-task` | `task decompose` |
| `design-milestone` | `milestone design` |
| `design-task` | `task design` |
| `diff-milestone` | `milestone diff` |
| `fail-milestone-verification` | `verification fail` |
| `fix-review` | `milestone fix-review` |
| `handoff-milestone` | `milestone handoff` |
| `implement-next` | `task next` |
| `implement-wave` | `wave implement` |
| `import-codebase` | `codebase import` |
| `normalize-project` | `project normalize` |
| `onboard-milestone` | `milestone onboard` |
| `onboard-project` | `project onboard` |
| `onboard-task` | `task onboard` |
| `organize-learnings` | `learning organize` |
| `organize-unplanned` | `task organize` |
| `pause-milestone` | `milestone pause` |
| `plan-task` | `task plan` |
| `plan-tasks` | `milestone plan` |
| `promote-task` | `task promote` |
| `reconcile-wave` | `wave reconcile` |
| `refine-task` | `task refine` |
| `replan-task` | `task replan` |
| `report-milestone-findings` | `milestone report-findings` |
| `resume-milestone` | `milestone resume` |
| `review-learnings` | `learning review` |
| `review-milestone` | `milestone review` |
| `review-project` | `project review` |
| `review-task-scope` | `task scope` |
| `rollover-project` | `project rollover` |
| `run-milestone` | `milestone run --mode step` |
| `run-milestone-loop` | `milestone run --mode loop` |
| `run-project` | `project run` |
| `run-task` | `task run` |
| `set-human-verification-policy` | `verification policy-set` |
| `split-task` | `task split` |
| `status-human-verification` | `verification status` |
| `status-milestone` | `milestone status` |
| `sync-milestone` | `milestone sync` |
| `trace-blockers` | `milestone blockers` |
| `update-project` | `project update` |
| `verify-milestone` | `milestone verify` |
| `verify-task` | `task verify` |
| `wrap-milestone` | `milestone wrap` |
