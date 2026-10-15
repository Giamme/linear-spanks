# Linear Spanks

Linear Spanks is a governed workflow runtime for turning project intent into bounded Linear
project, milestone, and task operations. Version 2 uses a typed Python 3.11+ runtime, a
namespaced command surface, immutable contract sets, JSON-first output, and authorized lazy
migration for persisted v1 artifacts.

Runtime dependencies: none. Ruff, mypy, and coverage are pinned development tools managed by
uv.

Balanced execution automatically takes the short path for localized, evidenced low-risk changes:
inspect, edit, focused checks, and one final self-review. Task, milestone, and project runs share
this decision. Optional review suggestions do not block completion; safe evidence refreshes and
routine repairs retain the existing plan. See the [task workflow](skills/linear-spanks/references/task-workflow.md).

## Requirements

- **Python 3.11 or newer** as the `python3` your agent runs. Nothing else at runtime.
- **Linear's MCP server, connected in your agent.** Linear Spanks reads and writes Linear only
  through it (`get_issue`, `save_issue`, `list_issues`, `get_project`). See
  [Linear's MCP guide](https://linear.app/docs/mcp). For example:
  - Claude Code: `claude mcp add --transport http linear-server https://mcp.linear.app/mcp`, or
    the Linear connector on claude.ai;
  - Codex: `codex mcp add linear --url https://mcp.linear.app/mcp`, then `codex mcp login linear`.

## Install

Linear Spanks is three skills: `linear-spanks` (the runtime and its commands), `linear-workflow`
(every Linear read and write) and `linear-spanks-git` (branches, commits and merges). The 27
execution and technology skills in [`skills/extras/`](skills/extras/) (debugging, testing,
security, Python, React and so on) are guidance it loads when a task calls for it. The plugin keeps
them as files, so they never fire on their own in unrelated sessions.

### Claude Code

```
/plugin install linear-spanks --marketplace Giamme/linear-spanks
```

On Claude Code before 2.1.275: `/plugin marketplace add Giamme/linear-spanks`, then
`/plugin install linear-spanks@linear-spanks`.

### Codex

```sh
codex plugin marketplace add Giamme/linear-spanks
codex plugin add linear-spanks@linear-spanks
```

### GitHub Copilot CLI

```sh
copilot plugin marketplace add Giamme/linear-spanks
copilot plugin install linear-spanks@linear-spanks
```

### Cursor, Gemini CLI, OpenCode and others

Install the three skills with [`npx skills`](https://github.com/vercel-labs/skills), which knows
where each agent looks:

```sh
npx skills add Giamme/linear-spanks --skill linear-spanks --skill linear-spanks-git --skill linear-workflow
```

Add extras the same way (`--skill exec-testing --skill tech-python`). Linear Spanks uses the ones it
can read and notes any it skipped in the plan.

### From a clone

The repository's installer links (or copies) the skills into each agent and keeps an ownership
record, so updates and uninstalls touch only its own entries:

```sh
git clone https://github.com/Giamme/linear-spanks ~/src/linear-spanks
cd ~/src/linear-spanks
./scripts/install-skills --client claude --scope linear --dry-run
./scripts/install-skills --client claude --scope linear
```

`--client` takes `claude`, `codex`, `openclaude`, `opencode`, `kimi`, `antigravity-cli`,
`antigravity-ide`, or `all` (every one of them, whether installed or not). `--scope all` adds the
extras as skills, `--mode copy` installs a snapshot instead of links, and `--uninstall` removes
only this checkout's entries. The `linear` and `all` scopes also install Ripwire (see
[What it runs](#what-it-runs)); `--without-ripwire` saves a permanent opt-out.

Install the skills in one place per agent. With the Claude Code plugin installed, don't also link
them into `~/.claude/skills`, or Claude Code lists them twice.

## Quick start

Ask your agent to analyze the codebase, create a project or run the next task. To see the commands
it uses, from a clone:

```bash
python3 skills/linear-spanks/scripts/linear_spanks_cli.py --format text help
```

The standard flow is:

```text
codebase analyze/import
        ↓
project create/review, then project run
        ↓
milestone clarify/design/create-tasks/plan/review/run/verify/wrap
        ↓
task refine/plan/next/run
```

For example:

```bash
python3 skills/linear-spanks/scripts/linear_spanks_cli.py milestone run ENG-42 --mode step
python3 skills/linear-spanks/scripts/linear_spanks_cli.py milestone run ENG-42 --mode loop --max-events 10
```

Commands emit a stable JSON envelope by default. Add `--format text` for human-readable output.
Flat v1 commands are intentionally rejected with `LEGACY_COMMAND_REMOVED` and their exact v2
replacement; they are never run as aliases.

## Updating a clone install

From your original checkout, run:

```bash
./scripts/update-skills
```

This fetches the current branch's upstream and fast-forwards the clean checkout, then
runs the existing installer for all supported clients: Codex, OpenClaude, Claude,
Antigravity CLI and IDE, Kimi, and OpenCode. It creates missing installations too.
Defaults are `--scope linear --mode link`; use `--scope all` for every skill group
or `--mode copy` to refresh snapshots as copies. Select one harness with `--client codex`.
Custom destinations require both `--client` and `--dest`.

```bash
./scripts/update-skills --dry-run                 # offline, no writes
./scripts/update-skills --local --mode copy       # current files, no Git fetch
./scripts/update-skills --client codex --scope all
```

Dirty or detached checkouts, missing upstreams, and diverged branches stop the default
update. `--source /path/to/checkout` selects another source checkout. Installer ownership
checks and rollback still apply; conflicting unmanaged files are preserved. If installation
fails after fetching, the updated source remains; fix the reported issue and retry with
`--local`. Ripwire setup follows the existing saved preference; `--without-ripwire` saves
an opt-out. Restart active harness sessions after updating. Model-routing configuration
is managed separately and is not refreshed by this script.

## What it runs

- **The runtime** is standard-library Python that your agent starts
  (`python3 skills/linear-spanks/scripts/linear_spanks_cli.py ...`). It makes no network calls,
  reads no credentials and sends no telemetry. It compiles contracts and write plans; your agent
  performs every Linear read and write through its Linear MCP connector, after the approval each
  command declares.
- **In your repository** it writes `.linear-spanks-git.yml` and `.linear-spanks/`, works on
  branches, and puts task worktrees in `../.linear-spanks-worktrees/`.
- **Ripwire** (optional code search): the clone installer, or `extensions ripwire install` when you
  ask for it, downloads Ripwire 0.4.0 from its GitHub releases, checks the pinned SHA-256 and
  installs it under `~/.config/linear-spanks/extensions/ripwire/`. Linear Spanks then runs it in
  your repository. Plugin and `npx skills` installs don't download it.
- **Caveman** (opt-in): `scripts/install-caveman` downloads a third-party skill pack from
  github.com/JuliusBrussee/caveman into `~/.cache/linear-spanks/extensions/caveman` and links it
  into your agents.
- **Model routing** (opt-in): `scripts/configure-model-routing --apply` writes agent profiles to
  `~/.codex/agents/`, `~/.claude/agents/`, OpenCode's agents folder and `~/.openclaude.json`.
- **Clone installs:** the installer writes a `.linear-spanks-managed` ownership record in each
  skills folder it manages, and `update-skills` runs `git fetch` on your checkout.

## Safety model

Linear Spanks resolves project scope before work, treats reads as non-mutating, requires the
declared approval before writes, refreshes before mutation, and performs durable read-back after
mutation. Done states require fresh verification. Material scope, integration, model-selection,
merge, and push gates remain explicit.

Existing v1 artifacts remain readable. Read-only operations migrate only in memory. An
already-authorized write previews the conversion, refreshes the source hash, writes v2 atomically,
and validates the read-back. There is no implicit bulk Linear migration.

## Documentation

- [Getting started](docs/guides/getting-started.md)
- [Task-oriented usage](docs/guides/usage.md)
- [Troubleshooting](docs/guides/troubleshooting.md)
- [Architecture](docs/guides/architecture.md)
- [Development and verification](docs/guides/development.md)
- [Migrating from v1](docs/guides/v1-to-v2.md)
- [Generated command catalog](skills/linear-spanks/references/command-catalog.md)
- [Generated artifact/schema reference](skills/linear-spanks/references/artifact-schemas.md)
- [v2 changelog](CHANGELOG.md)

The compact installed-skill router is [SKILL.md](skills/linear-spanks/SKILL.md); installed-skill
operators can use [USAGE.md](skills/linear-spanks/USAGE.md).

## License

[MIT](LICENSE)

## Development

```bash
uv sync --frozen --group dev
./scripts/check
```

`./scripts/check` disables bytecode writes and runs Ruff, strict mypy, contract validation,
generated-document and link checks, the complete unittest suite, and branch coverage with a 90%
package threshold. Hosted CI is intentionally outside this repository.

### Persistent context allowances

`context budget <project|milestone|task> <target> --tokens <integer>` raises an inherited token
allowance; `--reset` restores inheritance. `context inspect` and `runtime inspect` provide read-only
scope diagnostics. Project, milestone and task checkpoints prepare approval-bound snapshots with
preserved sources and subsequent deltas. Linear writes remain coordinator-owned; public CLI
commands compile contracts and internal `*-prepare` operations produce reviewable write plans.
See [context management](skills/linear-spanks/references/context-management.md).

The repeated-workflow regression benchmark runs with
`python3 scripts/benchmark-context`; its 100-cycle ceilings are recorded in
[replay budgets](tests/fixtures/context/replay-budgets.json). That benchmark bounds what the
context machinery saves; `python3 scripts/benchmark-envelope` bounds what it costs, measuring the
compiled envelope plus the required-reference packet each command loads before any target
evidence. Its per-command ceilings are recorded in
[envelope budgets](tests/fixtures/context/envelope-budgets.json).

### Optional Ripwire repository discovery

Skill setup installs checksum-pinned Ripwire 0.4.0 by default for `linear` and `all` scopes.
Use `scripts/install-skills --without-ripwire` to save a persistent user opt-out.
Dry runs remain offline and write-free; automatic Ripwire failure does not fail core setup.
See the [Ripwire integration reference](skills/linear-spanks/references/ripwire.md) for
configuration, explicit installation, query kinds, source exclusions, and advisory limits.
