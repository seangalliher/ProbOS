"""AD-722a-5: divergence history surface backend tests.

Covers ring buffer capture in ``apply_divergence_check`` and the new
``GET /api/agent/{agent_id}/avatar-telemetry/divergence-history`` endpoint.

Pattern: ``SimpleNamespace`` runtime stubs (mirrors AD-722a tests). Endpoint
tests use FastAPI ``TestClient`` against ``create_app``.
"""
from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.divergence_detector import (
    DivergenceHistoryEntry,
    DivergenceResult,
    EmotionalIntent,
    apply_divergence_check,
    compute_divergence,
)

# Inherit the OUTPUT-subject regex used by the AD-727 phrasing gate so the
# same regex test covers history-rendered notes too.
from tests.test_ad722a_divergence_detector import _FORBIDDEN_PHRASING_RE


# ── Helpers ─────────────────────────────────────────────────────────────


def _telemetry_cfg(
    *,
    history_size: int = 100,
    aggregate_window: int = 50,
    divergence_detection: bool = True,
    telemetry_enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=telemetry_enabled,
        inject_into_agent_context=False,
        divergence_detection=divergence_detection,
        divergence_negative_threshold=0.3,
        divergence_positive_threshold=0.5,
        divergence_negative_weight=0.4,
        divergence_positive_weight=0.1,
        divergence_history_size=history_size,
        divergence_aggregate_window=aggregate_window,
    )


def _make_agent_with_snap(
    *,
    intent_emotion: str = "warm",
    applied: tuple[str, ...] = ("intent_warm",),
) -> SimpleNamespace:
    """Build an agent with the cached snap apply_divergence_check needs."""
    modulation = SimpleNamespace(fired_rules=applied)
    signals = SimpleNamespace(
        trust_delta=0.0, load=0.0, working_state="idle", tier3_alert=False,
    )
    snap = SimpleNamespace(
        applied_modulation=modulation,
        current_signals=signals,
    )
    return SimpleNamespace(
        id="agent-007",
        _last_self_avatar_snap=snap,
    )


def _runtime_for_apply(
    *,
    history_size: int = 100,
) -> SimpleNamespace:
    """Stub runtime that satisfies the apply_divergence_check call site.

    No trust_network / hebbian_router => those branches no-op (read-only
    from history's perspective).
    """
    return SimpleNamespace(
        divergence_results={},
        divergence_history={},
        trust_network=None,
        hebbian_router=None,
        config=SimpleNamespace(
            avatar_telemetry=_telemetry_cfg(history_size=history_size),
            avatars=SimpleNamespace(enabled=True),
        ),
        profile_store=None,
    )


# ── 1. Ring buffer append on apply_divergence_check ─────────────────────


def test_apply_divergence_check_appends_to_history():
    runtime = _runtime_for_apply()
    agent = _make_agent_with_snap()
    response_text = "hello <intent emotion=warm>"

    apply_divergence_check(
        runtime, "agent-007", agent, response_text,
        runtime.config.avatar_telemetry,
    )

    bucket = runtime.divergence_history.get("agent-007")
    assert bucket is not None
    assert len(bucket) == 1
    entry = bucket[0]
    assert isinstance(entry, DivergenceHistoryEntry)
    assert entry.result.intent_emotion == "warm"
    assert entry.timestamp > 0


# ── 2. Buffer capped at divergence_history_size ─────────────────────────


def test_ring_buffer_caps_at_history_size():
    runtime = _runtime_for_apply(history_size=3)
    agent = _make_agent_with_snap()

    for _ in range(5):
        apply_divergence_check(
            runtime, "agent-007", agent, "hi <intent emotion=warm>",
            runtime.config.avatar_telemetry,
        )

    bucket = runtime.divergence_history["agent-007"]
    assert bucket.maxlen == 3
    assert len(bucket) == 3


# ── 3. Per-agent isolation ──────────────────────────────────────────────


def test_history_is_per_agent_isolated():
    runtime = _runtime_for_apply()
    agent_a = _make_agent_with_snap()
    agent_b = _make_agent_with_snap()

    apply_divergence_check(
        runtime, "agent-A", agent_a, "x <intent emotion=warm>",
        runtime.config.avatar_telemetry,
    )
    apply_divergence_check(
        runtime, "agent-B", agent_b, "y <intent emotion=concerned>",
        runtime.config.avatar_telemetry,
    )
    apply_divergence_check(
        runtime, "agent-B", agent_b, "z <intent emotion=concerned>",
        runtime.config.avatar_telemetry,
    )

    assert len(runtime.divergence_history["agent-A"]) == 1
    assert len(runtime.divergence_history["agent-B"]) == 2


# ── 4. divergence_history_size=0 disables capture cleanly ───────────────


def test_history_size_zero_disables_capture():
    runtime = _runtime_for_apply(history_size=0)
    agent = _make_agent_with_snap()

    apply_divergence_check(
        runtime, "agent-007", agent, "hi <intent emotion=warm>",
        runtime.config.avatar_telemetry,
    )

    # No bucket allocated, no append performed -- silent no-op.
    assert runtime.divergence_history == {}


# ── 5. AD-727 OUTPUT-subject regex passes for every combo ───────────────


