---
name: exec-documentation
description: Execution skill loaded when a task requires updating docs, READMEs, or inline comments.
---
# Documentation Strategy

When updating documentation, prioritize clarity, accuracy, and discoverability:

1. **README Updates**: If you added a new environment variable, script, or architectural pattern, update the project's root `README.md`.
2. **API Docs**: Ensure any changes to public functions, API endpoints, or GraphQL schemas are reflected in their respective documentation or OpenAPI specs.
3. **ADRs**: If you made a major architectural decision (e.g., introducing Redis, switching routers), draft an Architecture Decision Record (ADR) explaining the *why*.
4. **Inline Comments**: Focus on the *Why*, not the *What*. Do not comment self-explanatory code. Explain complex business logic, edge cases, or hacky workarounds.
5. **Changelog**: If applicable to the project, add a summary of your changes to the `CHANGELOG.md`.
