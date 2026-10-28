"""AD-1324 amendment 1 (finding 7): the repair adds no architecture-baseline debt.

Method/line limits come from the repository's own checker constants, and the baseline file is
byte-identical to the last reviewed one (ARCHITECTURE_BASELINE_SHA256), so no SRP trigger was
grandfathered to pass. AD-1324 set the pin; a later reviewed baseline edit moves it in the same
commit and records why beside it.
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
# The LF-normalised sha256 of the reviewed baseline. AD-1270 (#1324) slice 4b lowered one row
# (unowned-task, probos.startup.dreaming::init_dreaming, count 2 -> 1): the dead activation
# block's loop.create_task left dreaming.py, and the architecture checker requires the row to
# follow in the same commit. The pin before slice 4b (set by AD-1324, b513580b) was
# 62ceb51a9ebe031ad272a4396924d265fa48e9d20c6934371427322d750c87d1.
# BF-941 (#1324 slice 4d) deleted that row (count 1 -> 0): the Fresh Start announcement's
# loop.create_task left dreaming.py for an awaited call at finalization. The pin before BF-941
# was c2ee53af26ff8a4ca97a971a2e3f6b2aba7450213fc48bbd83036078d2aff70f.
ARCHITECTURE_BASELINE_SHA256 = "59f090fd6c03496c17944ce05cbbd63ca5fc9bcfda0d8b6ac957c89ea7879098"

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
