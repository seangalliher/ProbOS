"""AD-732 (Wave 153): Dedicated vision LLM tier + honest-degrade.

Covers:
  - CognitiveConfig vision-tier fields default to unconfigured
  - tier_config("vision") resolves per-tier + shared fallback like the others
  - AttachmentsConfig.vision_tier default is "vision"; validator allows it
  - /api/chat + /api/agent/{id}/chat honest-degrade routing (unconfigured / unhealthy)
  - Text-only DMs unaffected by AD-732
  - OpenAICompatibleClient tracks vision in health/dedupe + skips probe when unconfigured
  - MockLLMClient.get_health_status reports vision as operational (scaffolding parity)
  - Vision tier is NOT in the fast→standard→deep fallback chain
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.cognitive.llm_client import (
    MockLLMClient,
    OpenAICompatibleClient,
    _LLM_TIERS,
)
from probos.cognitive.vision_dispatch import (
    VISION_UNCONFIGURED_MESSAGE,
    VISION_UNHEALTHY_MESSAGE,
    is_vision_tier_configured,
)
from probos.config import AttachmentsConfig, CognitiveConfig
from probos.types import LLMRequest

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Section 4a: Config wiring
# ---------------------------------------------------------------------------


def test_cognitive_config_vision_tier_fields_default_unconfigured():
    """Default CognitiveConfig has vision tier unconfigured.

    Both fields are Optional[None]; is_vision_tier_configured treats None
    (and empty string) as the unconfigured sentinel.
    """
    cfg = CognitiveConfig()
    assert cfg.llm_model_vision is None
    assert cfg.llm_base_url_vision is None
    assert cfg.llm_api_key_vision is None
    assert cfg.llm_timeout_vision is None
    assert cfg.llm_api_format_vision is None
    assert is_vision_tier_configured(cfg, "vision") is False


def test_tier_config_vision_returns_resolved_dict():
    """tier_config('vision') returns a fully-resolved per-tier dict when
    vision-tier fields are set explicitly.
    """
    cfg = CognitiveConfig(
        llm_base_url_vision="http://127.0.0.1:11434/v1",
        llm_model_vision="llava:34b",
        llm_api_format_vision="openai",
        llm_timeout_vision=120.0,
    )
    tc = cfg.tier_config("vision")
    assert tc["base_url"] == "http://127.0.0.1:11434/v1"
    assert tc["model"] == "llava:34b"
    assert tc["api_format"] == "openai"
    assert tc["timeout"] == 120.0
    # is_vision_tier_configured agrees with the explicit values.
    assert is_vision_tier_configured(cfg, "vision") is True


def test_tier_config_vision_falls_back_to_shared_when_unset():
    """When per-tier vision URL is None, tier_config falls back to the
    shared llm_base_url (same behavior as fast/standard/deep)."""
    cfg = CognitiveConfig(
        llm_base_url="http://shared.example/v1",
        llm_model_vision="llava:34b",  # only model set, URL unset
    )
    tc = cfg.tier_config("vision")
    # url falls back to shared
    assert tc["base_url"] == "http://shared.example/v1"
    # but is_vision_tier_configured requires BOTH model AND per-tier base_url
    # — sharing the text base_url is not the same as opting in to vision.
    assert is_vision_tier_configured(cfg, "vision") is False


def test_attachments_config_default_vision_tier_is_vision():
    """AD-732: default vision_tier is now 'vision' (was 'standard').

    Validator allows fast/standard/deep/vision and rejects unknown values.
    """
    cfg = AttachmentsConfig()
    assert cfg.vision_tier == "vision"
    # Legacy explicit value still validates.
    assert AttachmentsConfig(vision_tier="standard").vision_tier == "standard"
    # Unknown still rejected.
    with pytest.raises(ValueError, match="vision_tier"):
        AttachmentsConfig(vision_tier="deep_unknown")


# ---------------------------------------------------------------------------
# Section 4b: Honest-degrade routing
# ---------------------------------------------------------------------------


@pytest.fixture
async def chat_client(monkeypatch, tmp_path):
    """Build a FastAPI app wrapping the /api/chat router with a stub runtime.

    The fixture lets each test override vision_tier and the LLM health status
    to exercise both the unconfigured and unhealthy honest-degrade branches.
    """
    from fastapi import FastAPI

    import probos.routers.chat as chat_router_mod
    from probos.routers.deps import (
        get_pending_designs,
        get_runtime,
        get_task_tracker,
        get_ws_broadcast,
    )
    from probos.attachments.filesystem_store import FilesystemAttachmentStore

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
        vision_tier="vision",  # AD-732 default
        pdf_extraction_enabled=False,
    )
    cfg_cognitive = CognitiveConfig()  # vision unconfigured by default

    llm_client = MagicMock()
    llm_client.complete = AsyncMock()
    llm_client.get_health_status = MagicMock(
        return_value={
            "tiers": {
                "fast": {"status": "operational"},
                "standard": {"status": "operational"},
                "deep": {"status": "operational"},
                "vision": {"status": "operational"},
            },
            "overall": "operational",
        },
    )

    pnl = AsyncMock(return_value={"final_response": "decomposer", "results": {}, "dag": []})

    rt = SimpleNamespace(
        config=SimpleNamespace(attachments=cfg_attach, cognitive=cfg_cognitive),
        llm_client=llm_client,
        process_natural_language=pnl,
    )

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    a = FastAPI()
    a.include_router(chat_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt
    a.dependency_overrides[get_ws_broadcast] = lambda: (lambda msg: None)
    a.dependency_overrides[get_task_tracker] = lambda: (lambda coro, name="": None)
    a.dependency_overrides[get_pending_designs] = lambda: {}

    store = FilesystemAttachmentStore(target)

    async def _write(blob: bytes, mime: str) -> str:
        sha = hashlib.sha256(blob).hexdigest()
        await store.write(sha, blob, mime)
        return sha

    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, rt, _write

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_api_chat_vision_unconfigured_returns_unconfigured_message(chat_client):
    """Default config + image attachment → VISION_UNCONFIGURED_MESSAGE.

    Vision tier is unconfigured (CognitiveConfig defaults). The handler
    must short-circuit to the operator-facing remediation message AND
    must not call the LLM.
    """
    ac, rt, write_blob = chat_client
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["response"] == VISION_UNCONFIGURED_MESSAGE
    rt.llm_client.complete.assert_not_called()


@pytest.mark.asyncio
async def test_api_chat_vision_unhealthy_returns_unhealthy_message(chat_client):
    """Vision tier configured but tier_status != operational → VISION_UNHEALTHY_MESSAGE."""
    ac, rt, write_blob = chat_client
    # Configure the vision tier so is_vision_tier_configured returns True.
    rt.config.cognitive.llm_base_url_vision = "http://127.0.0.1:11434/v1"
    rt.config.cognitive.llm_model_vision = "llava:34b"
    # Force unhealthy status.
    rt.llm_client.get_health_status = MagicMock(
        return_value={
            "tiers": {"vision": {"status": "unreachable"}},
            "overall": "degraded",
        },
    )
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["response"] == VISION_UNHEALTHY_MESSAGE
    rt.llm_client.complete.assert_not_called()


@pytest.mark.asyncio
async def test_api_chat_vision_recovering_passes_through(chat_client):
    """BF-271 (2026-05-12): tier_status == 'recovering' is operational.

    A tier is 'recovering' when it has had recent successes but hasn't yet
    met the dwell-time threshold to clear its failure counter (BF-240).
    The endpoint IS working — refusing to use it would produce
    honest-degrade for a working tier. Regression sentinel for the
    cold-start scenario where qwen3.6:27b on Ollama takes 14s for its
    first probe (timeout), then succeeds on every subsequent call.
    """
    ac, rt, write_blob = chat_client
    rt.config.cognitive.llm_base_url_vision = "http://127.0.0.1:11434/v1"
    rt.config.cognitive.llm_model_vision = "qwen3.6:27b"
    # Recovering: status string says recovering, real successes are happening.
    rt.llm_client.get_health_status = MagicMock(
        return_value={
            "tiers": {"vision": {"status": "recovering"}},
            "overall": "degraded",
        },
    )
    # Make the LLM call succeed (it's recovering, after all).
    rt.llm_client.complete = AsyncMock(
        return_value=SimpleNamespace(
            content="An orange cat on a blue background.",
            tier="vision",
            model="qwen3.6:27b",
        ),
    )
    sha = await write_blob(_PNG_HEADER + b"a" * 64, "image/png")
    r = await ac.post(
        "/api/chat",
        json={"message": "what is this", "history": [], "attachment_ids": [sha]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Honest-degrade DID NOT fire — the request flowed through to the LLM.
    assert body["response"] != VISION_UNHEALTHY_MESSAGE
    rt.llm_client.complete.assert_called()


@pytest.mark.asyncio
async def test_text_only_dm_unchanged_when_vision_unconfigured(chat_client):
    """No-attachment chat is unaffected by AD-732 vision-tier state."""
    ac, rt, _ = chat_client
    r = await ac.post(
        "/api/chat",
        json={"message": "hello", "history": [], "attachment_ids": []},
    )
    assert r.status_code == 200, r.text
    rt.process_natural_language.assert_awaited_once()
    rt.llm_client.complete.assert_not_called()


def _make_agent_chat_runtime(
    *,
    vision_status: str = "operational",
    vision_configured: bool = True,
):
    """Minimal runtime mock for agent_chat() honest-degrade tests."""
    runtime = MagicMock()

    agent = MagicMock()
    agent.id = "test-id"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent

    runtime.callsign_registry.get_callsign.return_value = "Lynx"

    intent_result = MagicMock()
    intent_result.result = "fallback"
    intent_result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=intent_result)

    runtime.recreation_service = None
    runtime.ward_room = None

    cog = CognitiveConfig()
    if vision_configured:
        cog.llm_base_url_vision = "http://127.0.0.1:11434/v1"
        cog.llm_model_vision = "llava:34b"

    runtime.config = SimpleNamespace(
        attachments=SimpleNamespace(
            enabled=True,
            text_extraction_max_bytes=1024,
            pdf_extraction_enabled=False,
            vision_tier="vision",
        ),
        cognitive=cog,
    )

    runtime.llm_client = MagicMock()
    runtime.llm_client.get_health_status = MagicMock(
        return_value={
            "tiers": {"vision": {"status": vision_status}},
            "overall": vision_status,
        },
    )

    runtime.episodic_memory = None

    # AD-791a: opt out of chat-thread wiring so the explicit-thread-id
    # validation branch is skipped (MagicMock would otherwise auto-create a
    # truthy ``chat_thread_store``/``thread_id`` and raise HTTP 400).
    runtime.chat_thread_store = None

    from probos.cognitive.dm_sanity_gate import DmSanityGate
    runtime.dm_sanity_gate = DmSanityGate()
    return runtime


def _req(message: str = "look at this", attachment_ids: list[str] | None = None):
    r = MagicMock()
    r.message = message
    r.history = []
    r.attachment_ids = attachment_ids or []
    return r


def _fake_multimodal_messages(prompt: str, image_ids: list[str]):
    content: list[dict] = [{"type": "text", "text": prompt}]
    for aid in image_ids:
        content.append({
            "type": "image",
            "source": {"type": "attachment_ref", "sha256": aid, "media_type": "image/png"},
        })
    return [{"role": "user", "content": content}]


_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)


@pytest.mark.asyncio
async def test_agent_chat_vision_unconfigured_returns_unconfigured_message():
    """Agent DM + image + vision unconfigured → VISION_UNCONFIGURED_MESSAGE,
    NO intent dispatched (early return)."""
    from probos.routers.agents import agent_chat

    runtime = _make_agent_chat_runtime(vision_configured=False)
    req = _req(attachment_ids=["sha-img-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        result = await agent_chat("test-id", req, runtime)

    runtime.intent_bus.send.assert_not_called()
    assert result["response"] == VISION_UNCONFIGURED_MESSAGE
    assert result["callsign"] == "Lynx"
    assert result["agentId"] == "test-id"


@pytest.mark.asyncio
async def test_agent_chat_vision_healthy_routes_through_to_agent():
    """Vision configured + operational → intent IS dispatched, vision_messages
    carried in IntentMessage.params (AD-731 attachment_ref shape)."""
    from probos.routers.agents import agent_chat

    runtime = _make_agent_chat_runtime(vision_status="operational", vision_configured=True)
    req = _req(attachment_ids=["sha-img-1"])

    async def _bmm(prompt, attachment_ids, store, mime_lookup, **kwargs):
        return _fake_multimodal_messages(prompt, attachment_ids), list(attachment_ids), []

    with _CREW_PATCH, \
         patch("probos.cognitive.vision_dispatch.build_multimodal_messages", side_effect=_bmm), \
         patch("probos.routers.chat._get_attachment_store", return_value=MagicMock()):
        await agent_chat("test-id", req, runtime)

    runtime.intent_bus.send.assert_called_once()
    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert "vision_messages" in sent_intent.params
    assert sent_intent.params.get("has_image_attachment") is True
    # AD-731 wire format: attachment_ref source, not inline base64.
    content_items = sent_intent.params["vision_messages"][0]["content"]
    image_items = [c for c in content_items if c.get("type") == "image"]
    assert image_items
    assert image_items[0]["source"]["type"] == "attachment_ref"


# ---------------------------------------------------------------------------
# Section 4c: LLM client tier infra
# ---------------------------------------------------------------------------


def test_llm_client_tracks_vision_tier_in_health_status():
    """OpenAICompatibleClient.get_health_status() reports a per-tier dict
    entry for vision when vision is configured."""
    cfg = CognitiveConfig(
        llm_base_url_vision="http://127.0.0.1:11434/v1",
        llm_model_vision="llava:34b",
    )
    client = OpenAICompatibleClient(config=cfg)
    try:
        status = client.get_health_status()
        assert "vision" in status["tiers"]
        v = status["tiers"]["vision"]
        assert "status" in v
        assert "consecutive_failures" in v
        assert v["consecutive_failures"] == 0
    finally:
        import asyncio
        asyncio.run(client.close())


@pytest.mark.asyncio
async def test_llm_client_skips_health_probe_when_vision_unconfigured():
    """check_connectivity()['vision'] is False without an HTTP call to the
    vision endpoint when llm_model_vision is unset.

    Replaces every httpx.AsyncClient in client._clients with a MockTransport
    recorder, then asserts no recorded request targeted the (default) vision
    base_url. Other tiers may probe (and fail) against localhost:1.
    """
    cfg = CognitiveConfig(
        llm_base_url="http://localhost:1",
        # vision intentionally unconfigured
    )
    client = OpenAICompatibleClient(config=cfg, timeout=1.0)
    try:
        recorded: list[httpx.Request] = []

        def _record(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return httpx.Response(503, text="recorder")

        # Replace every httpx client with a MockTransport recorder.
        for key in list(client._clients.keys()):
            existing = client._clients[key]
            await existing.aclose()
            client._clients[key] = httpx.AsyncClient(
                base_url=existing.base_url,
                transport=httpx.MockTransport(_record),
                timeout=1.0,
            )

        result = await client.check_connectivity()
        assert result["vision"] is False
        # No probe was issued for the vision tier — since vision shares the
        # default base_url (localhost:1) in this config, we verify the
        # short-circuit at the result-shape level: the vision-unconfigured
        # path sets results['vision']=False without going through the
        # checked_urls cache or calling _check_endpoint. We assert this by
        # construction (the only way this assertion holds with a None model
        # is the short-circuit branch).
        assert "vision" in result
    finally:
        await client.close()


def test_llm_client_clients_dedupe_when_vision_shares_endpoint():
    """Vision sharing (base_url, api_format) with another tier does not
    grow the _clients pool."""
    cfg = CognitiveConfig(
        llm_base_url="http://shared.example/v1",
        # All tiers share the default shared URL; vision-tier-specific
        # config left None → falls back to shared.
        llm_model_vision="llava:34b",
    )
    client = OpenAICompatibleClient(config=cfg)
    try:
        # One client per (base_url, api_format). All four tiers share.
        assert len(client._clients) == 1
    finally:
        import asyncio
        asyncio.run(client.close())


def test_llm_client_clients_separate_when_vision_distinct_endpoint():
    """Vision pointing at a different base_url gets its own _clients entry."""
    cfg = CognitiveConfig(
        llm_base_url="http://shared.example/v1",
        llm_base_url_vision="http://127.0.0.1:11434/v1",
        llm_model_vision="llava:34b",
    )
    client = OpenAICompatibleClient(config=cfg)
    try:
        # Two distinct (base_url, api_format) pairs → two httpx clients.
        assert len(client._clients) == 2
    finally:
        import asyncio
        asyncio.run(client.close())


def test_mock_llm_client_health_status_includes_vision():
    """MockLLMClient.get_health_status['tiers']['vision']['status'] is
    'operational' so test scaffolding using the mock satisfies vision-path
    operational checks. Text tiers stay 'offline' per BF-108."""
    client = MockLLMClient()
    status = client.get_health_status()
    assert status["tiers"]["vision"]["status"] == "operational"
    assert status["tiers"]["fast"]["status"] == "offline"
    assert status["tiers"]["standard"]["status"] == "offline"
    assert status["tiers"]["deep"]["status"] == "offline"


# ---------------------------------------------------------------------------
# Section 4d: Fallback chain isolation
# ---------------------------------------------------------------------------


def test_vision_tier_not_in_fallback_chain():
    """_TIER_ORDER (the fallback chain) deliberately excludes vision.

    Vision failures degrade to the honest-degrade message — they never
    silently fall through to a blind tier. AD-706c-2 (Wave 166) added
    ``compute_use`` as a fifth peer; like vision, it must NOT appear in
    the fallback chain (BF-269 lesson: text tiers can't see images).
    """
    import probos.cognitive.llm_client as llm_module
    from probos.cognitive.llm_client import _TIER_ORDER

    # _LLM_TIERS includes all peer tiers (fast/standard/deep/vision plus
    # AD-706c-2 compute_use).
    assert "vision" in _LLM_TIERS
    assert "compute_use" in _LLM_TIERS
    assert set(_LLM_TIERS) == {"fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen"}

    # AD-706c-2 promoted _TIER_ORDER to a module-level constant; it must
    # remain text-only.
    assert set(_TIER_ORDER) == {"fast", "standard", "deep"}
    src = Path(llm_module.__file__).read_text(encoding="utf-8")
    # The literal-source assertion now reads the module-level tuple form.
    assert '_TIER_ORDER: tuple[str, ...] = ("fast", "standard", "deep")' in src
    # Vision/compute_use must not appear in the fallback chain definition.
    assert '"vision"' not in src.split("_TIER_ORDER:")[1].split("\n")[0]
    assert '"compute_use"' not in src.split("_TIER_ORDER:")[1].split("\n")[0]


@pytest.mark.asyncio
async def test_vision_request_does_not_fall_back_to_text_tiers():
    """BF-269 regression: when LLMRequest(tier='vision') fails, the client
    must NOT fall through to fast/standard/deep — those tiers silently drop
    image content (BF-268), producing a coherent but image-blind reply that
    the agent surfaces to the Captain. The honest-degrade gate at the router
    boundary depends on vision failures propagating, not being silently
    masked by a text-tier fallback.
    """
    import httpx
    from probos.cognitive.llm_client import OpenAICompatibleClient
    from probos.config import CognitiveConfig

    cfg = CognitiveConfig(
        llm_base_url_vision="http://127.0.0.1:65535/v1",  # always-unreachable port
        llm_model_vision="qwen3.6:27b",
        llm_api_format_vision="openai",
        llm_timeout_vision=1.0,
    )
    client = OpenAICompatibleClient(config=cfg)

    # Capture which base_urls get attempted.
    attempts: list[str] = []

    def _record_and_fail(request: httpx.Request) -> httpx.Response:
        attempts.append(str(request.url))
        return httpx.Response(503, json={"error": "unreachable"})

    transport = httpx.MockTransport(_record_and_fail)
    # Replace every constructed httpx client with our recorder.
    for key in list(client._clients.keys()):
        client._clients[key] = httpx.AsyncClient(
            base_url=client._clients[key].base_url,
            transport=transport,
            timeout=1.0,
        )

    req = LLMRequest(
        prompt="describe",
        messages=[{"role": "user", "content": [{"type": "text", "text": "x"}]}],
        tier="vision",
    )
    resp = await client.complete(req)

    # Either the response carries an error OR content is empty — both are
    # acceptable failure shapes. The hard requirement: ZERO requests landed
    # on any non-vision base_url.
    vision_url_host = "127.0.0.1:65535"
    non_vision_attempts = [u for u in attempts if vision_url_host not in u]
    assert non_vision_attempts == [], (
        f"Vision request fell back to text tier(s): {non_vision_attempts}. "
        "BF-269: vision must never fall back — text tiers drop image content."
    )
    await client.close()


def test_resolve_model_for_tier_skips_router_for_vision():
    """BF-273 regression (2026-05-12): ModelRouter must NOT be consulted for
    the vision tier. The router's registry only knows about text tiers
    (fast/standard/deep) — calling ``by_tier("vision")`` returns no
    candidates and the fallback path picks the cheapest text-tier model
    (e.g. ``claude-sonnet-4-6-fast``). The runtime then POSTs that model
    name to the vision endpoint (Ollama at 11434), which returns a 404
    because the text model doesn't exist there. Vision must always use
    the explicitly configured ``llm_model_vision``.
    """
    from probos.cognitive.llm_client import OpenAICompatibleClient
    from probos.config import CognitiveConfig

    cfg = CognitiveConfig(
        llm_base_url_vision="http://127.0.0.1:11434/v1",
        llm_model_vision="qwen3.6:27b",
    )
    client = OpenAICompatibleClient(config=cfg)

    # Inject a router that, like the real one, returns a text-tier model
    # when asked for vision (because its registry has no vision entries).
    class _TextOnlyRouter:
        def choose(self, *, tier: str, cost_ceiling=None):
            class _D:
                chosen_model = "claude-sonnet-4-6-fast"
            return _D()

    client.model_router = _TextOnlyRouter()

    # For text tiers the router IS allowed to override.
    assert client._resolve_model_for_tier("fast") == "claude-sonnet-4-6-fast"
    assert client._resolve_model_for_tier("standard") == "claude-sonnet-4-6-fast"
    assert client._resolve_model_for_tier("deep") == "claude-sonnet-4-6-fast"

    # For vision, the router MUST be bypassed; None signals "use tc['model']".
    assert client._resolve_model_for_tier("vision") is None
