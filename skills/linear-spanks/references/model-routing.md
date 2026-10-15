# Model-Aware Orchestration and Assurance

The compiled runtime card and composite `orchestration-decision` are authoritative for optimized
task commands. Logical strengths and assurance profiles are portable policy labels, not vendor
model names. Full envelopes and the separate tier, context, and routing checks remain diagnostics.

## Assurance resolution

`balanced` is the default:

- `fast`: deterministic low-risk work only. The coordinator prepares the plan and the executor
  self-verifies; no independent reviewer runs.
- `balanced`: the coordinator records a compact plan for low-risk work; no separate planner or
  reviewer runs. A high planner handles medium, high, or uncertain work. Review remains risk-based.
- `strict`: high planning and independent high review, exact full packets, and per-write refresh/read-back.

Fast first escalates to balanced when ineligible. Uncertainty, security/auth risk, migration,
public compatibility, concurrency/distributed state, cross-repository coordination, broad
refactors, unclear failures, or detected drift resolve to strict. Assurance never removes project
scoping, approval, blocker readiness, idempotency, repository exclusions, drift rejection, fresh
verification, or final durable read-back.

## Coordinator boundary

The coordinator retains project resolution, approvals, all Linear reads and writes, git-strategy
enforcement, lifecycle transitions, durable plan persistence, and final read-back. Delegated
workers never mutate Linear. Preserve the command's approval, context, postcondition, and
`single-task` boundary even when the harness supports native subagents.

`project run` adds scoped coordinators without weakening this boundary. The high project
orchestrator owns project state but has no repository access. Each high milestone orchestrator owns
one milestone, bounded source reads for planning, task dispatch, and validated integration, but may
not edit tracked source. Executors and verifiers can append only their contract-defined issue
comments; the milestone orchestrator owns status and integration writes.

## Planner

Use the assurance decision's coordinator or high planner. Delegated planners run
read-only and return only the structured plan packet; the coordinator persists that packet after
the existing gate and read-back. Within the
planner budget from the orchestration envelope, inspect:

1. target modules
2. relevant call sites and affected interfaces
3. nearby tests
4. manifests and toolchain versions
5. relevant blocker outputs
6. the authoritative current plan revision

Validate the separate planning budget with:

```bash
python3 scripts/linear_spanks_cli.py context check task run --scope planner \
  --estimated-tokens 8000 --metric max_repository_files=16
```

Return `CONTEXT_OVERFLOW` when required evidence cannot fit. Do not silently omit it. A replan is
a fresh planner run against the latest source revision and must recompute the tier.

Balanced `milestone plan` groups up to four dependency-adjacent tasks per planner run while preserving
one plan packet, tier, plan revision, and acceptance mapping per task. Strict uses one high planner
run per task.

## Tier assessment

The pre-planner risk screen supplies every boolean in the assessment schema. Ordinary task work
passes it to the composite decision; use `tier-recommend` only for diagnostics:

```bash
python3 scripts/linear_spanks_cli.py routing recommend assessment.json
```

- `low`: localized established pattern, no active complexity dimension, and a deterministic
  focused verification path.
- `high`: any critical dimension or at least two medium dimensions.
- `medium`: everything between those boundaries.
- Uncertainty escalates one tier. An executor may request a stronger tier only through
  `REPLAN_REQUIRED`; it never downgrades the planner recommendation.

High tasks require an independent high reviewer. Medium tasks require an independent medium
reviewer when interface, migration, nondeterministic-debugging, or operational risk is active.
Low tasks self-verify.

Task, milestone, and project execution share `routing task-policy` and `runtime task-next`.
The assigned executor uses the validated plan tier. An independent verifier runs only when the
policy requires one; low-risk work self-verifies in the task execution invocation. Existing schema 1
attempts retain their legacy low-executor/high-verifier validation. Emit schema 2 attempts for new work.
Four executions remain the upper bound, not a prescribed sequence. Stronger repair still requires
explicit model selection and never resets consumed attempts.

See [task workflow](task-workflow.md) for policy bindings, safe refresh, and diagnosis handling.

## Worker handoff and drift

Send only the fields listed in `orchestration.worker_handoff.required_fields`: the current plan and
source revisions, stable task contract, relevant blocker outputs, selected skills, repository
evidence pointers, acceptance criteria, required verification, executor tier, and stop/replan
conditions. The executor implements exactly one task.

Any material scope, interface, dependency, acceptance, policy, or consumed-evidence drift returns
`REPLAN_REQUIRED`. A repository revision change alone is trace-only. The executor must not
improvise across a material boundary. The coordinator then runs `task replan`, persists the new
plan revision after its existing gates, and delegates again from a fresh handoff.

## Harness capability and fallback

Resolve the active route before delegation:

```bash
python3 scripts/linear_spanks_cli.py routing check \
  --harness codex --role executor --strength medium \
  --configured-model provider/model-id
```

Ordinary task work instead runs:

```bash
python3 scripts/linear_spanks_cli.py routing decide decision.json
```

Codex, Claude Code, OpenCode, and OpenClaude can enforce role-specific model configuration.
Antigravity delegates isolated subagents but their model is inherited; Kimi delegates through
`plan`, `coder`, and `explore` profiles without per-worker model pinning. For either fallback,
delegate where possible and record the requested tier as advisory, never as enforced.

Logical role identity is portable even when live session reuse is unavailable. The project receipt
binds orchestrator and task-pair IDs; each verifier invocation reconstructs continuity from the
validated verification ledger.

Configure native profiles separately from skill installation. Preview is the default; changes are
written only with `--apply`:

```bash
python3 scripts/configure_model_routing.py --client codex \
  --low-model provider/low-model \
  --medium-model provider/medium-model \
  --high-model provider/high-model
```

The helper does not hardcode provider models or credentials. It writes only marked profile files
or namespaced OpenClaude routing keys and preserves unrelated configuration.

## Completion receipt

Record the actual harness, worker role, configured model when observable, requested strength,
enforcement status, review result, requested/effective assurance and escalation reason,
planner/reviewer runs, delegated roles, Linear reads/writes/read-backs, context bytes, and preflight
reuse. Validate it with `runtime completion-receipt`. A verification failure leaves the task In
Progress and records evidence; it never advances the task to Done.
