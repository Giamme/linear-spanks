# Workflow State Contract

`workflow-contract.json` is authoritative for stage names and legal transitions. Store one
machine-readable marker in the milestone description alongside the human-readable stage:

```text
<!-- linear-spanks:state {"last_command":"plan-tasks","milestone_id":"...","project_id":"...","resume_stage":null,"revision":4,"run_id":"...","schema_version":1,"stage":"tasks-planned","updated_at":"..."} -->
```

Before a stage-changing mutation:

1. Parse the existing marker. Legacy milestones without one must be audited or onboarded before
   automatic continuation.
2. Verify project and milestone IDs match the resolved target.
3. Generate a proposed replacement marker with the next revision, then validate the complete
   transition before any mutation:
   `python3 scripts/linear_spanks_cli.py state advance --command milestone plan --transition plan-tasks --current-marker current-description.md --replacement-marker replacement-description.md`.
   This binds the command to the transition, preserves project and milestone IDs, requires exactly
   one revision increment, and validates the timestamp and command-stage relationship.
4. Generate an idempotency key using the current revision. Search relevant comments/documents for
   that key before creating a duplicate artifact.
5. Apply the Linear mutation, increment the revision, generate the replacement marker, and retain
   any required human-readable description content.
6. Read the entity back, parse the marker, and confirm the expected revision and stage.

For pause, store the previous non-terminal stage in `resume_stage`. Resume requires status and sync
before validating that stored destination; it cannot be supplied or changed by the resuming caller.
Never resume directly to `wrapped` or `archived`. `human-verified` is a resumable active state only
for milestones whose current effective human-verification policy is enabled.

The static transition contract permits `milestone-verified -> wrapped` for backward-compatible
disabled policy and `human-verified -> wrapped` for enabled policy. Before `milestone wrap`, run
`verification action-check`; the state transition alone is not sufficient authority.
