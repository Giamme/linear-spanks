# Skill Composition

Select the smallest skill set that covers the task. Record selected skills and conflict decisions
in the Implementation Plan.

## Precedence

Apply guidance in this order, highest first:

1. System/developer constraints and the user's explicit request
2. Safety, approval, project-scoping, and verification invariants
3. Existing repository architecture, conventions, dependencies, and supported versions
4. Task-type execution skills such as debugging, refactoring, testing, or accessibility
5. Technology skills as conditional defaults

Lower-precedence guidance must not overwrite a higher-precedence decision. In particular, words
such as `always`, `never`, and `strictly` in a technology skill describe a default unless they
protect a genuine safety property. When a default conflicts with the repository, preserve the
repository pattern and document the reason.

## Activation

- Establish repository patterns before implementation; reuse bound observations for unchanged areas.
- Load architecture for new modules, boundaries, or structural decisions.
- Load debugging for observed failures; testing for code changes requiring coverage; security for
  auth, input, data access, or external APIs; accessibility and UI/UX for interfaces.
- Load only technology skills detected in the target repository or explicitly requested.
- Load verification before completion and code review for a final diff self-review.

Load skills by role and phase. Workers receive repository-pattern and task-specific guidance, plus
testing when code changes require it. Load code-review and verification guidance only for the
completion phase. Planners do not receive worker-only mutation guidance.

## Version and evidence checks

Before applying a technology default, identify the project's framework/runtime version and its
existing toolchain. Prefer official project configuration and local documentation over generic
memory. For material choices, record the detected evidence and any default that was intentionally
overridden.

## Executable selection

Derive the selection inputs before selecting. `context detect-evidence` takes a repository
inventory (`files`, optional declared `dependencies`) and returns `technologies`, the
repository-derivable `evidence` tags (`ui`, `coverage-required`), the paths that proved each tag
in `provenance`, and a `binding` hash. It performs no filesystem access and no network access;
the coordinator supplies the inventory, optionally from a Ripwire `map` query. Record the binding
alongside the other packet evidence.

The remaining catalog tags describe the task, not the repository, and are returned in
`task_supplied`: `observed-failure`, `refactoring`, `documentation`, `performance`,
`structural-change` and `security-sensitive`. Supply those from the task contract. An explicit
user or coordinator decision keeps the precedence above and overrides a detected default.

The versioned `skill-selection-catalog.json` records roles, phases, technologies, applicability
predicates (`requires` repository evidence tags), precedence, and canonical source hashes.
Run `context select-skills` with the catalog and observed role/phase/technologies/evidence.
Record reasons, source hashes and conflicts in the plan and measured packet. An equal-precedence
source conflict blocks dispatch; repository and explicit user decisions retain the precedence above.
The catalog's execution and technology skills ship in `skills/extras/` of the linear-spanks repository
and plugin, at `../extras/<name>/SKILL.md` from this skill's folder; an agent may also have them
installed as skills. Before `context select-skills`, drop catalog entries whose `SKILL.md` you can't
read, and note them in the plan.
Use `context load-skills` with a session ID and fully read selected source contents. Carry its
`loaded` map only within that session. It loads each selected source hash fully once; a new session
must load it again. Reuse analysis may retain selection but never pretends the new session read it.
Include the complete applicable skill instructions when measuring every dispatched packet.

The final code review and verification skills are completion guidance for the assigned role, not
requests to spawn additional roles. Task policy determines independent review. Suggestions remain
non-blocking; routine fixes retain the material plan and unaffected evidence.
