# Ripwire 0.4.0 local validation

Measured 2026-09-07 on macOS ARM64 using the production SHA-256-pinned archive.
Reproduce with the local archive command in `tests/fixtures/ripwire/README.md`.
The test installs into a temporary configuration directory and performs no downloads.

The fixture contains a three-symbol call chain and one test. All six queries found their
expected symbol or test; secret paths, ignored files and symlinks were excluded. A dirty
source addition appeared on the next query and changed the evidence binding. Unit tests also
reject source drift during a query. This is a small discovery sanity check, not a recall or
precision evaluation on production repositories.

| Operation | Context bytes | Latency (ms) | Result |
|---|---:|---:|---|
| map | 2734 | 550.95 | Expected fixture result found |
| task | 4423 | 119.39 | Expected fixture result found |
| symbol | 3083 | 84.67 | Expected fixture result found |
| callers | 4745 | 84.58 | Expected fixture result found |
| impact | 5034 | 84.8 | Expected fixture result found |
| tests | 2455 | 85.74 | Expected fixture result found |
| disabled-adapter | 184 | 0.0 | Disabled; zero binary calls |
| disabled-search-and-reads | 1206 | 12.19 | Expected fixture result found |

Enabled byte counts include native output, provenance, bounded diagnostics and the advisory
label, measured by the existing context measurement function. The enclosing workflow must
also charge transport metadata. The disabled search baseline counts `rg` hits and targeted
reads of both fixture source files, and makes no Ripwire calls. It locates the fixture call
chain but does not compute an impact graph. The first enabled query includes cold startup;
these single-run wall-clock measurements should not be treated as general performance claims.

On this small fixture, existing search and reads are faster and smaller. Ripwire provides
structured relationship evidence; its usefulness on larger real tasks remains workload-dependent.
Impact and test suggestions do not replace required checks or coverage requirements.

Real-binary execution was verified on macOS ARM64 only. Linux and macOS x64 asset selection,
checksum rejection and archive validation are covered with network-independent fixtures;
their published binaries were not executed locally.
