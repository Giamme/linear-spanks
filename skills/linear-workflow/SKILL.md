---
name: linear-workflow
description: Use when working with Linear issues, milestones, dependencies, statuses, comments, or project roadmap context
---

# Linear Workflow

Linear is durable coordination memory for agents and humans. Keep descriptions stable, keep one
authoritative current plan, and persist compact completion evidence. The active command's project
scope, approval, context budget, and session boundary remain authoritative.

## Load only the required operation rules

- Read `references/connector-contract.md` before any Linear connector call.
- Read `references/task-lifecycle.md` only for issue, dependency, claim, milestone, status, or task
  execution operations.
- Read `references/document-persistence.md` only when reading or writing Linear Documents,
  retrospectives, learning indexes, or learning entries.

## Invariants

- Resolve the project before milestones, issues, or documents; stop on ambiguity.
- Use compact projected reads first. Expand full text only when it can affect the command result.
- Read all blocker states, but expand only unfinished or contract-relevant blockers within the
  active depth and node limits.
- Never mutate during a read-only request. For writes, re-read, apply only intended fields, and
  read back before reporting success.
- Preserve human-authored issue intent and enforce `Human draft -> Unplanned -> Backlog`; never
  skip refinement or planning readiness gates.
- Keep volatile plans and completion receipts out of stable issue descriptions.
- Do not infer completion, persistence, dependency, or milestone membership from titles or prior
  conversation state.
