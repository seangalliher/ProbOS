"""AD-1033: structural conformance tests for the ``CognitiveOrgan`` contract.

BF-287 discipline: real objects only, no ``MagicMock``. The fakes here are tiny
concrete classes so the runtime-checkable Protocol conformance and the
born-with / dies-with-parent lifecycle are exercised against reality, not a mock
that auto-fakes every attribute.
"""

from __future__ import annotations

import inspect

import pytest

from probos.cognitive.organ import (
    BaseCognitiveOrgan,
    CognitiveOrgan,
    OrganAuditEmit,
    make_organ_id,
)


class _FakeParent:
    """A minimal real stand-in for the owning agent (has ``id`` + ``sovereign_id``)."""

    def __init__(self, agent_id: str = "agent-7", sovereign_id: str = "") -> None:
        self.id = agent_id
        self.sovereign_id = sovereign_id


class _FakeOrgan(BaseCognitiveOrgan):
    """A real concrete organ that records its cycle inputs (no MagicMock)."""

    default_name = "attention"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.perceived: list[object] = []
        self.decisions: list[object] = []
        self.acts: list[object] = []

    def perceive(self, context: object) -> dict[str, object]:
        self.perceived.append(context)
        return {"seen": context}

    def decide(self, observation: object) -> dict[str, object]:
        self.decisions.append(observation)
        return {"bid": 1, "from": observation}

    def act(self, decision: object) -> str:
        self.acts.append(decision)
        return "done"


# -- child-identity helper -------------------------------------------------


def test_make_organ_id_namespaces_under_parent() -> None:
    assert make_organ_id("agent-7", "attention") == "agent-7.attention"


def test_make_organ_id_is_pure() -> None:
    assert make_organ_id("sov-1", "memory") == "sov-1.memory"
    assert make_organ_id("", "attention") == ".attention"


# -- runtime_checkable Protocol conformance --------------------------------


def test_fake_organ_conforms_to_protocol() -> None:
    organ = _FakeOrgan()
    assert isinstance(organ, CognitiveOrgan) is True


def test_base_organ_instance_conforms_to_protocol() -> None:
    organ = BaseCognitiveOrgan(name="memory")
    assert isinstance(organ, CognitiveOrgan) is True


def test_plain_object_does_not_conform() -> None:
    # Guards that the Protocol is not trivially satisfied by everything.
    assert isinstance(object(), CognitiveOrgan) is False


# -- identity stability ----------------------------------------------------


def test_organ_id_stable_across_life() -> None:
    organ = _FakeOrgan()
    organ.attach(_FakeParent(agent_id="agent-7"))
    assert organ.organ_id == "agent-7.attention"

    # Running the cycle does not mutate identity.
    organ.act(organ.decide(organ.perceive({"mention": True})))
    assert organ.organ_id == "agent-7.attention"

    # Identity remains inspectable post-detach.
    organ.detach()
    assert organ.organ_id == "agent-7.attention"


def test_unattached_organ_id_is_unnamespaced() -> None:
    organ = _FakeOrgan()
    assert organ.parent_id == ""
    assert organ.organ_id == ".attention"


# -- lifecycle: attach/detach idempotency + state tracking -----------------


def test_attach_tracks_state() -> None:
    organ = _FakeOrgan()
    assert organ.attached is False
    assert organ.parent_id == ""

    organ.attach(_FakeParent(agent_id="agent-7"))
    assert organ.attached is True
    assert organ.parent_id == "agent-7"


def test_attach_is_idempotent() -> None:
    organ = _FakeOrgan()
    parent = _FakeParent(agent_id="agent-7")
    organ.attach(parent)
    organ.attach(parent)  # second attach is a safe no-op
    assert organ.attached is True
    assert organ.parent_id == "agent-7"
    assert organ.organ_id == "agent-7.attention"


def test_attach_different_parent_while_attached_is_ignored() -> None:
    organ = _FakeOrgan()
    organ.attach(_FakeParent(agent_id="agent-7"))
    organ.attach(_FakeParent(agent_id="agent-99"))  # ignored — 1:1 ownership
    assert organ.parent_id == "agent-7"
    assert organ.organ_id == "agent-7.attention"


def test_detach_is_idempotent() -> None:
    organ = _FakeOrgan()
    organ.attach(_FakeParent(agent_id="agent-7"))
    organ.detach()
    organ.detach()  # second detach is a safe no-op
    assert organ.attached is False


def test_detach_before_attach_is_safe() -> None:
    organ = _FakeOrgan()
    organ.detach()  # no attach yet — must not raise
    assert organ.attached is False
    assert organ.parent_id == ""


def test_attach_detach_reattach_keeps_identity_stable() -> None:
    organ = _FakeOrgan()
    parent = _FakeParent(agent_id="agent-7")
    organ.attach(parent)
    organ.detach()
    organ.attach(parent)  # re-attach to the same parent
    assert organ.attached is True
    assert organ.organ_id == "agent-7.attention"


# -- parent-id resolution (AD-441 sovereign-id preference) -----------------


