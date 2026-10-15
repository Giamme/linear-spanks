---
name: tech-kotlin
description: Technology skill loaded when writing Android apps or backend services in Kotlin.
---
# Kotlin Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When writing Kotlin, leverage its modern, expressive syntax and safety features:

1. **Immutability**: Prefer `val` over `var` for variable declarations, and use immutable collections (`List`, `Map`) unless mutation is explicitly required.
2. **Null Safety**: Avoid the `!!` operator. Use safe calls `?.`, the Elvis operator `?:`, or `let` blocks to handle nullable types.
3. **Coroutines**: Use coroutines (`suspend` functions, `launch`, `async`) for asynchronous operations instead of raw threads or callbacks. Be mindful of Dispatchers (e.g., `Dispatchers.IO` for database/network).
4. **Data Classes**: Use `data class` for models and DTOs to automatically generate `equals()`, `hashCode()`, and `copy()`.
5. **Extension Functions**: Use extension functions to add utility methods to existing classes without subclassing, keeping the core APIs clean.
