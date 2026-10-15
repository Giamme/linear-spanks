"""Constants shared by v1 artifact decoders and owned v2 domains."""

from __future__ import annotations

import re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[3]
COMMANDS_PATH = SKILL_ROOT / "commands.json"
WORKFLOW_PATH = SKILL_ROOT / "workflow-contract.json"
ISSUE_WORKFLOW_PATH = SKILL_ROOT / "issue-workflow-contract.json"
EXECUTION_PATH = SKILL_ROOT / "execution-contract.json"
ROUTING_PATH = SKILL_ROOT / "routing-contract.json"
REPOSITORY_SCAN_PATH = SKILL_ROOT / "repository-scan-contract.json"
PROJECT_EPOCH_PATH = SKILL_ROOT / "project-epoch-contract.json"
PARALLEL_EXECUTION_PATH = SKILL_ROOT / "parallel-execution-contract.json"
PROJECT_ORCHESTRATION_PATH = SKILL_ROOT / "project-orchestration-contract.json"
MILESTONE_ORCHESTRATION_PATH = SKILL_ROOT / "milestone-orchestration-contract.json"
HUMAN_VERIFICATION_PATH = SKILL_ROOT / "human-verification-contract.json"
MILESTONE_REVIEW_PATH = SKILL_ROOT / "milestone-review-contract.json"
MILESTONE_RUNTIME_PATH = SKILL_ROOT / "milestone-runtime-contract.json"
MARKER_RE = re.compile(r"<!--\s*linear-spanks:state\s+(\{.*?\})\s*-->", re.DOTALL)
DEPENDENCY_GRAPH_MARKER_RE = re.compile(
    r"<!--\s*linear-spanks:dependency-graph\s+(\{.*?\})\s*-->", re.DOTALL
)
HUMAN_POLICY_MARKER_RE = re.compile(
    r"<!--\s*linear-spanks:human-verification-policy\s+(\{.*?\})\s*-->", re.DOTALL
)
HUMAN_OVERRIDE_MARKER_RE = re.compile(
    r"<!--\s*linear-spanks:human-verification-override\s+(\{.*?\})\s*-->", re.DOTALL
)
HUMAN_GATE_MARKER_RE = re.compile(
    r"<!--\s*linear-spanks:human-verification-gate\s+(\{.*?\})\s*-->", re.DOTALL
)
HUMAN_CHECKLIST_MARKER_RE = re.compile(
    r"<!--\s*linear-spanks:human-verification-checklist\s+(\{.*?\})\s*-->", re.DOTALL
)
HUMAN_REPAIR_MARKER_RE = re.compile(
    r"<!--\s*linear-spanks:human-verification-repair\s+(\{.*?\})\s*-->", re.DOTALL
)
MILESTONE_RUNTIME_REF_RE = re.compile(
    r"<!--\s*linear-spanks:milestone-runtime-ref\s+(\{.*?\})\s*-->", re.DOTALL
)
APPROVAL_KINDS = {"none", "preview", "invocation", "per_operation", "conditional", "staged"}
REPOSITORY_SCAN_TIERS = ("fast", "medium", "heavy")
ASSURANCE_VALUES = ("fast", "balanced", "strict")
ASSURANCE_RANK = {name: rank for rank, name in enumerate(ASSURANCE_VALUES)}
ORCHESTRATED_COMMANDS = {
    "refine-task",
    "plan-tasks",
    "plan-task",
    "replan-task",
    "run-task",
    "implement-next",
    "implement-wave",
    "reconcile-wave",
    "verify-task",
    "run-milestone-loop",
}
HARNESS_ALIASES = {
    "antigravity-cli": "antigravity",
    "antigravity-ide": "antigravity",
    "claude-code": "claude",
    "kimi-code": "kimi",
}
ROUTING_HARNESSES = {"codex", "claude", "opencode", "openclaude", "antigravity", "kimi"}
TASK_RUNTIME_COMMANDS = {
    "refine-task",
    "plan-task",
    "plan-tasks",
    "run-task",
    "replan-task",
    "verify-task",
    "implement-next",
    "implement-wave",
    "reconcile-wave",
}
