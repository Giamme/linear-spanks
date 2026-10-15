<!-- linear-spanks:completion-handoff -->
# Completion Handoff — {{ISSUE}} / Attempt {{ATTEMPT}}

- **Task loop / executor**: `{{task_loop_id}}` / `{{executor_id}}`
- **Attempt / candidate commit**: `{{attempt_id}}` / `{{commit}}`

## What changed
{{Concise summary of the change.}}

## Files/modules touched
- {{file or module}}
- {{file or module}}

## Decisions
- {{decision made during implementation}}

## Orchestration Receipt
- **Harness**: {{actual harness}}
- **Worker role**: {{planner | executor | reviewer}}
- **Requested / effective assurance**: `{{fast | balanced | strict}}` / `{{fast | balanced | strict}}`
- **Assurance escalation reason**: {{none or deterministic escalation reasons}}
- **Requested strength**: `{{low | medium | high}}`
- **Configured model when observable**: {{model identifier or not observable}}
- **Tier enforcement**: {{enforced | advisory — inherited-model | advisory — profile-only}}
- **Plan / source revision**: {{plan revision}} / {{source revision}}
- **Review result**: {{not required/self-verified | passed | blocking findings}}
- **Planner / reviewer runs**: {{count}} / {{count}}
- **Delegated roles**: {{roles or none}}
- **Linear reads / writes / read-backs**: {{count}} / {{count}} / {{count}}
- **Context bytes**: {{measured total}}
- **Preflight reused**: {{true | false}}

## Verification evidence
{{Test output, links, or observed behavior.}}

## Known limits
- {{limitation or follow-up required}}

## Follow-ups
- {{issue or task}}

## Newly unblocked issues
- {{issue that is now unblocked}}

## Measured context binding

- Packet hash / serialized bytes / estimated tokens: `<measured complete body>`
- Native token telemetry: `<actual or unavailable; never relabel the estimate>`
- Context policy revisions/hash and runtime-capacity evidence: `<current bindings>`
- Active snapshot and subsequent delta references: `<bounded scope view>`

Compile full instructions, selected skill contents, plan and evidence into the packet and validate
it immediately before dispatch. A policy/model/harness change requires recompilation.

Record execution path and policy hash, material/evidence bindings, reused observations, and the
actual full/targeted review and check counts. Carry the schema 2 workflow hash into task handoffs.
A low-risk task includes its final self-verification; do not schedule another reviewer for it.
