"""AD-1029: tests for the ``AttentionFaculty`` — the per-agent deterministic attention organ.

BF-287 discipline: real objects at the substrate boundary — a real ``AttentionFaculty``,
a real ``CognitiveSpine``, and a minimal real ``CognitiveAgent`` (via the AD-1028 golden
builders); NO ``MagicMock`` where an attribute typo could pass.

Coverage maps to the issue #977 acceptance criteria:
* default-OFF ⇒ the faculty is not composed ⇒ byte-identical (AD-1028 inline path runs);
* enabled + no exogenous + fixed salience ⇒ byte-identical (``arbitrate`` == ``assemble``,
  and ``_build_user_message`` ON == OFF on the same observation);
* an exogenous signal delivered between turns via ``spine.deliver_exogenous`` is visible to
  the next ``perceive`` / ``arbitrate`` and drained exactly once;
* one turn records a bid-competition audit trace that does NOT alter the prompt;
* NO ``await`` and NO intent-bus call on the synchronous arbitration path (AST + source);
* identity is namespaced under the parent and the faculty is NOT a mesh agent.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

from probos.cognitive.attention import AttentionBid, ContextAssembler, estimate_tokens
from probos.cognitive.attention_faculty import AttentionFaculty
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.organ import BaseCognitiveOrgan, CognitiveOrgan
from probos.cognitive.spine import EXOGENOUS_SIGNAL_KIND, CognitiveSpine
from probos.config import SystemConfig
from probos.substrate.agent import BaseAgent
from tests.fixtures.ad1028_golden._capture_golden import (
    dm_observation,
    make_dm_agent,
    make_wr_agent,
    wr_observation,
)


# ---------------------------------------------------------------------------
# Test doubles + helpers (real small objects — BF-287)
# ---------------------------------------------------------------------------


class _Parent:
    """Minimal real parent stand-in exposing only the public id the spine/organ read."""

    def __init__(self, runtime_id: str = "agent-att", sovereign_id: str = "") -> None:
        self.id = runtime_id
        self.sovereign_id = sovereign_id


class _Rt:
    """Minimal real runtime stand-in exposing a real ``SystemConfig``."""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config


def _bid(
    source: str,
    text: str,
    *,
    salience: float = 0.0,
    token_cost: int | None = None,
    zone_floor: int = 0,
    pin: bool = False,
) -> AttentionBid:
    """Build a bid whose lazy renderer returns ``text`` (mirrors the _emit scheme)."""
    return AttentionBid(
        source=source,
        render=(lambda _t=text: _t),
        salience=salience,
        token_cost=estimate_tokens(text) if token_cost is None else token_cost,
        zone_floor=zone_floor,
        pin=pin,
    )


def _per_turn_bids() -> list[AttentionBid]:
    """Two per-turn bids using the same fixed-priority scheme ``_build_user_message`` uses."""
    return [
        _bid("a", "alpha", salience=0.0, zone_floor=0),
        _bid("b", "bravo", salience=1.0, zone_floor=1),
    ]


def _attach_faculty(parent: _Parent | None = None) -> tuple[CognitiveSpine, AttentionFaculty]:
    """Attach a real AttentionFaculty to a real CognitiveSpine + wire exogenous intake."""
    spine = CognitiveSpine(parent or _Parent())
    faculty = AttentionFaculty()
    spine.attach_organ(faculty)
    spine.subscribe(EXOGENOUS_SIGNAL_KIND, faculty)
    return spine, faculty


def _enabled_config(token_budget: int = 120_000) -> SystemConfig:
    """A real SystemConfig with attention enabled at ``token_budget``."""
    cfg = SystemConfig()
    cfg.memory.attention.enabled = True
    cfg.memory.attention.token_budget = token_budget
    return cfg


# ---------------------------------------------------------------------------
# Default-OFF: the faculty is not composed ⇒ byte-identical
# ---------------------------------------------------------------------------


def test_default_off_no_faculty_composed() -> None:
    agent = make_dm_agent()  # constructed with no runtime ⇒ attention OFF
    assert agent._active_attention_faculty() is None
    assert agent._spine.has_organs is False


def test_compose_organs_off_by_default_constructs_no_organ() -> None:
    agent = CognitiveAgent(agent_id="ad1029-off", instructions="test")
    assert agent._spine.get_organ("attention") is None
    assert agent._active_attention_faculty() is None
    assert agent._spine.has_organs is False


async def test_dm_build_user_message_uses_inline_path_when_off() -> None:
    agent = make_dm_agent()
    assert agent._active_attention_faculty() is None
    msg = await agent._build_user_message(dm_observation())
    # The inline AD-1028 path produced a non-empty prompt containing the Captain line.
    assert "Captain says: What did we discuss about the warp core?" in msg


# ---------------------------------------------------------------------------
# Enabled + no exogenous + fixed salience ⇒ byte-identical
# ---------------------------------------------------------------------------


def test_arbitrate_no_exogenous_equals_assemble_unbounded() -> None:
    _spine, faculty = _attach_faculty()
    bids = _per_turn_bids()
    expected = ContextAssembler.assemble(bids, token_budget=1_000_000_000)
    assert faculty.arbitrate(_per_turn_bids(), token_budget=1_000_000_000) == expected
    assert expected == ["alpha", "bravo"]


def test_arbitrate_no_exogenous_equals_assemble_under_tight_budget() -> None:
    _spine, faculty = _attach_faculty()
    bids = [
        _bid("low", "LOW", salience=1.0, token_cost=10, zone_floor=0),
        _bid("high", "HIGH", salience=9.0, token_cost=10, zone_floor=1),
        _bid("mid", "MID", salience=5.0, token_cost=10, zone_floor=2),
    ]
    # Same selection the assembler makes: budget 20 admits the two highest-salience bids.
    expected = ContextAssembler.assemble(list(bids), token_budget=20)
    assert faculty.arbitrate(list(bids), token_budget=20) == expected == ["HIGH", "MID"]


def test_arbitrate_empty_bids_returns_empty() -> None:
    _spine, faculty = _attach_faculty()
    assert faculty.arbitrate([], token_budget=1000) == []


async def test_dm_build_user_message_on_equals_off_byte_identical() -> None:
    # OFF agent (no faculty) and ON agent (faculty manually composed) — both runtime=None
    # so _resolve_attention_budget is unbounded and every runtime-coupled block behaves
    # identically. The ONLY variable is the faculty driving vs the inline assemble.
    off_agent = make_dm_agent()
    off_msg = await off_agent._build_user_message(dm_observation())

    on_agent = make_dm_agent()
    on_agent._spine.attach_organ(AttentionFaculty())
    assert on_agent._active_attention_faculty() is not None
    on_msg = await on_agent._build_user_message(dm_observation())

    assert on_msg == off_msg


async def test_wr_build_user_message_on_equals_off_byte_identical() -> None:
    off_agent = make_wr_agent()
    off_msg = await off_agent._build_user_message(wr_observation())

    on_agent = make_wr_agent()
    on_agent._spine.attach_organ(AttentionFaculty())
    assert on_agent._active_attention_faculty() is not None
    on_msg = await on_agent._build_user_message(wr_observation())

    assert on_msg == off_msg


# ---------------------------------------------------------------------------
# _compose_organs wiring when enabled
# ---------------------------------------------------------------------------


def test_compose_organs_attaches_faculty_when_enabled() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_enabled_config())
    agent._compose_organs()  # idempotent re-invoke now that attention is enabled
    faculty = agent._active_attention_faculty()
    assert isinstance(faculty, AttentionFaculty)
    assert agent._spine.has_organs is True
    assert agent._spine.get_organ("attention") is faculty


def test_compose_organs_is_idempotent_when_enabled() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_enabled_config())
    agent._compose_organs()
    first = agent._active_attention_faculty()
    agent._compose_organs()  # second call must not replace the composed faculty
    assert agent._active_attention_faculty() is first


def test_compose_organs_subscribes_faculty_to_exogenous_inlet() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_enabled_config())
    agent._compose_organs()
    faculty = agent._active_attention_faculty()
    assert faculty is not None
    # The agent-owned spine inlet must reach the faculty's pending state.
    agent._spine.deliver_exogenous("between-turn alert")
    assert faculty.pending_exogenous_count == 1


# ---------------------------------------------------------------------------
# Exogenous intake: delivered between turns, visible to the next arbitration
# ---------------------------------------------------------------------------


def test_exogenous_signal_visible_to_next_arbitrate() -> None:
    spine, faculty = _attach_faculty()
    spine.deliver_exogenous("EXTERNAL ALERT")  # arrives between turns
    assert faculty.pending_exogenous_count == 1

    result = faculty.arbitrate(_per_turn_bids(), token_budget=10_000)
    # The exogenous bid is merged (after the per-turn bids) and visible in the prompt.
    assert "EXTERNAL ALERT" in result
    assert result == ["alpha", "bravo", "EXTERNAL ALERT"]
    # ...and drained exactly once (no longer pending after the turn consumed it).
    assert faculty.pending_exogenous_count == 0


def test_exogenous_drained_once_then_gone() -> None:
    spine, faculty = _attach_faculty()
    spine.deliver_exogenous("ONE-SHOT")
    first = faculty.arbitrate(_per_turn_bids(), token_budget=10_000)
    assert "ONE-SHOT" in first
    # The next turn (no new exogenous) is byte-identical to the inline assemble path.
    second = faculty.arbitrate(_per_turn_bids(), token_budget=10_000)
    assert second == ContextAssembler.assemble(_per_turn_bids(), token_budget=10_000)
    assert "ONE-SHOT" not in second


def test_exogenous_attention_bid_payload_passes_through() -> None:
    spine, faculty = _attach_faculty()
    spine.deliver_exogenous(_bid("mention", "@you were addressed"))
    assert faculty.pending_exogenous_count == 1
    result = faculty.arbitrate(_per_turn_bids(), token_budget=10_000)
    assert "@you were addressed" in result


def test_non_exogenous_signal_is_ignored() -> None:
    _spine, faculty = _attach_faculty()
    faculty.on_signal("some_other_kind", "ignored payload")
    assert faculty.pending_exogenous_count == 0


# ---------------------------------------------------------------------------
# drive_cycle (generic observation) is a deterministic no-op for the faculty
# ---------------------------------------------------------------------------


def test_drive_cycle_with_observation_does_not_drain_or_audit() -> None:
    spine, faculty = _attach_faculty()
    spine.deliver_exogenous("PENDING")
    assert faculty.pending_exogenous_count == 1

    # The spine drives the generic cycle with the raw observation dict every turn.
    spine.drive_cycle({"intent": "direct_message", "params": {}})

    # No drain (exogenous stays visible to the real arbitration) and no audit fired.
    assert faculty.pending_exogenous_count == 1
    assert faculty.last_audit is None


# ---------------------------------------------------------------------------
# Audit trace: records the bid competition; never alters the prompt
# ---------------------------------------------------------------------------


def test_audit_trace_recorded_and_prompt_unchanged() -> None:
    spine, faculty = _attach_faculty()
    captured: list[dict[str, Any]] = []
    faculty.set_audit_emit(lambda trace: captured.append(dict(trace)))

    bids = _per_turn_bids()
    expected = ContextAssembler.assemble(_per_turn_bids(), token_budget=10_000)
    result = faculty.arbitrate(list(bids), token_budget=10_000)

    # The audit is a pure side-effect: the prompt equals the inline assemble output.
    assert result == expected

    # Exactly one bid-competition trace recorded, with the competition metadata.
    assert len(captured) == 1
    trace = captured[0]
    assert trace["organ_id"] == "agent-att.attention"
    assert trace["phase"] == "arbitrate"
    assert trace["bids_in"] == 2
    assert trace["survivors"] == 2
    assert trace["dropped"] == 0
    assert trace["token_budget"] == 10_000
    assert trace["sources"] == ["a", "b"]


def test_audit_records_drops_under_tight_budget() -> None:
    _spine, faculty = _attach_faculty()
    captured: list[dict[str, Any]] = []
    faculty.set_audit_emit(lambda trace: captured.append(dict(trace)))
    bids = [
        _bid("low", "LOW", salience=1.0, token_cost=10, zone_floor=0),
        _bid("high", "HIGH", salience=9.0, token_cost=10, zone_floor=1),
        _bid("mid", "MID", salience=5.0, token_cost=10, zone_floor=2),
    ]
    faculty.arbitrate(list(bids), token_budget=20)
    assert captured[0]["bids_in"] == 3
    assert captured[0]["survivors"] == 2
    assert captured[0]["dropped"] == 1


def test_audit_default_sink_is_noop_but_last_audit_recorded() -> None:
    # No sink wired (default no-op) ⇒ arbitrate still works; introspection records it.
    _spine, faculty = _attach_faculty()
    result = faculty.arbitrate(_per_turn_bids(), token_budget=10_000)
    assert result == ["alpha", "bravo"]
    assert faculty.last_audit is not None
    assert faculty.last_audit["bids_in"] == 2


# ---------------------------------------------------------------------------
# No await / no intent-bus on the synchronous arbitration path
# ---------------------------------------------------------------------------


def _code_without_docstring(func: Any) -> str:
    """Return the function's source body as code (docstring stripped, comments dropped)."""
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


