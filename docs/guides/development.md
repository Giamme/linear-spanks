# Development and verification

## Toolchain

Python 3.11 is the minimum. Runtime code uses only the standard library. Development tools are
exactly pinned in `pyproject.toml` and `uv.lock`.

```bash
uv sync --frozen --group dev
./scripts/check
```

The check runs Ruff format/lint, strict mypy for the typed package, versioned contract validation,
generated-document drift, local Markdown link validation, unittest, and branch coverage. Python
bytecode writes are disabled.

The 90% branch threshold covers the typed operational runtime. Frozen `_v1` compatibility modules
remain protected by characterization tests, and the exhaustive semantic contract validator remains
protected by contract mutation and cross-reference tests; those two defensive surfaces are excluded
from the numeric percentage so their intentionally repetitive rejection branches do not dilute the
runtime gate.

## Package boundaries

- `core`: errors, result/types, canonical hashing, JSON and atomic filesystem I/O, validation.
- `contracts`: immutable indexed loading and command compilation.
- `domains`: state, context, routing, reviews, runtime, graphs, isolation, orchestration, artifacts,
  installation, and documentation behavior.
- `cli`: argument boundary and JSON/text adapters.
- `compat`: frozen v1 characterization only; new contributor APIs must not be added here.

Keep domain functions pure when feasible. Pass paths, payloads, clocks, and contract sets explicitly;
perform filesystem and process behavior at adapters.

## Generated files

Do not edit these files directly:

- `skills/linear-spanks/references/command-catalog.md`
- `skills/linear-spanks/references/artifact-schemas.md`

Regenerate and then verify them with:

```bash
python3 skills/linear-spanks/scripts/generate_command_catalog.py
python3 skills/linear-spanks/scripts/generate_command_catalog.py --check
```

## Local acceptance

Run `./scripts/check`, then repeat the complete test suite with both supported boundary
interpreters:

```bash
uv run --python 3.11 --frozen --group dev python -m unittest discover -s tests
uv run --python 3.14 --frozen --group dev python -m unittest discover -s tests
```

Finally run link and copy installation with explicit destinations below a temporary directory so
no real client configuration can be touched.
