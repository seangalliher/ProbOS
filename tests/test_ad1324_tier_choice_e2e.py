"""AD-1324 (#1479): agent-chosen tier under a stakes floor, through the real executor.

Real WorkItemAgenticExecutor, loop, economic organ handle, tier controller, LLM client,
ModelRouter (via the real startup wiring) and an in-process httpx endpoint. The request
body is read to prove which model was sent.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from probos.cognitive import agentic_dispatch
from probos.cognitive.economic_judgment_organ import EconomicJudgmentOrgan
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.spine import CognitiveSpine
from probos.config import CognitiveConfig, DmAgenticConfig, ModelRoutingConfig, SystemConfig
from probos.config_models.agentic import EconomicJudgmentConfig, TierChoiceConfig
from probos.events import EventType
from probos.startup.finalize import _wire_model_routing

_PRICED = {
    "llm_model_fast": "claude-sonnet-4-6-fast",
    "llm_model_standard": "claude-sonnet-4-6",
    "llm_model_deep": "claude-opus-4-6",
}


class _Endpoint:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.replies: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "offline.invalid"
        self.bodies.append(json.loads(request.content))
        text = self.replies.pop(0) if self.replies else "Done."
        return httpx.Response(200, json={
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 5, "prompt_tokens": 2},
        })

    @property
    def models(self) -> list[str]:
        return [b.get("model") for b in self.bodies]


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> _Endpoint:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    fake = _Endpoint()

    def build(client: OpenAICompatibleClient, tier: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=client._tier_configs[tier]["base_url"],
            transport=httpx.MockTransport(fake.handle),
        )

    monkeypatch.setattr(OpenAICompatibleClient, "_build_client", build)
    return fake


class _Requests:
    def __init__(self) -> None:
        self.filed: list[dict[str, Any]] = []
        # Amendment 1: the floor ask now dedupes under the store's lock.
        self.gap_filing_lock = asyncio.Lock()

    async def list_pending(self) -> list[Any]:
        return []

    async def file_request(self, **kw: Any) -> Any:
        self.filed.append(kw)
        return SimpleNamespace(id=f"req{len(self.filed):029d}")


class _Items:
    def __init__(self, stakes: str, provenance: Any = None) -> None:
        self._item = SimpleNamespace(value_band="minor", stakes=stakes, stakes_provenance=provenance)

    async def get_work_item(self, _id: str) -> Any:
        return self._item


async def _drive(*, endpoint: _Endpoint, armed: bool, stakes: str, ceiling: float | None,
                 tier: str = "fast", event_log: Any = None, store: Any = None,
                 seen: list[tuple[Any, Any]] | None = None, registry_hook: Any = None, provenance: Any = None,
                 ) -> tuple[Any, Any, list[tuple[Any, dict[str, Any]]], _Requests]:
    from tests.test_ad1208_cost_bounded_turns import _executor_runtime

    config = SystemConfig(
        cognitive=CognitiveConfig(llm_base_url="https://offline.invalid/v1/", **_PRICED),
        model_routing=ModelRoutingConfig(
            enabled=True, cost_ceiling_per_million_output_tokens=ceiling,
        ),
        dm_agentic=DmAgenticConfig(
            enabled=True,
            economic_judgment=EconomicJudgmentConfig(
                enabled=True, tier_choice=TierChoiceConfig(enabled=armed),
            ),
        ),
    )
    client = OpenAICompatibleClient(config=config.cognitive)
    events: list[tuple[Any, dict[str, Any]]] = []
    wiring = SimpleNamespace(
        llm_client=client, model_registry=None, model_router=None,
        emit_event=lambda et, data: events.append((et, data)),
    )
    _wire_model_routing(runtime=wiring, config=config)
    if registry_hook is not None:
        registry_hook(wiring.model_router.registry)
    runtime = _executor_runtime()
    runtime.config = SimpleNamespace(
        agentic_dispatch=SimpleNamespace(enabled=True),
        dm_agentic=config.dm_agentic, model_routing=config.model_routing,
    )
    runtime.work_item_store = _Items(stakes, provenance)
    runtime.model_registry = None
    runtime.model_router = wiring.model_router
    requests = _Requests()
    runtime.capability_request_store = store if store is not None else requests
    if event_log is not None:
        runtime.event_log = event_log
    if seen is not None:
        _complete = client.complete

        async def _spy(req: Any, **kw: Any) -> Any:
            response = await _complete(req, **kw)
            seen.append((req.id, getattr(response, "refusal_cause", None)))
            return response

        client.complete = _spy  # type: ignore[method-assign]
    organ = EconomicJudgmentOrgan(emit=lambda _t: None)
    CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client)
    try:
        outcome = await executor.run(
            agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go.",
            runtime=runtime, max_iterations=5, tier=tier,
            extra_context={"_crew_work_item_id": "wi-1", "_crew_session_id": "s-1"},
            inner_loop_hook=organ.open_turn_hook(),
        )
    finally:
        await client.close()
    return outcome, client, events, requests


@pytest.mark.asyncio
async def test_armed_high_stakes_raises_call_site_fast_to_standard_and_emits_correlation(
    endpoint: _Endpoint,
) -> None:
    outcome, _, events, _ = await _drive(endpoint=endpoint, armed=True, stakes="high", ceiling=None)
    assert outcome.stopped_reason == "complete"
    assert endpoint.models == ["claude-sonnet-4-6"]
    routed = [d for et, d in events if et == EventType.MODEL_ROUTED]
    assert routed and routed[0]["agent_id"] == "counselor-ezri"
    assert routed[0]["work_item_id"] == "wi-1"


@pytest.mark.asyncio
async def test_flag_off_sends_the_call_site_tier_and_adds_no_event_keys(endpoint: _Endpoint) -> None:
    outcome, _, events, _ = await _drive(endpoint=endpoint, armed=False, stakes="high", ceiling=None)
    assert outcome.stopped_reason == "complete"
    assert endpoint.models == ["claude-sonnet-4-6-fast"]
    routed = [d for et, d in events if et == EventType.MODEL_ROUTED]
    assert routed and "agent_id" not in routed[0] and "work_item_id" not in routed[0]


@pytest.mark.asyncio
async def test_severe_stakes_without_a_deep_model_sends_nothing_and_files_a_linked_ask(
    endpoint: _Endpoint,
) -> None:
    outcome, _, _, requests = await _drive(
        endpoint=endpoint, armed=True, stakes="severe", ceiling=20.0,
    )
    assert endpoint.bodies == []
    assert outcome.stopped_reason == "tier_floor_unavailable"
    assert len(requests.filed) == 1
    filed = requests.filed[0]
    assert filed["work_item_id"] == "wi-1" and filed["kind"] == "continue"
    assert "'deep' tier" in filed["rationale"]


@pytest.mark.asyncio
async def test_flag_off_with_the_same_ceiling_serves_the_call_site_tier(endpoint: _Endpoint) -> None:
    outcome, _, _, requests = await _drive(
        endpoint=endpoint, armed=False, stakes="severe", ceiling=20.0,
    )
    assert outcome.stopped_reason == "complete"
    assert endpoint.models == ["claude-sonnet-4-6-fast"] and requests.filed == []


class _DmHost:
    from probos.cognitive.cognitive_agent import CognitiveAgent as _CA

    id = "agent-1"
    _compose_economic_judgment_organ = _CA._compose_economic_judgment_organ
    _economic_judgment_config = _CA._economic_judgment_config
    economic_inner_loop_hook = _CA._economic_inner_loop_hook if hasattr(_CA, "_economic_inner_loop_hook") else _CA.economic_inner_loop_hook
    _emit_economic_audit = _CA._emit_economic_audit
    _maybe_run_conversational_agentic = _CA._maybe_run_conversational_agentic


@pytest.mark.asyncio
@pytest.mark.parametrize("armed", [True, False], ids=["armed", "off"])
async def test_dm_turn_correlation_reaches_the_routing_event_through_the_real_agent_path(
    endpoint: _Endpoint, armed: bool,
) -> None:
    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.tools.registry import ToolRegistry
    from tests.test_ad1208_cost_bounded_turns import _Fetch, _fetch_runtime

    config = SystemConfig(
        cognitive=CognitiveConfig(llm_base_url="https://offline.invalid/v1/", **_PRICED),
        model_routing=ModelRoutingConfig(
            enabled=True, cost_ceiling_per_million_output_tokens=20.0,
        ),
        dm_agentic=DmAgenticConfig(
            enabled=True, max_iterations=5, token_budget=500_000, max_total_iterations=100,
            economic_judgment=EconomicJudgmentConfig(
                enabled=True, tier_choice=TierChoiceConfig(
                    enabled=armed, stakes_floor={"high": "deep", "severe": "deep"},
                ),
            ),
        ),
    )
    client = OpenAICompatibleClient(config=config.cognitive)
    events: list[tuple[Any, dict[str, Any]]] = []
    wiring = SimpleNamespace(
        llm_client=client, model_registry=None, model_router=None,
        emit_event=lambda et, data: events.append((et, data)),
    )
    _wire_model_routing(runtime=wiring, config=config)
    registry = ToolRegistry()
    registry.register(_Fetch(), provider="ad1324-test", default_permissions={"ensign": "read"})
    requests = _Requests()
    runtime = _fetch_runtime(registry, requests, config.dm_agentic)
    runtime.config.model_routing = config.model_routing
    runtime.work_item_store = None
    runtime.model_registry = None
    runtime.model_router = wiring.model_router

    class _Agent(_DmHost):
        def __init__(self) -> None:
            self._runtime = runtime
            self._spine = CognitiveSpine(self)
            self._llm_client = client
            self.department = "counseling"
            self.rank = "lieutenant"
            self._conversational_agentic_will_run = (
                lambda obs: CognitiveAgent._conversational_agentic_will_run(self, obs)
            )

    agent = _Agent()
    agent._compose_economic_judgment_organ()
    try:
        await agent._maybe_run_conversational_agentic(
            {"intent": "direct_message", "params": {}},
            system_prompt="You are Ezri.", user_message="Hello.",
        )
    finally:
        await client.close()
    routed = [d for et, d in events if et == EventType.MODEL_ROUTED]
    if armed:
        # Stakes are unrecorded for a DM turn with no work item: no floor, no raise.
        assert endpoint.models == ['claude-sonnet-4-6']
        assert routed and routed[0]['agent_id'] == 'agent-1'
        assert requests.filed == []
    else:
        assert endpoint.models == ["claude-sonnet-4-6-fast"] or endpoint.models == ["claude-sonnet-4-6"]
        assert routed and "agent_id" not in routed[0]


# -- Amendment 1 (finding 2): a promoted DM turn that stops on the floor ask PARKS and RESUMES ----
import asyncio  # noqa: E402

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome  # noqa: E402
from probos.cognitive.tier_floor_ask import file_tier_floor_request  # noqa: E402
from probos.cognitive.turn_promotion import _INCOMPLETE_STOP_REASONS  # noqa: E402
from probos.dm_reply import ToolFailures  # noqa: E402
from tests.test_bf887_continue_resumes_the_promoted_turn import (  # noqa: E402,F401
    AGENT as _BF_AGENT,
    FINAL as _BF_FINAL,
    PARTIAL as _BF_PARTIAL,
    _Executor as _BfExecutor,
    _agent_bodies,
    _approve,
    _done,
    _promote_and_stop,
    _settle,
    make_rig,
    scripted,
)


def _floor_outcome(text: str, request_id: str) -> WorkItemAgenticOutcome:
    return WorkItemAgenticOutcome(
        final_text=text, stopped_reason="tier_floor_unavailable",
        tool_failures=ToolFailures.from_mapping({}, merge_open=True), tool_defect_evaluated=True,
        parked_request_id=request_id,
    )


def _floor_executor(monkeypatch: pytest.MonkeyPatch, rig: Any, plan: list[Any]) -> list[dict[str, Any]]:
    """A scripted executor whose floor stop files the tier-floor ask itself, as production does."""
    calls: list[dict[str, Any]] = []

    class _Log:
        async def log(self, **_kw: Any) -> None:
            return None

    # Production always has an event log; with one the executor receives the promoted item's id provider.
    rig.runtime.event_log = _Log()

    class _FloorExecutor:
        def __init__(self, *, llm_client: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> Any:
            index = len(calls)
            calls.append(kwargs)
            gate = _BfExecutor.gates.get(index)
            if gate is not None:
                await asyncio.wait_for(gate.wait(), timeout=30)
            step = plan[index]
            if step != "floor":
                return step
            parked: dict[str, str] = {}
            await file_tier_floor_request(
                rig.runtime, agent_id=_BF_AGENT, thread_id=kwargs["thread_id"],
                work_item_id=kwargs["work_item_id_provider"](),
                floor="deep", stakes="severe", stakes_provenance="captain", tried=1, park=True, parked=parked,
            )
            return _floor_outcome(_BF_PARTIAL, parked.get("request_id", ""))

    monkeypatch.setattr("probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _FloorExecutor)
    return calls


def test_incomplete_stop_reasons_contains_tier_floor_unavailable() -> None:
    assert "tier_floor_unavailable" in _INCOMPLETE_STOP_REASONS


async def test_promoted_dm_floor_ask_parks_holds_continuation_approve_resumes_not_failed(
    make_rig: Any, scripted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.gates = {0: gate}
    calls = _floor_executor(monkeypatch, rig, ["floor", _done(_BF_FINAL)])

    item, pending = await _promote_and_stop(rig, gate)

    assert len(pending) == 1 and pending[0].kind == "continue", "premise: one parked ask exists"
    assert pending[0].work_item_id == item.id
    parked = await rig.work_items.get_work_item(item.id)
    assert parked.status == "blocked", "the item is parked, not failed"
    assert item.id in rig.agent._promoted_turn_continuations, "the continuation is held for the resume"

    await _approve(rig, pending[0].id)

    assert len(calls) == 2, "approval resumed the turn's next pass"
    assert _agent_bodies(rig)[-1] == _BF_FINAL
    assert (await rig.work_items.get_work_item(item.id)).status == "done"


async def test_settle_turn_copies_parked_request_id_before_end_segment(
    make_rig: Any, scripted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.gates = {0: gate}
    _floor_executor(monkeypatch, rig, ["floor", _done(_BF_FINAL)])
    item, pending = await _promote_and_stop(rig, gate)
    # The continuation survives _end_segment only because the parked id was copied first.
    assert pending and item.id in rig.agent._promoted_turn_continuations


async def test_resumed_segment_floor_ask_also_propagates(
    make_rig: Any, scripted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await make_rig()
    gate = asyncio.Event()
    scripted.gates = {0: gate}
    calls = _floor_executor(monkeypatch, rig, ["floor", "floor", _done(_BF_FINAL)])
    item, pending = await _promote_and_stop(rig, gate)
    await _approve(rig, pending[0].id)
    again = await rig.requests.list_pending()
    assert len(calls) == 2 and len(again) == 1, "the resumed pass parked on a NEW ask"
    assert (await rig.work_items.get_work_item(item.id)).status == "blocked"
    await _approve(rig, again[0].id)
    assert len(calls) == 3 and _agent_bodies(rig)[-1] == _BF_FINAL


async def test_crew_child_floor_ask_unparked_residual() -> None:
    # Accepted residual (amendment 1): a crew child's floor ask is filed unparked, so approval
    # fulfils the request but starts no run. Pinned so the day it changes is a decision.
    store_calls: list[dict[str, Any]] = []

    class _Store:
        gap_filing_lock = asyncio.Lock()

        async def list_pending(self) -> list[Any]:
            return []

        async def file_request(self, **kw: Any) -> Any:
            store_calls.append(kw)
            return SimpleNamespace(id="req-1")

    runtime = SimpleNamespace(capability_request_store=_Store())
    request_id = await file_tier_floor_request(
        runtime, agent_id="a", thread_id="t", work_item_id="w", floor="deep", stakes="severe",
        stakes_provenance="captain", tried=1, park=False,
    )
    assert request_id == "req-1" and store_calls[0]["kind"] == "continue"