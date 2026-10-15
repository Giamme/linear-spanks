# Codebase Analysis — {{REPOSITORY}}

## Scan identity

- Run ID: {{RUN_ID}}
- Scan tier: {{FAST_MEDIUM_HEAVY}}
- Repository root: {{REPOSITORY_ROOT}}
- Source revision: {{SOURCE_REVISION}}
- Repository fingerprint: {{REPOSITORY_FINGERPRINT}}
- Stage: {{STAGE}}

## Coverage

| Metric | Count |
|---|---:|
| Eligible files | {{ELIGIBLE_FILES}} |
| Selected files | {{SELECTED_FILES}} |
| Analyzed files | {{ANALYZED_FILES}} |
| Excluded files | {{EXCLUDED_FILES}} |
| Selected source bytes | {{SELECTED_SOURCE_BYTES}} |

**Exclusions and unreadable paths:** {{EXCLUSIONS}}

## Current architecture

{{EVIDENCE_LINKED_ARCHITECTURE_SUMMARY}}

## Evidence capsules

### {{MODULE}}

- Capsule ID: {{CAPSULE_ID}}
- Confidence: {{LOW_MEDIUM_HIGH}}
- Responsibilities: {{RESPONSIBILITIES}}
- Public interfaces: {{PUBLIC_INTERFACES}}
- Dependencies: {{DEPENDENCIES}}
- Implemented capabilities: {{IMPLEMENTED_CAPABILITIES}}
- Tests and verification: {{TESTS_AND_VERIFICATION}}
- Known gaps: {{KNOWN_GAPS}}
- Evidence: {{REPOSITORY_RELATIVE_POINTERS}}
- Source hashes: {{SOURCE_HASHES}}

## Capability and completion findings

| Outcome | Classification | Confidence | Evidence | Verification gap |
|---|---|---|---|---|
| {{OUTCOME}} | {{VERIFIED_DELIVERED_OR_IMPLEMENTED_UNVERIFIED_OR_HISTORICAL_INFERRED}} | {{CONFIDENCE}} | {{POINTERS}} | {{GAP}} |

## Open questions

- {{QUESTION_OR_UNCERTAINTY}}

## Checkpoint

- Completed batches: {{COMPLETED_BATCH_IDS}}
- Remaining batches: {{REMAINING_BATCH_IDS}}
- Next command: {{NEXT_COMMAND}}
