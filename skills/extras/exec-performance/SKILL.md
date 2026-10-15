---
name: exec-performance
description: Execution skill loaded when optimizing code, dealing with large datasets, or addressing latency issues.
---
# Performance Execution Strategy

When your task targets performance optimizations, evaluate the following before changing code:

1. **Algorithmic Complexity**: Avoid O(n^2) or worse loops. Use HashMaps/Sets for O(1) lookups instead of nested arrays.
2. **Caching**: Is the data static or rarely changing? Propose a caching layer (in-memory, Redis) rather than recomputing.
3. **Batching**: Group database queries or API calls into batches to minimize network latency.
4. **Lazy Loading**: Do not load resources (images, components, data) until they are needed by the user.
5. **Memory Leaks**: Ensure event listeners are cleaned up and large objects are garbage collected.

Do not prematurely optimize. Ensure you have a baseline metric to prove the optimization actually works.
