# Task comment checkpoint

## Comment slots are the steady state

Each managed type — `plan`, `handoff`, `review`, `execution` — owns one comment slot on the task.
The normal write path never appends: resolve the layout with `context task-comment-slots`, then
plan the write with `context task-comment-slot`, which returns `update-comment` for an occupied
slot and `create-comment` only for an empty one. The returned `written_fields` feeds the read-back
projection, so confirming the edit costs one field rather than a whole comment.

Slots are keyed by the managed marker, not by comment position. Human comments and thread replies
interleave with managed ones, so an ordinal would break the first time somebody commented before
the plan existed. Two comments claiming one type stop with `TASK_SLOT_AMBIGUOUS` rather than
picking one; `task checkpoint` consolidates them. Each edit records a bounded superseded-revision
summary inside the comment so the previous state stays legible, while the exact prior bodies
remain recoverable from the task archive.

`task checkpoint` remains the repair path for tasks that accumulated appended comments before
slots, or that acquired duplicates.

## Consolidating existing history

`task checkpoint` reduces the task's actual comment history. Archive all original comments in
one project Document, keep one canonical comment per selected type, then remove approved
redundant comments. The stable task description and status are not rewritten. This is distinct
from project/milestone context snapshots; no new manifest, snapshot, receipt or active-reference
Documents are created. Existing snapshots remain historical and are not the task's active source.

## Prepare a reviewable checkpoint

Use linear-workflow. Resolve the task/project, list every comment page, and preserve each exact
connector object including body, ID, author/onBehalfOf, createdAt/updatedAt, parentId, quotedText,
resolvedAt and any extra metadata. Also snapshot the exact task object/description. Resolve one
Document by the exact title `task-comment-archive/<project-id>/<task-id>`, including archived
matches; ambiguity or an unreadable existing archive stops the command. Never truncate originals.

Classify explicitly from content/provenance, not just author or a title regex:

- `plan`: current implementation plan and superseded replans; retain current structured plan,
  hashes, revision, material/evidence bindings and unresolved decisions verbatim. Older approaches
  become a concise history with source references; never treat them as current instructions.
- `review`: multiple review passes; preserve open/resolved/regressed findings and acceptance
  evidence, the latest authoritative ledger, candidate hash and limits of verification.
- `handoff`: completion/resume handoffs; retain current outcome, constraints, next actions and
  exact structured completion/verification bindings.
- `execution`: isolation/integration receipts; retain current structured receipt, commits,
  approval bindings, unresolved integration work and recovery references.

Keep one comment ID per selected type (prefer its existing managed canonical comment). Merge
all selected comments of that type into its exact proposed body. Keep human discussion, unknown
comments and threads with replies intact by default; archive them too. Do not classify a comment
as agent-generated solely because the connector uses the human account. Show the classification
and exact deletion list. Do not invent resolved findings or fresh verification. If required
structured bindings exceed the compact budget, stop instead of dropping fields.

Compile `context task-checkpoint-preview INPUT.json [--context-policy inventory.json]` with:
`project_id`, `task_id` (UUID), `identifier`, exact `issue`, complete `comments`,
`has_next_page: false`, `archive` (existing parsed Document or null), `archive_max_bytes`
(the connector's confirmed single-document capacity), optional `default_tokens`, and:

- `groups`: `{type, source_ids, canonical_id, body}` entries, at most one per type;
- `keep_ids`: every unselected comment ID.

The helper archives all comment versions and issue descriptions, preserving prior archive
entries. It emits exact archive content, canonical comments, deletions, before/after sizes,
deterministic operation ID and preview hash. The active size includes kept discussion and all
canonical comments. Serialize the archive as compact JSON in one fenced block; its key is its
Document title. A single archive exceeding provider capacity fails without splitting or deletion.
The source archive can be larger than the active-context budget: transport it file-backed and
read/verify in bounded sections; do not inject the entire archive into the agent's working context.

Approve the exact preview hash before mutation. A prior snapshot-activation approval does not
authorize deleting comments. Explicit user instructions can authorize the specified consolidation;
do not invent additional approval gates when the exact scope/content is already authorized.

## Apply and resume safely

Persist the approved preview locally for the current operation; it is disposable, not evidence
of persistence. Call `context task-checkpoint-next INPUT.json --context-policy inventory.json` with `preview`, `approved_hash`,
fresh exact `issue`, complete current `comments`, `has_next_page: false` and current parsed
`archive` (null if absent). The helper is pure and returns one action, never makes a Linear call.

1. `save-archive`: refresh the singleton Document, check the expected hash, then create/update
   exactly the archive value. Read it back by returned ID; compare parsed canonical JSON hashes.
   This one Document contains the complete originals and the checkpoint's operation manifest.
2. `save-comment`: refresh the target; compare its full object hash with `expected_hash`; update
   only its body. Read the complete current comments again and verify exact body plus preserved
   metadata. The generated marker identifies task, type and archive key; preserve it on later updates.
3. `delete-comment`: only after the archive and every canonical comment match fresh readbacks,
   refresh that exact original, compare its full hash, delete it, and list comments again to prove
   absence. Never delete by title, positional index or an incomplete page. Deletion acknowledgement
   alone is not success.
4. Repeat the selector on fresh observations. `complete` requires every approved redundant ID
   absent, every canonical body exact, all kept originals unchanged and the exact archive intact.
   Return the single archive link, remaining per-type comments and unresolved work. Stop this run.

On interruption reuse the same approved preview. Already matching writes and absent approved
IDs are skipped. A changed/new comment, task contract/status change, archive drift or failed
read-back stops further mutation. Before replanning a partial operation, recover the approved
archive and reconcile completed writes; never overwrite it with only the remaining live comments.
An unchanged task timestamp bump caused by comment mutations is not contract drift. Never claim
rollback restored original IDs/authorship after deletion; originals remain recoverable in the archive.

## Reading afterward

Execution reads the canonical comments plus any subsequent new comments. Do not automatically
load this archive, obsolete plan versions or old snapshot/manifest Documents. Resolve missing
historical evidence through the archive key in the canonical marker, selecting a source ID/version
and a bounded section. The remaining issue comments, not an optional hidden snapshot, deliver the
context reduction even to an agent that lists all current comments.
