# Project Orchestration Receipt — {{PROJECT}}

Persist one active project-scoped Linear Document per project revision. Update the same document in
place, read it back, and validate it with `project-loop-receipt-check` and
`project-loop-transition`.

- **Receipt / state**: `{{receipt_id}}` / `{{state}}`
- **Project / revision**: `{{project_id}}` / `{{project_revision}}`
- **Project orchestrator**: `{{project_orchestrator_id}}`
- **Trace source / dependency graph hashes**: `{{source_hash}}` / `{{dependency_graph_hash}}`
- **Current / next event**: `{{current_event}}` / `{{next_event}}`
- **Milestone orchestrators**: `{{milestone bindings and states}}`
- **Human verification policies**: `{{one effective value, source, project revision, override revision, and hash per milestone}}`
- **Task loops**: `{{task, milestone, plan, executor, verifier, state, attempt}}`
- **Approval**: `{{status, preview hash, approved hash}}`
- **Budget**: `{{role invocations and injected input tokens}}`
- **Created / updated / state timestamps**: `{{RFC3339 timestamps}}`
- **Failure**: `{{evidence or none}}`

Do not place raw role transcripts, full task histories, or raw verification logs in this receipt.
For a transition, bind the completed event, re-read and supply the current project, source,
dependency-graph, milestone, and task bindings, then supply the next durable bindings, role-state
arrays, human-verification policy bindings, and monotonic budget. Never rebind an existing logical
role ID. Policy drift invalidates the event and requires recomputation.
