"""AD-1032: tests for the ``AttentionFaculty`` arousal model — exogenous interrupts.

BF-287 discipline: real objects at the substrate boundary — a real ``AttentionFaculty``,
a real ``CognitiveSpine``, a real ``SystemConfig``/``AttentionConfig``, and (for the
governed boundary) a real ``CognitiveAgent`` via the AD-1028 golden builders. NO
``MagicMock`` where an attribute typo could pass.

Coverage maps to issue #980 (AD-1032) acceptance + the Captain-approved policy:
* the severity table maps event_type → zone; the zone raises UPWARD only;
* a RED event narrows the next turn to non-ambient + pinned bids and shrinks the budget;
* an AMBER (mention) event suppresses ONLY the ambient camera bid;
* a single low-severity ``scene_change`` only QUEUES (zone stays GREEN, no narrowing);
  the SAME low-severity type repeating within the window escalates to AMBER;
* a pinned bid is NEVER dropped under RED;
* the zone decays one level per quiet arbitrate and fully resets to GREEN after the window;
* arousal OFF ⇒ ``arbitrate`` is byte-identical to AD-1029 even with an event delivered;
* the governed boundary ``on_exogenous_event`` forwards when ON and is a no-op when OFF;
* no ``await`` / intent-bus call on the arbitration path (AST + source).
"""
from __future__ import annotations

import ast
import inspect
import textwrap
import time
from typing import Any

from probos.cognitive.attention import AttentionBid, ContextAssembler, estimate_tokens
from probos.cognitive.attention_faculty import (
    _AMBIENT_SOURCES,
    _SEVERITY_BY_EVENT,
    AttentionFaculty,
)
from probos.cognitive.circuit_breaker import CognitiveZone
from probos.cognitive.spine import EXOGENOUS_SIGNAL_KIND, CognitiveSpine
from probos.config import SystemConfig
from tests.fixtures.ad1028_golden._capture_golden import make_dm_agent


# ---------------------------------------------------------------------------
# Test doubles + helpers (real small objects — BF-287)
# ---------------------------------------------------------------------------


class _ArousalParent:
    """Real parent exposing the spine-read id + the agent's ``_attention_config`` resolver.

    The faculty reads its arousal config from the parent via that resolver (the same one
    the AD-1030 salience path uses), so a parent that supplies it is all the faculty needs.
    """

    def __init__(self, att_cfg: Any, runtime_id: str = "agent-arousal", sovereign_id: str = "") -> None:
        self.id = runtime_id
        self.sovereign_id = sovereign_id
        self._att_cfg = att_cfg

    def _attention_config(self) -> Any:
        return self._att_cfg


class _Rt:
    """Minimal real runtime stand-in exposing a real ``SystemConfig`` (mirrors AD-1029)."""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config


def _att_cfg(*, arousal_enabled: bool = True, **overrides: Any) -> Any:
    """A real ``AttentionConfig`` (via ``SystemConfig``) with attention + arousal enabled."""
    cfg = SystemConfig()
    att = cfg.memory.attention
    att.enabled = True
    att.arousal_enabled = arousal_enabled
    for key, value in overrides.items():
        setattr(att, key, value)
    return att


def _agent_config(*, arousal_enabled: bool) -> SystemConfig:
    """A real ``SystemConfig`` with attention enabled (so the faculty composes) + arousal flag."""
    cfg = SystemConfig()
    cfg.memory.attention.enabled = True
    cfg.memory.attention.arousal_enabled = arousal_enabled
    return cfg


def _bid(
    source: str,
    text: str,
    *,
    salience: float = 0.0,
    token_cost: int | None = None,
    zone_floor: int = 0,
    pin: bool = False,
) -> AttentionBid:
    """Build a bid whose lazy renderer returns ``text`` (mirrors the AD-1029 ``_bid``)."""
    return AttentionBid(
        source=source,
        render=(lambda _t=text: _t),
        salience=salience,
        token_cost=estimate_tokens(text) if token_cost is None else token_cost,
        zone_floor=zone_floor,
        pin=pin,
    )


def _attach(att_cfg: Any) -> tuple[CognitiveSpine, AttentionFaculty]:
    """Attach a real ``AttentionFaculty`` to a real spine whose parent supplies ``att_cfg``."""
    spine = CognitiveSpine(_ArousalParent(att_cfg))
    faculty = AttentionFaculty()
    spine.attach_organ(faculty)
    spine.subscribe(EXOGENOUS_SIGNAL_KIND, faculty)
    return spine, faculty


