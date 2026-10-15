---
name: tech-rust
description: Technology skill loaded when writing systems or backend code in Rust.
---
# Rust Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When writing Rust, prioritize memory safety, zero-cost abstractions, and idiomatic error handling:

1. **Ownership & Borrowing**: Minimize cloning (`.clone()`). Prefer passing references (`&T` or `&mut T`) and structure your data to satisfy the borrow checker naturally.
2. **Error Handling**: Never use `unwrap()` or `expect()` in production code. Propagate errors using the `?` operator and return `Result<T, E>`.
3. **Pattern Matching**: Use exhaustive `match` statements instead of long `if/else` chains, especially when dealing with `Option` and `Result` types.
4. **Iterators**: Prefer iterator methods (`.map()`, `.filter()`, `.fold()`) over manual `for` loops where possible for conciseness and optimization.
5. **Clippy**: Ensure code passes `cargo clippy` without warnings. Adhere strictly to the linter's idiomatic suggestions.
