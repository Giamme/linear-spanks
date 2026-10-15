---
name: tech-tailwind
description: Technology skill loaded when styling components with Tailwind CSS.
---
# Tailwind CSS Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When applying styles using Tailwind:

1. **Utility-First**: Strictly use Tailwind utility classes. Avoid writing custom CSS in stylesheets unless absolutely necessary (e.g., complex animations).
2. **Arbitrary Values**: Minimize the use of arbitrary values (e.g., `w-[32px]`). Use the theme design tokens (e.g., `w-8`) to maintain consistency.
3. **Responsiveness**: Design mobile-first. Apply base styles for mobile and use `sm:`, `md:`, `lg:` prefixes for larger screens.
4. **Extraction**: Do not prematurely extract classes using `@apply`. If a component is reused, extract the React/HTML component itself, not the CSS classes.
5. **State Modifiers**: Use `hover:`, `focus:`, `active:`, and `disabled:` for interactive states natively within the class string.
