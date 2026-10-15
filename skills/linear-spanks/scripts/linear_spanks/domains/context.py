"""Bounded context measurement and repository checkpoint validation."""

from __future__ import annotations

# Context state is carried by the coordinator, never restored from a local cache.
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, NamedTuple, NoReturn, Protocol

from ..core.errors import GovernedStop, UsageError
from ..core.hashing import canonical_json_bytes, sha256_digest
from . import _context_v1 as legacy
from . import _routing_v1 as routing_legacy
from ._validation import checked


def validate_usage(
    command: str,
    estimated_tokens: int,
    metrics: list[str],
    scope: str = "command",
    scan_tier: str | None = None,
) -> dict[str, Any]:
    return checked(
        routing_legacy.validate_context_usage,
        command,
        estimated_tokens,
        metrics,
        scope,
        scan_tier,
    )


def measure_packet(
    command: str,
    payload: dict[str, Any],
    scope: str = "command",
    scan_tier: str | None = None,
) -> dict[str, Any]:
    return checked(legacy.measure_context_packet, command, payload, scope, scan_tier)


def validate_checkpoint(
    payload: dict[str, Any],
    expected_source_revision: str | None = None,
    drift_classification: str | None = None,
) -> dict[str, Any]:
    return checked(
        legacy.validate_repository_checkpoint,
        payload,
        expected_source_revision,
        None,
        drift_classification,
    )


SCOPES = ("project", "milestone", "task")
ACTIVE_TOKEN_LIMITS = frozenset(
    {"max_input_tokens", "max_active_context_tokens", "max_capsule_tokens"}
)
# Compaction thresholds are the smaller of a share of the effective budget and an absolute cap.
# Percentages alone would scale durable snapshots with every raised ceiling, so a large budget
# would silently stop compacting; the absolute caps keep persisted history small regardless.
COMPACTION_SUGGEST_PERCENT = 70
COMPACTION_TARGET_PERCENT = 50
COMPACTION_SUGGEST_MAX_TOKENS = 21000
COMPACTION_TARGET_MAX_TOKENS = 15000
COMPACTION_HISTORY_TOKENS = 4000
COMPACTION_EVENTS_SINCE_CHECKPOINT = 3


