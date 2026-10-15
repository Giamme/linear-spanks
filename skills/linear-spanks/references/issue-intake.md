# Issue Intake

Use this policy for Human draft refinement, issue planning, and Unplanned work organization.

## Status capability preflight

Resolve the issue's team and list its issue statuses before any mutation. Require exactly one status
named `Human draft`, `Unplanned`, and `Backlog`. These names are issue-readiness states, not
milestone workflow stages. Stop without mutation when a required status is absent or ambiguous.

Validate every readiness change with:

```bash
python3 scripts/linear_spanks_cli.py state issue-transition <namespace> <command> \
  --from-status '<current>' --to-status '<proposed>'
```

Never skip `Human draft -> Unplanned -> Backlog`. Re-read the issue immediately before and after
each approved write.

## Refine a Human draft

`task refine` operates on exactly one issue whose current status is `Human draft`:

1. Preserve the source issue ID, revision, human-authored text, and current relationships in the
   proposal. Treat the human text as intent, not disposable copy.
2. Resolve ambiguity through concise questions. Do not invent product decisions merely to make the
   issue look complete.
3. Draft a stable task contract with goal, context, scope, non-scope, testable acceptance criteria,
   dependencies, verification, risks, and open questions using `task-refinement.md`.
4. Report milestone-fit signals, but do not attach the issue or create roadmap entities during
   refinement.
5. Show the exact replacement description and the status change to `Unplanned`. Apply both only
   after approval and only if the source revision and status are unchanged.
6. Read back description, status, project, relationships, and milestone. Report
   `task organize` as an optional next command.

## Plan an Unplanned task

`task plan` operates on exactly one refined issue whose current status is `Unplanned`. Use the high,
read-only planner and repository evidence rules from model routing. Persist one authoritative
`Implementation Plan`, read it back, validate `Unplanned -> Backlog`, then move the issue to
`Backlog` and read it back. Do not implement code. If the task contract is still ambiguous, return
to `task refine` instead of planning assumptions.

For `milestone plan`, apply the same rule independently to every `Unplanned` task in the approved
milestone planning stage. A task moves to `Backlog` only after its own authoritative plan is saved
and read back. Do not change already planned or active task statuses.

## Organize refined Unplanned work

`task organize` starts read-only. Resolve either the explicitly selected Unplanned issues or a
bounded project-wide candidate set, then build a compact matrix containing goal, deliverable
boundary, inputs, outputs, dependencies, milestone membership, and source revision.

For each candidate, return exactly one recommendation:

- `existing-milestone`: use only when the milestone objective, scope, success criteria, timing, and
  dependencies genuinely contain the task. A title, label, component, or technology match alone is
  insufficient.
- `new-milestone`: use only when at least two tasks share one independently verifiable deliverable
  boundary and no existing milestone fits without changing its contract.
- `standalone`: use when neither milestone condition is satisfied.

Inspect existing non-terminal milestones before proposing a new one. For a new milestone, provide
objective, scope, non-scope, success criteria, ordered existing tasks, formal blockers, and the
minimal complementary tasks required for completeness or verification. Do not invent complementary
tasks merely to reach the two-task threshold. AI-created complementary tasks start in `Unplanned`
with a stable task contract and explicit provenance in the proposal.

Render `unplanned-work-grouping.md` with source revisions and exact proposed operations. Obtain
approval separately for existing-task attachments, milestone creation, and every complementary
task. Use bulk operation IDs and canonical payload hashes. Re-read all affected issues and the
milestone after writes; omit every unapproved operation.
