---
name: exec-debugging
description: Execution skill loaded when a task involves fixing bugs, tracing errors, or diagnosing failures.
---
# Debugging Execution Strategy

When implementing a task that requires debugging, follow this strict Chain-of-Thought process BEFORE writing any fix:

1. **Reproduce & Isolate**: What is the exact state or sequence of events that triggers the bug? Which specific file/function is the boundary of the error?
2. **Formulate Hypotheses**: State the 2-3 most likely root causes based on the error trace or behavior.
3. **Gather Evidence**: What logs, variable states, or code paths confirm which hypothesis is correct?
4. **Minimal Fix**: Do not rewrite the entire function. Propose the absolute minimum change required to resolve the issue.
5. **Verify Root Cause**: Explain why this fix addresses the root cause and not just the symptom.
6. **Safety Check**: Could this minimal fix break other parts of the system? (e.g., downstream consumers of this function).

Only after completing these 6 steps should you apply the fix.
