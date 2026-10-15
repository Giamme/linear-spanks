# Milestone Orchestration Loop

Without loop flags, `milestone run --mode loop` advances one receipt-backed event for exactly one
milestone. With `--until ... --max-events ... --repair-safe`, its outer supervisor repeatedly
starts fresh bounded single events and stops only for a configured material condition or the
event ceiling. Use `milestone run --mode loop`; the removed v1 `--autopilot` spelling is rejected
with its exact replacement.

Create one high-strength milestone orchestrator and one executor at the validated tier per task.
Use the shared task policy to decide whether an independent verifier is required. The orchestrator may create and plan local tasks, dispatch a fixed
isolated-worktree frontier, integrate only verifier-approved commits through the existing exact
preview, verify the milestone, and persist its retrospective. It never edits tracked source.

Persist each `Milestone Orchestration Receipt` immutably and project current coordination state
into exactly one `Linear Spanks Milestone Runtime — <milestone-id>` Document. If Documents are
unavailable, use one managed fallback comment. Promote a matching comment when capability returns;
duplicate, malformed, or conflicting artifacts stop with `MILESTONE_RUNTIME_STATE_CONFLICT`.
Live issues and immutable receipts remain authoritative. Before creating
or resuming it, run `orchestration-scope-check`: an active project loop blocks a milestone loop,
and any active milestone loop blocks a project loop. Different milestone loops may proceed only
when their dependency graph has no project-level or cross-milestone coordination requirement.

Use `milestone-loop-next` to select one event: project coordination required, approval, execution,
verification, integration, dispatch, pending human verification, wrap, milestone orchestration,
completion, or blocked. The
same receipt resumes with `milestone run --mode loop --resume <receipt-id>`; ambiguous active receipts stop
with `MILESTONE_ORCHESTRATION_RECEIPT_AMBIGUOUS`, while changed bound state stops with
`MILESTONE_ORCHESTRATION_DRIFT`.

After every event, read the receipt and runtime projection back before policy reevaluation. A
guarded policy survives sessions but expires on material scope, acceptance, dependency,
authorization, migration, or project-policy drift. Integration, model selection, merge, and push
are never automatic. The default is 20 events and the hard cap is 100.

Bind the effective human-verification value, source, project-policy revision, override revision,
and hash in the milestone receipt. Drift returns `HUMAN_VERIFICATION_POLICY_DRIFT`. When enabled
machine verification produces a current pending checklist, select `await-human-verification` and
stop; neither wrap nor downstream dispatch is legal until explicit confirmation or an approved
disable/bypass has been reconciled.

Each task follows the shared progress-aware loop, with at most four automatic executions. After four failures,
return `MODEL_SELECTION_REQUIRED`; one explicitly configured medium/high model selection authorizes
one repair and fresh verification appropriate to its risk. Preserve verifier continuity through the bounded ledger.

Milestone wrap may write the milestone retrospective and candidate learning handoff only. Project
description changes, project learning curation, and cross-milestone conflict resolution require
`project run` and return `PROJECT_COORDINATION_REQUIRED` from this loop.

## Optional repository discovery

Follow [Ripwire](ripwire.md) after each child resolves its repository. Carry only the compiled
`ripwire.child_arguments` into child invocations and role briefs; resolve saved preferences
against that child repository. Include advisory query evidence in the measured context packet.
