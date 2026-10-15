"""Dependency graph and parallel-wave domain."""

from __future__ import annotations

from typing import Any

from ..core.legacy_constants import DEPENDENCY_GRAPH_MARKER_RE
from . import _graphs_v1 as legacy
from ._validation import checked
from .embedded_json import parse_embedded_object


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    if type(payload.get("schema_version")) is not int:
        raise ValueError("dependency graph schema_version must be an integer")
    return legacy.validate_dependency_graph(payload)


def _parse(text: str) -> dict[str, Any]:
    matches = DEPENDENCY_GRAPH_MARKER_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one dependency graph marker, found {len(matches)}")
    payload = parse_embedded_object(matches[0], "dependency graph marker")
    return _validate(payload)


def build(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.build_dependency_graph, payload)


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(_validate, payload)


def render(payload: dict[str, Any]) -> str:
    checked(_validate, payload)
    return checked(legacy.render_dependency_graph, payload)


def parse(text: str) -> dict[str, Any]:
    return checked(_parse, text)


def upsert(description: str, graph: dict[str, Any]) -> str:
    checked(_validate, graph)
    return checked(legacy.upsert_dependency_graph, description, graph)


def select_wave(payload: dict[str, Any], max_parallel: int, capacity: int) -> dict[str, Any]:
    return checked(legacy.select_parallel_wave, payload, max_parallel, capacity)


def validate_wave_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return checked(legacy.validate_wave_receipt, payload)
