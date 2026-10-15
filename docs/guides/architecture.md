# Architecture

Linear Spanks v2 uses a one-way dependency structure: CLI adapters call domain operations; domains
consume immutable contracts and core primitives. Compatibility code exists only at the edge for v1
characterization and decoders.

## Components and sources of truth

```mermaid
flowchart TB
    Registry[command-registry.v2.json] --> ContractSet[Immutable ContractSet]
    Index[contract-set.v2.json + digests] --> ContractSet
    Contracts[Workflow, routing, review, runtime contracts] --> ContractSet
    Codecs[Artifact codec registry] --> Domains[Typed domains]
    ContractSet --> Domains
    Core[Errors, types, hashing, JSON I/O] --> ContractSet
    Core --> Domains
    Domains --> CLI[Namespaced JSON-first CLI]
    Registry --> Docs[Generated command catalog]
    Codecs --> Schemas[Generated artifact reference]
    CLI --> Linear[Linear workflow adapter]
```

The command registry owns path, tier, access, approval text, profiles, templates, transitions, and
legacy mappings. The contract-set index owns the exact validated contract snapshot. It is loaded
once into an immutable, injectable `ContractSet`; command compilation carries bounded policy
slices plus source/digest pointers instead of copying whole policy documents into every envelope.
The load boundary runs exhaustive characterized semantic validators against the injected in-memory
collection, so a digest-valid policy cannot weaken workflow safety literals or cross-contract
requirements. Domain calls reuse that validated snapshot without repeated file reads. The codec
registry owns durable artifact kinds and migration rules.

`compat/v1_runtime.py` is only a parser and diagnostic edge for frozen characterization. The
versioned workflow validators it calls live in owned domain modules; typed public facades and new
behavior do not depend on the compatibility edge. Effective milestone orchestration is composed
from the indexed project role, task-loop, verification-ledger, handoff, and capability policies.

## Command compilation and execution envelope

```mermaid
flowchart LR
    Input[namespace command + options] --> Lookup[Typed CommandSpec lookup]
    Lookup --> Mode{milestone run mode}
    Mode -->|step| Step[Single-stage runtime contract]
    Mode -->|loop| Loop[Receipt-backed loop contract]
    Step --> Compile[Compile assurance, context, references, writes]
    Loop --> Compile
    Compile --> Envelope[ExecutionEnvelope]
    Envelope --> Result[CliResult schema v2]
    Result --> JSON[JSON default]
    Result --> Text[Text adapter]
```

Loop-only flags are validated before compilation. Removed flat commands stop at lookup and return
their exact replacement.

## Orchestration topology

```mermaid
flowchart TB
    Project[Project orchestrator] --> M1[Milestone orchestrator A]
    Project --> M2[Milestone orchestrator B]
    M1 --> E1[Task executor]
    M1 --> V1[Independent task verifier]
    M1 --> E2[Task executor]
    M1 --> V2[Independent task verifier]
    E1 --> Receipt1[Completion handoff]
    V1 --> Ledger1[Verification ledger]
    Receipt1 --> M1
    Ledger1 --> M1
    M1 --> ProjectReceipt[Durable project receipt]
    M2 --> ProjectReceipt
```

Role capability allowlists, bounded handoffs, and receipt bindings survive fresh sessions. Linear
writes, approval, lifecycle transitions, and integration remain coordinator-owned.

The architectural decision and rejected schema-engine alternative are recorded in
[ADR 0001](../architecture/adr-0001-typed-domain-modules.md).
