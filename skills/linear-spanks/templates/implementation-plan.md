# Implementation Plan

For the small-change path, render only identity/bindings, scope and acceptance, affected files,
a short approach, selected skills, and focused checks. Reuse the current plan when valid; keep
routine evidence refreshes in the execution receipt without incrementing the material plan revision.
Preserve required structured routing, approval, and footprint fields; omit empty narrative sections.

## Plan Identity
- **Plan revision**: {{monotonic revision}}
- **Requested / effective assurance**: `{{fast | balanced | strict}}` / `{{fast | balanced | strict}}`
- **Assurance escalation reason**: {{none or deterministic escalation reasons}}
- **Planner strength**: `{{coordinator | medium | high}}`
- **Source revision / trace source HEAD**: {{commit inspected; trace-only, never a milestone-global invalidator}}
- **Target file hashes**: {{repository-relative path -> sha256}}
- **Consumed surface hashes**: {{symbol or interface -> sha256; use file hash fallback when symbol extraction is unavailable}}
- **Selected dependency receipt/output hashes**: {{dependency task -> immutable receipt hash and provided-output hash}}
- **Acceptance contract hash**: {{sha256 of scope and acceptance contract}}

## Repository Evidence Inspected
- **Target modules**: {{paths and source revisions}}
- **Call sites / interfaces**: {{paths, symbols, or contract pointers}}
- **Nearby tests**: {{paths}}
- **Manifests / toolchain**: {{files and detected versions}}
- **Blocker outputs**: {{relevant issue/output revisions, or none}}
- **Prior plan**: {{authoritative plan revision, or none}}

## Complexity and Routing
- **Assessment schema**: `routing-contract.json` v{{version}}
- **Active dimensions**: {{validated assessment dimensions, or none}}
- **Uncertainty**: {{true/false and evidence}}
- **Executor tier**: `{{low | medium | high}}`
- **Tier rationale**: {{deterministic tier-recommend output}}
- **Escalation triggers**: {{conditions that raise the tier or require replanning}}
- **Reviewer**: {{execution_policy.review: self-verify | independent medium | independent high}}

## Approach
{{High-level approach and key decisions.}}

## Selected Skills
- **Repository/execution**: {{e.g., exec-repo-patterns, exec-debugging, exec-testing}}
- **Technology**: {{skills selected from the detected stack, or none}}
- **Detected versions/evidence**: {{package manifests, toolchain files, or local docs}}
- **Precedence decisions**: {{generic defaults intentionally overridden by project constraints}}

## Exact Implementation Steps
1. {{bounded implementation step and expected result}}
2. {{bounded implementation step and expected result}}

## Files / Areas Likely Touched
- {{file or module}}
- {{file or module}}

## Affected Interfaces
- {{public, schema, persistence, operational, or internal interface; use none when applicable}}

## Execution Footprint
- **Repository**: {{canonical repository identity}}
- **Write scopes**: {{canonical repository-relative paths; use `*` only when genuinely unknown}}
- **Exclusive resources**: {{schemas, migrations, generated catalogs, locks, or shared state}}
- **Parallel safe**: {{true | false}}
- **Serialization rationale**: {{why this can run beside sibling plans or must serialize}}

## Isolation (when requested)
- **Mode**: `{{recorded strategy | isolated worktree}}`
- **Receipt / run ID**: {{durable issue-comment receipt and run identifiers}}
- **Parent branch / baseline HEAD**: {{clean attached parent and exact commit}}
- **Worktree root / path**: {{configured safe root and task worktree}}
- **Child branch**: `linear-spanks/run-{{run-id}}/{{issue-id}}`

## Verification Commands
- `{{exact focused command}}` → {{expected signal}}
- `{{broader command only when required by the repository or affected behavior}}` → {{expected signal}}

## Stop / Replan Conditions
- Keep the plan `valid` when no bound surface changed.
- Permit a guarded `safe-refresh` when only repository evidence, target details, steps,
  verification commands, target hashes, dependency receipt identity with unchanged output,
  or execution footprint changed.
- Return `REPLAN_REQUIRED` for `material` drift in scope, acceptance, dependencies,
  consumed interfaces, authorization, migration policy, product decisions, or project policy.
- {{task-specific stop condition}}

## Risks
- {{risk}} → {{mitigation or watch item}}

## Open questions
- {{question}}
