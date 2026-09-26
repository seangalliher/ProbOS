"""AD-1228 (#1201): end to end -- register, the state changes, the agent is told.

Nothing between the steps is stubbed. The only doubles are the LLM client (the
model boundary) and a runtime host whose event methods ARE ``ProbOSRuntime``'s;
the store, service, listener, tool registry, work-item store, trust network,
proactive loop, ConcurrencyManager and CognitiveAgent are all real, and the
feature is wired by the real ``_wire_standing_interests``.
"""

from __future__ import annotations

import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.llm_client import LLMResponse, MockLLMClient
from probos.cognitive.self_similarity_history import SelfSimilarityHistory
from probos.cognitive.standing_interests import format_utc
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import Rank
from probos.proactive import ProactiveCognitiveLoop
from probos.startup.finalize import _wire_standing_interests
from probos.substrate.registry import AgentRegistry
from probos.tools.registry import ToolRegistry
from probos.types import IntentDescriptor
from probos.workforce import WorkItemStore
from tests.test_ad1228_standing_interests import (
    _R_CLINICAL,
    _STATUS_EVENTS,
    _Callsigns,
    _drain,
    _EmitHost,
)

_TITLE = "SENTINEL TITLE 1201 do not surface"
_DESCRIPTION = "SENTINEL DESCRIPTION 1201 do not surface"
_HEADER = "standing interests fired (AD-1228)"
# A reply: the model read the notice. It still ends the think without a Ward Room post.
_REMARK = "Noted; the stranded item is mine to follow up. [NO_RESPONSE]"


class _RecordingLLM(MockLLMClient):
    """The model boundary: records each prompt with the agent's slot snapshot taken inside the call."""

    def __init__(self, reply: str = "[NO_RESPONSE]") -> None:
        super().__init__()
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.manager: ConcurrencyManager | None = None

    async def complete(self, request: Any, **_kwargs: Any) -> Any:  # type: ignore[override]
        snapshot = self.manager.snapshot() if self.manager is not None else {}
        self.calls.append(((request.system_prompt or "") + "\n" + (request.prompt or ""), snapshot))
        return LLMResponse(content=self.reply, model="mock", tier="standard")


def _agent_class(agent_type: str) -> type[CognitiveAgent]:
    return type(
        f"_E2E_{agent_type}",
        (CognitiveAgent,),
        {
            "agent_type": agent_type,
            "_handled_intents": {"e2e_probe"},
            "instructions": "You are a crew member. Respond concisely.",
            "intent_descriptors": [
                IntentDescriptor(name="e2e_probe", params={}, description="probe", tier="domain"),
            ],
        },
    )


async def _crew_member(
    host: Any, agent_type: str, reply: str = "[NO_RESPONSE]",
) -> tuple[CognitiveAgent, _RecordingLLM]:
    llm = _RecordingLLM(reply)
    agent = _agent_class(agent_type)(llm_client=llm)
    manager = ConcurrencyManager(agent.id, max_concurrent=1, queue_max_size=0)
    agent.set_concurrency_manager(manager)
    llm.manager = manager
    await host.registry.register(agent)
    return agent, llm


class _Host(_EmitHost):
    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.trust_network = TrustNetwork()
        self.self_similarity_history = SelfSimilarityHistory()
        self.registry = AgentRegistry()
        self.work_item_store = WorkItemStore(
            db_path=str(data_dir / "w.db"), emit_event=self._emit_event, tick_interval=3600.0,
        )
        self.tool_registry = ToolRegistry()
        self.callsign_registry: Any = None
        self.clearance_grant_store = None
        self.clinical_access_audit: deque[dict[str, Any]] = deque(maxlen=1000)
        self._start_time_wall = time.time()
        self.standing_interest_store: Any = None
        self.standing_interests: Any = None


def _config() -> SystemConfig:
    config = SystemConfig()
    config.proactive_cognitive.enabled = True
    config.proactive_cognitive.standing_interests_enabled = True
    return config


async def _think(loop: ProactiveCognitiveLoop, agent: CognitiveAgent, llm: _RecordingLLM) -> tuple[str, list[tuple[str, int]]]:
    before = len(llm.calls)
    await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.6)
    new = llm.calls[before:]
    assert len(new) == 1, f"expected one model call for the think, got {len(new)}"
    prompt, snapshot = new[0]
    return prompt, [(t["intent_type"], t["priority"]) for t in snapshot.get("active_threads", [])]


