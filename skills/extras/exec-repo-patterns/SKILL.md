---
name: exec-repo-patterns
description: Execution skill loaded to adapt code generation to the existing repository architecture, style, and conventions.
---
# Repository Patterns Strategy

Before implementation, establish the following facts for the affected area. Reuse observations
already verified against relevant source hashes, worktree identity, contracts, and toolchain; inspect
only missing or changed evidence. A tiny edit does not require a new repository-wide exploration:

1. **Architecture Layout**: Where does business logic live vs. UI logic vs. data access?
2. **Naming Conventions**: Are files `kebab-case`, `camelCase`, or `PascalCase`? Are interfaces prefixed with `I`?
3. **Error Handling**: How does this codebase handle exceptions? Does it return Error objects, throw exceptions, or use a specific logging service?
4. **Testing**: What testing library is used? Where are tests located (`__tests__`, co-located, etc.)?

**CRITICAL RULE**: Generate code that feels native to this repository. Do not introduce a new paradigm, pattern, or preferred library unless explicitly requested. Mimic the existing code structure.