# ---------------------------------------------------------------------------
# Severity table → zone; the zone raises UPWARD only
# ---------------------------------------------------------------------------


def test_severity_table_maps_event_type_to_zone() -> None:
    assert _SEVERITY_BY_EVENT["alert"] == CognitiveZone.RED
    assert _SEVERITY_BY_EVENT["consensus"] == CognitiveZone.RED
    assert _SEVERITY_BY_EVENT["safety"] == CognitiveZone.RED
    assert _SEVERITY_BY_EVENT["mention"] == CognitiveZone.AMBER
    assert _SEVERITY_BY_EVENT["scene_change"] == CognitiveZone.GREEN
    assert _SEVERITY_BY_EVENT["gossip"] == CognitiveZone.GREEN


def test_ambient_sources_are_the_approved_set() -> None:
    assert _AMBIENT_SOURCES == frozenset(
        {"camera_scene_ambient", "camera_scene", "telemetry", "gossip"}
    )


def test_red_event_raises_zone_to_red() -> None:
    spine, faculty = _attach(_att_cfg())
    spine.deliver_exogenous({"event_type": "alert", "severity": "red"})
    assert faculty.arousal_zone == CognitiveZone.RED


def test_mention_event_raises_zone_to_amber() -> None:
    spine, faculty = _attach(_att_cfg())
    spine.deliver_exogenous({"event_type": "mention"})
    assert faculty.arousal_zone == CognitiveZone.AMBER


def test_exogenous_prefixed_event_type_is_normalized() -> None:
    # The EventType taxonomy values (e.g. EXOGENOUS_ALERT == "exogenous_alert") map
    # through the same severity table after the prefix is stripped.
    spine, faculty = _attach(_att_cfg())
    spine.deliver_exogenous({"event_type": "exogenous_alert"})
    assert faculty.arousal_zone == CognitiveZone.RED


def test_zone_raises_upward_only() -> None:
    spine, faculty = _attach(_att_cfg())
    spine.deliver_exogenous({"event_type": "alert"})  # RED
    assert faculty.arousal_zone == CognitiveZone.RED
    spine.deliver_exogenous({"event_type": "mention"})  # AMBER must NOT lower RED
    assert faculty.arousal_zone == CognitiveZone.RED


def test_explicit_severity_raises_event_type_baseline() -> None:
    # scene_change baseline is GREEN; an explicit severity="red" raises it to RED.
    spine, faculty = _attach(_att_cfg())
    spine.deliver_exogenous({"event_type": "scene_change", "severity": "red"})
    assert faculty.arousal_zone == CognitiveZone.RED


# ---------------------------------------------------------------------------
# RED narrowing: ambient suppressed + budget shrunk; pinned + non-ambient survive
# ---------------------------------------------------------------------------


def test_red_event_drops_ambient_sources_and_keeps_core_plus_event_bid() -> None:
    spine, faculty = _attach(_att_cfg(arousal_red_budget_multiplier=0.5))
    bids = [
        _bid("episodic", "EPISODIC", token_cost=5),
        _bid("camera_scene_ambient", "AMBIENT-CAM", token_cost=5),
        _bid("camera_scene", "CAM", token_cost=5),
        _bid("telemetry", "TELEM", token_cost=5),
        _bid("gossip", "GOSSIP", token_cost=5),
    ]
    spine.deliver_exogenous({"event_type": "alert", "severity": "red", "text": "INTRUDER"})
    result = faculty.arbitrate(list(bids), token_budget=10_000)

    assert faculty.arousal_zone == CognitiveZone.RED
    # Non-ambient core survives; the pinned threat-relevant event bid survives.
    assert "EPISODIC" in result
    assert "INTRUDER" in result
    # Every ambient source is suppressed under RED.
    for ambient in ("AMBIENT-CAM", "CAM", "TELEM", "GOSSIP"):
        assert ambient not in result


def test_red_event_applies_budget_multiplier() -> None:
    spine, faculty = _attach(_att_cfg(arousal_red_budget_multiplier=0.5))
    spine.deliver_exogenous({"event_type": "alert"})
    faculty.arbitrate([_bid("episodic", "EP", token_cost=5)], token_budget=10_000)
    # The effective budget that drove the (narrowed) competition is the multiplied one.
    assert faculty.last_audit is not None
    assert faculty.last_audit["token_budget"] == 5_000
    assert faculty.last_audit["arousal_zone"] == "red"


