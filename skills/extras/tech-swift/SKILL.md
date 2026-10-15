---
name: tech-swift
description: Technology skill loaded when developing iOS/macOS apps in Swift.
---
# Swift Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When working with Swift, write safe, expressive, and performant code:

1. **Optionals**: Avoid force-unwrapping (`!`). Use `if let` or `guard let` to safely unwrap optionals. Prefer `guard` for early exits to avoid deep nesting.
2. **Value Types**: Use `struct` by default for models and state. Only use `class` when you explicitly need reference semantics, inheritance, or Objective-C interoperability.
3. **Concurrency**: Use the modern `async`/`await` and `Task` APIs for concurrency instead of legacy Grand Central Dispatch (GCD) closures where possible.
4. **Protocol-Oriented**: Prefer Protocols and Protocol Extensions for sharing behavior rather than deep class inheritance hierarchies.
5. **SwiftUI State**: When using SwiftUI, explicitly differentiate between `@State` (local), `@Binding` (passed), and `@EnvironmentObject` (global). Do not over-couple views to global state.
