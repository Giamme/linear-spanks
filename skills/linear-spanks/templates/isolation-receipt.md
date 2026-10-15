# Isolated Worktree Receipt

Persist this as one durable issue comment. Update the same receipt in place and validate every
revision with `isolation-receipt-check` and `isolation-transition`.

- **Receipt / run**: `{{receipt_id}}` / `{{run_id}}`
- **State**: `{{prepared | executing | verified-pending-integration | integrating | integrated | failed}}`
- **Command / issue / plan revision**: `{{command}}` / `{{issue_id}}` / `{{plan_revision}}`
- **Source hash**: `{{sha256 digest}}`
- **Parent branch / baseline**: `{{branch}}` / `{{commit}}`
- **Repository / worktree root / worktree**: `{{absolute paths}}`
- **Child branch / commit**: `{{linear-spanks/run-...}}` / `{{commit or pending}}`
- **Verification**: `{{status, exact commands, completed_at}}`
- **Integration preview / approval**: `{{hashes and bound parent HEAD}}`
- **Integrated HEAD**: `{{commit or pending}}`
- **Completion read-back**: `{{receipt, issue Done, newly unblocked relations}}`
- **Cleanup**: `{{pending | removed | retained}}`
- **Failure**: `{{code, message, timestamp, or none}}`
- **Created / updated / state timestamps**: `{{RFC3339 timestamps}}`
