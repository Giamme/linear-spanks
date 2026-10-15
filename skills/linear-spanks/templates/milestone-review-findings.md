# Milestone Review Findings — {{MILESTONE}}

## Coverage

- **Mode**: {{legacy | next-wave | incremental | testing-session}}
- **Changed / adjacent / unchanged**: {{counts}}
- **Task contract / dependency graph / coverage hashes**: {{sha256 values}}
- **Testing session ID / batch hash**: {{when submitted through milestone report-findings}}

## Blocking findings
<!-- Issues that prevent implementation until resolved or explicitly accepted. -->

1. **{{TITLE}}**
   - Task: {{issue identifier}}
   - What: {{description of the issue}}
   - Why it blocks: {{impact on dependency graph, scope, or verification}}
   - Suggested fix: {{concrete action}}

## Non-blocking observations
<!-- Issues that should be fixed but do not block implementation. -->

1. **{{TITLE}}**
   - Task: {{issue identifier}}
   - What: {{description of the issue}}
   - Suggested fix: {{concrete action}}

## Suggested fixes

| # | Issue | Proposed fix |
|---|-------|--------------|
| 1 | {{issue summary}} | {{concrete action}} |

## Decision

Implementation for {{MILESTONE}} is **blocked** until the findings above are resolved or explicitly accepted.

Please approve one of the following:

- **(a)** Apply the suggested fixes and re-run review.
- **(b)** Provide alternate instructions.
- **(c)** Accept the risks and proceed without fixes.
