# Codebase Import Proposal — {{PROJECT_NAME}}

## Scan receipt

- Analysis run: {{RUN_ID}}
- Scan tier: {{SCAN_TIER}}
- Source revision: {{SOURCE_REVISION}}
- Coverage: {{ANALYZED_FILES}} / {{ELIGIBLE_FILES}} eligible files
- Confidence gaps: {{CONFIDENCE_GAPS}}

## Proposed Linear project description

### Product vision and current scope

{{CURRENT_PRODUCT_CAPABILITIES_AND_USERS}}

### Technical architecture and constraints

{{EVIDENCE_LINKED_CURRENT_ARCHITECTURE}}

### Current success baseline

- {{MEASURABLE_CURRENT_BEHAVIOR}}

### Naming conventions

- Milestones: {{MILESTONE_NAMING}}
- Issues: {{ISSUE_NAMING}}

### Future blueprint

{{FUTURE_DIRECTION_SEPARATE_FROM_IMPLEMENTED_BASELINE}}

## Proposed historical milestones

| # | Outcome | Classification | Proposed status | Evidence | Verification |
|---|---|---|---|---|---|
| 1 | {{SHIPPED_OUTCOME}} | {{CLASSIFICATION}} | {{STATUS}} | {{POINTERS}} | {{FRESH_VERIFICATION_OR_GAP}} |

Historical milestones are outcome-oriented. Only `verified-delivered` may be proposed as completed;
no `implemented-unverified` or `historical-inferred` milestone may be marked completed.

## Proposed future milestones

| # | Outcome | Rationale | Dependencies |
|---|---|---|---|
| 1 | {{FUTURE_OUTCOME}} | {{WHY}} | {{DEPENDENCIES}} |

## Exact Linear operations

| Operation ID | Artifact | Mutation | Payload hash |
|---|---|---|---|
| {{STABLE_OPERATION_ID}} | {{PROJECT_OR_MILESTONE}} | {{CREATE_OR_UPDATE}} | {{SHA256_PAYLOAD_HASH}} |

## Decision

- **(a)** Approve the listed Linear operations.
- **(b)** Request changes to the project or milestone proposal.
- **(c)** Keep the analysis checkpoint without creating Linear artifacts.
