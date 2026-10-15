---
name: tech-vue
description: Technology skill loaded when working in a Vue.js ecosystem.
---
# Vue.js Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When building Vue applications, prioritize modern API usage and component composition:

1. **Composition API**: Use the Composition API (`<script setup>`) by default. Avoid the Options API in new components.
2. **Reactivity**: Differentiate between `ref` (for primitives) and `reactive` (for objects). Avoid destructuring `reactive` objects without `toRefs`.
3. **Composables**: Extract reusable stateful logic into Composables (`use...`) rather than relying on mixins.
4. **Template Logic**: Keep templates clean. Move complex logic (e.g., nested ternaries) into `computed` properties.
5. **State Management**: Use Pinia over Vuex for new global state management needs, leveraging its modular, type-safe stores.