def test_attach_prefers_sovereign_id() -> None:
    organ = _FakeOrgan()
    organ.attach(_FakeParent(agent_id="agent-7", sovereign_id="sov-1"))
    assert organ.parent_id == "sov-1"
    assert organ.organ_id == "sov-1.attention"


def test_attach_falls_back_to_runtime_id_when_no_sovereign() -> None:
    organ = _FakeOrgan()
    organ.attach(_FakeParent(agent_id="agent-7", sovereign_id=""))
    assert organ.parent_id == "agent-7"


# -- the cognitive cycle is sync + deterministic-by-default ----------------


def test_cycle_methods_are_synchronous() -> None:
    # Encodes the "no await on the cycle path" discipline (§9): a future change
    # making these async would break this guard.
    organ = _FakeOrgan()
    for method in (organ.perceive, organ.decide, organ.act):
        assert inspect.iscoroutinefunction(method) is False
    for method in (
        BaseCognitiveOrgan.perceive,
        BaseCognitiveOrgan.decide,
        BaseCognitiveOrgan.act,
    ):
        assert inspect.iscoroutinefunction(method) is False


def test_default_cycle_is_deterministic_noop() -> None:
    organ = BaseCognitiveOrgan(name="memory")
    assert organ.perceive({"x": 1}) is None
    assert organ.decide({"x": 1}) is None
    assert organ.act({"x": 1}) is None


def test_concrete_cycle_runs_deterministically() -> None:
    organ = _FakeOrgan()
    observation = organ.perceive({"mention": True})
    decision = organ.decide(observation)
    result = organ.act(decision)
    assert observation == {"seen": {"mention": True}}
    assert decision == {"bid": 1, "from": {"seen": {"mention": True}}}
    assert result == "done"
    assert organ.perceived == [{"mention": True}]


# -- audit hook (decoupled from the cognitive journal, AD-431) -------------


def test_audit_emit_default_is_noop() -> None:
    # An unwired organ emits silently (byte-identical default).
    organ = _FakeOrgan()
    organ._emit_audit_trace("perceive", {"k": "v"})  # must not raise


def test_set_audit_emit_injects_sink() -> None:
    captured: list[dict[str, object]] = []

    def _sink(trace) -> None:  # type: ignore[no-untyped-def]
        captured.append(dict(trace))

    organ = _FakeOrgan()
    organ.attach(_FakeParent(agent_id="agent-7"))
    organ.set_audit_emit(_sink)
    organ._emit_audit_trace("decide", {"bid": 3})

    assert len(captured) == 1
    assert captured[0]["organ_id"] == "agent-7.attention"
    assert captured[0]["phase"] == "decide"
    assert captured[0]["bid"] == 3


def test_audit_emit_failure_is_swallowed() -> None:
    def _bad_sink(trace) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("sink exploded")

    organ = _FakeOrgan()
    organ.set_audit_emit(_bad_sink)
    organ._emit_audit_trace("act")  # log-and-degrade: must not raise


def test_set_audit_emit_none_restores_noop() -> None:
    captured: list[object] = []
    organ = _FakeOrgan()
    organ.set_audit_emit(lambda trace: captured.append(trace))
    organ.set_audit_emit(None)  # restore the no-op default
    organ._emit_audit_trace("perceive")
    assert captured == []


# -- construction guards ---------------------------------------------------


def test_base_requires_name() -> None:
    with pytest.raises(ValueError):
        BaseCognitiveOrgan()  # no default_name, no name= → invalid


def test_name_override_via_init() -> None:
    organ = _FakeOrgan(name="custom")
    assert organ.name == "custom"
    organ.attach(_FakeParent(agent_id="agent-7"))
    assert organ.organ_id == "agent-7.custom"


# -- non-membership (an organ is NOT a mesh agent) -------------------------


def test_organ_is_not_a_mesh_agent() -> None:
    # The cheap structural proof of non-membership (§2.1): an organ does not share
    # the BaseAgent surface — no tier, no trust score, no vote, no mesh lifecycle.
    from probos.substrate.agent import BaseAgent

    assert not issubclass(BaseCognitiveOrgan, BaseAgent)

    organ = _FakeOrgan()
    for forbidden in (
        "tier",
        "trust_score",
        "capabilities",
        "report",
        "start",
        "stop",
        "intent_descriptors",
    ):
        assert not hasattr(organ, forbidden), (
            f"Organ must not expose mesh-agent member {forbidden!r}"
        )


# -- no runtime side effects (byte-identical) ------------------------------


def test_module_is_standalone_no_side_effects() -> None:
    # The contract module imports nothing from probos: no registry, no runtime, no
    # mesh — so importing it cannot register an organ or change runtime behavior.
    import probos.cognitive.organ as organ_mod

    source = inspect.getsource(organ_mod)
    assert "import probos" not in source
    assert "from probos" not in source


def test_import_smoke_runtime_and_contract() -> None:
    # The acceptance smoke: the runtime still imports alongside the new contract.
    import probos.runtime  # noqa: F401

    assert CognitiveOrgan is not None
    assert callable(make_organ_id)
    assert OrganAuditEmit is not None