def test_pinned_bid_never_dropped_under_red() -> None:
    spine, faculty = _attach(_att_cfg())
    # A pinned bid on an AMBIENT source must STILL survive RED suppression.
    bids = [_bid("camera_scene", "PINNED-CAM", token_cost=5, pin=True)]
    spine.deliver_exogenous({"event_type": "alert"})
    result = faculty.arbitrate(list(bids), token_budget=10_000)
    assert faculty.arousal_zone == CognitiveZone.RED
    assert "PINNED-CAM" in result


# ---------------------------------------------------------------------------
# AMBER narrowing: only the ambient camera bid is suppressed
# ---------------------------------------------------------------------------


def test_amber_event_drops_only_ambient_camera_bid() -> None:
    spine, faculty = _attach(_att_cfg())
    bids = [
        _bid("episodic", "EPISODIC", token_cost=5),
        _bid("camera_scene_ambient", "AMBIENT-CAM", token_cost=5),
        _bid("camera_scene", "CAM", token_cost=5),
        _bid("telemetry", "TELEM", token_cost=5),
    ]
    spine.deliver_exogenous({"event_type": "mention"})
    result = faculty.arbitrate(list(bids), token_budget=10_000)

    assert faculty.arousal_zone == CognitiveZone.AMBER
    # Only the ambient camera bid is suppressed at AMBER; the rest are kept.
    assert "AMBIENT-CAM" not in result
    assert "EPISODIC" in result
    assert "CAM" in result
    assert "TELEM" in result


def test_amber_does_not_apply_budget_multiplier() -> None:
    spine, faculty = _attach(_att_cfg(arousal_red_budget_multiplier=0.5))
    spine.deliver_exogenous({"event_type": "mention"})
    faculty.arbitrate([_bid("episodic", "EP", token_cost=5)], token_budget=10_000)
    assert faculty.last_audit is not None
    assert faculty.last_audit["token_budget"] == 10_000  # unchanged at AMBER


# ---------------------------------------------------------------------------
# Interruptibility: a single low-severity event queues; a repeat escalates
# ---------------------------------------------------------------------------


def test_single_low_severity_event_stays_green_no_narrowing() -> None:
    spine, faculty = _attach(_att_cfg())
    bids = [_bid("camera_scene_ambient", "AMBIENT-CAM", token_cost=5)]
    spine.deliver_exogenous({"event_type": "scene_change"})  # single low-severity
    result = faculty.arbitrate(list(bids), token_budget=10_000)
    # Zone stays GREEN (the event only queued) ⇒ NO narrowing ⇒ ambient bid kept.
    assert faculty.arousal_zone == CognitiveZone.GREEN
    assert "AMBIENT-CAM" in result


def test_repeated_low_severity_within_window_escalates_to_amber() -> None:
    spine, faculty = _attach(_att_cfg())
    spine.deliver_exogenous({"event_type": "scene_change"})  # queues (GREEN)
    assert faculty.arousal_zone == CognitiveZone.GREEN
    spine.deliver_exogenous({"event_type": "scene_change"})  # same type, within window
    assert faculty.arousal_zone == CognitiveZone.AMBER

    bids = [_bid("camera_scene_ambient", "AMBIENT-CAM", token_cost=5)]
    result = faculty.arbitrate(list(bids), token_budget=10_000)
    assert "AMBIENT-CAM" not in result  # AMBER suppresses the ambient camera bid


def test_repeat_outside_window_does_not_escalate() -> None:
    spine, faculty = _attach(_att_cfg(arousal_repeat_window_seconds=60.0))
    spine.deliver_exogenous({"event_type": "scene_change"})  # GREEN
    # Age the first record past the repeat window so the second is not a "repeat".
    faculty._recent_low_severity = [
        (ts - 10_000.0, et) for (ts, et) in faculty._recent_low_severity
    ]
    spine.deliver_exogenous({"event_type": "scene_change"})  # window elapsed ⇒ still GREEN
    assert faculty.arousal_zone == CognitiveZone.GREEN


# ---------------------------------------------------------------------------
# Decay: one level per quiet arbitrate; full reset to GREEN after the window
# ---------------------------------------------------------------------------


