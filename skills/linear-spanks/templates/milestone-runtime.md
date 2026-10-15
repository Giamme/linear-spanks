# Linear Spanks Milestone Runtime — {{milestone_id}}

Keep exactly one revisioned projection for the milestone. Prefer a Linear Document and fall back
to one managed comment only when Documents are unavailable. Live issues and immutable receipts
remain authoritative.

<!-- linear-spanks:milestone-runtime -->

- **Runtime / revision**: `{{runtime_id}}` / `{{revision}}`
- **Project / milestone**: `{{project_id}}` / `{{milestone_id}}`
- **Storage source**: `{{document | managed-comment}}`
- **Guarded policy binding**: {{bound hashes, expiry fields, and approval status}}
- **Active wave**: {{selected tasks, graph hash, and receipt}}
- **Plan validity**: {{valid, safe-refresh, and material counts with task IDs}}
- **Incremental review coverage**: {{changed, adjacent, unchanged counts and hashes}}
- **Human repair**: {{session batch, owner or repair task, machine reverification, fresh checklist}}
- **Last event / event count**: `{{event}}` / `{{count}}`
- **Updated**: `{{RFC3339 timestamp}}`
- **Projection hash**: `{{sha256 of every field above except this hash}}`

The milestone description contains only a revisioned reference marker. Promote a matching fallback
comment when Documents become available. Stop with `MILESTONE_RUNTIME_STATE_CONFLICT` for duplicate,
malformed, or conflicting artifacts.