async def test_e2e_register_own_work_item_then_it_finishes_then_notified_in_an_accounted_think(
    tmp_path: Path,
) -> None:
    host = _Host(tmp_path)
    await host.work_item_store.start()
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
    loop.set_runtime(host)
    try:
        # A-6: a bare [NO_RESPONSE] is a silence, which returns a notice until its second showing (E3).
        # Until A-6 this model answered that bare token, and step 4 pinned "retired at delivery" on it.
        agent, llm = await _crew_member(host, "operations_officer", reply=_REMARK)
        host.callsign_registry = _Callsigns({agent.id: ("operations_officer", "Rahda")})
        assert await _wire_standing_interests(runtime=host, config=_config(), proactive_loop=loop) is True

        # Step 0 -- premise: an item this agent owns, in progress; a think reaches the model, no notice.
        work = host.work_item_store
        item = await work.create_work_item(title=_TITLE, description=_DESCRIPTION, assigned_to=agent.id)
        assert (await work.transition_work_item(item.id, "in_progress", source="test")).status == "in_progress"
        await _drain(host)
        prompt, _slot = await _think(loop, agent, llm)
        assert _HEADER not in prompt

        # Step 1 -- register through the real tool registry, by an 8-character prefix.
        receipt = (await host.tool_registry.check_and_invoke(
            agent.id, "standing_interest",
            {"action": "register", "kind": "work_item_finished", "subject": item.id[:8]},
            agent_rank="lieutenant",
        )).output
        assert receipt["registered"] is True and len(receipt["registration_id"]) == 32

        # Step 2 -- the BF-730 stranding write, which emits work_item_updated only.
        seen: list[str] = []
        host.add_event_listener(lambda event: seen.append(event["type"]), _STATUS_EVENTS)
        metadata = dict((await work.get_work_item(item.id)).metadata or {})
        metadata["stranded_reason"] = "stalled_not_dispatchable"
        metadata["stranded_at"] = time.time()
        await work.update_work_item(item.id, status="failed", metadata=metadata)
        await _drain(host)
        assert seen == ["work_item_updated"]  # premise: no work_item_status_changed for this write

        # Step 3 -- the next think carries the notice, inside the accounted proactive_think slot.
        prompt, slot = await _think(loop, agent, llm)
        assert f"Work item {item.id[:8]} finished: failed" in prompt
        assert "stalled_not_dispatchable" in prompt
        assert slot == [("proactive_think", 2)]
        assert _TITLE not in prompt and _DESCRIPTION not in prompt

        # Step 4 -- retired at delivery: nothing held, no second notice, no row left.
        listed = (await host.tool_registry.check_and_invoke(
            agent.id, "standing_interest", {"action": "list"}, agent_rank="lieutenant",
        )).output
        assert listed["held"] == []
        prompt, _slot = await _think(loop, agent, llm)
        assert _HEADER not in prompt
        conn = sqlite3.connect(tmp_path / "standing_interests.db")
        try:
            assert conn.execute("SELECT COUNT(*) FROM standing_interests").fetchone() == (0,)
        finally:
            conn.close()
    finally:
        if host.standing_interest_store is not None:
            await host.standing_interest_store.stop()
        await host.work_item_store.stop()


