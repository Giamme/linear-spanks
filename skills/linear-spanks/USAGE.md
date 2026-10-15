# Installed-skill usage

Discover the bounded core pipeline:

```bash
python3 scripts/linear_spanks_cli.py --format text help
```

Compile one public command before executing its Linear workflow:

```bash
python3 scripts/linear_spanks_cli.py contracts envelope task run ENG-42 --assurance balanced
python3 scripts/linear_spanks_cli.py contracts brief milestone plan ENG-42 --assurance strict --scan heavy
```

Run a milestone as one bounded step or a receipt-backed loop:

```bash
python3 scripts/linear_spanks_cli.py milestone run ENG-42 --mode step
python3 scripts/linear_spanks_cli.py milestone run ENG-42 --mode loop --max-events 10
```

JSON is the default. `--format text` changes presentation only. Exit codes are `0` success, `1`
internal failure, `2` usage/payload validation, `3` governed stop, and `4` filesystem/configuration
failure.

Use [the command catalog](references/command-catalog.md) for every public and legacy mapping and
[the artifact reference](references/artifact-schemas.md) for lazy migration behavior.

## Context policies and checkpoints

```text
$linear-spanks context budget task ENG-123 --tokens 24000
$linear-spanks context budget milestone "Phase 3" --project "My Project" --tokens 32000
$linear-spanks context budget task ENG-123 --reset
$linear-spanks context inspect task ENG-123
$linear-spanks runtime inspect milestone "Phase 3" --project "My Project"
$linear-spanks task checkpoint ENG-123
$linear-spanks milestone checkpoint "Phase 3" --project "My Project"
```

Explicit budget invocations authorize just that update/reset. Task settings override milestone,
then project; higher built-in ceilings stay higher. Checkpoints prepare an exact preview and wait
for approval before activation. See [context management](references/context-management.md) for
source bindings, document persistence, recovery and internal compilation operations.

## Faster routine edits

Use ordinary `task run ENG-123` or the existing milestone/project run commands. Balanced assurance
automatically selects the short path when the risk assessment supports it; no new flag is needed.
Use `--assurance strict` for high planning and independent review. Explicit `task plan` remains
planning-only. `runtime inspect task ENG-123` explains the current path, stale evidence, and next action.

An optional naming suggestion does not restart work. A failing acceptance check gets a focused repair
under the existing plan. Changed acceptance criteria require material replanning. See
[task workflow](references/task-workflow.md) for coordinator operations and receipt schemas.

## Milestone comment compaction

```text
$linear-spanks milestone checkpoint "My milestone"
$linear-spanks milestone checkpoint "My milestone" --level compact
$linear-spanks milestone checkpoint "My milestone" --level prune
```

Compact updates one archive and one milestone summary, consolidating task comments while
keeping task entities. Prune additionally proposes deletion of selected completed, verified
tasks; the explicit argument, exact preview approval, consumer archive references and
confirmed issue-delete capability are required. General approval never selects prune.
