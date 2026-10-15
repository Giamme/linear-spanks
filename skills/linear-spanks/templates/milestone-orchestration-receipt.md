# Milestone Orchestration Receipt — {{MILESTONE}}

Persist this immutable single-event receipt, read it back, and validate it with
`milestone-loop-receipt-check` and `milestone-loop-transition`. Project current coordination state
into the singleton `Linear Spanks Milestone Runtime — {{milestone_id}}` artifact; do not use the
receipt as a second mutable runtime document.

<!-- linear-spanks:milestone-orchestration-receipt -->

- **Receipt / state**: `{{receipt_id}}` / `{{state}}`
- **Project / milestone revisions**: `{{project_id}}` / `{{project_revision}}` / `{{milestone_id}}` / `{{milestone_revision}}`
- **Milestone orchestrator**: `{{milestone_orchestrator_id}}`
- **Trace source / dependency graph hashes**: `{{source_hash}}` / `{{dependency_graph_hash}}`
- **Human verification policy**: `{{effective value, source, project revision, override revision, and hash}}`
- **Current / next event**: `{{current_event}}` / `{{next_event}}`
- **Task loops**: `{{task, plan, executor, verifier, state, attempt}}`
- **Approval**: `{{status, preview hash, approved hash}}`
- **Budget**: `{{role invocations and injected input tokens}}`
- **Created / updated / state timestamps**: `{{RFC3339 timestamps}}`
- **Failure**: `{{evidence or none}}`
- **Runtime projection revision**: `{{runtime revision and projection hash}}`

Do not include raw role transcripts, full task histories, or raw verification logs. Before each
transition, re-read the bound project, milestone, source, graph, task plans, review coverage,
runtime projection, and effective human verification policy. Never rebind the milestone
orchestrator or an existing executor/verifier pair. Policy drift requires recomputing the next
event. A supervisor invocation starts each next event in a fresh bounded session and reads back
both the receipt and runtime projection before continuing.
