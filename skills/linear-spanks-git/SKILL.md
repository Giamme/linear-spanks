---
name: linear-spanks-git
description: Use when running linear-spanks milestones or tasks in a project where git branching, commits, and merge behavior needs a repeatable, agreed strategy
---

# Linear Spanks Git

Extension to **linear-spanks** that standardizes git operations across the milestone pipeline. Load this skill alongside `linear-spanks` whenever the project does not yet have a recorded git strategy.

## When to Use

- Starting `milestone run --mode step` or `task run` and no `.linear-spanks-git.yml` exists in the project root.
- The user asks anything like "how should we handle branches?" or "commit after each task".
- You notice inconsistent git behavior across tasks or milestones.

## Git Strategies

Present these four options to the user. Record the chosen strategy in `.linear-spanks-git.yml` at the project root.

| Strategy | Branching | Commits | Milestone boundary |
|---|---|---|---|
| `branch-per-milestone` | Create `milestone/<milestone-short-id>` at first `task next`. Stay on it for all milestone tasks. | Commit after each verified task. | Merge branch at `milestone wrap`; ask before merging. |
| `branch-per-task` | Create `task/<issue-short-id>` for each task. | Commit and merge/PR after each verified task. | Ask whether to delete task branches at `milestone wrap`. |
| `commit-per-task` | Stay on base branch. | Commit after each verified task. | Ask whether to create a release/hotfix branch at `milestone wrap`. |
| `manual` | Ask before every branch. | Ask before every commit. | No automatic operations. |

## Storage

```yaml
# .linear-spanks-git.yml
strategy: branch-per-milestone
base-branch: main
parallel-worktree-root: ../.linear-spanks-worktrees
```

Only `strategy` is required. `base-branch` defaults to `main`. Parallel or flagged isolated
execution also requires an explicit `parallel-worktree-root`; resolve it to an absolute safe path
outside the repository tree, record that path in every receipt, and reject cleanup targets outside
it.

## Integration Points

- **Before `milestone run --mode step` / `task run`**: If `.linear-spanks-git.yml` is missing, stop and ask the user to pick one of the four strategies. Create the file only after explicit approval.
- **`task next` / `task run` start**: Apply the strategy (create/check out the right branch). Never silently create branches.
- **`task verify` success**: Commit using a conventional message that includes the Linear issue ID (e.g., `feat(ENG-23): update user profile`) so Linear's GitHub/GitLab integrations can auto-link the commit. For `manual`, ask first.
- **`milestone wrap`**: Apply the milestone-boundary action from the table above. If the strategy requires a merge/PR, push the branch to the remote before opening the PR.

## Parallel Wave Overlay

`wave implement` always overlays the recorded strategy with isolated task branches and worktrees;
it never reuses the active checkout for a task. The clean currently checked-out branch and HEAD are
the wave parent and immutable baseline. Create every child from that exact baseline using
`linear-spanks/wave-<wave-id>/<issue-id>` and one clean worktree per task. The coordinator records
branch, worktree, baseline, claim, commit, and verification state in the durable wave receipt.

Executors may commit only on their assigned child branch. They may not merge, advance the parent,
or mark a Linear issue Done. `wave reconcile` owns integration after one exact preview approval:
use a temporary integration worktree, merge each verified child with `--no-ff` in deterministic
order, verify each candidate, then run combined verification before advancing the parent. Continue
past independent conflicts while retaining failed branches and worktrees.

After a merged receipt is persisted and read back, remove successful clean task worktrees. Preserve
child branches by default. Delete merged branches only when `--delete-merged-branches` was approved
and ancestry is verified. This overlay applies to every recorded strategy, including `manual`;
manual retains its explicit gates for operations outside the approved wave contract.

## Optional Single-Task Isolation Overlay

`task run` and `task next` accept `--isolated-worktree`. `milestone run --mode step` accepts it only
after resolving `start-implementation`; reject the flag before any other stage mutation.
`milestone run --mode loop --isolated-worktree` and `wave implement --isolated-worktree` are
idempotent assertions because those task executions are always isolated. No other command may
accept the flag.

For one isolated task, bind the clean attached current branch and exact HEAD in a durable issue
comment receipt, create `linear-spanks/run-<run-id>/<issue-id>` and a new worktree below the
configured root, then let the executor edit, verify, and commit only there. The overlay supersedes
the recorded strategy for that invocation, including `manual`, but always requires a separate
exact integration preview and approval.

Integrate with `--no-ff` in a temporary worktree, rerun required verification, and fast-forward the
still-clean parent only on success. Parent advancement invalidates approval and requires a fresh
preview; conflict, plan/source drift, or failed verification preserves the child branch/worktree
and leaves Linear In Progress. Mark Done only after the integrated receipt and completion read-back.
Remove the successful worktree after that receipt is durable. Preserve the child branch and never
push, open a PR, or delete it automatically.

## Project Orchestration Overlay

`project run` requires the same explicit `parallel-worktree-root` and isolated integration
authority. Each milestone orchestrator dispatches a fixed reviewed frontier into one child branch
and clean worktree per task; task executors commit only there, and task verifiers never edit tracked
source. The default project-wide concurrency is two and the hard maximum is eight.

The milestone orchestrator owns the exact integration preview and the existing temporary-worktree
verification sequence. The project orchestrator has no repository access and resolves only
project/milestone coordination. Every failed execution, verification, merge, or post-merge check
preserves the parent and keeps Linear from Done. Successful cleanup happens only after durable
integration and completion receipts; child branches remain local unless the user separately asks
to push or integrate them.

## Milestone Orchestration Overlay

`milestone run --mode loop` uses the same explicit `parallel-worktree-root`, fixed reviewed frontier,
child branch/worktree isolation, exact integration preview, temporary-worktree verification, and
durable completion sequence as `project run`. Its milestone orchestrator owns integration; task
executors and verifiers never advance the parent or mark Linear Done. It must first confirm no
active project orchestration receipt owns the project, and it stops for cross-milestone conflicts.

## Approval Gates

Ask before:
- Creating `.linear-spanks-git.yml` for the first time.
- Merging a milestone or task branch.
- Deleting branches.
- Any git operation under the `manual` strategy.

Routine commits after verified tasks do not need a separate gate once the strategy is recorded.

## Common Mistakes

- Treating a vague "continue" or "go ahead" as approval for a specific branch/merge question. If the user did not answer the question, repeat the options and wait.
- Creating `.linear-spanks-git.yml` without explicit user approval. Always confirm the chosen strategy before writing the file.
- Inventing a default strategy when the user says "just pick one". Present all four options; the user must choose.

## Red Flags

- Silently picking a git strategy because the user wants to "just start coding".
- Creating a branch that does not match the recorded strategy.
- Mixing strategies within one milestone.
- Committing before verification evidence is collected.
- Forgetting to record the strategy in `.linear-spanks-git.yml`.
