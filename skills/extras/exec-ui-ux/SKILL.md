---
name: exec-ui-ux
description: Execution skill loaded when making decisions about user interface layout, states, or user experience flows.
---
# UI/UX Execution Strategy

When building user-facing features, ensure the interface is resilient, responsive, and intuitive:

1. **Loading States**: Never assume instantaneous network responses. Always design and implement skeleton loaders or spinners for async actions.
2. **Error States**: Handle failures gracefully. Do not show raw stack traces to the user. Provide clear error messages and recovery actions (e.g., a "Retry" button).
3. **Empty States**: If a list or dashboard has no data, design a friendly empty state that guides the user on what to do next.
4. **Responsive Design**: Ensure layouts do not break on mobile viewports. Check text wrapping, tap target sizes (min 44x44px), and overflowing flex/grid containers.
5. **Micro-interactions**: Use subtle transitions (e.g., `transition-all duration-200`) for hover and active states to make the interface feel responsive and premium.
