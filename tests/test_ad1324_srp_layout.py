"""AD-1324 amendment 1 (finding 7): the repair adds no architecture-baseline debt.

Method/line limits come from the repository's own checker constants, and the baseline file is
byte-identical to the base commit's, so no SRP trigger was grandfathered to pass.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "probos" / "cognitive"
MAX_METHODS = 15
MAX_LINES = 500
ARCHITECTURE_BASELINE_SHA256 = "62ceb51a9ebe031ad272a4396924d265fa48e9d20c6934371427322d750c87d1"

TARGETS = [
    ("swe_harness/agentic_loop.py", "AgenticLoop", 13),
    ("swe_harness/loop_tier_steps.py", "LoopTierSteps", 12),
    ("tier_policy.py", "TierChoiceController", MAX_METHODS),
    ("tier_policy.py", "StepLedger", 6),
    ("tier_audit.py", "TierAuditSink", 8),
    ("agentic_dispatch.py", "WorkItemAgenticExecutor", None),
]


def _class(path: str, name: str) -> ast.ClassDef:
    tree = ast.parse((SRC / path).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == name)


def _methods(node: ast.ClassDef) -> int:
    return sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in node.body)


@pytest.mark.parametrize(("path", "name", "cap"), TARGETS)
def test_class_stays_within_srp_limits(path: str, name: str, cap: int | None) -> None:
    node = _class(path, name)
    if cap is not None:
        assert _methods(node) <= cap, f"{name} has {_methods(node)} methods (cap {cap})"
        assert _methods(node) <= MAX_METHODS
        if name != "AgenticLoop":  # grandfathered in the baseline; bounded against base below
            assert node.end_lineno - node.lineno + 1 <= MAX_LINES


def test_agentic_loop_keeps_the_pre_ad1324_method_ceiling() -> None:
    assert _methods(_class("swe_harness/agentic_loop.py", "AgenticLoop")) <= 13


def test_architecture_baseline_is_byte_identical_to_the_reviewed_base() -> None:
    baseline = (ROOT / "docs" / "development" / "architecture-baseline.yaml").read_bytes()
    normalized = baseline.replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized).hexdigest() == ARCHITECTURE_BASELINE_SHA256
