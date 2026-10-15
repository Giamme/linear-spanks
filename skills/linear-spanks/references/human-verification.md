# Final Human Verification

Final human verification is opt-in. Resolve the effective value in this exact order:
milestone override, project default, then the disabled system default. Missing project policy is
not an error for reads or milestone execution; it means disabled.

## Persistence

The project default is the singleton project-scoped Linear Document titled
`Linear Spanks Human Verification Policy`. Its managed marker binds the project ID, default,
positive revision, canonical hash, actor, and RFC 3339 timestamp. Resolve the project first, find
all exact-title matches, and stop on collisions or malformed content. Project-wide mutation
requires Document create/update capability; otherwise return
`HUMAN_VERIFICATION_POLICY_UNAVAILABLE`. Never fall back to a project description or comment.

Store a milestone override in its description as exactly one
`linear-spanks:human-verification-override` marker. `inherit` removes its precedence while
preserving the revisioned marker. Re-read and hash-check both sources before every decision.

## Previewed policy changes

`verification policy-set` is idempotent and always preview-gated. A project preview lists
every non-terminal active milestone exactly once, including its prior and resulting effective
value, gate create/reactivate/cancel action, checklist supersede/bypass action, and every active
project or milestone orchestration receipt to reconcile. A milestone preview covers exactly that
milestone. The approved hash must equal the freshly recomputed preview hash.

Enabling creates or reactivates one managed gate immediately. A milestone already at
`milestone-verified` must rerun `milestone verify`; do not reuse old machine evidence. Disabling
cancels rather than deletes the gate. If a current checklist is pending, disabling also requires a
non-empty reason, an immutable `bypassed` reply on that checklist, gate cancellation read-back,
and receipt reconciliation. A bypass is not human confirmation. Wrapped and archived milestones
are omitted and unchanged.

## Gate and checklist lifecycle

The one managed issue is titled `Human verification gate — <milestone>` and contains exactly one
`linear-spanks:human-verification-gate` marker. Filter this marker before planning, dependency
graphs, waves, task selection, execution, and regular task totals. Never infer a gate from its
title. Disabled gates are Canceled, not deleted, so the issue and checklist history remain.

For enabled policy, `milestone verify` moves the gate to In Progress, appends a new checklist
bound to the machine-verification revision and current effective-policy hash, and stops at
`milestone-verified` with `await-human-verification`. Older pending checklists become
`superseded`. `verification confirm` requires explicit confirmation of the current pending checklist,
writes an immutable confirmed reply, marks the gate Done, reads the gate and native Linear
milestone completion back, advances to `human-verified`, and returns `milestone wrap`.

`verification fail --reason` previews one repair issue marked
`linear-spanks:human-verification-repair`, creates it in `Unplanned`, records the failed outcome
beneath the current checklist, keeps the gate open, and returns the milestone to `implementing`.
The same failure revision is idempotent and cannot create a second repair task. Machine
verification must run again after repair.

## Wrap and orchestration

Disabled milestones preserve the legacy `milestone-verified -> wrapped` path. Enabled milestones
may wrap only from `human-verified` with a Done gate and confirmed current checklist.

Project and milestone orchestration receipts bind the effective value, source, project-policy
revision, milestone-override revision, and policy hash. Drift returns
`HUMAN_VERIFICATION_POLICY_DRIFT` and recomputes the next event. An enabled pending checklist
selects `await-human-verification`; automated loops must not wrap that milestone or dispatch
downstream milestone work. An approved disable/bypass removes the stop only after gate and receipt
read-backs reconcile.
