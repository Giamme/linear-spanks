---
name: tech-react
description: Technology skill loaded when working in a React ecosystem.
---
# React Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When building React components, prioritize functional purity and rendering efficiency:

1. **Functional Components**: Use functional components and Hooks exclusively. Do not write Class components.
2. **Derived State**: Avoid storing state that can be computed from existing state or props on the fly.
3. **Dependencies**: Ensure `useEffect`, `useMemo`, and `useCallback` dependency arrays are exhaustive and accurate.
4. **Render Optimization**: Do not use `React.memo` or `useMemo` prematurely. Only use them when you have proven a rendering bottleneck.
5. **Colocation**: Keep component styles, tests, and specific utilities colocated in the same directory as the component.
