# Document Persistence

Use Linear Documents for durable project memory such as the Project Learning Index, Learning
Entries, milestone retrospectives, and other artifacts that must outlive an agent session. Keep
repository documentation in the repository and link it from Linear.

`Active Project Context` is a singleton project-scoped retrieval index. Replace it only through an
approved `checkpoint-project` or `rollover-project` operation after validating the complete body
and source coverage. Keep the prior document revision available through Linear history; do not
create several competing active capsules.

`Linear Spanks Human Verification Policy` is also a singleton project-scoped Document. Its managed
marker binds the project ID, enabled/disabled default, positive revision, canonical hash, actor,
and timestamp. Exact-title collisions or malformed markers fail closed. Missing policy means the
disabled system default. If Document create/update capability is unavailable, project-wide policy
mutation returns `HUMAN_VERIFICATION_POLICY_UNAVAILABLE`; do not fall back to a project
description or comment. Milestone overrides are stored independently in milestone descriptions.

A release rollover similarly owns one source-project Document titled `Project Rollover Receipt —
<next release>`. Store the validated machine-readable receipt there before any rollover mutation,
update and read it back after each phase, and link it from the successor project. Without durable
Document persistence, a rollover may produce a preview but must not begin mutation.

Task checkpoints own exactly one `task-comment-archive/<project-id>/<task-id>` Document.
Preserve complete comment versions (body, IDs, authors, timestamps, thread/anchor metadata)
and the original task description there before replacing canonical comments or deleting
approved redundant comments. Update that same Document on later checkpoints; never create
per-pass archive Documents. Read it back in full and compare its canonical payload hash.

Milestone checkpoints own one `milestone-task-archive/<project-id>/<milestone-id>` Document.
Embed prior task comment archives, preserve all original issue/comment versions, and update the
same Document on later checkpoints. Compact keeps issues. Prune requires the explicit public
`--level prune` argument, exact preview approval, verified terminal outcomes, and a confirmed
issue-delete capability. Archive, canonical comments, consumer handoffs and the managed milestone
paragraph must be read back before issue deletion; verify absence using a fresh complete inventory.
Do not use issue status changes, cancellation or milestone detachment as substitutes for deletion.

Resolve the project before writing a project-scoped document. Prefer an explicit project target;
otherwise infer only from an unambiguous issue, milestone, or project argument. Stop on ambiguity.

For every durable artifact mutation:

1. Draft the exact content and obtain the active command contract's approval.
2. Create or update only the intended artifact; do not create empty placeholders.
3. Read back the artifact by returned ID or link.
4. Return its title, status, and Linear link.

If the connector cannot create or update Documents, report the capability gap and return the draft.
Do not claim persistence or silently fall back to a comment or project-description mutation. When
no reusable learning exists, record that in the retrospective or status update instead of creating
an empty Learning Entry.
