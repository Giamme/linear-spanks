# Artifact and schema reference

<!-- Generated from the artifact codec registry; do not edit. -->

Every durable v2 artifact has exactly these top-level fields:

| Field | Contract |
|---|---|
| `kind` | Stable codec key |
| `schema_version` | `2` |
| `revision` | Non-negative source revision or deterministic fallback |
| `provenance` | Original product/schema version and canonical source hash |
| `payload` | Validated source payload, including its original hashes |
| `integrity` | SHA-256 over the other canonical v2 fields |

## Registered kinds

| Kind | Accepted v1 schema | Revision source | Integrity |
|---|---:|---|---|
| `ContextSnapshot` | 1 | `revision` | SHA-256 |
| `ContextDelta` | 1 | `revision` | SHA-256 |
| `ContextManifest` | 1 | `revision` | SHA-256 |
| `CompactionReceipt` | 1 | `revision` | SHA-256 |
| `ContextBudgetPolicy` | 1 | `revision` | SHA-256 |
| `state-marker` | 1 | `revision` | SHA-256 |
| `dependency-graph` | 1 | `graph_revision` | SHA-256 |
| `human-verification-policy` | 1 | `revision` | SHA-256 |
| `human-verification-override` | 1 | `revision` | SHA-256 |
| `human-verification-gate` | 1 | `gate_revision` | SHA-256 |
| `human-verification-checklist` | 1 | `checklist_revision` | SHA-256 |
| `human-verification-repair` | 1 | `failure_revision` | SHA-256 |
| `milestone-runtime-projection` | 1 | `revision`, `event_count` | SHA-256 |
| `autopilot-policy` | 1 | `revision` | SHA-256 |
| `repository-checkpoint` | 1 | fallback | SHA-256 |
| `project-context-capsule` | 1 | `project_revision` | SHA-256 |
| `verification-ledger` | 1, 2 | `plan_revision` | SHA-256 |
| `project-loop-receipt` | 1 | `project_revision` | SHA-256 |
| `milestone-loop-receipt` | 1 | `milestone_revision` | SHA-256 |
| `isolation-receipt` | 1 | `plan_revision` | SHA-256 |
| `wave-receipt` | 1 | fallback | SHA-256 |
| `rollover-receipt` | 1 | fallback | SHA-256 |

## Lazy migration protocol

1. Decode and validate v1 without changing the source.
2. Include the exact path, source hash, source schema, revision, and v2 target in the
   normal write preview.
3. After the enclosing write is authorized, re-read and compare the source hash.
4. Atomically persist v2 and perform a typed read-back.

Read-only commands stop after step 1. Malformed, drifted, and future-version artifacts
fail closed. There is no implicit bulk Linear migration.