async def test_e2e_counselor_registers_trust_falling_on_a_crewmate_then_notified(tmp_path: Path) -> None:
    host = _Host(tmp_path)
    await host.work_item_store.start()
    host.trust_network.set_event_callback(host._emit_event)
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
    loop.set_runtime(host)
    try:
        counselor, counselor_llm = await _crew_member(host, "counselor")
        crewmate, crewmate_llm = await _crew_member(host, "security_officer")
        host.callsign_registry = _Callsigns({
            counselor.id: ("counselor", "Troi"), crewmate.id: ("security_officer", "Worf"),
        })
        assert await _wire_standing_interests(runtime=host, config=_config(), proactive_loop=loop) is True

        # Premise: the crewmate's identical registration about the Counselor is refused (AD-903).
        refused = (await host.tool_registry.check_and_invoke(
            crewmate.id, "standing_interest", {"action": "register", "kind": "trust_falling", "subject": "Troi"},
            agent_rank="lieutenant",
        )).output
        assert refused == {"registered": False, "reason": _R_CLINICAL}

        # Step 1 -- the Counselor registers on the crewmate by id.
        receipt = (await host.tool_registry.check_and_invoke(
            counselor.id, "standing_interest",
            {"action": "register", "kind": "trust_falling", "subject": crewmate.id},
            agent_rank="commander",
        )).output
        assert receipt["registered"] is True

        # Step 2 -- twenty failures through the real trust network.
        for _ in range(20):
            host.trust_network.record_outcome(crewmate.id, success=False, intent_type="test")

        # Step 3 -- the Counselor's think carries the trend, inside the accounted slot, and both reads are audited.
        prompt, slot = await _think(loop, counselor, counselor_llm)
        assert "is falling" in prompt and "Trust for Worf" in prompt
        assert slot == [("proactive_think", 2)]
        audit = [
            (e["query_type"], e["granted"])
            for e in host.clinical_access_audit
            if e.get("requester_agent_id") == counselor.id and e.get("target_agent_id") == crewmate.id
        ]
        assert ("standing_interest_register", True) in audit
        assert ("standing_interest_notice", True) in audit

        # Step 4 -- the crewmate is told the interest exists, never its values.
        record = host.standing_interest_store.live_for_holder(counselor.id)[0]
        prompt, _slot = await _think(loop, crewmate, crewmate_llm)
        assert (
            f"Troi registered a standing interest in your trust trend until {format_utc(record.expires_at)}."
        ) in prompt
        assert "-0.012" not in prompt and "r2" not in prompt
    finally:
        if host.standing_interest_store is not None:
            await host.standing_interest_store.stop()
        await host.work_item_store.stop()


async def test_e2e_a_notice_survives_a_shed_think_and_reaches_the_model_on_the_next_think(
    tmp_path: Path,
) -> None:
    host = _Host(tmp_path)
    await host.work_item_store.start()
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
    loop.set_runtime(host)
    try:
        agent, llm = await _crew_member(host, "operations_officer")
        host.callsign_registry = _Callsigns({agent.id: ("operations_officer", "Rahda")})
        assert await _wire_standing_interests(runtime=host, config=_config(), proactive_loop=loop) is True
        work = host.work_item_store
        item = await work.create_work_item(title=_TITLE, description=_DESCRIPTION, assigned_to=agent.id)
        assert (await work.transition_work_item(item.id, "in_progress", source="test")).status == "in_progress"
        await _drain(host)
        receipt = (await host.tool_registry.check_and_invoke(
            agent.id, "standing_interest",
            {"action": "register", "kind": "work_item_finished", "subject": item.id},
            agent_rank="lieutenant",
        )).output
        assert receipt["registered"] is True
        assert (await work.transition_work_item(item.id, "done", source="test")).status == "done"
        await _drain(host)
        line = f"Work item {item.id[:8]} finished: done"
        sent: list[tuple[str, Any]] = []
        handle_intent = agent.handle_intent

        async def observed(intent: Any) -> Any:  # an observation point: the real lifecycle still runs
            result = await handle_intent(intent)
            sent.append((str(intent.params["context_parts"].get("system_note", "")), result))
            return result

        agent.handle_intent = observed  # type: ignore[method-assign]

        # Step 1 -- a shed think: another intent holds the agent's only slot, and its queue holds none (AD-672).
        held = await llm.manager.acquire("direct_message", 8)
        try:
            await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.6)
        finally:
            await llm.manager.release(held)
        assert llm.calls == []  # premise: the shed think never reached the model
        assert len(sent) == 1 and line in sent[0][0]  # premise: the notice rode it
        assert (sent[0][1].success, sent[0][1].result) == (True, "[NO_RESPONSE]")  # the AD-672 shed shape

        # Step 2 -- the notice survived: the next think carries it to the model, inside the accounted slot.
        prompt, slot = await _think(loop, agent, llm)
        assert line in prompt
        assert slot == [("proactive_think", 2)]

        # Step 3 -- shown twice to a silent model, it is consumed at the cap: retired, with no third showing.
        listed = (await host.tool_registry.check_and_invoke(
            agent.id, "standing_interest", {"action": "list"}, agent_rank="lieutenant",
        )).output
        assert listed["held"] == []
        prompt, _slot = await _think(loop, agent, llm)
        assert _HEADER not in prompt
    finally:
        if host.standing_interest_store is not None:
            await host.standing_interest_store.stop()
        await host.work_item_store.stop()
