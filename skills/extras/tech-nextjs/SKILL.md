---
name: tech-nextjs
description: Technology skill loaded when working in a Next.js environment.
---
# Next.js Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When working with Next.js, strictly differentiate between server and client environments:

1. **RSC vs Client Components**: Default to React Server Components (RSC). Only add `"use client"` when you need interactivity (hooks, event listeners) or browser APIs.
2. **Data Fetching**: Fetch data on the server. Avoid using `useEffect` for data fetching unless absolutely necessary (e.g., highly dynamic client-only state).
3. **Routing Paradigm**: Determine if the project uses the App Router (`app/`) or Pages Router (`pages/`). Do not mix their routing and fetching patterns.
4. **Caching**: Understand Next.js caching behavior (`fetch` cache, revalidation). Explicitly opt-out of caching if data must be real-time.
5. **Image Optimization**: Always use the `next/image` component for remote and local images to prevent layout shift and optimize load times.
