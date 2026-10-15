# Troubleshooting

## Exit codes

| Code | Meaning | Typical action |
|---:|---|---|
| `0` | Success | Continue using the returned result and warnings. |
| `1` | Unexpected internal failure | Capture the full envelope and reproduce with `./scripts/check`. |
| `2` | Usage or payload validation | Correct the command, option, JSON, or artifact. |
| `3` | Governed workflow stop | Satisfy the approval, refresh, scope, or drift condition. |
| `4` | Filesystem or configuration failure | Repair paths, permissions, ownership, or contract integrity. |

Every result contains `schema_version`, `command`, `ok`, `warnings`, and exactly one of `result` or
`error`.

## `LEGACY_COMMAND_REMOVED`

The v1 flat command was not executed. Use the exact `error.details.replacement`, or consult the
[generated mapping](../../skills/linear-spanks/references/command-catalog.md#removed-v1-command-mapping).

## `CONTRACT_INTEGRITY_MISMATCH`

A contract changed without updating the versioned contract-set index. Do not bypass the check.
Review the intended contract change, update its index digest, regenerate docs, and run the complete
check.

## `ARTIFACT_HASH_DRIFT`

The artifact content no longer matches its stored integrity evidence. Refresh from the authoritative
source. Do not rewrite the digest around unknown content.

## `MIGRATION_APPROVAL_INVALID`, `MIGRATION_PREVIEW_DRIFT`, or `ARTIFACT_SOURCE_DRIFT`

A v1 artifact can migrate only within an already-authorized write. Include the migration in that
preview. A missing, pending, or mismatched receipt is invalid; a changed migration list invalidates
the preview. If the refreshed source hash differs, discard the approval and produce a new preview.

## Installer refusal

Installers replace only their own links, copies, cache, and model-routing keys. Move or remove a
user-owned collision yourself after confirming its purpose; `--force` never claims unmanaged data.

## Caveman archive rejection

`UNSAFE_ARCHIVE_PATH`, `ARCHIVE_PATH_LIMIT`, `ARCHIVE_LINK_REJECTED`,
`ARCHIVE_SPECIAL_FILE`, and the archive size/member limit errors occur before cache or destination
publication. Offline source trees similarly reject links with `SOURCE_LINK_REJECTED` and special
files with `SOURCE_SPECIAL_FILE`. Use a trusted ref or inspect an offline `--source-dir`; do not
weaken the 64 MiB archive, 256 MiB expanded-data, or 10,000-member limits. A failed cache swap or
destination write retains the previous managed cache and installation.

## Model-routing capability differs by client

Codex, Claude Code, OpenClaude, and OpenCode have native managed destinations. Antigravity workers
inherit the parent model and Kimi model strength is advisory. The preview reports this explicitly;
configuration cannot convert an inherited or advisory harness into native per-worker pinning.
