---
name: exec-architecture
description: Execution skill loaded when making structural decisions, creating new modules, or defining component boundaries.
---
# Architecture Execution Strategy

When adding a new feature or module, avoid jumping straight into implementation. Instead, evaluate the architectural placement:

1. **Placement**: Should this be a generic utility, a specific domain service, or a UI component?
2. **Extensibility**: Are you extending an existing abstraction or creating a new one? If creating a new one, is it truly necessary?
3. **Coupling**: How tightly coupled will this new code be to existing modules? Aim for loose coupling and high cohesion.
4. **Trade-offs**: Before writing the final code, present 2 viable design options (e.g., interface vs. abstract class, or stateful vs. stateless) and state the trade-offs.

**Rule of Thumb**: Many coding mistakes are architectural. Ask yourself if the proposed structure will scale with the project before writing the implementation.