def compaction_suggest_threshold(limit: int) -> int:
    return min(limit * COMPACTION_SUGGEST_PERCENT // 100, COMPACTION_SUGGEST_MAX_TOKENS)


def compaction_target(limit: int) -> int:
    return min(limit * COMPACTION_TARGET_PERCENT // 100, COMPACTION_TARGET_MAX_TOKENS)


def integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise UsageError("INVALID_CONTEXT_VALUE", f"{field} must be an integer >= {minimum}")
    return value


def stop(code: str, evidence: Any, action: str) -> NoReturn:
    raise GovernedStop(code, str(evidence), details={"evidence": evidence, "next_action": action})


def scope_key(scope: str, target: str, project_id: str) -> str:
    if scope not in SCOPES or not target or not project_id:
        raise UsageError("INVALID_CONTEXT_SCOPE", "Resolve project and exact scope IDs first")
    if scope == "project" and target != project_id:
        raise UsageError("INVALID_CONTEXT_SCOPE", "Project target must equal project_id")
    return f"context/{project_id}/{scope}/{target}"


@dataclass(frozen=True)
class EffectiveBudget:
    tokens: int | None
    source: str
    binding: str
    revisions: tuple[tuple[str, int], ...]
    runtime: Mapping[str, Any]
    ancestry: Mapping[str, str]

    def ceiling(self, default: int) -> int:
        return max(default, self.tokens or 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "source": self.source,
            "hash": self.binding,
            "revisions": dict(self.revisions),
            "runtime": dict(self.runtime),
            "ancestry": dict(self.ancestry),
        }


_DEFAULT = EffectiveBudget(None, "built-in", sha256_digest([]), (), {}, {})
_BUDGET: ContextVar[EffectiveBudget] = ContextVar("context_budget", default=_DEFAULT)


def validate_policy(payload: dict[str, Any]) -> dict[str, Any]:
    expected = {"kind", "schema_version", "scope", "target", "project_id", "revision", "tokens"}
    if (
        set(payload) != expected
        or payload["kind"] != "ContextBudgetPolicy"
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
    ):
        raise UsageError("INVALID_CONTEXT_POLICY", "ContextBudgetPolicy fields/version are invalid")
    scope_key(payload["scope"], payload["target"], payload["project_id"])
    integer(payload["revision"], "revision", minimum=1)
    if payload["tokens"] is not None:
        integer(payload["tokens"], "tokens", minimum=1)
    return payload


def resolve_budget(payload: dict[str, Any]) -> EffectiveBudget:
    """Resolve only policies whose exact IDs match the coordinator's refreshed ancestry."""
    ancestry = payload["ancestry"]
    if not isinstance(ancestry, dict) or not ancestry.get("project") or set(ancestry) - set(SCOPES):
        raise UsageError("INVALID_CONTEXT_SCOPE", "Ancestry requires a resolved project")
    policies = payload.get("policies", [])
    selected: dict[str, dict[str, Any]] = {}
    for policy in policies:
        validate_policy(policy)
        scope = policy["scope"]
        if policy["project_id"] != ancestry["project"] or policy["target"] != ancestry.get(scope):
            stop("CONTEXT_POLICY_DRIFT", policy, "Refresh scope ancestry and policies")
        if scope in selected:
            stop("CONTEXT_POLICY_CONFLICT", scope, "Reconcile duplicate policy documents")
        selected[scope] = policy
    runtime = payload.get("runtime", {})
    if runtime:
        if set(runtime) != {"model", "harness", "input_capacity", "reserved_tokens", "source"}:
            raise UsageError("INVALID_RUNTIME_CAPACITY", "Runtime capacity evidence is incomplete")
        for field in ("model", "harness", "source"):
            if not isinstance(runtime[field], str) or not runtime[field]:
                raise UsageError("INVALID_RUNTIME_CAPACITY", f"Missing runtime {field}")
        integer(runtime["reserved_tokens"], "reserved_tokens")
        if runtime["input_capacity"] is not None:
            integer(runtime["input_capacity"], "input_capacity", minimum=1)
    ordered = [selected[s] for s in SCOPES if s in selected]
    chosen = next((p for p in reversed(ordered) if p["tokens"] is not None), None)
    return EffectiveBudget(
        chosen["tokens"] if chosen else None,
        chosen["scope"] if chosen else "built-in",
        sha256_digest({"ancestry": ancestry, "policies": ordered}),
        tuple((p["scope"], p["revision"]) for p in ordered),
        runtime,
        ancestry,
    )


@contextmanager
def budget_session(payload: dict[str, Any] | None) -> Iterator[EffectiveBudget]:
    effective = resolve_budget(payload) if payload is not None else _DEFAULT
    token = _BUDGET.set(effective)
    try:
        yield effective
    finally:
        _BUDGET.reset(token)


def effective_limit(default: int) -> int:
    return _BUDGET.get().ceiling(default)


def effective_limits(defaults: Mapping[str, Any]) -> dict[str, Any]:
    return {k: effective_limit(v) if k in ACTIVE_TOKEN_LIMITS else v for k, v in defaults.items()}


def check_capacity(tokens: int) -> None:
    runtime = _BUDGET.get().runtime
    if runtime.get("input_capacity") is not None:
        available = runtime["input_capacity"] - runtime["reserved_tokens"]
        if tokens > available:
            stop(
                "RUNTIME_CONTEXT_OVERFLOW",
                {"used": tokens, "available": available, **runtime},
                "Partition context or select an authorized runtime with sufficient input capacity",
            )


def measurement(payload: Any) -> dict[str, Any]:
    encoded = canonical_json_bytes(payload)
    return {
        "bytes": len(encoded),
        "estimated_tokens": (len(encoded) + 3) // 4,
        "hash": sha256_digest(payload),
        "estimate_method": "ceil(utf8_bytes/4)",
        "actual_tokens": None,
    }


def enforce_measurement(payload: Any, default: int, declared: int | None = None) -> dict[str, Any]:
    measured = measurement(payload)
    limit = effective_limit(default)
    if measured["estimated_tokens"] > limit:
        stop(
            "CONTEXT_OVERFLOW",
            {**measured, "limit": limit},
            "Partition required evidence, preview compaction, or request an explicit budget increase",
        )
    if declared is not None and declared != measured["estimated_tokens"]:
        stop(
            "CONTEXT_MEASUREMENT_MISMATCH",
            {"declared": declared, "measured": measured},
            "Recompile the complete serialized packet",
        )
    check_capacity(measured["estimated_tokens"])
    return measured


def compile_packet(payload: dict[str, Any]) -> dict[str, Any]:
    """The body is exactly what is dispatched, including every expanded reference."""
    body = payload["body"]
    required = {"instructions", "skills", "plan", "evidence", "bindings"}
    if not isinstance(body, dict) or set(body) != required:
        raise UsageError(
            "INVALID_CONTEXT_PACKET",
            "Packet requires instructions, skills, plan, evidence, bindings",
        )
    if not isinstance(body["bindings"], dict):
        raise UsageError("INVALID_CONTEXT_PACKET", "Packet bindings must be an object")
    budget = _BUDGET.get()
    bound_body = {**body, "bindings": {**body["bindings"], "context_policy": budget.as_dict()}}
    measured = enforce_measurement(
        bound_body,
        integer(payload["default_tokens"], "default_tokens", minimum=1),
        payload.get("declared_tokens"),
    )
    return {
        "kind": "ContextPacket",
        "schema_version": 1,
        "body": bound_body,
        "measurement": measured,
    }


def validate_packet(payload: dict[str, Any]) -> dict[str, Any]:
    packet = payload["packet"]
    if packet.get("kind") != "ContextPacket" or packet.get("schema_version") != 1:
        raise UsageError("INVALID_CONTEXT_PACKET", "Unsupported packet")
    if packet["body"]["bindings"].get("context_policy") != _BUDGET.get().as_dict():
        stop(
            "CONTEXT_POLICY_DRIFT",
            packet["body"]["bindings"],
            "Recompile before dispatch; retain factual evidence",
        )
    measured = enforce_measurement(packet["body"], payload["default_tokens"])
    if packet["measurement"] != measured:
        stop(
            "CONTEXT_MEASUREMENT_MISMATCH",
            packet["measurement"],
            "Recompile the complete serialized packet",
        )
    return {"status": "valid", "measurement": measured, "policy": _BUDGET.get().as_dict()}


class DocumentStore(Protocol):
    """Coordinator adapter: project-scoped Linear Documents, fresh reads and atomic revision guards.

    put must reject a changed revision. For providers without conditional writes, the
    coordinator serializes this scope and performs a second fresh read before mutation.
    """

    def read(self, key: str) -> dict[str, Any] | None: ...

    def put(self, key: str, value: dict[str, Any], expected_hash: str) -> None: ...


def write_read_back(store: DocumentStore, key: str, value: dict[str, Any], previous: Any) -> None:
    current = store.read(key)
    if current == value:
        return
    if current != previous:
        stop("CONTEXT_SOURCE_DRIFT", key, "Refresh the preview and approval binding")
    store.put(key, value, sha256_digest(previous))
    if store.read(key) != value:
        stop(
            "CONTEXT_READ_BACK_FAILED",
            key,
            "Read the exact document and resume the same operation idempotently",
        )


def budget_update(store: DocumentStore, payload: dict[str, Any]) -> dict[str, Any]:
    scope, target, project = payload["scope"], payload["target"], payload["ancestry"]["project"]
    key = scope_key(scope, target, project) + "/budget"
    if payload["ancestry"].get(scope) != target:
        raise UsageError("INVALID_CONTEXT_SCOPE", "Target must match refreshed ancestry")
    reset = payload.get("reset", False)
    if not isinstance(reset, bool) or (reset and payload.get("tokens") is not None):
        raise UsageError("INVALID_CONTEXT_VALUE", "Choose tokens or reset")
    tokens = None if reset else integer(payload.get("tokens"), "tokens", minimum=1)
    authorization = {"scope": scope, "target": target, "tokens": tokens, "reset": reset}
    if payload.get("authorization") != authorization:
        stop(
            "APPROVAL_REQUIRED",
            authorization,
            "Obtain explicit invocation or approval for exactly this update",
        )
    policies = []
    previous_documents: dict[str, Any] = {}
    for level in SCOPES:
        if level in payload["ancestry"]:
            policy_key = scope_key(level, payload["ancestry"][level], project) + "/budget"
            value = store.read(policy_key)
            previous_documents[policy_key] = value
            if value is not None:
                policies.append(value)
    binding = {"ancestry": payload["ancestry"], "policies": policies}
    effective = resolve_budget(binding)
    if payload["expected_policy_hash"] != effective.binding:
        stop(
            "CONTEXT_POLICY_DRIFT",
            effective.as_dict(),
            "Refresh policies and recompile the specified operation",
        )
    current = next((p for p in policies if p["scope"] == scope), None)
    if (current is None and reset) or (current is not None and current["tokens"] == tokens):
        return {"status": "unchanged", "policy": current, "binding": effective.as_dict()}
    if tokens is not None and tokens <= effective.ceiling(payload["default_tokens"]):
        stop(
            "CONTEXT_BUDGET_DECREASE",
            tokens,
            "Use --reset to restore inheritance; --tokens only increases the effective allowance",
        )
    policy = {
        "kind": "ContextBudgetPolicy",
        "schema_version": 1,
        "scope": scope,
        "target": target,
        "project_id": project,
        "revision": current["revision"] + 1 if current else 1,
        "tokens": tokens,
    }
    validate_policy(policy)
    receipt = {
        "operation": authorization,
        "previous_policy_hash": effective.binding,
        "policy": policy,
    }
    operation_id = sha256_digest(receipt)
    # Receipt precedes the policy so an interrupted operation remains discoverable.
    receipt_key = key + "/operations/" + operation_id
    write_read_back(store, receipt_key, receipt, None)
    # Refresh all ancestors again: a concurrent ancestor update changes raise-only semantics.
    for old_key, old in previous_documents.items():
        if store.read(old_key) != old:
            stop("CONTEXT_POLICY_DRIFT", old_key, "Refresh policies and recompile the operation")
    write_read_back(store, key, policy, current)
    return {"status": "persisted", "policy": policy, "operation_id": operation_id, "read_back": key}


def inspect_context(payload: dict[str, Any]) -> dict[str, Any]:
    measured = measurement(payload.get("body", {}))
    default = integer(payload["default_tokens"], "default_tokens", minimum=1)
    effective = _BUDGET.get()
    limit = effective.ceiling(default)
    history = integer(payload.get("history_tokens", 0), "history_tokens")
    events = integer(payload.get("events_since_checkpoint", 0), "events_since_checkpoint")
    suggest_at = compaction_suggest_threshold(limit)
    trigger = (
        measured["estimated_tokens"] >= suggest_at
        or history > COMPACTION_HISTORY_TOKENS
        or events >= COMPACTION_EVENTS_SINCE_CHECKPOINT
    )
    suggestion = sha256_digest({"sources": payload.get("sources", {}), "policy": effective.binding})
    declined = payload.get("declined_hash") == suggestion
    capacity = effective.runtime.get("input_capacity")
    available = None if capacity is None else capacity - effective.runtime["reserved_tokens"]
    limits = effective_limits({"max_input_tokens": default, **payload.get("limits", {})})
    usage = {**payload.get("usage", {}), "max_input_tokens": measured["estimated_tokens"]}
    blockers = [k for k, v in limits.items() if usage.get(k, 0) > v]
    if available is not None and measured["estimated_tokens"] > available:
        blockers.append("runtime_input_capacity")
    return {
        "scope": payload.get("scope"),
        "target": payload.get("target"),
        "configured": effective.tokens,
        "effective_tokens": limit,
        "inheritance": effective.source,
        "policy": effective.as_dict(),
        "measurement": measured,
        "headroom_tokens": limit - measured["estimated_tokens"],
        "runtime_capacity": "unknown" if available is None else available,
        "runtime_headroom": None if available is None else available - measured["estimated_tokens"],
        "compaction": {
            "suggested": trigger and not declined,
            "declined": declined,
            "suggestion_hash": suggestion,
            "suggest_at_tokens": suggest_at,
            "target_tokens": compaction_target(limit),
        },
        "blocking_limits": blockers,
    }


FACT_FIELDS = frozenset(
    {
        "ids",
        "revisions",
        "requirements",
        "constraints",
        "dependencies",
        "approvals",
        "commits",
        "verification",
        "findings",
        "acceptance",
        "next_action",
        "plan_binding",
    }
)


def retained_facts(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Retain conflicting values and their provenance; narrative never changes state."""
    facts: dict[str, Any] = {}
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source.get("id"), str) or not source["id"] or source["id"] in source_ids:
            raise UsageError(
                "INVALID_CONTEXT_SOURCE", "Source IDs must be unique nonempty document references"
            )
        integer(source["revision"], "source revision", minimum=1)
        source_ids.add(source["id"])
        if set(source) != {"id", "revision", "hash", "facts", "narrative"}:
            raise UsageError(
                "INVALID_CONTEXT_SOURCE", "Source requires ID, revision, hash, facts and narrative"
            )
        if source["hash"] != sha256_digest(
            {"facts": source["facts"], "narrative": source["narrative"]}
        ):
            stop("CONTEXT_SOURCE_DRIFT", source["id"], "Refresh original source content")
        if not isinstance(source["facts"], dict) or set(source["facts"]) != FACT_FIELDS:
            raise UsageError(
                "INVALID_CONTEXT_SOURCE",
                "Authoritative source facts must contain every required field",
            )
        for field, value in source["facts"].items():
            facts.setdefault(field, []).append(
                {"source": source["id"], "revision": source["revision"], "value": value}
            )
    return facts


def validate_context_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "ContextSnapshot": {"facts", "narrative", "sources", "policy_hash", "manifest"},
        "ContextDelta": {"changes", "evidence", "previous_hash", "policy_hash"},
        "ContextManifest": {"entries", "next_page"},
        "CompactionReceipt": {
            "preview_hash",
            "snapshot_hash",
            "previous_active",
            "source_hash",
            "policy_hash",
        },
    }
    kind = payload.get("kind")
    if kind == "ContextBudgetPolicy":
        return validate_policy(payload)
    common = {"kind", "schema_version", "scope", "target", "project_id", "revision"}
    if (
        kind not in fields
        or set(payload) != common | fields[kind]
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
    ):
        raise UsageError("INVALID_CONTEXT_ARTIFACT", "Context artifact fields/version are invalid")
    scope_key(payload["scope"], payload["target"], payload["project_id"])
    integer(payload["revision"], "revision", minimum=1)
    from ..contracts.legacy import project_epoch_contract

    byte_limit = project_epoch_contract()["capsule"]["max_body_bytes"]
    size = measurement(payload)["bytes"]
    if size > byte_limit:
        stop(
            "CONTEXT_OVERFLOW",
            {"max_capsule_bytes": byte_limit, "used_bytes": size},
            "Partition the document; token increases cannot raise capsule byte limits",
        )
    if kind == "ContextManifest":
        if not isinstance(payload["entries"], list) or len(payload["entries"]) > 50:
            stop(
                "CONTEXT_OVERFLOW",
                "manifest page exceeds 50 entries",
                "Paginate original source references",
            )
    elif kind == "ContextSnapshot":
        if not isinstance(payload["facts"], dict) or set(payload["facts"]) != FACT_FIELDS:
            raise UsageError("INVALID_CONTEXT_ARTIFACT", "Snapshot facts are incomplete")
    elif kind == "ContextDelta":
        if not isinstance(payload["changes"], dict) or set(payload["changes"]) - FACT_FIELDS:
            raise UsageError(
                "INVALID_CONTEXT_ARTIFACT", "Delta changes must name authoritative fact fields"
            )
        if not payload["evidence"]:
            raise UsageError("INVALID_CONTEXT_ARTIFACT", "Delta changes require source evidence")
    return payload


def checkpoint_preview(payload: dict[str, Any]) -> dict[str, Any]:
    base = {k: payload[k] for k in ("scope", "target", "project_id", "revision")}
    key = scope_key(base["scope"], base["target"], base["project_id"])
    sources = payload["sources"]
    if (
        payload.get("previous_active")
        and base["revision"] <= payload["previous_active"]["revision"]
    ):
        stop(
            "CONTEXT_SOURCE_DRIFT",
            base["revision"],
            "Advance the snapshot revision from the current active reference",
        )
    facts = retained_facts(sources)
    source_bindings = [{k: s[k] for k in ("id", "revision", "hash")} for s in sources]
    # Source references are paginated; only the first page is present in the active reference.
    pages: list[dict[str, Any]] = []
    next_page = payload.get("history_manifest")
    for offset in reversed(range(0, len(source_bindings), 50)):
        page = {
            **base,
            "kind": "ContextManifest",
            "schema_version": 1,
            "entries": source_bindings[offset : offset + 50],
            "next_page": next_page,
        }
        page_key = key + "/manifests/" + sha256_digest(page)
        pages.insert(0, {"key": page_key, "value": page})
        next_page = page_key
    snapshot = {
        **base,
        "kind": "ContextSnapshot",
        "schema_version": 1,
        "facts": facts,
        "narrative": payload["narrative"],
        "sources": sha256_digest(source_bindings),
        "policy_hash": _BUDGET.get().binding,
        "manifest": next_page,
    }
    validate_context_artifact(snapshot)
    measured = enforce_measurement(snapshot, payload["default_tokens"])
    target = compaction_target(effective_limit(payload["default_tokens"]))
    if measured["estimated_tokens"] > target:
        stop(
            "CONTEXT_COMPACTION_TARGET_OVERFLOW",
            measured,
            "Partition required facts; do not omit unresolved evidence",
        )
    before = measurement(sources)
    snapshot_key = key + "/snapshots/" + sha256_digest(snapshot)
    active = {
        "snapshot": snapshot_key,
        "hash": sha256_digest(snapshot),
        "revision": base["revision"],
        "manifest": next_page,
        "delta_head": None,
        "policy_hash": _BUDGET.get().binding,
    }
    receipt = {
        **base,
        "kind": "CompactionReceipt",
        "schema_version": 1,
        "preview_hash": None,
        "snapshot_hash": active["hash"],
        "previous_active": payload.get("previous_active"),
        "source_hash": sha256_digest(source_bindings),
        "policy_hash": _BUDGET.get().binding,
    }
    preview = {
        "snapshot": snapshot,
        "sources": source_bindings,
        "before": before,
        "after": measured,
        "reduction_bytes": before["bytes"] - measured["bytes"],
        "previous_active": payload.get("previous_active"),
        "writes": [*pages, {"key": snapshot_key, "value": snapshot}],
        "active_key": key + "/active",
        "active": active,
        "receipt": receipt,
    }
    preview["preview_hash"] = sha256_digest(preview)
    return preview


def activate_checkpoint(store: DocumentStore, payload: dict[str, Any]) -> dict[str, Any]:
    preview = payload["preview"]
    digest = sha256_digest({k: v for k, v in preview.items() if k != "preview_hash"})
    if preview["preview_hash"] != digest or payload.get("approved_hash") != digest:
        stop("APPROVAL_REQUIRED", digest, "Approve this exact checkpoint preview before activation")
    if preview["snapshot"]["policy_hash"] != _BUDGET.get().binding:
        stop("CONTEXT_POLICY_DRIFT", digest, "Recompile checkpoint and refresh approval")
    current_sources = []
    for source in preview["sources"]:
        current = store.read(source["id"])
        if (
            current is None
            or current.get("revision") != source["revision"]
            or sha256_digest({"facts": current.get("facts"), "narrative": current.get("narrative")})
            != source["hash"]
        ):
            stop("CONTEXT_SOURCE_DRIFT", source, "Refresh original sources and checkpoint approval")
        current_sources.append(
            {**source, "facts": current["facts"], "narrative": current["narrative"]}
        )
    if retained_facts(current_sources) != preview["snapshot"]["facts"]:
        stop(
            "CONTEXT_FACT_DRIFT",
            preview["snapshot"]["facts"],
            "Rebuild deterministic facts from original sources",
        )
    snapshot = preview["snapshot"]
    scope = scope_key(snapshot["scope"], snapshot["target"], snapshot["project_id"])
    snapshot_key = scope + "/snapshots/" + sha256_digest(snapshot)
    if (
        preview["active_key"] != scope + "/active"
        or preview["active"]["snapshot"] != snapshot_key
        or preview["writes"][-1] != {"key": snapshot_key, "value": snapshot}
        or any(not w["key"].startswith(scope + "/manifests/") for w in preview["writes"][:-1])
    ):
        stop(
            "CONTEXT_SOURCE_DRIFT",
            preview["active_key"],
            "Rebuild exact scope-bound checkpoint writes",
        )
    if preview["active"]["hash"] != sha256_digest(preview["snapshot"]):
        stop(
            "CONTEXT_SOURCE_DRIFT",
            preview["active"],
            "Recompile the exact snapshot and active reference",
        )
    current_active = store.read(preview["active_key"])
    if current_active not in (preview["previous_active"], preview["active"]):
        stop("CONTEXT_SOURCE_DRIFT", current_active, "Refresh the active context reference")
    for write in preview["writes"]:
        validate_context_artifact(write["value"])
        write_read_back(store, write["key"], write["value"], None)
    receipt = {**preview["receipt"], "preview_hash": digest}
    receipt_key = preview["active_key"] + "/operations/" + digest
    write_read_back(store, receipt_key, receipt, None)
    write_read_back(store, preview["active_key"], preview["active"], preview["previous_active"])
    return {"status": "active", "receipt": receipt_key, "active": preview["active"]}


def persist_delta(store: DocumentStore, payload: dict[str, Any]) -> dict[str, Any]:
    delta = validate_context_artifact(payload["delta"])
    if delta["kind"] != "ContextDelta" or delta["policy_hash"] != _BUDGET.get().binding:
        stop("CONTEXT_POLICY_DRIFT", delta, "Refresh policy before recording the attempt")
    key = scope_key(delta["scope"], delta["target"], delta["project_id"])
    active = store.read(key + "/active")
    if active is None:
        stop("CONTEXT_SNAPSHOT_REQUIRED", key, "Prepare and approve the first checkpoint")
    delta_hash = sha256_digest(delta)
    delta_key = key + "/deltas/" + delta_hash
    if active["delta_head"] == delta_key:
        return {"status": "unchanged", "evidence": delta_key}
    if delta["previous_hash"] != active["hash"]:
        stop("CONTEXT_SOURCE_DRIFT", active, "Refresh active context before appending a delta")
    if delta["revision"] <= active["revision"]:
        stop("CONTEXT_SOURCE_DRIFT", delta["revision"], "Advance the delta revision")
    for field, values in delta["changes"].items():
        if not isinstance(values, list) or not values:
            raise UsageError(
                "INVALID_CONTEXT_ARTIFACT", "Changed facts require explicit sourced values"
            )
        for fact in values:
            source = store.read(fact["source"])
            if (
                fact["source"] not in delta["evidence"]
                or source is None
                or source.get("revision") != fact["revision"]
                or source.get("facts", {}).get(field) != fact["value"]
            ):
                stop(
                    "CONTEXT_FACT_DRIFT",
                    fact,
                    "Read authoritative verification evidence before changing state",
                )
    enforce_measurement(delta, payload["default_tokens"])
    write_read_back(store, delta_key, delta, None)
    updated = {**active, "delta_head": delta_key, "hash": delta_hash, "revision": delta["revision"]}
    write_read_back(store, key + "/active", updated, active)
    return {
        "status": "persisted",
        "evidence": delta_key,
        "comment": f"Verification changes and evidence: {delta_key}",
    }


def expand_context(store: DocumentStore, payload: dict[str, Any]) -> dict[str, Any]:
    """Read exactly one addressable section, with a caller-declared reason and ceiling."""
    if not payload.get("reason"):
        raise UsageError("INVALID_CONTEXT_EXPANSION", "Evidence expansion requires a reason")
    source = store.read(payload["source"])
    if source is None or payload["section"] not in source:
        stop("CONTEXT_SOURCE_UNAVAILABLE", payload["source"], "Recover the exact source document")
    section = source[payload["section"]]
    measured = measurement(section)
    if measured["bytes"] > integer(payload["max_bytes"], "max_bytes", minimum=1):
        stop("CONTEXT_OVERFLOW", measured, "Request a smaller section or the next manifest page")
    return {
        "source": payload["source"],
        "section": payload["section"],
        "content": section,
        "measurement": measured,
        "reason": payload["reason"],
    }


def repair_action(payload: dict[str, Any]) -> dict[str, Any]:
    attempts = payload["attempts"]
    if not isinstance(attempts, list):
        raise UsageError("INVALID_REPAIR_EVIDENCE", "Attempts must be a list")
    if not attempts:
        return {"next_action": "implement"}
    last = attempts[-1]
    for attempt in attempts:
        if (
            attempt.get("result") not in {"passed", "failed"}
            or not isinstance(attempt.get("acceptance"), dict)
            or not isinstance(attempt.get("fingerprint"), str)
            or not attempt["fingerprint"]
            or not attempt["acceptance"]
            or any(
                state not in {"unverified", "passing", "failing", "regressed"}
                for state in attempt["acceptance"].values()
            )
        ):
            raise UsageError(
                "INVALID_REPAIR_EVIDENCE",
                "Each completed attempt requires a result, failure fingerprint and acceptance states",
            )
    if last["result"] == "passed":
        if any(state != "passing" for state in last["acceptance"].values()):
            raise UsageError(
                "INVALID_REPAIR_EVIDENCE", "A passing attempt requires passing acceptance states"
            )
        return {"next_action": "verified-pending-integration"}
    if last.get("failure_class") == "environment":
        recovery = payload.get("prerequisite_recovery")
        if recovery is not None:
            if (
                not isinstance(recovery, dict)
                or set(recovery) != {"fingerprint", "evidence"}
                or recovery["fingerprint"] != last["fingerprint"]
                or not isinstance(recovery["evidence"], list)
                or not recovery["evidence"]
                or not all(isinstance(ref, str) and ref.strip() for ref in recovery["evidence"])
            ):
                raise UsageError(
                    "INVALID_REPAIR_EVIDENCE",
                    "Prerequisite recovery must cite evidence for this failure",
                )
            return {"next_action": "verify", "evidence": recovery["evidence"]}
        return {"next_action": "prerequisite-recovery", "evidence": last.get("evidence", [])}
    if len(attempts) >= 4:
        return {"next_action": "user-model-selection", "approval_required": True}
    if len(attempts) >= 2:
        previous = attempts[-2]
        previous_passing = {
            key for key, state in previous["acceptance"].items() if state == "passing"
        }
        current_passing = {key for key, state in last["acceptance"].items() if state == "passing"}
        if (
            previous["result"] == "failed"
            and last["result"] == "failed"
            and previous["fingerprint"] == last["fingerprint"]
            and not current_passing > previous_passing
        ):
            binding = sha256_digest(
                {"fingerprint": last["fingerprint"], "acceptance": last["acceptance"]}
            )
            diagnosis = payload.get("diagnosis")
            if diagnosis is not None:
                if (
                    not isinstance(diagnosis, dict)
                    or set(diagnosis)
                    != {"failure_binding", "after_attempt", "new_approach", "new_evidence"}
                    or not isinstance(diagnosis["new_approach"], str)
                    or not isinstance(diagnosis["new_evidence"], list)
                    or not all(
                        isinstance(ref, str) and ref.strip() for ref in diagnosis["new_evidence"]
                    )
                ):
                    raise UsageError(
                        "INVALID_REPAIR_EVIDENCE",
                        "Diagnosis requires its failure binding, attempt count, changed approach and evidence references",
                    )
                after = integer(diagnosis["after_attempt"], "after_attempt", minimum=2)
                if after > len(attempts):
                    raise UsageError(
                        "INVALID_REPAIR_EVIDENCE", "Diagnosis cannot precede its bound failures"
                    )
                if diagnosis["failure_binding"] == binding:
                    if after == len(attempts) and (
                        diagnosis["new_approach"].strip() or diagnosis["new_evidence"]
                    ):
                        return {"next_action": "automatic-repair", "diagnosis_binding": binding}
                    return {
                        "next_action": "blocked",
                        "code": "REPAIR_STALLED",
                        "diagnosis_binding": binding,
                        "recovery": "Supply new evidence or a changed approach; retain consumed attempts",
                    }
            return {
                "next_action": "diagnose",
                "code": "REPAIR_DIAGNOSIS_REQUIRED",
                "diagnosis_binding": binding,
            }
    return {"next_action": "automatic-repair"}


REUSE_BINDINGS = frozenset(
    {"source_hashes", "worktree", "contracts", "toolchain", "dependencies", "selection"}
)


def reuse_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    previous, current = payload["previous"], payload["current"]
    if (previous is not None and set(previous) != REUSE_BINDINGS) or set(current) != REUSE_BINDINGS:
        raise UsageError(
            "INVALID_REUSE_BINDING",
            "Reuse requires source, worktree, contracts, toolchain, dependency and selection bindings",
        )
    changed = sorted(k for k in REUSE_BINDINGS if previous is None or previous[k] != current[k])
    return {
        "reusable": not changed,
        "stale_evidence": changed,
        "binding": sha256_digest(current),
        "required_verification": ["actual-candidate", "integrated-result"],
    }


class _TechnologyRule(NamedTuple):
    """One repository-derivable technology tag and the facts that prove it."""

    tag: str
    names: frozenset[str]
    suffixes: frozenset[str]
    dependencies: frozenset[str]


def _rule(
    tag: str,
    names: tuple[str, ...] = (),
    suffixes: tuple[str, ...] = (),
    dependencies: tuple[str, ...] = (),
) -> _TechnologyRule:
    return _TechnologyRule(tag, frozenset(names), frozenset(suffixes), frozenset(dependencies))


_TECHNOLOGY_RULES: tuple[_TechnologyRule, ...] = (
    _rule("python", ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile"), (".py",)),
    _rule("node", ("package.json",)),
    _rule("typescript", ("tsconfig.json",), (".ts", ".tsx"), ("typescript",)),
    _rule("react", (), (".jsx", ".tsx"), ("react",)),
    _rule("nextjs", ("next.config.js", "next.config.mjs", "next.config.ts"), (), ("next",)),
    _rule("vue", ("vue.config.js",), (".vue",), ("vue",)),
    _rule("tailwind", ("tailwind.config.js", "tailwind.config.ts"), (), ("tailwindcss",)),
    _rule("go", ("go.mod",), (".go",)),
    _rule("rust", ("Cargo.toml",), (".rs",)),
    _rule("swift", ("Package.swift",), (".swift",)),
    _rule("kotlin", ("build.gradle.kts",), (".kt", ".kts")),
    _rule("flutter", ("pubspec.yaml",), (".dart",)),
    _rule("docker", ("Dockerfile", "docker-compose.yml", "docker-compose.yaml")),
    _rule("graphql", (), (".graphql", ".gql"), ("graphql",)),
    _rule("postgres", (), (".sql",), ("pg", "psycopg", "psycopg2", "postgres")),
)

_UI_TECHNOLOGIES = frozenset({"react", "vue", "nextjs", "tailwind", "flutter", "swift"})
_UI_SUFFIXES = frozenset({".css", ".scss", ".html", ".vue", ".jsx", ".tsx"})
_TEST_MARKERS = ("test", "spec")

# Tags that describe the task rather than the repository. A detector cannot observe them, so
# they stay caller-supplied and are reported here so the boundary is explicit.
TASK_SUPPLIED_EVIDENCE = frozenset(
    {
        "observed-failure",
        "refactoring",
        "documentation",
        "performance",
        "structural-change",
        "security-sensitive",
    }
)


def detect_repository_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Derive skill-selection technologies and evidence from repository facts.

    ``select_skills`` decides which execution and technology skills load, so its inputs
    should be observed rather than guessed. This is a pure function over a supplied
    inventory: ``files`` are repository-relative paths and ``dependencies`` are declared
    package names. Every emitted tag carries the paths that proved it.

    Only ``ui`` and ``coverage-required`` are repository-derivable. The remaining catalog
    tags describe the task and are returned in ``task_supplied`` for the caller to decide.
    """

    files = payload["files"]
    if not isinstance(files, list) or any(not isinstance(item, str) for item in files):
        raise UsageError(
            "INVALID_REPOSITORY_INVENTORY", "files must be a list of repository-relative paths"
        )
    dependencies = {str(name).lower() for name in payload.get("dependencies", [])}
    provenance: dict[str, list[str]] = {}

    def prove(tag: str, path: str) -> None:
        entries = provenance.setdefault(tag, [])
        if path not in entries:
            entries.append(path)

    for rule in _TECHNOLOGY_RULES:
        for path in files:
            name = path.rsplit("/", 1)[-1]
            suffix = name[name.rfind(".") :] if "." in name else ""
            if name in rule.names or (suffix and suffix in rule.suffixes):
                prove(rule.tag, path)
        for dependency in sorted(rule.dependencies & dependencies):
            prove(rule.tag, f"dependency:{dependency}")

    technologies = sorted(rule.tag for rule in _TECHNOLOGY_RULES if rule.tag in provenance)

    for path in files:
        name = path.rsplit("/", 1)[-1]
        suffix = name[name.rfind(".") :] if "." in name else ""
        if suffix in _UI_SUFFIXES:
            prove("ui", path)
        lowered = path.lower()
        if any(marker in lowered for marker in _TEST_MARKERS):
            prove("coverage-required", path)
    if _UI_TECHNOLOGIES.intersection(technologies) and "ui" not in provenance:
        for technology in sorted(_UI_TECHNOLOGIES.intersection(technologies)):
            provenance.setdefault("ui", []).extend(provenance[technology])

    evidence = sorted(tag for tag in ("ui", "coverage-required") if tag in provenance)
    result = {
        "technologies": technologies,
        "evidence": evidence,
        "provenance": {tag: sorted(paths) for tag, paths in sorted(provenance.items())},
        "task_supplied": sorted(TASK_SUPPLIED_EVIDENCE),
    }
    return {**result, "binding": sha256_digest(result)}


def select_skills(payload: dict[str, Any]) -> dict[str, Any]:
    selected, conflicts = [], []
    roles, phase, technologies = payload["role"], payload["phase"], set(payload["technologies"])
    seen: dict[str, dict[str, Any]] = {}
    for skill in payload["catalog"]:
        applicable = (
            roles in skill["roles"]
            and phase in skill["phases"]
            and (not skill["technologies"] or technologies.intersection(skill["technologies"]))
            and set(skill["requires"]).issubset(payload["evidence"])
        )
        if not applicable:
            continue
        name = skill["name"]
        if (
            name in seen
            and seen[name]["precedence"] == skill["precedence"]
            and seen[name]["source_hash"] != skill["source_hash"]
        ):
            conflicts.append(name)
        if name not in seen or seen[name]["precedence"] < skill["precedence"]:
            seen[name] = skill
    for _name, skill in sorted(seen.items()):
        selected.append(
            {
                **skill,
                "reason": {
                    "role": roles,
                    "phase": phase,
                    "technologies": sorted(technologies.intersection(skill["technologies"])),
                    "evidence": skill["requires"],
                },
            }
        )
    return {
        "selected": selected,
        "conflicts": sorted(set(conflicts)),
        "hash": sha256_digest(selected),
    }


def load_skills(payload: dict[str, Any]) -> dict[str, Any]:
    selection = select_skills(payload)
    if selection["conflicts"]:
        stop(
            "SKILL_SELECTION_CONFLICT",
            selection["conflicts"],
            "Resolve source precedence before dispatch",
        )
    loaded = dict(payload.get("loaded", {}))
    contents = []
    for skill in selection["selected"]:
        binding = f"{payload['session_id']}:{skill['name']}"
        content = payload["contents"][skill["name"]]
        if sha256_digest(content) != skill["source_hash"]:
            stop(
                "SKILL_SOURCE_DRIFT",
                skill["name"],
                "Refresh skill selection from repository evidence",
            )
        if loaded.get(binding) != skill["source_hash"]:
            contents.append({"name": skill["name"], "content": content})
            loaded[binding] = skill["source_hash"]
    return {"selection": selection, "loaded": loaded, "contents": contents}


def compressor_slot(payload: dict[str, Any]) -> dict[str, Any]:
    retry = integer(payload.get("validation_failures", 0), "validation_failures")
    if retry > 1:
        stop(
            "COMPRESSION_VALIDATION_FAILED", retry, "Partition context or diagnose source conflicts"
        )
    strong = (
        payload["scope"] == "project"
        or payload.get("conflicts")
        or payload.get("ratio", 1) > 4
        or retry == 1
    )
    slot = "strong" if strong else "fast"
    capabilities = payload.get("capabilities", {})
    provider = capabilities.get(slot)
    if not provider:
        return {
            "slot": slot,
            "provider": "active-agent",
            "independent_compressor": False,
            "model_strength_verified": False,
        }
    if provider.get("external") and not (
        provider.get("endpoint") and provider.get("data_sharing_authorized") is True
    ):
        stop(
            "CAPABILITY_UNAVAILABLE", slot, "Configure endpoint and authorize external data sharing"
        )
    return {
        "slot": slot,
        "provider": provider["name"],
        "independent_compressor": True,
        "model_strength_verified": True,
    }


def assemble_context(store: DocumentStore, payload: dict[str, Any]) -> dict[str, Any]:
    key = scope_key(payload["scope"], payload["target"], payload["project_id"])
    active = store.read(key + "/active")
    if active is None:
        stop("CONTEXT_SNAPSHOT_REQUIRED", key, "Prepare and approve an initial checkpoint")
    snapshot = store.read(active["snapshot"])
    if snapshot is None:
        stop(
            "CONTEXT_SOURCE_UNAVAILABLE", active["snapshot"], "Recover preserved snapshot document"
        )
    validate_context_artifact(snapshot)
    changes = []
    digest = active["hash"]
    snapshot_hash = sha256_digest(snapshot)
    seen: set[str] = set()
    while digest != snapshot_hash:
        if digest in seen or len(seen) >= 50:
            stop(
                "CONTEXT_OVERFLOW",
                "delta traversal limit",
                "Checkpoint through bounded resumable source reads",
            )
        seen.add(digest)
        delta = store.read(key + "/deltas/" + digest)
        if delta is None or sha256_digest(delta) != digest:
            stop("CONTEXT_SOURCE_DRIFT", digest, "Recover exact delta document")
        validate_context_artifact(delta)
        changes.append(delta)
        digest = delta["previous_hash"]
    facts = dict(snapshot["facts"])
    for delta in reversed(changes):
        for field, value in delta["changes"].items():
            facts[field] = value
    body = {
        "facts": facts,
        "narrative": snapshot["narrative"],
        "snapshot": active["snapshot"],
        "delta_head": active["delta_head"],
        "manifest": active["manifest"],
        "policy": _BUDGET.get().as_dict(),
    }
    measured = enforce_measurement(body, payload["default_tokens"])
    return {
        "body": body,
        "measurement": measured,
        "historical_artifacts_expanded": len(changes),
        "events_since_checkpoint": len(changes),
    }


class PreparedDocuments:
    """Pure write-plan adapter for CLI; acknowledges no real Linear persistence."""

    def __init__(self, documents: dict[str, Any]) -> None:
        self.documents = dict(documents)
        self.writes: list[dict[str, Any]] = []

    def read(self, key: str) -> dict[str, Any] | None:
        value: dict[str, Any] | None = self.documents.get(key)
        return value

    def put(self, key: str, value: dict[str, Any], expected_hash: str) -> None:
        if sha256_digest(self.read(key)) != expected_hash:
            stop("CONTEXT_SOURCE_DRIFT", key, "Refresh exact source documents")
        self.writes.append(
            {
                "key": key,
                "value": value,
                "expected_hash": expected_hash,
                "required_read_back_hash": sha256_digest(value),
            }
        )
        self.documents[key] = value


def prepare_document_operation(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    store = PreparedDocuments(payload["documents"])
    operations = {
        "budget-prepare": budget_update,
        "activate-prepare": activate_checkpoint,
        "delta-prepare": persist_delta,
        "expand": expand_context,
        "assemble": assemble_context,
    }
    result = operations[operation](store, payload["request"])
    return {
        "status": "prepared" if store.writes else "read-only",
        "projection": result,
        "writes": store.writes,
        "persistence_verified": False,
        "next_action": "Coordinator refreshes each document, applies one write at a time, and verifies each read-back"
        if store.writes
        else None,
    }


def validate_dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    from ..contracts.legacy import project_orchestration_contract
    from ._orchestration_v1 import validate_role_handoff

    handoff = validate_role_handoff(payload["handoff"], payload.get("receipt"))
    role = handoff["role"]
    for scope, target in _BUDGET.get().ancestry.items():
        if handoff.get(scope + "_id") != target:
            stop(
                "CONTEXT_POLICY_DRIFT",
                {"scope": scope, "target": target},
                "Restore policies for the actual handoff ancestry",
            )
    default = project_orchestration_contract()["roles"][role]["max_input_tokens"]
    packet = payload["packet"]
    if packet["body"]["bindings"].get("handoff_hash") != sha256_digest(
        {k: v for k, v in handoff.items() if k != "context_tokens"}
    ):
        stop("ROLE_HANDOFF_DRIFT", handoff["handoff_id"], "Recompile packet for the exact handoff")
    if handoff["schema_version"] == 2:
        from .runtime import task_next

        workflow = task_next(payload["workflow"])
        if (
            not workflow["dispatch_ready"]
            or workflow["task_id"] != handoff["task_id"]
            or workflow["candidate_commit"] != handoff["repository_head"]
            or workflow["roles"]["executor" if role == "task-executor" else "verifier"]
            != handoff["logical_role_id"]
            or workflow["bindings"] is None
            or payload["workflow"]["plan_drift"]["current"]["plan_revision"]
            != handoff["plan_revision"]
            or workflow["workflow_hash"] != handoff["workflow_hash"]
            or workflow["execution_policy"] != handoff["execution_policy"]
            or packet["body"]["bindings"].get("task_workflow") != sha256_digest(payload["workflow"])
        ):
            stop(
                "TASK_WORKFLOW_DRIFT",
                handoff["handoff_id"],
                "Refresh task evidence and recompile before dispatch",
            )
        if role == "task-verifier" and workflow["next_action"] != "verify":
            stop("TASK_WORKFLOW_DRIFT", workflow, "Dispatch review only after a candidate is ready")
        if (
            role == "task-executor"
            and workflow["next_action"] == "verify"
            and workflow["execution_policy"]["review"]["required"]
        ):
            stop("TASK_WORKFLOW_DRIFT", workflow, "Dispatch the required independent reviewer")
        if payload.get("receipt") is not None and workflow["next_action"] in {
            "implement",
            "automatic-repair",
            "verify",
        }:
            task_loop = next(
                item
                for item in payload["receipt"]["task_loops"]
                if item["task_id"] == handoff["task_id"]
            )
            if task_loop["attempt_index"] != len(payload["workflow"]["progress"]["attempts"]):
                stop(
                    "TASK_PROGRESS_DRIFT",
                    task_loop,
                    "Restore consumed attempts from the durable task loop before dispatch",
                )
    result = validate_packet({"packet": packet, "default_tokens": default})
    if handoff["context_tokens"] != result["measurement"]["estimated_tokens"]:
        stop(
            "CONTEXT_MEASUREMENT_MISMATCH",
            handoff["context_tokens"],
            "Bind measured token estimate to the handoff",
        )
    return {**result, "handoff_id": handoff["handoff_id"], "role": role}


def bind_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(envelope)
    result["context"] = effective_limits(result["context"])
    for section in ("repository_scan", "orchestration"):
        if isinstance(result.get(section), dict):
            value = dict(result[section])
            if isinstance(value.get("context"), dict):
                value["context"] = effective_limits(value["context"])
            if isinstance(value.get("planner"), dict) and "context" in value["planner"]:
                value["planner"] = {
                    **value["planner"],
                    "context": effective_limits(value["planner"]["context"]),
                }
            result[section] = value
    result["context_policy"] = _BUDGET.get().as_dict()
    return result
