# Project Epochs

Use `project checkpoint` for a compact session boundary inside an active project and
`project rollover` for a major release boundary. Neither command deletes historical entities or
rewrites milestone, issue, comment, or document history.

## Active Project Context

`project checkpoint` reads the project inventory in deterministic measured batches and prepares
an immutable ContextSnapshot, paginated ContextManifest documents, a CompactionReceipt, and a small
active reference. Follow [context management](context-management.md): preview exact writes and source
bindings, obtain preview-hash approval, refresh sources, persist and read back the snapshot, then
update the active reference. Preserve existing `Active Project Context` capsules as original sources;
convert them only through bounded reads during an approved checkpoint. If Documents are unavailable,
return the validated preview and capability gap without claiming activation.

The capsule is a retrieval index, not a second system of record. Later project, milestone, and task
commands read it first for project-wide orientation, then re-read their current target, relations,
plans, blockers, and revisions from Linear. Current entity state always wins. Capsule provenance
must identify every expected source as covered or explicitly excluded with a reason.

Inventory batches are ordered by milestone order, entity type, Linear priority with null last,
creation time, and ID. A batch may contain at most 30 compact rows and 12 expanded entities. The
run may contain at most 64 batches and the Markdown body at most 24 KiB. Release each raw batch
after reducing it into capsule content and provenance. Return `CONTEXT_OVERFLOW` rather than
silently omitting evidence.

## Release rollover

`project rollover` resumes with `--resume <receipt>` from a validated `RolloverReceipt` and executes
at most one phase per agent session. Persist exactly one source-project Linear Document titled
`Project Rollover Receipt — <next release>` before the first Linear mutation; update and read it
back after every phase, and link it from the successor once created. If durable Document
persistence is unavailable, stop after returning the preview and capability gap:

1. `inventory`: resolve the source project and Initiative membership; build the complete milestone,
   issue, document, learning, and open-decision inventory. The source remains active.
2. `preview`: draft the release capsule, successor Project Spec, three-to-seven outcome milestones,
   selected carry-over issue contracts, and a disposition for every unfinished source issue and
   milestone. Persist no Linear changes during this phase.
3. `successor-created`: after approval and a final source refresh, persist and read back the prepared
   capsule and successor project. Copy existing Initiative membership; if absent, continue
   standalone and report the warning unless `--initiative` was supplied.
4. `roadmap-created`: preview-gate, create, reconcile, and read back the approved successor roadmap.
   Do not create ordinary roadmap tasks.
5. `carryover-created`: preview-gate and recreate only selected issues. Preserve stable intent and
   acceptance criteria, start each issue in `Unplanned`, and add reciprocal provenance links. Do
   not copy volatile plans, completion comments, or stale status.
6. `source-resolved`: after every successor read-back, separately approve and apply each source
   issue and milestone disposition. Recreated source issues become superseded or canceled. Any
   missing approval, failed read-back, or unresolved source item blocks this phase.
7. `finalized`: finalize and read back the release capsule, post and read back the release update,
   then separately approve and set the source project to a Completed-category status. Report the
   successor entry point and let Linear apply the workspace's normal archival policy.

Use `context rollover-transition` before changing phases and `context rollover-receipt` before every
phase.
Bind the receipt to the source project revision, source snapshot hash, and approved plan hash. Any
mismatch returns `ROLLOVER_DRIFT`; refresh the inventory and preview instead of applying stale
operations. Every bulk mutation uses a stable operation ID and payload hash. A failed or partial
phase persists only acknowledged operations, keeps the source active, and resumes idempotently.

The rollover is complete only when the successor project, capsule, roadmap, selected carry-overs,
source dispositions, and final source status have all been explicitly read back and the unresolved
source list is empty.
