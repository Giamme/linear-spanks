# ADR 0001: Typed domain modules over a generic schema engine

- Status: accepted
- Date: 2026-08-03

## Context

The v1 workflow runtime concentrated contract loading, validation, orchestration, artifact parsing,
and CLI dispatch in one module. Cross-contract rules were expressed as scattered dictionary access,
and repeated subprocess tests made architectural changes slow to verify.

## Decision

Use Python 3.11 typed domain modules with the dependency direction `core → contracts → domains →
CLI`. Load one immutable, injectable `ContractSet`. Represent public commands with `CommandSpec`,
durable artifact behavior with `ArtifactCodec`, compiled work with `ExecutionEnvelope`, and process
results with `CliResult` and `LinearSpanksError`.

Keep runtime dependencies empty. Use explicit adapters for filesystem, streams, timestamps, and
process behavior. Retain a frozen compatibility edge only while v1 artifacts and internal Python
consumers need characterization.

## Rejected alternative: generic schema engine

A general JSON-schema-style engine could reduce some field-validation code, but it would introduce a
runtime dependency or a local schema language, obscure cross-artifact safety semantics, and make
approval/read-back rules harder to express and type-check. The repository needs a small number of
high-value workflow domains, not a second general-purpose validation platform.

## Consequences

Contributors add behavior to a named domain and register durable kinds explicitly. Contract and
artifact documentation can be generated from canonical registries. Some compatibility adapters
remain temporarily verbose, but they cannot define new public behavior.
