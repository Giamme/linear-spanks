# Milestone checkpoints: compact and prune

`milestone checkpoint <milestone>` and `--level compact` consolidate actual task comments by
plan/review/handoff/execution type, retain every task entity, archive all originals in one
milestone Document, and update one short paragraph in the milestone description.

`milestone checkpoint <milestone> --level prune` performs that same consolidation and additionally
deletes explicitly selected completed, verified tasks. Prune is never inferred from approval,
project/milestone execution permission, configuration, a parent loop or a previous checkpoint.
A resumed prune must restore the exact original invocation, including its level. The exact preview
approval covers the selected IDs and bodies; the argument alone does not approve unseen deletions.
Open tasks, canceled tasks without completed acceptance and managed human-verification gates stay.

## Evidence and storage

Use linear-workflow. Resolve project and milestone, then fetch a complete paginated task inventory.
For each task retrieve its exact issue object and complete comments with author/timestamp/thread
metadata. Resolve existing standalone task archives and the singleton milestone archive, including
archived title matches. Never infer missing originals from the reduced live comments: embed prior
task archives in the milestone archive. The key/title is
`milestone-task-archive/<project-id>/<milestone-id>`. Subsequent checkpoints update the same Document.
Do not create per-task archive Documents, context manifests, snapshots or active-reference Documents.

Use the task checkpoint classification and preservation rules. Provide one proposed canonical
comment per selected type, keeping unknown/human discussion and reply threads. An already compact
plan index continues to reference its exact archived payload; do not expand it by default or turn
it into a new authoritative plan revision. Preserve description and status on retained task entities.
Milestone criteria and existing prose remain unchanged outside one managed summary block.

The summary is one paragraph (at most 2,000 characters): delivered outcomes, retained work and
unresolved limits. Never equate task completion with milestone verification. The generated block
includes the archive link and its stable key. Update it in place, not by appending new summaries.
The preview uses `{{archive_url}}`; its sole permitted substitution is the URL returned by the
fresh readback of the exact archive Document. This deterministic provider-assigned link substitution
is part of the preview, not permission to change paragraph text.

## Preview input

`context milestone-checkpoint-preview INPUT.json --context-policy inventory.json` takes:

- `invocation`: the exact compiled public invocation (`command`, `target`, `positionals`, `options`);
  absent `options.level` means compact. Only its explicit value `prune` permits task deletion.
- `project_id`, exact `milestone` with `id`, `name`, `description`, complete `tasks`, and
  `tasks_has_next_page: false`.
- Each task has exact `issue`, `comments`, `has_next_page: false`, `groups` and `keep_ids` as in
  task checkpoint, plus `archive` (parsed prior task archive, or null). The helper can also reuse
  an embedded task archive from the previous milestone checkpoint. Bind native task UUIDs and
  projectMilestone membership; do not pass unselected cross-milestone tasks into this inventory.
- `archive`: the existing parsed milestone archive or null; `archive_max_bytes`: confirmed
  single-document capacity. Transport/read the archive file-backed in bounded sections. Overflow
  stops without splitting into extra Documents or dropping originals.
- `summary`: the proposed paragraph; `prune_ids`: exact task UUIDs (empty in compact).
- For every prune ID, `outcomes[id]` contains `verification_status: passed`, exact
  `candidate_commit`, concise `summary` and `evidence: [{id, hash}]`. Each hash binds the full
  original completion/review comment object, live or archived. The coordinator must validate
  the evidence actually establishes this task's completed acceptance at that candidate; a status
  label, agent assertion, stale plan, missing source or title is insufficient.
- Prune requires fresh complete native `relations.blocks`, `blockedBy` and `relatedTo` on selected
  issues. Every surviving related issue (including cross-project consumers) appears in `consumers`
  with exact `issue`, complete `comments`, and `has_next_page: false`. The preview includes one
  short archive-reference comment for each consumer. These references must exist before deletion.

The result binds all original versions, embedded task archives, canonical bodies, selected prune
IDs, dependency handoffs, milestone summary, policy, invocation and exact preview hash. Approval
must name this concrete preview. An approved compact preview can never be promoted to prune.

## Apply one operation, refresh, resume

`context milestone-checkpoint-next INPUT.json --context-policy inventory.json` takes `preview`,
`approved_hash`, exact original `invocation`, current complete task/consumer inventories and
milestone, current parsed `archive`, and `archive_url` from its readback. For already deleted IDs, include
`absence_readbacks: [{id, direct_lookup: "not_found", milestone_absent: true}]` from actual
post-delete reads; disappearance from milestone membership alone is not deletion. If pruning, supply freshly
confirmed `delete_issue_capability: {available: true, provider, operation}`; capability cannot be
invented or assumed. Without it the helper stops before any mutation. Use a connected API/CLI only
when actually available and authorized; never substitute Canceled, archive or detach for delete.

The selector returns one action, never performs a Linear mutation itself:

1. `save-archive`: refresh by singleton key, compare expected hash, save compact JSON in one fenced
   block, and read back the complete parsed payload hash. Preserve all earlier archive versions.
2. `save-comment`: refresh the exact source comment and expected hash, update only its body, then
   list comments to verify body and original provenance. All canonical comments across the milestone
   must match before redundant comment deletion begins.
3. `save-dependency-comment`: persist the exact proposed archive-reference body on the survivor;
   read back the complete comment inventory. Reuse one exact matching body on retry; never post a
   duplicate. For internal survivors, use the same fresh issue/comment state in tasks and consumers.
4. `save-milestone-summary`: compare the current description hash, replace only the managed block
   according to the exact returned full description, and read it back.
5. `delete-comment`: refresh and hash-check the exact redundant comment, delete, then prove absence
   via a fresh complete inventory. Human/unknown comments and reply threads are preserved.
6. `delete-issue`: available only in explicit prune, after every prior readback. Refresh exact issue
   and full comment history immediately before deletion; re-run the selector against changed state.
   Confirm outcome/relations, perform the declared issue-delete operation, then verify absence from
   the milestone and direct native lookup. Do not treat a permissions error or ambiguous lookup as
   absence. Archive and consumer references must remain accessible independently of deleted tasks.
7. `complete`: archive, summary, retained tasks/comments and deleted IDs match fresh observations.
   Return level, archive URL, consolidated/pruned counts, retained work and limitations; stop.

Refresh the full relevant state after every write. New tasks/comments, changed source bodies,
reopened work, policy drift, missing retained tasks or modified archive stop further mutations.
Expected timestamp bumps, derived progress changes and relation removal caused by already approved
issue deletions do not invalidate the run. Reuse the same approved preview after interruption.
Never recreate deleted tasks and claim their original identities/authorship were restored.

## Read archived dependencies

A consumer's managed archive-reference comment and the milestone summary are retrieval indexes.
Read the current native task first. Only a verified missing issue can be resolved through
`context archived-task` with `task_id`, parsed `archive`, its `expected_archive_hash`, and
`native_absence_verified: true`. The helper requires an explicit prune record and exact preserved
terminal evidence. It returns an archived completed outcome row, not fresh verification.

Before runtime task-next, milestone/project event selection and graph validation, the coordinator
adds these archived outcome rows to the compact dependency matrix. Keep native unresolved nodes;
exclude archived terminal nodes from new dispatches while retaining their output references.
Revalidate consumed artifacts for the current candidate. Missing IDs without an archive binding
remain errors. Do not load whole task histories merely to satisfy a former blocker edge.
