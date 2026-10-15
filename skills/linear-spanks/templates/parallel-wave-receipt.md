# Parallel Wave Receipt — {{wave_id}}

- **Milestone**: {{milestone_id}}
- **State**: {{prepared | executing | awaiting-reconciliation | reconciling | partially-integrated | integrated | failed}}
- **Graph hash**: {{sha256}}
- **Source hash**: {{sha256}}
- **Parent branch**: {{branch}}
- **Baseline HEAD**: {{commit}}
- **Worktree root**: {{safe absolute sibling-directory root}}
- **Parallelism**: requested {{n}}, effective {{n}}
- **Created / updated**: {{RFC 3339 timestamps}}

## Tasks

| Issue | Plan revision | Child branch | Worktree | Claim | Execution | Commit | Verification | Integration |
|---|---:|---|---|---|---|---|---|---|
| {{ID}} | {{n}} | {{branch}} | {{path}} | {{status}} | {{status}} | {{sha or null}} | {{status}} | {{status}} |

## Reconciliation preview

{{Exact ordered children, current parent HEAD, proposed merge commits, verification, cleanup, and branch deletion policy.}}

## Durable marker

{{Validate the compact JSON payload with `wave-receipt-check` before persistence and resume.}}
