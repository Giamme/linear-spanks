---
name: exec-testing
description: Execution skill loaded when writing tests or implementing code that requires test coverage.
---
# Testing Execution Strategy

Choose checks proportional to the behavior changed and follow required repository checks. Reuse the
existing verification plan when it still applies. Do not add tests for reversible, low-impact edits
or tests that merely restate the implementation. For behavior changes, follow these guidelines:

1. **Existing Style**: Identify whether the project uses TDD, BDD, or standard unit tests. Match the syntax (e.g., Jest, Mocha, Vitest).
2. **Level of Testing**: Focus on unit tests for pure logic and integration tests for boundaries (e.g., database, external APIs).
3. **Edge Cases**: Do not just test the "happy path". Test null inputs, boundary conditions, and unexpected types.
4. **Mocking**: Do not overmock. Mocking internal implementation details makes tests brittle. Mock external boundaries only.
5. **Regression**: If fixing a bug, write a failing test that reproduces the bug *before* writing the fix.

During repair, rerun failed checks and checks affected by the edit. Run required final checks against
the actual candidate before completion. Do not repeat passing checks on unchanged inputs unless
new evidence, environment/toolchain changes, or a repository requirement makes repetition necessary.
