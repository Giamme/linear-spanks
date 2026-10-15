# Lifecycle Commands

## Selection and visibility

`task next` selects among unblocked tasks by milestone task-list order ascending, then Linear
priority ascending with null last, dependency fan-out descending, creation time ascending, and
issue ID ascending as the final tie-breaker. State the selection reason before running exactly one
task. After selection it uses the same plan revision, executor-tier delegation, drift handling,
risk-based review, coordinator ownership, and `single-task` boundary as `task run`.
With `--isolated-worktree`, it selects first and then uses the same one-receipt isolated execution,
integration approval, recovery, and cleanup rules as flagged `task run`.

Persist a revision-bound preflight receipt after selection and readiness checks. Reuse it when
handing the selected task to `task run` only if target, blocker, plan, harness,
requested/effective assurance, and scan tier still match. Repository revision is trace-only and
may refresh without invalidating the preflight. Validate with `runtime preflight`; any material
mismatch returns `PREFLIGHT_INVALIDATED` and repeats preflight instead of trusting stale readiness.

`milestone status` is read-only. Return a status table and Mermaid dependency graph with done,
in-progress, blocked, and todo classes; annotate the critical path. Report final
human-verification effective value, source, revisions, gate state, current checklist, and receipt
drift separately. Exclude the managed gate from regular task totals and graph nodes.

When a reviewed persistent graph exposes at least two compatible ready tasks and the harness has
capacity, recommend `wave implement`; otherwise recommend `task next`. `wave implement` and
`wave reconcile` follow `parallel-execution.md`, use a `single-wave` boundary, and never collapse
execution and integration into one approval.

`milestone blockers` is read-only and follows transitive blockers up to four levels, distinguishing
internal from external project blockers. `milestone diff` and `milestone handoff` are also
read-only and use their registered templates.

## Pause, resume, and synchronization

- `milestone pause`: preserve the prior stage as `resume_stage`, record the reason, then transition
  to `paused`.
- `milestone resume`: run status and sync first. Resolve conflicts, validate the stored resume
  stage, then transition back to it.
- `milestone sync`: classify drift as benign, informational, or conflicting. Report benign and
  informational changes; obtain approval before resolving conflicts.

## Archival and onboarding

`milestone archive` requires a reason and approval. Leave Done tasks intact; ask about In Progress
tasks; cancel internal Todo/Backlog work; and ask whether to reparent tasks with external
dependents. Read back every changed task and the archived state.

`milestone onboard` and `task onboard` normalize one legacy entity after showing and receiving
approval for the exact changes.
