---
name: tech-typescript
description: Technology skill loaded when working in a TypeScript codebase.
---
# TypeScript Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When writing TypeScript, adhere to strict typing constraints:

1. **No `any`**: Never use the `any` type. Use `unknown` if the type is truly dynamic, and narrow it down with type guards.
2. **Strict Null Checks**: Always handle `null` and `undefined` explicitly.
3. **Interfaces vs Types**: Use `interface` for object shapes and class contracts. Use `type` for unions, intersections, and primitives.
4. **Generics**: Use generics to create reusable, type-safe functions instead of duplicating logic.
5. **Inference**: Rely on TypeScript's type inference for simple variable assignments; don't over-annotate.
