<!-- linear-spanks:verification-result -->
# Verification Result — {{ISSUE}} / Attempt {{ATTEMPT}}

- **Task loop / verifier**: `{{task_loop_id}}` / `{{verifier_id}}`
- **Attempt / candidate commit**: `{{attempt_id}}` / `{{commit}}`
- **Project / milestone / plan / source revisions**: `{{revisions}}`
- **Result**: `{{passed | failed}}`
- **Verification ledger**: `{{ledger ID or durable link}}`

## Acceptance Results

| Criterion | Result | Evidence |
|---|---|---|
| {{criterion}} | `{{passing | failing | regressed}}` | {{evidence}} |

## Blocking Findings

- `{{finding ID}}`: {{evidenced defect, acceptance gap, or repository requirement violation}}
  Requirement: {{reference}}. Evidence: {{reference}}.

## Suggestions (non-blocking)

{{Optional polish only; no required repair or new review cycle.}}

## Commands and Evidence

- `{{command}}` — `{{passed | failed}}` — {{short diagnostic or artifact}}

## Executor Repair Handoff

{{Only open or regressed blocking findings, exact acceptance gaps, and required next checks. Do not copy the verifier conversation.}}

## Authoritative Verification Ledger

{{Link to the current snapshot and attempt delta documents. Preserve the original verification
ledger as historical evidence; never embed accumulated attempt history or raw transcripts.}}

## Current context changes

- Active snapshot: `<document reference and hash>`
- Attempt delta: `<direct document reference; changed acceptance/findings/checks only>`
- Policy revision/hash: `<effective inherited binding>`
- Failure fingerprint / acceptance-state hash: `<current values>`
- Next legal action: `<repair, prerequisite recovery, diagnosis, material replan, or approval>`

Preserve the legacy ledger as a source artifact; link to it instead of embedding its accumulated
attempt history in this comment. Success and resolution must cite the actual candidate evidence.

Emit schema 2 ledgers. Each finding includes classification (`blocking` or `suggestion`) and a
requirement reference for blockers (`null` for suggestions). Legacy unclassified findings remain
blocking until explicitly reviewed; never infer their resolution.

- Execution binding: `{{runtime task-next verification_binding after actual checks}}`

Store this as `execution_binding` in the schema 2 ledger. Never update the binding on old test
results to make them appear current; changed commands or toolchain evidence require verification.