def test_synchronous_arbitration_path_has_no_await() -> None:
    for method in (
        AttentionFaculty.arbitrate,
        AttentionFaculty.perceive,
        AttentionFaculty.decide,
        AttentionFaculty.act,
        AttentionFaculty.on_signal,
    ):
        assert inspect.iscoroutinefunction(method) is False
        assert _contains_await(method) is False


def test_synchronous_arbitration_path_has_no_bus_call() -> None:
    for method in (
        AttentionFaculty.arbitrate,
        AttentionFaculty.perceive,
        AttentionFaculty.decide,
        AttentionFaculty.act,
        AttentionFaculty.on_signal,
    ):
        code = _code_without_docstring(method)
        for forbidden in ("intent_bus", ".broadcast(", ".publish(", "create_task"):
            assert forbidden not in code, f"{method.__name__} must not call {forbidden!r}"


# ---------------------------------------------------------------------------
# Identity / non-membership: a paired organ, not a mesh peer
# ---------------------------------------------------------------------------


def test_faculty_organ_id_namespaced_under_parent() -> None:
    spine, faculty = _attach_faculty(_Parent(runtime_id="ignored", sovereign_id="cap-1"))
    assert faculty.name == "attention"
    assert faculty.organ_id == "cap-1.attention"
    assert faculty.parent_id == "cap-1"
    assert faculty.attached is True
    assert spine.organ_names == ("attention",)


def test_faculty_is_a_cognitive_organ_not_a_mesh_agent() -> None:
    faculty = AttentionFaculty()
    assert isinstance(faculty, BaseCognitiveOrgan)
    assert isinstance(faculty, CognitiveOrgan) is True
    assert not isinstance(faculty, BaseAgent)
    assert not issubclass(AttentionFaculty, BaseAgent)
    for forbidden in ("tier", "trust_score", "capabilities", "report", "intent_descriptors"):
        assert not hasattr(faculty, forbidden), (
            f"AttentionFaculty must not expose mesh-agent member {forbidden!r}"
        )


def test_import_smoke_runtime_imports_with_faculty() -> None:
    import probos.runtime  # noqa: F401

    assert AttentionFaculty is not None
    assert AttentionFaculty.default_name == "attention"
