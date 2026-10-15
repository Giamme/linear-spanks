---
name: exec-refactoring
description: Execution skill loaded when a task involves restructuring code, reducing tech debt, or improving maintainability.
---
# Refactoring Execution Strategy

When your task involves refactoring, your primary directive is: **Preserve existing behavior.** Do not mix feature development with refactoring.

Follow this Red-Green-Refactor loop strategy:

1. **Identify the Code Smell**: Is it duplicated code, a God object, poor naming, or high cyclomatic complexity?
2. **Baseline**: Ensure you understand the current inputs, outputs, and side effects of the target code.
3. **Smallest Safe Change**: Break the refactoring down into atomic steps (e.g., extract function first, then rename variables).
4. **Preserve APIs**: Do not change the public API or function signatures unless that is the explicit goal of the refactoring task. If you must, list the downstream consumers that will need updating.
5. **Justify**: Explain why this structural change improves maintainability or performance.

Do not refactor code outside the immediate scope of the task just because it "looks messy."
