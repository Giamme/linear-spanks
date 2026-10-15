# Changelog

## 1.0 — 2026-10-15

The first public release, with runtime v2 below.

### 2026-10-15

- Install as a plugin in Claude Code, Codex or Copilot CLI, or with `npx skills` in most other
  agents. The plugin ships the three core skills; the 27 execution and technology skills moved to
  `skills/extras/`, where Linear Spanks still reads them, so they no longer load as skills of their
  own unless you install them.
- `scripts/install-skills` finds skills in `skills/` and `skills/extras/`. Links into the old
  `skills/exec-*` and `skills/tech-*` folders are replaced on the next install or update.
- The CLI and the installer stop with a clear message on Python older than 3.11.
- Document the Linear MCP connector as a requirement, and what the runtime, installers and
  extensions run, download and write.
- MIT license file.

### 2026-09-08

- Dispatch core policy as a bounded `core_policy` contract slice on every command, so the approval
  and mutation protocol, recovery table, and postcondition definitions reach the agent instead of
  living in a reference no command loaded.
- Compile `model-routing`, `task-workflow`, and `workflow-state` references for the commands that
  govern, plus the learning-entry, learning-index, and milestone-runtime templates.
- Reject an unreachable reference or template from `docs check` with `UNREACHABLE_REFERENCE`.
- Require `references/ripwire.md` only for commands that resolve a repository, and split
  staged-scan guidance out of `codebase-analysis.md` into `repository-scan.md`.
- Raise the project, milestone, task, and lifecycle context ceilings to fit the dispatched policy
  with evidence headroom.
- Add `context detect-evidence` to derive skill-selection technologies and evidence from a
  repository inventory with per-tag provenance; task-scoped tags remain caller-supplied.
- Lock the v2 public command surface with a 59-command reference snapshot; the existing contract
  assertions run through the frozen v1 grammar and never covered it.

### 2026-09-07

- Automatically use a short path for low-risk tasks across task, milestone, and project execution.
- Preserve material plans through guarded evidence refreshes; review affected changes after repairs.
- Separate blocking defects from optional suggestions and diagnose stalled repairs without automatic replanning.
- Bind current execution policies and progress to schema 2 attempts/handoffs; retain legacy readers.
- Add workflow dispatch/recovery replays alongside context benchmarks.

## Runtime v2 — 2026-08-03

Breaking release: Python 3.11+ typed package, immutable versioned contract set, namespaced
JSON-first CLI, stable exit codes, explicit artifact codecs with authorized lazy migration, and
stdlib transactional installers. Runtime dependencies remain empty.

Flat v1 workflow commands are rejected with `LEGACY_COMMAND_REMOVED`; they are not aliases. This
includes `run-milestone --autopilot`, whose replacement is `milestone run --mode loop`. On the
namespaced command, `milestone run ... --autopilot` is rejected with `LEGACY_OPTION_REMOVED`; use
`--mode loop` instead.

| Removed v1 command | v2 replacement |
|---|---|
| `analyze-codebase` | `codebase analyze` |
| `apply-learnings` | `learning apply` |
| `archive-milestone` | `milestone archive` |
| `audit-project` | `project audit` |
| `backfill-completion` | `task backfill` |
| `checkpoint-project` | `project checkpoint` |
| `clarify-milestone` | `milestone clarify` |
| `confirm-milestone` | `verification confirm` |
| `create-bug-task` | `task create-bug` |
| `create-project` | `project create` |
| `create-tasks` | `milestone create-tasks` |
| `decompose-task` | `task decompose` |
| `design-milestone` | `milestone design` |
| `design-task` | `task design` |
| `diff-milestone` | `milestone diff` |
| `fail-milestone-verification` | `verification fail` |
| `fix-review` | `milestone fix-review` |
| `handoff-milestone` | `milestone handoff` |
| `implement-next` | `task next` |
| `implement-wave` | `wave implement` |
| `import-codebase` | `codebase import` |
| `normalize-project` | `project normalize` |
| `onboard-milestone` | `milestone onboard` |
| `onboard-project` | `project onboard` |
| `onboard-task` | `task onboard` |
| `organize-learnings` | `learning organize` |
| `organize-unplanned` | `task organize` |
| `pause-milestone` | `milestone pause` |
| `plan-task` | `task plan` |
| `plan-tasks` | `milestone plan` |
| `promote-task` | `task promote` |
| `reconcile-wave` | `wave reconcile` |
| `refine-task` | `task refine` |
| `replan-task` | `task replan` |
| `report-milestone-findings` | `milestone report-findings` |
| `resume-milestone` | `milestone resume` |
| `review-learnings` | `learning review` |
| `review-milestone` | `milestone review` |
| `review-project` | `project review` |
| `review-task-scope` | `task scope` |
| `rollover-project` | `project rollover` |
| `run-milestone` | `milestone run --mode step` |
| `run-milestone-loop` | `milestone run --mode loop` |
| `run-project` | `project run` |
| `run-task` | `task run` |
| `set-human-verification-policy` | `verification policy-set` |
| `split-task` | `task split` |
| `status-human-verification` | `verification status` |
| `status-milestone` | `milestone status` |
| `sync-milestone` | `milestone sync` |
| `trace-blockers` | `milestone blockers` |
| `update-project` | `project update` |
| `verify-milestone` | `milestone verify` |
| `verify-task` | `task verify` |
| `wrap-milestone` | `milestone wrap` |

Persisted v1 artifacts remain readable and convert only as part of a previewed,
already-authorized write. See the [migration guide](docs/guides/v1-to-v2.md).

## Context reliability

- Preserve actionable overflow, drift, approval and capability errors; measure complete serialized
  packets and verifier ledgers rather than trusting declared token counts.
- Add inherited, persistent context token policies, explicit raise/reset commands, input-capacity
  checks, policy-bound compilation and read-only context/runtime inspection.
- Add approved project/milestone/task snapshots, paginated manifests, evidenced deltas and resumable
  receipt-backed document write plans. Verification comments link to current evidence documents.
- Add progress-aware repairs, bound analysis reuse, executable skill metadata and session loading,
  compressor capability selection, and a 100-cycle context regression benchmark.
