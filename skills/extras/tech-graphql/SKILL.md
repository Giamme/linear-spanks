---
name: tech-graphql
description: Technology skill loaded when defining GraphQL schemas, resolvers, or querying an API.
---
# GraphQL Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When working with GraphQL APIs, optimize for type safety and query efficiency:

1. **N+1 Problem**: Always use tools like DataLoader to batch and cache database requests inside resolvers. Never fire SQL queries in a loop.
2. **Schema Design**: Design schemas driven by UI/client needs, not by blindly mirroring the underlying database schema.
3. **Mutations**: Return specific payload types for mutations (e.g., `UpdateUserPayload`) containing the updated entity and potential `UserError` objects, rather than returning raw scalars.
4. **Pagination**: Use cursor-based pagination (Relay Connection pattern) for lists that will grow large, rather than offset-based pagination.
5. **Over-fetching**: When writing client queries, only request the exact fields the component needs. Do not fetch `*`.
