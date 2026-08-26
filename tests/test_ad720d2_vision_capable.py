"""AD-720d-2 (Wave 154): per-agent vision_capable gating.

Vision-bearing DMs are routed through the vision tier only when the
receiving agent's CrewProfile.vision_capable is True. Otherwise the
turn falls back to the text-only attachment-augmentation path so the
Captain's intent (the image marker + extracted text) is preserved
without smuggling pixels into a non-vision agent's prompt.

The default for an unflagged crew profile is False. Counselor and
Architect default to True via seed YAML.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.config import AttachmentsConfig, CognitiveConfig
from probos.crew_profile import CallsignRegistry, CrewProfile, load_seed_profile

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def test_crew_profile_vision_capable_round_trip():
    """CrewProfile.vision_capable defaults False and survives to_dict/from_dict."""
    prof = CrewProfile(agent_id="a1", agent_type="counselor")
    assert prof.vision_capable is False

    flipped = CrewProfile(agent_id="a2", agent_type="counselor", vision_capable=True)
    rt = CrewProfile.from_dict(flipped.to_dict())
    assert rt.vision_capable is True

    # Unset key in incoming dict still produces default False
    legacy = CrewProfile.from_dict({"agent_id": "a3", "agent_type": "scout"})
    assert legacy.vision_capable is False


def test_default_crew_seed_counselor_and_architect_vision_capable():
    """Counselor + Architect seed YAMLs flip vision_capable on; others do not."""
    counselor_seed = load_seed_profile("counselor")
    architect_seed = load_seed_profile("architect")
    scout_seed = load_seed_profile("scout")
    default_seed = load_seed_profile("_default")

    assert counselor_seed.get("vision_capable") is True
    assert architect_seed.get("vision_capable") is True
    # Other crew DO NOT set the field — they inherit the dataclass default.
    assert "vision_capable" not in scout_seed
    # _default.yaml must not opt every agent in by accident.
    assert default_seed.get("vision_capable") is not True


def test_callsign_registry_exposes_vision_capable_on_profile():
    """CallsignRegistry.get_profile() surfaces vision_capable from the seed YAMLs."""
    reg = CallsignRegistry()
    reg.load_from_profiles()
    counselor_prof = reg.get_profile("counselor")
    scout_prof = reg.get_profile("scout")
    assert counselor_prof is not None
    assert counselor_prof.get("vision_capable") is True
    assert scout_prof is not None
    # Scout inherits the dataclass default via the registry plumbing.
    assert scout_prof.get("vision_capable", False) is False


@pytest.fixture
async def agents_client(monkeypatch, tmp_path):
    """FastAPI test client wrapping /api/agent routes with a stub runtime."""
    import probos.routers.agents as agents_router_mod
    import probos.routers.chat as chat_router_mod
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.routers.deps import get_runtime

    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )

    cfg_attach = AttachmentsConfig(
        attachments_dir=str(target),
        max_attachment_bytes=10 * 1024 * 1024,
        text_extraction_max_bytes=1024,
        vision_tier="vision",
        pdf_extraction_enabled=False,
    )
    cfg_cognitive = CognitiveConfig(
        llm_base_url_vision="http://127.0.0.1:11434/v1",
        llm_model_vision="llava:34b",
    )

    llm_client = MagicMock()
    llm_client.complete = AsyncMock()
    llm_client.get_health_status = MagicMock(
        return_value={"tiers": {"vision": {"status": "operational"}}, "overall": "operational"},
    )

    intent_bus = SimpleNamespace()
    sent: list = []

    async def _send(intent, **kwargs):
        # BF-790: the real ``IntentBus.send`` grew a ``raise_on_denial``
        # keyword, and ``/api/agent/{id}/chat`` now passes it so a policy
        # denial renders 403 instead of a 200 with an empty reply. This double
        # rejected the keyword and every request through it became a 500.
        #
        # ``**kwargs`` rather than the one named parameter, because the point
        # of this fixture is the VISION routing -- it should not have to be
        # edited again the next time an unrelated keyword is added to the bus.
        sent.append(intent)
        return SimpleNamespace(result="ack", success=True)

    intent_bus.send = _send

    # Stub registry returning a single agent
    agent = SimpleNamespace(
        id="agent-1",
        agent_type="counselor",
        is_alive=True,
    )
    registry = SimpleNamespace(
        get=lambda aid: agent if aid == "agent-1" else None,
        get_by_pool=lambda t: [agent] if t == "counselor" else [],
    )

    callsigns = CallsignRegistry()
    callsigns.bind_registry(registry)

    rt = SimpleNamespace(
        config=SimpleNamespace(attachments=cfg_attach, cognitive=cfg_cognitive),
        llm_client=llm_client,
        intent_bus=intent_bus,
        registry=registry,
        callsign_registry=callsigns,
        ontology=None,
    )

    # is_crew_agent gate — patch to always return True for this stub.
    monkeypatch.setattr(
        agents_router_mod, "is_crew_agent", lambda agent, ontology: True
    )

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    a = FastAPI()
    a.include_router(agents_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt

    store = FilesystemAttachmentStore(target)

    async def _write(blob: bytes, mime: str) -> str:
        sha = hashlib.sha256(blob).hexdigest()
        await store.write(sha, blob, mime)
        return sha

    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, rt, _write, callsigns, sent

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_agent_chat_vision_capable_false_routes_to_text_fallback(agents_client):
    """vision_capable=False → image_ids cleared → text-only fallback; no vision_messages on intent."""
    ac, rt, write_blob, callsigns, sent = agents_client
    # Inject a profile where vision is OFF.
    callsigns._type_to_profile["counselor"] = {
        "display_name": "Counselor",
        "department": "bridge",
        "vision_capable": False,
    }
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/agent/agent-1/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    # The IntentMessage forwarded to the agent MUST NOT carry vision_messages.
    assert len(sent) == 1
    intent = sent[0]
    assert "vision_messages" not in intent.params


@pytest.mark.asyncio
async def test_agent_chat_vision_capable_true_routes_to_vision_tier(agents_client):
    """vision_capable=True → IntentMessage carries vision_messages + has_image_attachment."""
    ac, rt, write_blob, callsigns, sent = agents_client
    callsigns._type_to_profile["counselor"] = {
        "display_name": "Counselor",
        "department": "bridge",
        "vision_capable": True,
    }
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/agent/agent-1/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    assert len(sent) == 1
    intent = sent[0]
    assert "vision_messages" in intent.params
    assert intent.params.get("has_image_attachment") is True
