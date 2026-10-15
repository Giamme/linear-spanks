# Task Commands

## Design and scope

- `task design`: for a small standalone outcome. Gather missing intent, scope, acceptance criteria,
  dependencies, and verification; render `task-spec.md`; gate before issue creation.
- `task create-bug`: capture reproduction, expected/actual behavior, impact, environment,
  acceptance criteria, and investigation hints using `bug-task-spec.md`.
- `task scope`: report whether the issue is appropriately sized.
- `task decompose`: recommend split versus promotion and draft the relevant proposal without
  mutation.
- `task split`: after approval, create smaller issues, formalize dependencies, and decide the
  original issue's disposition.
- `task promote`: after approval, create a milestone with independent tasks and decide the
  original issue's disposition.

## Human draft intake

- `task refine`: require `Human draft`, preserve the human-authored source and revision, resolve
  ambiguity, show the exact stable task contract, then after approval update the description and
  move to `Unplanned`. Do not plan, attach to a milestone, or create tasks in the same command.
- `task plan`: require `Unplanned`, use its declared fast repository scan and the assurance
  decision's coordinator/high planner, create and read back one authoritative plan, then
  move to `Backlog`. Do not implement.
- `task organize`: compare refined tasks with existing milestone contracts before proposing a
  new milestone. Start read-only and apply only separately approved attachments, milestone
  creation, or complementary tasks. Complementary tasks start in `Unplanned`.

Read `issue-intake.md` for exact status, fit, approval, and read-back rules.

## `task run`

Add `--isolated-worktree` to use the single-task flow in `parallel-execution.md`. Without the flag,
the recorded Git strategy remains authoritative. With it, compile isolation into the envelope,
brief, and runtime card; run `isolation preflight`; resume any one matching active receipt;
and keep the task In Progress until parent integration and completion read-back are durable.

1. Resolve the strict project target. Build the bounded task context packet from the full target
   issue, compact milestone contract, compact blocker statuses, authoritative current plan, and
   only siblings or learning entries selected by `context-management.md`.
2. Stop if the issue is `Human draft` or `Unplanned`, any hard blocker is not Done, or scope is
   unclear. Refine or plan the task before implementation.
3. Compile the compact runtime card and run `runtime task-next` with current task evidence. Select
   skills by role and phase; reuse bound observations. When no current plan exists, let the
   coordinator persist the compact low-risk plan or the required high-planner output.
4. Claim the issue when claim mode is configured, re-read the assignee, and back off on collision.
5. Validate the state transition and apply the configured git strategy.
6. Move In Progress, build the minimal worker handoff, and delegate exactly one task to the
   plan-selected executor tier. The coordinator retains Linear writes and lifecycle ownership.
7. On material scope, interface, dependency, acceptance, policy, or consumed-evidence drift, stop
   on `REPLAN_REQUIRED`; a repository revision change alone is trace-only. Never let the executor
   improvise or downgrade the tier. Refresh safe execution evidence inside the current run;
   preserve the material plan revision and recompile after durable read-back.
8. Verify with fresh evidence inside `task run`. Run the risk-based independent reviewer when
   required by the decision. Do not nest `task verify`; that command is explicit recovery or an
   independent verification request.
   On failure, keep In Progress and record the failure.
9. For isolated execution, gate the exact integration preview, integrate and verify in a temporary
   worktree, fast-forward the unchanged parent, and persist the integrated receipt before cleanup.
   Preserve failed worktrees and the merged child branch.
10. Add a completion handoff including the actual routing receipt, mark Done, read back the issue,
   then read `relations.blocks` for newly unblocked work.

Balanced/fast perform one pre-write revision refresh and one final durable read. Use
`runtime readback-plan` for every mutation, not only bulk ones: it returns the read mode and the
`readback_fields` projection, reconciles bulk phases once, and targets recovery reads only at
failed, missing, or stale results. Strict preserves per-write refresh and read-back.

## Task pairs inside `project run`

`project run` binds a logical executor and verifier identity per task. The IDs survive retries and
session refreshes. Every task executes in an isolated worktree using the same `runtime task-next`
policy as standalone execution. Low-risk work self-verifies; required independent review uses the
resolved strength. Four automatic executions remain an upper bound, not mandatory review rounds.

Workers return marked completion and verification outputs; the coordinator owns Linear persistence.
New handoffs and attempts use schema 2 policy/progress bindings. Suggestions do not enter repair
queues. Repair blocking findings within the current plan and check affected areas. Diagnose repeated
unchanged failures once; stop without new evidence or a changed approach. Preserve consumed attempts.
Stronger-model repair still requires explicit selection and approval.

`milestone run --mode loop` applies this same task-pair contract within one milestone. The pair IDs are
bound to its Milestone Orchestration Receipt; the high milestone orchestrator alone owns task status
changes and approved integration.

## Replanning and backfill

`task replan` appends `task replan.md`, preserves prior revisions as history, and records an
authoritative current-plan revision or pointer. Active task runs read only that revision. If outputs
or downstream expectations change, mark milestone review findings stale. Material replanning uses a fresh assessment and recomputes the executor tier and reviewer
requirement. Routine evidence refresh and optional polish do not enter this command.

`task backfill` runs only when explicitly requested. Label reconstructed facts and their
confidence using `reconstructed-completion.md`; never present inference as original evidence.
