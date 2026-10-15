# Linear Connector Contract

`get_issue` uses `id`, not `identifier` or `issueId`. `save_issue` uses camelCase fields such as
`state`, `blockedBy`, and `relatedTo`. Pass only fields intended to change; omit empty optional
strings, arrays, and nulls. `list_issues` filters directly by `project`, `team`, and `assignee`; do
not invent a `filter` object. Page with `limit` and `cursor` until `hasNextPage:false` when complete
results matter. Resolve milestones with `get_project(query, includeMilestones:true)`.

Release fields are Business-plan gated. Never pass `addReleases`, `removeReleases`, or
`setReleases`, including empty arrays, unless release management was explicitly requested and the
workspace capability was confirmed.

For issue creation, supply non-empty `title` and `team`. For updates, omit `title` unless renaming
and never send an empty title. Treat `Entity not found` as an identifier-resolution failure; do not
guess another target.

Use a two-pass read: compact identity, state, revision, and relations first; full entity text only
when required by the active command contract. Before a write, re-read the target, compare relevant
fields, apply the smallest field set, then read back by returned ID or link.

Before issue-intake status changes, list the resolved team's issue statuses and resolve exactly one
status named `Human draft`, `Unplanned`, and `Backlog`. Use the connector's returned status ID or
accepted state value for the write; never guess an ID from the display name. Stop if any required
status is missing or duplicated.
