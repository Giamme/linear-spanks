---
name: tech-python
description: Technology skill loaded when writing Python applications or scripts.
---
# Python Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When writing Python, adhere to modern tooling and typing standards:

1. **Type Hinting**: Always use type hints (`def process(data: list[str]) -> int:`). Use `typing.Optional` or `| None` explicitly.
2. **Formatting & Linting**: Write code that conforms to `Ruff` or `Black` formatting standards. Avoid overly clever one-liners.
3. **Environment Management**: Prefer modern tools like `uv` or `Poetry` for dependency management. Never global-install packages using `pip`.
4. **Testing**: Write tests using `pytest`. Use fixtures for setup/teardown instead of `setup_method`.
5. **Comprehensions**: Use list/dict/set comprehensions for simple transformations, but fall back to standard `for` loops if the comprehension becomes difficult to read.
