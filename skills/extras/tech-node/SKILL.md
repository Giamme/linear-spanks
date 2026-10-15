---
name: tech-node
description: Technology skill loaded when writing backend Node.js services or scripts.
---
# Node.js Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When writing Node.js backend logic, prioritize non-blocking IO and robust error handling:

1. **Event Loop**: Never write synchronous, CPU-intensive code (`JSON.parse` on massive objects, sync file reads) in the main request path. It blocks the event loop.
2. **Async/Await**: Use `async`/`await` over raw Promises or callbacks. Ensure all Promises are awaited or have `.catch()` attached.
3. **Error Handling**: Do not swallow errors. Handle uncaught exceptions and unhandled promise rejections gracefully, logging them and exiting if the state is unrecoverable.
4. **Streams**: When dealing with large files or network responses, use Streams instead of buffering the entire payload into memory.
5. **Security**: Avoid `eval()`, sanitize inputs before passing them to `exec()` or `spawn()`, and never expose raw stack traces to the client.
