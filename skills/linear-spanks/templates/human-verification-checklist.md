# Final Human Verification

Milestone: {{Milestone name and Linear link}}
Gate issue: {{Managed gate issue link}}
Machine verification revision: {{Positive revision}}
Effective policy: `{{enabled}}` from `{{milestone-override | project-default}}`
Policy hash: `{{sha256 digest}}`

## Human checklist

- [ ] {{Concrete product behavior or outcome to inspect}}
- [ ] {{Concrete evidence or workflow to exercise}}
- [ ] {{Regression or downstream behavior to confirm}}

## Evidence

{{Links, screenshots, observations, or concise notes. Do not include secrets.}}

## Outcome

Status: `{{pending | confirmed | failed | bypassed | superseded}}`
Actor: `{{Human or approved bypass actor}}`
Reason: {{Required for failed or bypassed; otherwise omit}}

<!-- linear-spanks:human-verification-checklist {"actor":"{{actor}}","checklist_id":"{{stable id}}","checklist_revision":{{positive revision}},"effective_policy_hash":"{{sha256 digest}}","evidence":["{{evidence}}"],"gate_issue_id":"{{issue id}}","instructions":["{{instruction}}"],"machine_verification_revision":{{positive revision}},"milestone_id":"{{milestone id}}","project_id":"{{project id}}","schema_version":1,"status":"{{pending | confirmed | failed | bypassed | superseded}}","updated_at":"{{RFC 3339 timestamp}}"} -->
