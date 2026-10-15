---
name: tech-postgres
description: Technology skill loaded when writing SQL, ORM queries, or database migrations for PostgreSQL.
---
# PostgreSQL Best Practices

Apply this skill after inspecting repository conventions and supported versions. Treat its rules
as defaults unless they protect a concrete safety property; preserve an established project
pattern when it conflicts, and record the reason in the implementation plan.

When interacting with a Postgres database, prioritize safety, efficiency, and data integrity:

1. **Migrations**: Always modify schemas using version-controlled migrations. Never alter tables manually.
2. **Backwards Compatibility**: Migrations must be backwards compatible (e.g., add new columns as nullable first) to support zero-downtime deployments.
3. **Indexes**: Add indexes to foreign keys and frequently filtered/sorted columns, but avoid over-indexing to prevent slow writes.
4. **N+1 Queries**: When fetching relationships, use `JOIN`s or data loaders instead of firing a query inside a loop.
5. **Transactions**: Wrap multi-step data mutations in a transaction. Ensure rollbacks are handled on failure.
