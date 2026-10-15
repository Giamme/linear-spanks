---
name: exec-verification
description: Execution skill loaded to explicitly verify if the task solved the original user intent.
---
# Verification Strategy

Before finalizing your work, step back from the code and answer these verification questions:

1. **Core Intent**: Did I actually solve the user's primary goal, or did I get distracted by an implementation detail?
2. **Breakage**: Did my changes inadvertently break an existing feature or assumption? (Check downstream consumers of any modified functions).
3. **Unverified Paths**: What edge cases or code paths remain untested or unverified? Explicitly state these in your completion handoff.
4. **Required Checks**: Run checks appropriate to the change and all checks required by the repository. A documentation or copy edit does not automatically require a full application build.
5. **Evidence**: Provide concrete evidence of verification (e.g., "Tested locally by hitting the `/auth` endpoint with an expired token").

Verification is the completion phase of the current task, not a new planning or independent-review
request. Reuse valid evidence and record which checks cover the actual candidate. Do not restart
checks or planning for optional polish. Material defects and unmet acceptance criteria still block.
