"""AD-1203 (#1147): a Captain-visible claim resolves to the calls behind it.

The agentic DM run already persisted a complete tool trace (AD-1151) and
computed its content hash, and then dropped it. The crew path records the ref
(``fault_report.tool_trace_ref``); the 1:1 path did not, so there was no way --
from outside the process -- to tie something the agent said to what it did.

This threads the ref: agentic run -> observation -> decision -> act -> the
IntentResult the caller receives -> the reply message's metadata, where
``GET /api/traces/{ref}`` can resolve it.

Every hop is additive and absent on a non-agentic turn, so those turns are
byte-identical.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.routers import traces as traces_router
from probos.routers.deps import get_runtime
from probos.types import IntentResult

REF = "a1b2c3d4e5f6" + "0" * 52
TRACE = [
    {"id": "1", "name": "http_fetch", "arguments": {"url": "https://pypi.org/x"},
     "output": "{}", "is_error": False, "output_chars": 2},
]


class _Agent(CognitiveAgent):
    def __init__(self) -> None:
        self.id = "counselor_counselor_0_test"
        self.agent_type = "counselor"
        self._llm_client = None
        self._runtime = None


# ── the carrier ───────────────────────────────────────────────────


def test_intent_result_metadata_defaults_to_empty() -> None:
    """Additive: every existing producer constructs IntentResult without it."""
    r = IntentResult(intent_id="i1", agent_id="a1", success=True)

    assert r.metadata == {}


def test_intent_result_metadata_is_not_shared_between_instances() -> None:
    """``default_factory``, not a mutable default -- one turn's provenance must
    not leak into another's.
    """
    a = IntentResult(intent_id="i1", agent_id="a1", success=True)
    b = IntentResult(intent_id="i2", agent_id="a1", success=True)

    a.metadata["tool_trace_ref"] = REF

    assert b.metadata == {}


# ── act() forwards it ─────────────────────────────────────────────


async def test_act_forwards_the_trace_ref_when_the_run_produced_one() -> None:
    out = await _Agent().act({
        "action": "execute", "llm_output": "here you go", "_tool_trace_ref": REF,
    })

    assert out["success"] is True
    assert out["result"] == "here you go"
    assert out["_tool_trace_ref"] == REF


async def test_act_omits_the_key_entirely_on_a_non_agentic_turn() -> None:
    """Absent, not empty-string: the IntentResult check is truthiness, and an
    empty key would still be a key for anything iterating the report.
    """
    out = await _Agent().act({"action": "execute", "llm_output": "hello"})

    assert out == {"success": True, "result": "hello"}


async def test_act_still_short_circuits_an_error_decision() -> None:
    out = await _Agent().act({"action": "error", "reason": "no llm"})

    assert out == {"success": False, "error": "no llm"}


@pytest.mark.parametrize("intent_name", ["direct_message", "ward_room_notification"])
async def test_act_result_is_unchanged_for_the_ad407b_conversational_intents(
    intent_name: str,
) -> None:
    """AD-407b had an explicit branch for these two that returned exactly what
    the fallthrough returned. Collapsing it is behaviour-preserving; this pins
    that so the equivalence is asserted rather than assumed.
    """
    out = await _Agent().act({
        "action": "execute", "intent": intent_name, "llm_output": "spoken",
    })

    assert out == {"success": True, "result": "spoken"}


# ── the reply message carries it ──────────────────────────────────


def _reply_metadata(result: Any, response: dict | None = None) -> dict:
    """The construction ``routers/agents.py`` performs at the append.

    Calls the production helper rather than restating it. A restatement drifts
    silently -- BF-766 review showed the mirror plus an existence check passed
    while the real value came from the wrong source.
    """
    from probos.routers.agents import _build_reply_metadata

    return _build_reply_metadata("intent-1", result, response)


def test_reply_metadata_carries_the_ref_from_an_agentic_turn() -> None:
    result = IntentResult(
        intent_id="i1", agent_id="a1", success=True,
        metadata={"tool_trace_ref": REF},
    )

    assert _reply_metadata(result) == {"intent_id": "intent-1", "tool_trace_ref": REF}


def test_reply_metadata_is_byte_identical_on_a_non_agentic_turn() -> None:
    result = IntentResult(intent_id="i1", agent_id="a1", success=True)

    assert _reply_metadata(result) == {"intent_id": "intent-1"}


@pytest.mark.parametrize("result", [None, SimpleNamespace(), "a string", 0])
def test_reply_metadata_degrades_on_any_result_shape(result: Any) -> None:
    """``intent_bus.send`` can return None, and a fake runtime can return
    anything. Recording provenance must never break the append that carries the
    Captain's reply.
    """
    assert _reply_metadata(result) == {"intent_id": "intent-1"}


# ── THE CROSSING TEST ─────────────────────────────────────────────


class _Store:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    async def list_by_origin(self, origin: str) -> list[tuple[str, float]]:
        return [(h, 1.0) for h in self._blobs]

    async def read(self, content_hash: str) -> bytes:
        if content_hash not in self._blobs:
            raise FileNotFoundError(content_hash)
        return self._blobs[content_hash]


async def test_the_crossing_agentic_run_to_reply_metadata_to_the_calls() -> None:
    """A run produces a trace -> act carries the ref -> the IntentResult carries
    it -> the reply message metadata carries it -> GET /api/traces/{ref} returns
    the calls behind the claim.

    This is the chain #1147 says does not exist. Nothing in the middle is
    stubbed except the transport itself.
    """
    agent = _Agent()

    # 1. The agentic run reported this trace ref on the decision.
    report = await agent.act({
        "action": "execute", "llm_output": "boto3 is 1.43.67", "_tool_trace_ref": REF,
    })

    # 2. The IntentResult the caller receives, built exactly as handle_intent does.
    result = IntentResult(
        intent_id="i1", agent_id=agent.id, success=True,
        result=report.get("result"),
        metadata=(
            {"tool_trace_ref": report["_tool_trace_ref"]}
            if report.get("_tool_trace_ref") else {}
        ),
    )

    # 3. The reply message the Captain sees records it.
    meta = _reply_metadata(result)
    assert meta["tool_trace_ref"] == REF

    # 4. That ref resolves to the calls behind the claim.
    app = FastAPI()
    app.include_router(traces_router.router)
    store = _Store({REF: json.dumps(TRACE).encode("utf-8")})
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(
        attachment_store=store,
    )
    resp = TestClient(app).get(f"/api/traces/{meta['tool_trace_ref']}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["calls"] == TRACE
    assert body["summary"]["tools_used"] == ["http_fetch"]
    assert body["summary"]["total_calls"] == 1


def test_the_router_records_the_ref_at_the_append_site() -> None:
    """The wiring above is only real if the production append performs it. A
    static check, because the alternative is booting the whole DM router.
    """
    import inspect

    from probos.routers import agents as agents_router

    src = inspect.getsource(agents_router)

    assert 'metadata=_reply_meta' in src
    assert '"tool_trace_ref"' in src


def test_the_router_records_the_emotion_at_the_append_site() -> None:
    """BF-766: the AD-738e-1 emotion rode only on the chat HTTP response, but
    the server pushes CHAT_THREAD_MESSAGE_APPENDED before returning that body,
    so the transcript usually wins the shared speech claim and spoke flat.

    Asserted on the VALUE, not on the presence of an assignment. An existence
    check -- even an AST one -- survives the assignment being fed the wrong
    source, which review demonstrated.
    """
    result = IntentResult(intent_id="i1", agent_id="a1", success=True)

    assert _reply_metadata(result, {"emotion": "warm"}) == {
        "intent_id": "intent-1", "emotion": "warm",
    }


@pytest.mark.parametrize(
    "response",
    [None, {}, {"emotion": None}, {"emotion": ""}],
    ids=["absent", "empty-dict", "null", "empty-string"],
)
def test_a_turn_without_an_emotion_keeps_byte_identical_metadata(response) -> None:
    """Rows persisted before this carried no emotion key, and every turn whose
    reply has none must stay exactly as it was."""
    result = IntentResult(intent_id="i1", agent_id="a1", success=True)

    assert _reply_metadata(result, response) == {"intent_id": "intent-1"}


def test_the_emotion_and_the_trace_ref_do_not_displace_each_other() -> None:
    result = IntentResult(
        intent_id="i1", agent_id="a1", success=True,
        metadata={"tool_trace_ref": REF},
    )

    assert _reply_metadata(result, {"emotion": "concerned"}) == {
        "intent_id": "intent-1", "tool_trace_ref": REF, "emotion": "concerned",
    }


def test_a_malformed_response_never_breaks_the_append() -> None:
    """The append carries the Captain's reply; recording prosody must not be
    able to stop it."""
    result = IntentResult(intent_id="i1", agent_id="a1", success=True)

    for bad in ("a string", 0, SimpleNamespace()):
        assert _reply_metadata(result, bad) == {"intent_id": "intent-1"}


def test_the_append_site_uses_the_helper() -> None:
    """The value tests above are only real if production calls this. A static
    check, because the alternative is booting the whole DM router."""
    import inspect

    from probos.routers import agents as agents_router

    src = inspect.getsource(agents_router)

    assert "_reply_meta = _build_reply_metadata(intent.id, result, response)" in src
