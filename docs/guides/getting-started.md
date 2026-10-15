# Getting started

Linear Spanks v2 requires Python 3.11 or newer and has no runtime dependencies.

It reaches Linear only through your agent's Linear MCP connector; set that up first. To install
without a clone, as a plugin or with `npx skills`, see the [README](../../README.md#install).

## Install

Link mode points clients at this checkout and reflects changes immediately:

```bash
./scripts/install-skills --client codex --scope linear --mode link
```

Copy mode creates a managed snapshot:

```bash
./scripts/install-skills --client codex --scope linear --mode copy
```

Both modes refuse unmanaged collisions. Use `--dry-run` to inspect destinations without writing and
`--uninstall` to remove only entries owned by this checkout.

## Confirm the runtime

```bash
python3 skills/linear-spanks/scripts/linear_spanks_cli.py contracts validate --format text
python3 skills/linear-spanks/scripts/linear_spanks_cli.py help --format text
```

The first command validates the indexed contract collection. The second shows the core public
pipeline; add `--advanced` for the full surface.

## First dry run in an isolated home

```bash
sandbox_home=$(mktemp -d)
./scripts/install-skills --client codex --scope linear --mode link \
  --dest "$sandbox_home/link/skills" --dry-run
./scripts/install-skills --client codex --scope linear --mode copy \
  --dest "$sandbox_home/copy/skills" --dry-run
```

Explicit destinations keep the dry run isolated even when `CODEX_HOME`, `OPENCLAUDE_HOME`, or
`XDG_CONFIG_HOME` is already exported. Remove `--dry-run` to perform the isolated install. The
managed ownership record makes both operations repeatable and uninstallable.

Continue with [task-oriented usage](usage.md) or review the
[v1 migration guide](v1-to-v2.md).
