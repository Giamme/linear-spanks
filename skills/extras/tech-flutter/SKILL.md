---
name: tech-flutter
description: Technology skill loaded when building cross-platform apps with Flutter and Dart.
---
# Flutter & Dart Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When working with Flutter, focus on widget tree efficiency and robust state management:

1. **Widget Composition**: Build small, single-purpose widgets. Prefer composing widgets over passing multiple boolean flags to a monolithic widget.
2. **`const` Constructors**: Always use `const` constructors for widgets that do not change. This dramatically improves rendering performance.
3. **State Management**: Adhere to the project's chosen state management pattern (Provider, Riverpod, Bloc, etc.). Do not mix patterns or abuse `setState` for global state.
4. **Null Safety**: Leverage Dart's sound null safety. Avoid using the `!` (bang) operator to force unwrap; handle nulls gracefully.
5. **Async UI**: Use `FutureBuilder` or `StreamBuilder` when dealing with asynchronous data to prevent blocking the main UI isolate.
