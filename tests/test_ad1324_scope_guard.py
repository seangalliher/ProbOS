"""AD-1324 amendment 2 (finding 8): scope guards for a pin that once swallowed assertions."""

from __future__ import annotations

import ast
from pathlib import Path

_AD1165 = Path(__file__).with_name("test_ad1165_turn_promotion.py")
_BASE_ASSERT_COUNT = 141  # d811d8a3: the number of assert statements in the AD-1165 test file


def test_ad1165_keeps_every_base_assertion_as_code() -> None:
    text = _AD1165.read_text(encoding="utf-8")
    asserts = sum(isinstance(node, ast.Assert) for node in ast.walk(ast.parse(text)))
    assert asserts >= _BASE_ASSERT_COUNT, "an assertion was commented out, merged into a string or deleted"
    assert "`" + "n" not in text, "a PowerShell newline escape was written literally"