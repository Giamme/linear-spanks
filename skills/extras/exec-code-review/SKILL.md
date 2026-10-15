---
name: exec-code-review
description: Execution skill loaded to perform a final diff review proportional to the change.
---
# Code Review Strategy

Review the final task diff once against the user's goal, acceptance criteria, repository requirements,
and concrete correctness, security, and regression risks. Use the workflow's existing review decision;
this skill does not require another reviewer or planning phase.

Classify each finding:

- **Blocking**: an evidenced defect, unmet acceptance criterion, or violated repository requirement.
  Cite the affected code/evidence and the requirement or failure. Fix it within the existing plan
  when its scope and assumptions still hold.
- **Suggestion**: optional naming, style, cleanup, or design alternatives that satisfy the existing
  requirements. Report useful suggestions briefly; they do not block completion or authorize edits.

After a fix, inspect the changed areas and rerun affected checks. Preserve unaffected review coverage;
do not restart a whole-task review or hunt for additional polish. New evidenced defects still block.
Replan only for material changes to the task's scope, acceptance, interfaces, dependencies, or policy.

Finish with the changes, meaningful verification, and any material remaining limitations. Do not
produce a separate critique transcript or launch another review when current evidence is sufficient.
