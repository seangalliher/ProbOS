"""BF-744 (#1131 prerequisite): a build through the ladder had no consensus gate.

Found while checking whether #1131's reroute -- "route every capability gap
through the AD-854 ladder" -- could be done as a simple redirect. It could not,
and the reason is a governance defect that already ships.

`fulfil_build` called the pipeline with three positionals:

    handle_unhandled_intent(gap_target, rationale, {})

`handle_unhandled_intent` declares `requires_consensus: bool = False`. So every
agent designed through the capability ladder was built with **no consensus
gate**, however destructive the gap that produced it. The standing rule is the
opposite: destructive intents must set `requires_consensus=True`.

The NL path in `runtime.py` does pass it, along with the extracted description,
the parameters and the execution context. So the two producers of a designed
agent disagreed about its governance, and the governed-looking one was the
weaker of the two -- which is the worst arrangement, because it is the one a
reviewer would trust.

The context now rides on `CapabilityRequest.payload`, so it survives to a LATER
Captain approval as well. That path was strictly worse than file-time before:
approving a pending build designed from `rationale` alone.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.cognitive.capability_triage import (
    _DESIGN_CONTEXT_KEYS,
    _build_payload,
    fulfil_build,
)


class _Pipeline:
    """Records exactly what the pipeline was asked to design."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def handle_unhandled_intent(self, *args: Any, **kw: Any) -> Any:
        self.calls.append((args, kw))
        return type("R", (), {"status": "active"})()


class _Store:
    def __init__(self) -> None:
        self.fulfilled: list[str] = []

    async def mark_fulfilled(self, request_id: str) -> Any:
        self.fulfilled.append(request_id)
        return type("Req", (), {"id": request_id, "status": "fulfilled"})()


def _run(design_context: Any = None) -> _Pipeline:
    pipe = _Pipeline()
    asyncio.run(fulfil_build(
        "req-1",
        store=_Store(),
        gap_target="delete_everything",
        rationale="the gap",
        self_mod_pipeline=pipe,
        design_context=design_context,
    ))
    return pipe


# ── the defect ────────────────────────────────────────────────────


def test_a_destructive_gap_now_designs_with_consensus_required() -> None:
    """The headline. Before BF-744 this call could not express it at all."""
    pipe = _run({"requires_consensus": True})
    _args, kw = pipe.calls[0]
    assert kw["requires_consensus"] is True


def test_a_non_destructive_gap_still_designs_without_consensus() -> None:
    pipe = _run({"requires_consensus": False})
    assert pipe.calls[0][1]["requires_consensus"] is False


def test_the_description_and_parameters_reach_the_designer() -> None:
    """Three positionals meant the pipeline designed from the rationale string
    and an empty parameter dict, whatever the gap actually described.
    """
    pipe = _run({
        "intent_description": "remove a file from disk",
        "parameters": {"path": "absolute path to remove"},
    })
    args, _kw = pipe.calls[0]
    assert args[1] == "remove a file from disk"
    assert args[2] == {"path": "absolute path to remove"}


def test_execution_context_reaches_the_designer() -> None:
    pipe = _run({"execution_context": "last run produced report.md"})
    assert pipe.calls[0][1]["execution_context"] == "last run produced report.md"


# ── absent context is byte-identical to the old call ──────────────


@pytest.mark.parametrize("ctx", [None, {}, "not a dict", 42, []])
def test_no_context_reproduces_the_previous_behaviour(ctx: Any) -> None:
    """A caller with nothing to add must be unchanged -- name, rationale as the
    description, empty parameters, no consensus.
    """
    pipe = _run(ctx)
    args, kw = pipe.calls[0]
    assert args[0] == "delete_everything"
    assert args[1] == "the gap"
    assert args[2] == {}
    assert kw["requires_consensus"] is False
    assert kw["execution_context"] == ""


def test_a_hostile_parameters_value_does_not_reach_the_designer() -> None:
    """``parameters`` is typed dict[str, str] and the shape gate reads it. A
    payload arriving from the store is not trusted to be well-formed.
    """
    for bad in ("x", 3, [], None):
        pipe = _run({"parameters": bad})
        assert pipe.calls[0][0][2] == {}


# ── the payload the request carries is bounded ────────────────────


def test_only_the_four_design_keys_are_persisted() -> None:
    """The request payload must not become an open side-channel: what the
    Captain approves has to be what gets designed.
    """
    payload = _build_payload({
        "intent_description": "d",
        "requires_consensus": True,
        "smuggled": "should not survive",
        "source_code": "import os; os.system('...')",
    })
    assert payload == {"intent_description": "d", "requires_consensus": True}
    assert set(payload).issubset(set(_DESIGN_CONTEXT_KEYS))


@pytest.mark.parametrize("ctx", [None, {}, "no", 7, {"unrelated": 1}])
def test_nothing_worth_carrying_stores_no_payload(ctx: Any) -> None:
    assert _build_payload(ctx) is None


def test_a_build_request_carries_its_design_context_to_a_later_approval() -> None:
    """The approve-later path was strictly worse than file-time: it designed
    from ``rationale`` alone. Now it reads what was recorded when the gap was
    triaged.
    """
    import inspect

    from probos.routers import capability_requests

    src = inspect.getsource(capability_requests._fulfil_build_request)
    assert "design_context=decided.payload" in src


def test_the_ladder_and_the_nl_path_agree_on_what_a_build_needs() -> None:
    """The two producers of a designed agent disagreed about its governance,
    and the governed-looking one was the weaker. Both now name the same four.
    """
    import inspect

    from probos.cognitive import self_mod

    sig = inspect.signature(self_mod.SelfModificationPipeline.handle_unhandled_intent)
    for key in _DESIGN_CONTEXT_KEYS:
        expected = "intent_description" if key == "intent_description" else key
        assert expected in sig.parameters, key