def test_decay_steps_down_one_level_per_quiet_arbitrate() -> None:
    spine, faculty = _attach(_att_cfg())
    spine.deliver_exogenous({"event_type": "alert"})  # RED
    faculty.arbitrate([], token_budget=10_000)  # event turn: not quiet ⇒ stays RED
    assert faculty.arousal_zone == CognitiveZone.RED
    faculty.arbitrate([], token_budget=10_000)  # quiet: RED → AMBER
    assert faculty.arousal_zone == CognitiveZone.AMBER
    faculty.arbitrate([], token_budget=10_000)  # quiet: AMBER → GREEN
    assert faculty.arousal_zone == CognitiveZone.GREEN
    faculty.arbitrate([], token_budget=10_000)  # quiet: GREEN floors at GREEN
    assert faculty.arousal_zone == CognitiveZone.GREEN


def test_full_decay_resets_to_green_after_window(monkeypatch) -> None:
    # Deterministic clock: the event stamps ``_last_event_at`` at ``now``; a long
    # quiet gap then makes the next quiet arbitrate jump STRAIGHT to GREEN (not
    # the one-level step-down to AMBER). Patching the faculty's monotonic clock
    # (instead of ``_last_event_at = time.monotonic() - 10_000``) keeps the test
    # independent of the runner's boot time: on a freshly-booted CI runner
    # ``time.monotonic()`` is small, so ``monotonic() - 10_000`` goes NEGATIVE and
    # trips the ``_last_event_at > 0.0`` guard, wrongly stepping down to AMBER.
    import types as _types
    import probos.cognitive.attention_faculty as af_mod
    clock = {"t": 100_000.0}
    monkeypatch.setattr(af_mod, "time", _types.SimpleNamespace(monotonic=lambda: clock["t"]))
    spine, faculty = _attach(_att_cfg())  # full_decay default 300s
    spine.deliver_exogenous({"event_type": "alert"})  # RED (stamps _last_event_at)
    faculty.arbitrate([], token_budget=10_000)  # event turn: RED
    assert faculty.arousal_zone == CognitiveZone.RED
    clock["t"] += 10_000.0  # quiet period far past the 300s full-decay window
    faculty.arbitrate([], token_budget=10_000)
    assert faculty.arousal_zone == CognitiveZone.GREEN


# ---------------------------------------------------------------------------
# Default-OFF: byte-identical to AD-1029 even with an event delivered
# ---------------------------------------------------------------------------


def test_arousal_off_arbitrate_byte_identical_with_event_delivered() -> None:
    spine, faculty = _attach(_att_cfg(arousal_enabled=False))
    bids = [
        _bid("episodic", "EP", token_cost=5),
        _bid("camera_scene_ambient", "CAM", token_cost=5),
    ]
    # Deliver a fully-formed arousal event (even one carrying "text") while OFF.
    spine.deliver_exogenous({"event_type": "alert", "severity": "red", "text": "INTRUDER"})
    # OFF ⇒ the event contributes NOTHING: no pending bid, no zone change.
    assert faculty.pending_exogenous_count == 0
    assert faculty.arousal_zone == CognitiveZone.GREEN

    expected = ContextAssembler.assemble(list(bids), token_budget=10_000)
    assert faculty.arbitrate(list(bids), token_budget=10_000) == expected


def test_arousal_on_green_no_event_is_byte_identical() -> None:
    # Arousal ON but no event ⇒ zone GREEN ⇒ no narrowing ⇒ exactly the AD-1029 path.
    spine, faculty = _attach(_att_cfg())
    bids = [
        _bid("episodic", "EP", token_cost=5),
        _bid("camera_scene_ambient", "CAM", token_cost=5),
    ]
    expected = ContextAssembler.assemble(list(bids), token_budget=10_000)
    assert faculty.arbitrate(list(bids), token_budget=10_000) == expected
    assert faculty.arousal_zone == CognitiveZone.GREEN


def test_non_event_payload_takes_ad1029_coerce_path_when_on() -> None:
    # A plain string is NOT an arousal event ⇒ the unchanged AD-1029 coerce-to-bid path.
    spine, faculty = _attach(_att_cfg())
    spine.deliver_exogenous("PLAIN ALERT")
    assert faculty.pending_exogenous_count == 1
    assert faculty.arousal_zone == CognitiveZone.GREEN  # a non-event never raises arousal
    result = faculty.arbitrate([_bid("a", "alpha")], token_budget=10_000)
    assert "PLAIN ALERT" in result


# ---------------------------------------------------------------------------
# Governed boundary: on_exogenous_event forwards when ON, no-op when OFF
# ---------------------------------------------------------------------------


def test_governed_boundary_forwards_when_on() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_agent_config(arousal_enabled=True))
    agent._compose_organs()
    faculty = agent._active_attention_faculty()
    assert faculty is not None

    agent.on_exogenous_event("alert", severity="red")
    # The boundary forwarded the event through the spine inlet to the faculty.
    assert faculty.arousal_zone == CognitiveZone.RED
    assert faculty.pending_exogenous_count == 1  # the pinned event bid is queued


