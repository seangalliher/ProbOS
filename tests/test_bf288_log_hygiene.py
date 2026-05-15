"""BF-288: Avatar telemetry warning throttle + analyze empty-content classification.

Two log-hygiene regressions caught from a warm-restart log capture on
2026-05-15:

1. ``AD-722 telemetry: insufficient_trust_history for agent=...; field=trust_delta``
   fired ~4/sec/agent (HIGH sampling tier) — 60+ WARNING/sec across the crew
   for the persistent "agent has no trust history yet" degraded state.
2. ``AD-632c: JSON parse failure, content:`` logged "content:" with nothing
   after it — the underlying LLM returned an empty string. Logging it as
   a parse failure (with empty content payload) was misleading: the root
   cause is an LLM-side empty completion, not a JSON-shape issue.

Tests guard both behaviors against future regression.
"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

import pytest


def test_bf288_avatar_warn_throttles_repeated_identical_reasons(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.avatars import telemetry as t

    # Clean slate.
    t._warn_last_emitted.clear()

    caplog.set_level(logging.WARNING, logger="probos.avatars.telemetry")
    t._warn("insufficient_trust_history", "agent-1", "trust_delta")
    t._warn("insufficient_trust_history", "agent-1", "trust_delta")
    t._warn("insufficient_trust_history", "agent-1", "trust_delta")

    # Only the first should reach WARNING. Subsequent two go to DEBUG.
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and r.name == "probos.avatars.telemetry"
    ]
    assert len(warnings) == 1, (
        f"Expected 1 throttled WARNING; got {len(warnings)}: "
        f"{[r.getMessage() for r in warnings]}"
    )


def test_bf288_avatar_warn_emits_per_distinct_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.avatars import telemetry as t

    t._warn_last_emitted.clear()
    caplog.set_level(logging.WARNING, logger="probos.avatars.telemetry")

    # Different agents — should NOT throttle each other.
    t._warn("insufficient_trust_history", "agent-1", "trust_delta")
    t._warn("insufficient_trust_history", "agent-2", "trust_delta")
    # Different reason on agent-1 — should NOT throttle.
    t._warn("dsl_not_persisted", "agent-1", "dsl_summary")

    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and r.name == "probos.avatars.telemetry"
    ]
    assert len(warnings) == 3, (
        f"Three distinct keys must produce three WARNINGs; got {len(warnings)}"
    )


def test_bf288_avatar_warn_throttle_window_expires() -> None:
    from probos.avatars import telemetry as t

    t._warn_last_emitted.clear()
    key = ("insufficient_trust_history", "agent-1", "trust_delta")

    # First emit registers timestamp.
    t._warn(*key)
    first_ts = t._warn_last_emitted[key]
    assert first_ts > 0

    # Roll the clock back to simulate window expiry.
    t._warn_last_emitted[key] = first_ts - (t._WARN_THROTTLE_S + 1.0)

    t._warn(*key)
    # New timestamp must be more recent than the rolled-back one.
    assert t._warn_last_emitted[key] > first_ts - (t._WARN_THROTTLE_S + 1.0)


def test_bf288_analyze_empty_content_distinguished_from_parse_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Empty LLM completion must log as "LLM returned empty content", not as
    a JSON parse failure with an empty payload."""
    import inspect

    from probos.cognitive.sub_tasks import analyze as analyze_module

    # Source-level contract — guard against silent reversion.
    src = inspect.getsource(analyze_module.AnalyzeHandler.__call__)
    assert "LLM returned empty content" in src, (
        "Empty-content branch must log via the dedicated empty-content "
        "WARNING (see BF-288)."
    )
    assert "if not content.strip():" in src, (
        "Empty-content branch must be reached via `if not content.strip():` "
        "(see BF-288)."
    )


def test_bf288_analyze_parse_failure_path_preserved() -> None:
    """Non-empty content with malformed JSON must still log via the original
    parse-failure WARNING (the truncated-content variant), not the
    empty-content variant."""
    import inspect

    from probos.cognitive.sub_tasks import analyze as analyze_module

    src = inspect.getsource(analyze_module.AnalyzeHandler.__call__)
    assert "JSON parse failure, content: %s" in src, (
        "Non-empty parse-failure WARNING must be preserved alongside the "
        "BF-288 empty-content branch."
    )
