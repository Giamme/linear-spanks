# Verification Ledger — {{ISSUE}}

This is the bounded durable memory for one logical task verifier. Validate every revision with
`verification-ledger-check`. A refreshed verifier session keeps the same `verifier_id` and ledger.

- **Ledger / verifier**: `{{ledger_id}}` / `{{verifier_id}}`
- **Project / milestone / plan / source revisions**: `{{revisions}}`
- **Candidate commit**: `{{commit}}`
- **Reviewed attempts**: `{{attempt IDs, indexes, commits, results, timestamps}}`
- **Live session**: `{{session ID or unavailable, state, measured context tokens}}`

## Acceptance Criteria

| Criterion | State | Evidence | Last checked commit |
|---|---|---|---|
| {{criterion}} | `{{unverified | passing | failing | regressed}}` | {{evidence}} | `{{commit or none}}` |

## Findings

| Finding | State | Summary | Introduced | Resolved | Evidence |
|---|---|---|---|---|---|
| {{finding ID}} | `{{open | resolved | regressed}}` | {{summary}} | `{{commit}}` | `{{commit or none}}` | {{evidence}} |

## Verification Runs

| Command | Result | Short summary | Artifact | Commit |
|---|---|---|---|---|
| `{{command}}` | `{{passed | failed}}` | {{at most 2,000 characters}} | {{link or none}} | `{{commit}}` |

## Baseline Failures and Exclusions

- **Baseline failures**: {{bounded list}}
- **Exclusions**: {{bounded list with rationale}}

## Next Checks

- {{check required on the next verifier invocation}}

- **Required verification current**: `{{true | false}}`
- **Final result**: `{{pending | passed | failed}}`
- **Updated**: `{{RFC3339 timestamp}}`
- **Raw executor transcript included**: `false`
