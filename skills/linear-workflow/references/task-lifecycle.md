# Issue and Milestone Lifecycle

## Task lifecycle

1. `Human draft` holds raw human-authored intent. Preserve it while proposing a stable contract;
   after approval, update the description and move the issue to `Unplanned`.
2. `Unplanned` means refined but not approved for implementation planning. The description holds
   stable goal, scope, acceptance criteria, dependencies, and optional milestone.
3. The authoritative `Implementation Plan` holds approach, likely files, verification, risks, and
   open questions. Prefer updating one canonical plan comment. If updates are unavailable, append a
   revision marker with its revision and superseded comment ID; retrieve only the highest valid
   revision into active execution context.
4. Move an issue from `Unplanned` to `Backlog` only after its authoritative plan is saved and read
   back. Move Backlog or Todo to In Progress before coding. Follow the plan unless evidence requires a
   replan.
5. Before Done, save a compact completion receipt with changes, decisions, verification, limits,
   follow-ups, and newly unblocked issues. Read back the issue and inspect `relations.blocks`.

Use Backlog for planned work, formal blocker relations for blocked work, and Canceled for
duplicates. Do not mark Done without fresh evidence.

## Dependencies and claiming

Hard blockers use `blockedBy`; soft context uses `relatedTo`. Relations append. Milestone membership
does not imply dependency. Compare described dependencies with formal relations and report gaps.
Traverse compact blocker states first; expand unfinished or contract-relevant blockers within the
active context limits.

When claim mode is enabled, confirm the task is unassigned or assigned to the known service account,
assign it and move it In Progress, re-read, and back off if another assignee won. A human's explicit
request to work on their assigned issue overrides the automatic skip rule.

## Milestones

Create a milestone only for at least two issues sharing one deliverable boundary. Inspect existing
non-terminal milestones first and prefer a compatible one when its objective, scope, success
criteria, timing, and dependencies contain the work. Follow the resolved project's naming
convention. When assigning an issue to a milestone, pass both milestone and project because Linear
may reject milestone membership without project membership.

Do not create dependency links merely because issues share a milestone, duplicate repository docs
in Linear, or comment every commit.