def test_history_entry_notes_pass_ad727_phrasing_rule():
    """Every taxonomy x applied-rules combo's rendered note must be OUTPUT-subject."""
    applied_samples = [
        ("intent_warm",),
        ("intent_concerned",),
        ("intent_excited",),
        ("high_trust_pitch",),
        ("low_trust_pitch",),
        ("blocked_rate_pitch",),
        ("tier3_rate_volume",),
        ("responding_rate", "high_trust_pitch"),
        (),  # empty applied -> "no_rules_fired" branch
    ]
    for intent in EmotionalIntent:
        for applied in applied_samples:
            result = compute_divergence(intent.value, applied)
            entry = DivergenceHistoryEntry(timestamp=1234567890.0, result=result)
            note = entry.to_note()
            assert not _FORBIDDEN_PHRASING_RE.search(note), (
                f"AD-727 phrasing violation in note: {note!r} "
                f"(intent={intent.value}, applied={applied})"
            )


# ── Endpoint test fixtures ──────────────────────────────────────────────


def _endpoint_runtime(
    *,
    agent_present: bool = True,
    divergence_detection: bool = True,
    telemetry_enabled: bool = True,
    history: dict[str, list[DivergenceHistoryEntry]] | None = None,
    aggregate_window: int = 50,
) -> MagicMock:
    runtime = MagicMock()
    agent = MagicMock() if agent_present else None
    if agent is not None:
        agent.id = "agent-007"
        agent.agent_type = "counselor"
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent

    cfg = MagicMock()
    cfg.avatars = MagicMock()
    cfg.avatars.enabled = True
    cfg.avatars.avatars_dir = "data/avatars"
    cfg.avatars.max_vrm_size_bytes = 25 * 1024 * 1024
    cfg.avatar_telemetry = MagicMock()
    cfg.avatar_telemetry.enabled = telemetry_enabled
    cfg.avatar_telemetry.divergence_detection = divergence_detection
    cfg.avatar_telemetry.divergence_aggregate_window = aggregate_window
    cfg.avatar_telemetry.inject_into_agent_context = False
    runtime.config = cfg

    if history is None:
        runtime.divergence_history = {}
    else:
        runtime.divergence_history = {
            aid: deque(entries) for aid, entries in history.items()
        }

    # Minimum runtime surface that create_app touches at construction.
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Troi"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Troi", "agent_type": "counselor",
        "agent_id": "agent-007",
        "display_name": "Counselor", "department": "bridge",
    }
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    return runtime


def _entry(intent: str, applied: tuple[str, ...], ts: float) -> DivergenceHistoryEntry:
    return DivergenceHistoryEntry(
        timestamp=ts,
        result=compute_divergence(intent, applied),
    )


# ── 6. Endpoint returns history most-recent-first ───────────────────────


def test_endpoint_returns_history_most_recent_first():
    from probos.api import create_app

    entries = [
        _entry("warm", ("intent_warm",), 1000.0),
        _entry("concerned", ("intent_concerned",), 2000.0),
        _entry("excited", ("intent_excited",), 3000.0),
    ]
    runtime = _endpoint_runtime(history={"agent-007": entries})
    client = TestClient(create_app(runtime))
    resp = client.get(
        "/api/agent/agent-007/avatar-telemetry/divergence-history?limit=10",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == "agent-007"
    timestamps = [e["timestamp"] for e in body["history"]]
    assert timestamps == [3000.0, 2000.0, 1000.0]


# ── 7. Endpoint aggregate metric arithmetic ─────────────────────────────


def test_endpoint_aggregate_arithmetic_60_percent():
    """3 diverged + 2 perfect over the window -> 60%."""
    from probos.api import create_app

    # warm intent with the matching intent rule -> match_score=1.0, magnitude=0
    perfect = _entry("warm", ("intent_warm",), 1.0)
    # warm intent with only operational rules (no intent_*) -> match_score=0.0, magnitude=1.0
    diverged = _entry("warm", ("blocked_rate_pitch",), 2.0)

    entries = [perfect, diverged, diverged, perfect, diverged]
    runtime = _endpoint_runtime(
        history={"agent-007": entries},
        aggregate_window=10,
    )
    client = TestClient(create_app(runtime))
    resp = client.get(
        "/api/agent/agent-007/avatar-telemetry/divergence-history?limit=10",
    )
    assert resp.status_code == 200
    agg = resp.json()["aggregate"]
    assert agg["total"] == 5
    assert agg["diverged"] == 3
    assert agg["percentage"] == pytest.approx(0.6, abs=1e-6)


# ── 8. Endpoint 503 when divergence_detection off ───────────────────────


def test_endpoint_503_when_divergence_detection_off():
    from probos.api import create_app

    runtime = _endpoint_runtime(divergence_detection=False)
    client = TestClient(create_app(runtime))
    resp = client.get(
        "/api/agent/agent-007/avatar-telemetry/divergence-history",
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "divergence_detection_disabled"


# ── 9. Endpoint 404 unknown agent ───────────────────────────────────────


def test_endpoint_404_unknown_agent():
    from probos.api import create_app

    runtime = _endpoint_runtime(agent_present=False)
    client = TestClient(create_app(runtime))
    resp = client.get(
        "/api/agent/missing-999/avatar-telemetry/divergence-history",
    )
    assert resp.status_code == 404
