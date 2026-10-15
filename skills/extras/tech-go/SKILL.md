---
name: tech-go
description: Technology skill loaded when writing Go backend services or CLIs.
---
# Go Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When writing Go, prioritize simplicity, explicit error handling, and idiomatic standard library usage:

1. **Error Handling**: Do not ignore errors. Always check `if err != nil`. Avoid `panic` in production code; return errors up the stack.
2. **Context**: Always pass `context.Context` as the first argument to functions that do I/O (network, database) to enable timeouts and cancellation.
3. **Concurrency**: Use goroutines for concurrent tasks, but always know how they will terminate. Prevent goroutine leaks by using WaitGroups or channels.
4. **Interfaces**: Define interfaces where they are *used* (consumer side), not where they are *implemented* (producer side). Keep interfaces small (1-2 methods).
5. **Standard Library**: Prefer the standard library over third-party packages for routing, HTTP clients, and string manipulation unless the standard library is proven insufficient.
