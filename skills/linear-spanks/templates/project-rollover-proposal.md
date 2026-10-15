# Project Release Rollover Proposal

**Source Project**: {{Name and URL}}
**Source Revision**: {{Revision}}
**Next Release**: {{Release label}}
**Proposed Successor**: {{Project name}}
**Initiative**: {{Inherited or explicitly selected Initiative, or None}}
**Rollover Run**: {{Run ID}}
**Rollover Receipt**: {{Source-project Linear Document link or Not yet persisted}}
**Current Phase**: {{Phase}}

## Release Capsule Preview

{{Render the `Active Project Context` capsule for the completed release, including its source snapshot hash and coverage summary.}}

## Successor Project Spec

{{Compact current product baseline, next-release goal, architecture constraints, success criteria, naming conventions, and non-scope.}}

## Proposed Roadmap

| Proposal ID | Milestone | Outcome | Success Criteria | Dependencies |
| --- | --- | --- | --- | --- |
| {{Stable ID}} | {{Name}} | {{Outcome}} | {{Measurable criteria}} | {{Links or None}} |

Propose three to seven outcome-oriented milestones. Do not create detailed tasks or plans here.

## Selected Carry-overs

| Source Issue | Source Revision | Successor Contract | Why It Still Applies | Source Disposition |
| --- | ---: | --- | --- | --- |
| {{Issue link}} | {{Revision}} | {{Stable goal, scope, and acceptance digest}} | {{Reason}} | {{superseded / canceled}} |

Only approved rows are recreated. New issues start in `Unplanned`, link back to the source issue,
and do not copy superseded implementation-plan comments.

## Source Milestone Dispositions

| Milestone | Disposition | Evidence | Approved |
| --- | --- | --- | --- |
| {{Milestone}} | {{wrapped / archived / canceled}} | {{Links}} | {{Yes / No}} |

## Source Issue Dispositions

| Issue | Disposition | Replacement | Approved |
| --- | --- | --- | --- |
| {{Issue}} | {{completed / superseded / canceled}} | {{Successor issue or None}} | {{Yes / No}} |

## Approval Gate

- **Operations in this phase**: {{Exact writes}}
- **Operations deferred to later phases**: {{Exact writes}}
- **Unresolved source items**: {{IDs or None}}
- **Plan payload hash**: {{sha256 digest}}
- **Next command**: `{{Exact project rollover resume command}}`
