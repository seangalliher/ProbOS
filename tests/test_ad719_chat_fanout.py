"""AD-719: tests for multi-agent chat fan-out + helper.

Covers:
- extract_all_leading_callsign_mentions helper (zero / one / N / unknown)
- /api/chat fan-out branch (zero / single / two / unknown / off-duty)
- ChatResponse + PerAgentReply Pydantic shape
- Defense: no consensus import path on the fan-out branch
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from probos.api import create_app
from probos.api_models import ChatResponse, PerAgentReply
from probos.cognitive.llm_client import MockLLMClient
from probos.crew_profile import extract_all_leading_callsign_mentions
from probos.runtime import ProbOSRuntime


# ── Helper tests ──────────────────────────────────────────────────


def test_extract_all_leading_callsigns_zero_mentions():
    assert extract_all_leading_callsign_mentions("hello team") == ([], "hello team")


def test_extract_all_leading_callsigns_one_mention():
    assert extract_all_leading_callsign_mentions("@counselor hi") == (["counselor"], "hi")


def test_extract_all_leading_callsigns_n_mentions():
    callsigns, remaining = extract_all_leading_callsign_mentions(
        "@counselor @worf @echo hello team"
    )
    assert callsigns == ["counselor", "worf", "echo"]
    assert remaining == "hello team"


def test_extract_all_leading_callsigns_unknown_callsign_passes_through():
    # Helper does not validate against the registry — that's the caller's job.
    callsigns, remaining = extract_all_leading_callsign_mentions("@ghost hi")
    assert callsigns == ["ghost"]
    assert remaining == "hi"


def test_extract_all_leading_callsigns_lowercased():
    callsigns, _ = extract_all_leading_callsign_mentions("@Counselor @WORF hi")
    assert callsigns == ["counselor", "worf"]


def test_extract_all_leading_callsigns_empty_input():
    assert extract_all_leading_callsign_mentions("") == ([], "")


def test_extract_all_leading_callsigns_only_mentions_no_message():
    callsigns, remaining = extract_all_leading_callsign_mentions("@a @b")
    assert callsigns == ["a", "b"]
    assert remaining == ""


# ── Pydantic model tests ──────────────────────────────────────────


def test_chat_response_model_backward_compat():
    """ChatResponse(response='x') validates with empty defaults for AD-719 fields."""
    r = ChatResponse(response="x")
    assert r.mentions == []
    assert r.per_agent_replies == []
    assert r.dag is None


def test_chat_response_per_agent_reply_round_trip():
    reply = PerAgentReply(agent_id="a-1", callsign="counselor", text="hi")
    response = ChatResponse(response="", per_agent_replies=[reply], mentions=["counselor"])
    dump = response.model_dump()
    assert dump["per_agent_replies"] == [{"agent_id": "a-1", "callsign": "counselor", "text": "hi"}]
    assert dump["mentions"] == ["counselor"]


# ── Endpoint tests ────────────────────────────────────────────────


@pytest.fixture
async def chat_client(tmp_path):
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    app = create_app(rt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, rt
    await rt.stop()


@pytest.mark.asyncio
async def test_chat_fanout_zero_mentions_falls_through_to_nl(chat_client):
    """No leading @ — existing NL path runs; per_agent_replies absent or empty."""
    client, _rt = chat_client
    r = await client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 200
    data = r.json()
    # Either field absent (legacy NL path returns dict without it) or empty.
    assert not data.get("per_agent_replies")
    assert not data.get("mentions")


def _single_word_callsigns(rt) -> list[str]:
    """Return callsigns that contain no whitespace (\\w+ regex compatible)."""
    return [c for c in rt.callsign_registry.all_callsigns().values() if " " not in c and c]


@pytest.mark.asyncio
async def test_chat_fanout_single_mention_uses_existing_dm_path(chat_client):
    """One @callsign — single-mention DM short-circuit; no per_agent_replies."""
    client, rt = chat_client
    callsigns = _single_word_callsigns(rt)
    if not callsigns:
        pytest.skip("No single-word crew callsigns registered")
    cs = callsigns[0]
    r = await client.post("/api/chat", json={"message": f"@{cs} hi"})
    assert r.status_code == 200
    data = r.json()
    # Single-mention path returns empty/absent per_agent_replies.
    assert not data.get("per_agent_replies")


@pytest.mark.asyncio
async def test_chat_fanout_two_mentions_returns_per_agent_replies(chat_client):
    """Two @callsigns — fan-out branch produces per_agent_replies of length 2."""
    client, rt = chat_client
    callsigns = _single_word_callsigns(rt)
    if len(callsigns) < 2:
        pytest.skip("Need at least 2 single-word crew callsigns")
    a, b = callsigns[0], callsigns[1]
    r = await client.post("/api/chat", json={"message": f"@{a} @{b} hello team"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("mentions") == [a.lower(), b.lower()]
    replies = data.get("per_agent_replies") or []
    assert len(replies) == 2
    callsigns_in_replies = {r["callsign"].lower() for r in replies}
    assert callsigns_in_replies == {a.lower(), b.lower()}


@pytest.mark.asyncio
async def test_chat_fanout_unknown_callsign_returns_stub(chat_client):
    """Two mentions, one unknown — known reply present, unknown gets stub."""
    client, rt = chat_client
    callsigns = _single_word_callsigns(rt)
    if not callsigns:
        pytest.skip("No single-word crew callsigns")
    known = callsigns[0]
    r = await client.post("/api/chat", json={"message": f"@{known} @ghostsentinel hi"})
    assert r.status_code == 200
    data = r.json()
    replies = data.get("per_agent_replies") or []
    assert len(replies) == 2
    ghost = next((r for r in replies if r["callsign"].lower() == "ghostsentinel"), None)
    assert ghost is not None
    assert "not recognized" in ghost["text"].lower() or "not currently on duty" in ghost["text"].lower()
    assert ghost["agent_id"] == ""


@pytest.mark.asyncio
async def test_chat_fanout_off_duty_callsign_returns_stub(chat_client):
    """An on-registry but agent_id-None callsign returns a stub reply.

    We force this by patching CallsignRegistry.resolve to return agent_id=None
    for the second callsign while keeping the first live.
    """
    client, rt = chat_client
    callsigns = _single_word_callsigns(rt)
    if len(callsigns) < 2:
        pytest.skip("Need at least 2 single-word crew callsigns")
    a, b = callsigns[0], callsigns[1]
    real_resolve = rt.callsign_registry.resolve

    def stub_resolve(cs: str):
        if cs.lower() == b.lower():
            return {"callsign": b, "agent_type": "x", "agent_id": None,
                    "display_name": "", "department": ""}
        return real_resolve(cs)

    with patch.object(rt.callsign_registry, "resolve", side_effect=stub_resolve):
        r = await client.post("/api/chat", json={"message": f"@{a} @{b} hi"})
    assert r.status_code == 200
    data = r.json()
    replies = data.get("per_agent_replies") or []
    off_duty = next((r for r in replies if r["callsign"].lower() == b.lower()), None)
    assert off_duty is not None
    assert "not currently on duty" in off_duty["text"].lower()
    assert off_duty["agent_id"] == ""


@pytest.mark.asyncio
async def test_chat_fanout_does_not_import_consensus(chat_client):
    """Hard-stop guard: fan-out branch must NOT touch probos.consensus.quorum.

    We patch a bogus attribute on the consensus module and assert no call.
    """
    client, rt = chat_client
    callsigns = _single_word_callsigns(rt)
    if len(callsigns) < 2:
        pytest.skip("Need at least 2 single-word crew callsigns")
    a, b = callsigns[0], callsigns[1]
    import probos.consensus.quorum as qmod
    # If the fan-out path ever calls into quorum, this spy will see it.
    with patch.object(qmod, "QuorumEngine", side_effect=AssertionError("consensus touched on fan-out")):
        r = await client.post("/api/chat", json={"message": f"@{a} @{b} ping"})
    assert r.status_code == 200