def test_governed_boundary_noop_when_off() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_agent_config(arousal_enabled=False))
    agent._compose_organs()  # faculty STILL composed (attention.enabled=True)
    faculty = agent._active_attention_faculty()
    assert faculty is not None

    agent.on_exogenous_event("alert", severity="red")
    # OFF ⇒ the boundary is a no-op ⇒ nothing reaches the faculty.
    assert faculty.arousal_zone == CognitiveZone.GREEN
    assert faculty.pending_exogenous_count == 0


def test_governed_boundary_noop_when_no_faculty() -> None:
    # attention OFF entirely ⇒ no faculty composed ⇒ boundary is a safe no-op.
    agent = make_dm_agent()
    assert agent._active_attention_faculty() is None
    agent.on_exogenous_event("alert", severity="red")  # must not raise
    assert agent._active_attention_faculty() is None


# ---------------------------------------------------------------------------
# No await / no intent-bus on the synchronous arbitration path (AST + source)
# ---------------------------------------------------------------------------


def _code_without_docstring(func: Any) -> str:
    src = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(src)
    fn = tree.body[0]
    body = getattr(fn, "body", [])
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(getattr(body[0], "value", None), ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.unparse(node) for node in body)


def _contains_await(func: Any) -> bool:
    src = textwrap.dedent(inspect.getsource(func))
    return any(isinstance(node, ast.Await) for node in ast.walk(ast.parse(src)))


_AROUSAL_PATH_METHODS = (
    AttentionFaculty.arbitrate,
    AttentionFaculty.perceive,
    AttentionFaculty.decide,
    AttentionFaculty.act,
    AttentionFaculty.on_signal,
    AttentionFaculty._ingest_arousal_event,
    AttentionFaculty._decay_if_quiet,
    AttentionFaculty._narrow_for_arousal,
    AttentionFaculty._zone_for_event,
    AttentionFaculty._build_event_bid,
    AttentionFaculty._record_low_severity,
    AttentionFaculty._arousal_config,
    AttentionFaculty._arousal_enabled,
)


def test_arousal_path_has_no_await() -> None:
    for method in _AROUSAL_PATH_METHODS:
        assert inspect.iscoroutinefunction(method) is False
        assert _contains_await(method) is False


def test_arousal_path_has_no_bus_call() -> None:
    for method in _AROUSAL_PATH_METHODS:
        code = _code_without_docstring(method)
        for forbidden in ("intent_bus", ".broadcast(", ".publish(", "create_task"):
            assert forbidden not in code, f"{method.__name__} must not call {forbidden!r}"


# ---------------------------------------------------------------------------
# BF-638 (#1002): _coerce_exogenous_bid must not alias a caller-supplied bid
# ---------------------------------------------------------------------------


def test_coerce_exogenous_bid_copies_a_ready_attention_bid() -> None:
    """BF-638: passing a ready ``AttentionBid`` returns a DISTINCT copy (no aliasing),
    with the same field values."""
    _spine, faculty = _attach(_att_cfg())
    original = _bid("caller", "x", salience=7.0, zone_floor=3, pin=True)
    coerced = faculty._coerce_exogenous_bid(original)
    assert coerced is not None
    assert coerced is not original
    assert (coerced.source, coerced.salience, coerced.zone_floor, coerced.pin) == (
        original.source,
        original.salience,
        original.zone_floor,
        original.pin,
    )


def test_delivering_an_attention_bid_does_not_mutate_the_caller_object() -> None:
    """BF-638: a caller that delivers a reusable ``AttentionBid`` keeps its
    ``salience``/``zone_floor``. ``_coerce_exogenous_bid`` copies, so the in-place
    reprice in ``_drain_pending_exogenous`` hits the faculty's COPY, never the
    caller's object."""
    spine, faculty = _attach(_att_cfg())
    original = _bid("caller", "reusable bid", salience=99.0, zone_floor=99)

    spine.deliver_exogenous(original)  # public inlet -> coerce(copy) -> _pending_exogenous
    assert faculty.pending_exogenous_count == 1
    faculty.arbitrate([_bid("a", "alpha")], token_budget=10_000)  # drains + reprices

    # the caller's bid is untouched (the faculty repriced its own copy, not this one)
    assert original.salience == 99.0
    assert original.zone_floor == 99
