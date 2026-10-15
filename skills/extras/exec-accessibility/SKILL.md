---
name: exec-accessibility
description: Execution skill loaded when building or modifying user interfaces (UI) to ensure they are usable by everyone.
---
# Accessibility (a11y) Strategy

When generating UI code, accessibility is a strict requirement, not an afterthought:

1. **Semantic HTML**: Use native semantic elements (`<button>`, `<nav>`, `<main>`) instead of `<div>` with click handlers. Native elements have built-in keyboard and screen-reader support.
2. **ARIA Attributes**: Use ARIA attributes (`aria-expanded`, `aria-hidden`, `aria-label`) only when native HTML falls short (e.g., for complex custom widgets). "No ARIA is better than bad ARIA."
3. **Keyboard Navigation**: Ensure all interactive elements are reachable via the `Tab` key and have visible `:focus` or `:focus-visible` states.
4. **Color Contrast**: Ensure text has sufficient contrast against its background (aim for WCAG AA standard of 4.5:1).
5. **Alt Text**: Always provide meaningful `alt` text for images conveying information. Use empty `alt=""` for purely decorative images.
