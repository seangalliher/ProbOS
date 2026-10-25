"""BF-922 (#1639) M1: BF-204 grounds on what the composing call was given; pure-decimal numbers and repeats do not count.

The contract is ``prompts/bf-922-output-gate-grounding-and-fallback.md``. The live cases come from
``tests/fixtures/bf922_live_grounding_cases.json``, written by the orchestrator read-only from the live vessel: real
cited ids and their real Ward Room rows. Each row's id is placed through a production renderer that shows that kind:
the real QUERY step and COMPOSE's real renderer over ``thread_metadata`` (full post and thread ids, the
ward_room_notification chain) or ``unread_counts`` (channel ids, the proactive_think chain), and a post's first 8 hex in
the router's thread line (ward_room_router.py). It is a placement, not a replay: the live prompts were not retained.

Stand-ins, named: EVALUATE's model client (approves), so a reply that passes the deterministic checks reaches the judge;
``_WardRoomReads``, the two WardRoomService reads behind those QUERY operations, answering with the case's rows in the
production shapes (ward_room/threads.py ``get_thread``, ward_room/messages.py ``get_unread_counts``). The lookup tests
run a real ``WardRoomService`` in ``tmp_path``, the real AD-1347 dispatch and the real chain with real handlers; their
stand-ins are the model client (``_TwoCalls``: ANALYZE's JSON, then COMPOSE's reply) and the runtime surface
(``_ChainRuntime``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.output_grounding import (
    MIN_UNGROUNDED_IDS,
    REJECTION_UNGROUNDED,
    cited_ids,
    deterministic_rejection,
    intent_entity_ids,
    shown_hex_runs,
    ungrounded_ids,
)
from probos.cognitive.sub_task import SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks import AnalyzeHandler, ComposeHandler, QueryHandler, ReflectHandler
from probos.cognitive.sub_tasks.compose import _build_user_prompt, composer_world_text
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.config import SystemConfig
from probos.config_models.crew import WardRoomConfig
from probos.types import LLMResponse
from probos.ward_room.service import WardRoomService

FIXTURE = Path(__file__).parent / "fixtures" / "bf922_live_grounding_cases.json"
LIVE: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
INVENTED = "Per post 7f3a9c2e and thread b81d04aa, the backlog cleared."
ANALYSIS_ONLY = "Post deadc0de and thread facefeed matter."


def _handler() -> EvaluateHandler:
    response = MagicMock()
    response.content = '{"pass": true, "score": 0.8, "criteria": {}, "recommendation": "approve"}'
    response.tokens_used = 50
    response.tier = "fast"
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=response)
    return EvaluateHandler(llm_client=llm)


def _spec() -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE, name="evaluate-reply", prompt_template="ward_room_quality", tier="fast",
    )


def _compose(output: str) -> SubTaskResult:
    return SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name="compose-reply", result={"output": output})


def _analysis(situation: str) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-reply",
        result={"composition_brief": {"situation": situation}},
    )


def _context(**sections: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "_agent_type": "science_officer",
        "_agent_id": "agent-7",
        "_callsign": "Kira",
        "_department": "science",
        "_chain_trust_band": "mid",
    }
    context.update(sections)
    return context


class _WardRoomReads:
    """The two WardRoomService reads the chains' QUERY steps make, answering with one live case's real rows."""

    def __init__(self, case: dict[str, Any]) -> None:
        self._rows = case["rows"]

    async def get_thread(self, thread_id: str, **_kwargs: Any) -> dict[str, Any]:
        posts = [
            {"id": row["id"], "thread_id": thread_id, "author_callsign": row["author_callsign"],
             "body": row["body"], "children": []}
            for row in self._rows if row["kind"] == "post"
        ]
        thread = {"id": thread_id, "channel_name": self._rows[0]["channel_name"], "title": "live case"}
        return {"thread": thread, "posts": posts, "total_post_count": len(posts)}

    async def get_unread_counts(self, agent_id: str) -> dict[str, int]:
        return {row["id"]: 1 for row in self._rows if row["kind"] == "channel"}


class _QueryRuntime:
    """The one runtime attribute the two QUERY operations read."""

    def __init__(self, ward_room: _WardRoomReads) -> None:
        self.ward_room = ward_room


async def _placed(case: dict[str, Any]) -> tuple[dict[str, Any], list[SubTaskResult]]:
    """The case's ids where a production renderer shows that kind, through the real QUERY step.

    Posts and threads: the ward_room_notification chain's QUERY ``thread_metadata`` and the router's thread line.
    Channels: the proactive_think chain's QUERY ``unread_counts``. The spec names only the operation the stand-in
    answers (a missing service fails the step, and COMPOSE then renders no Prior Data). One case is one chain, so a
    case that mixed channels with posts, or posts from two threads, is not placeable and fails here.
    """
    kinds = {row["kind"] for row in case["rows"]}
    if "channel" in kinds:
        assert kinds == {"channel"}, f"{_case_id(case)}: channels with posts are not one chain's QUERY"
        context = _context(context="Thread: live case")
        spec = SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="query-situation", context_keys=("unread_counts",))
    else:
        threads = {row["thread_id"] if row["kind"] == "post" else row["id"] for row in case["rows"]}
        assert len(threads) == 1, f"{_case_id(case)}: posts from {len(threads)} threads are not one chain's QUERY"
        thread_id = threads.pop()
        lines = [
            f"[{row['id'][:8]}] {row['author_callsign']}: {row['body']}"
            for row in case["rows"] if row["kind"] == "post"
        ]
        context = _context(context="Thread: live case\n" + "\n".join(lines), params={"thread_id": thread_id})
        spec = SubTaskSpec(
            sub_task_type=SubTaskType.QUERY, name="query-thread-context", context_keys=("thread_metadata",),
        )
    query = await QueryHandler(_QueryRuntime(_WardRoomReads(case)))(spec, context, [])
    assert query.success, query.error
    return context, [query]


def _reply(case: dict[str, Any]) -> str:
    return "Building on " + ", ".join(case["cited"]) + "."


def _case_id(case: dict[str, Any]) -> str:
    return f"{case['logged_at']}-{case['agent_type']}"


# --- the pattern and the count ---------------------------------------------------------------------


def test_pure_decimal_numbers_are_not_cited_ids() -> None:
    assert cited_ids("Latency 5999983 ms over 123456 samples; channel 80593080; post 8a66bf93.") == ("8a66bf93",)


def test_a_repeated_id_counts_once() -> None:
    assert ungrounded_ids("8a66bf93, again 8A66BF93", ()) == ("8a66bf93",)
    assert deterministic_rejection("8a66bf93, again 8a66bf93", ()) is None


def test_one_ungrounded_id_is_below_the_threshold() -> None:
    assert MIN_UNGROUNDED_IDS == 2
    assert deterministic_rejection("Only 7f3a9c2e here.", ()) is None


def test_two_invented_ids_are_still_suppressed() -> None:
    rejection = deterministic_rejection(INVENTED, shown_hex_runs("A thread with no identifiers at all."))

    assert rejection is not None
    assert rejection.reason == REJECTION_UNGROUNDED
    assert rejection.ungrounded == ("7f3a9c2e", "b81d04aa")


def test_an_id_inside_a_given_run_is_grounded() -> None:
    shown = shown_hex_runs("Post b090ebe5-3f40-4c1d-9e2a-05b2bd92121b in thread b1fba6b3-d991-4f00-8a1b-2c3d4e5f6a7b")

    assert ungrounded_ids("b090ebe5, 05b2bd92121b and b090eb", shown) == ()


def test_raw_intent_json_is_rejected_before_grounding() -> None:
    rejection = deterministic_rejection('{"intents": [{"intent": "ward_room_post"}]}', ())

    assert rejection is not None and rejection.reason == "raw_json_output"


def test_the_bf233_intent_ids_are_given() -> None:
    context = {
        "params": {"thread_id": "A6EC8B06-1234", "channel_id": "", "author_id": "captain"},
        "_agent_id": "78a87214-aaaa",
        "target_agent_id": None,
        "intent_id": "i-1",
    }

    assert intent_entity_ids(context) == ("A6EC8B06-1234", "captain", "78a87214-aaaa", "i-1")
    assert intent_entity_ids({"params": "not a dict"}) == ()


# --- the source: what COMPOSE was given ------------------------------------------------------------


def test_the_world_text_leaves_out_the_analysis() -> None:
    text = composer_world_text(
        {"context": "Thread: Readiness\n[c71f7ab2] Meridian: nominal"}, [_analysis(ANALYSIS_ONLY)],
    )

    assert "c71f7ab2" in text
    assert "deadc0de" not in text and "facefeed" not in text


@pytest.mark.asyncio
async def test_an_id_only_in_the_analysis_is_not_grounded() -> None:
    result = await _handler()(_spec(), _context(context="Thread: Readiness"), [_analysis(ANALYSIS_ONLY), _compose(ANALYSIS_ONLY)])

    assert result.result["rejection_reason"] == "confabulation_detected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "section",
    ["context", "_formatted_memories", "_ward_room_lookup_context", "_ward_room_activity", "_oracle_context"],
)
async def test_an_id_in_any_world_section_is_grounded(section: str) -> None:
    sections: dict[str, Any] = {section: "Post 7f3a9c2e in thread b81d04aa"}
    if section == "_ward_room_lookup_context":
        sections["_ward_room_lookup_outcome"] = "found"  # BF-922 A1: a lookup's text grounds for a record only
    result = await _handler()(_spec(), _context(**sections), [_compose(INVENTED)])

    assert result.success and result.result["recommendation"] == "approve"


@pytest.mark.asyncio
async def test_the_bf204_log_line_names_the_agent_and_the_gate(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.output_grounding"):
        await _handler()(_spec(), _context(context="No identifiers here."), [_compose(INVENTED)])

    assert (
        "BF-204: Grounding check failed for science_officer (agent_id=agent-7, callsign=Kira, path=chain)"
        " — 2 ungrounded hex IDs: ['7f3a9c2e', 'b81d04aa']"
    ) in caplog.text


# --- the live cases ---------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("case", LIVE["cases"], ids=_case_id)
async def test_a_live_false_positive_is_grounded_when_given(case: dict[str, Any]) -> None:
    """Every id the live reply cites is in what the real renderers gave the composer, and the judge approves it."""
    context, prior = await _placed(case)
    reply = _reply(case)

    assert cited_ids(reply), "premise: the live reply cites ids"
    assert ungrounded_ids(reply, shown_hex_runs(composer_world_text(context, prior), *intent_entity_ids(context))) == ()
    result = await _handler()(_spec(), context, [*prior, _compose(reply)])

    assert result.success and result.result["recommendation"] == "approve"


@pytest.mark.parametrize(
    "case",
    [c for c in LIVE["cases"] if len(cited_ids(" ".join(c["cited"]))) >= MIN_UNGROUNDED_IDS],
    ids=_case_id,
)
def test_the_same_live_reply_is_flagged_when_not_given(case: dict[str, Any]) -> None:
    """The live cases exercise the grounding source, not only the pattern."""
    assert deterministic_rejection(_reply(case), ()) is not None


@pytest.mark.parametrize("case", LIVE["pattern_cases"], ids=_case_id)
def test_a_live_decimal_or_repeat_case_is_not_suppressed(case: dict[str, Any]) -> None:
    assert deterministic_rejection(_reply(case), ()) is None


def test_the_fixture_holds_real_cases() -> None:
    assert len(LIVE["cases"]) >= 8
    assert any(row["kind"] == "channel" for case in LIVE["cases"] for row in case["rows"])
    assert any(case["cited"] == ["5999983", "5999983"] for case in LIVE["pattern_cases"])
    for case in LIVE["cases"]:  # BF-922 A1: each case is one chain's QUERY, so every case is placeable
        kinds = {row["kind"] for row in case["rows"]}
        assert kinds == {"channel"} or "channel" not in kinds, _case_id(case)


# --- the AD-1347 lookup: a record grounds, a failed lookup's echo does not (BF-922 A1) -----------------

LOOKUP_AGENT = "agent-7"


@pytest.mark.parametrize(
    ("outcome", "grounds"),
    [
        ("found", True), ("ambiguous", True), ("not_found", False), ("invalid_ref", False),
        ("refused", False), ("unavailable", False), (None, False),
    ],
    ids=["found", "ambiguous", "not_found", "invalid_ref", "refused", "unavailable", "no_outcome"],
)
def test_the_lookup_text_grounds_only_for_a_record_outcome(outcome: str | None, grounds: bool) -> None:
    context: dict[str, Any] = {"_ward_room_lookup_context": "No Ward Room thread or post with id 7f3a9c2e."}
    if outcome is not None:
        context["_ward_room_lookup_outcome"] = outcome

    assert ("7f3a9c2e" in composer_world_text(context, [])) is grounds
    assert "7f3a9c2e" in _build_user_prompt(context, [])  # COMPOSE's own prompt is unchanged


@dataclass
class _ChainRuntime:
    """The runtime surface the real chain handlers read (as the BF-922 round-1 review's probe built it)."""

    ward_room: WardRoomService
    config: SystemConfig = field(default_factory=SystemConfig)
    events: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    boot_camp: Any = None
    trust_network: Any = None
    cognitive_journal: Any = None
    ontology: Any = None

    def emit_event(self, event: Any, data: dict[str, Any]) -> None:
        self.events.append((event, dict(data)))


class _TwoCalls:
    """ANALYZE's JSON, then COMPOSE's reply; any further call (the judge, REFLECT) fails the test."""

    def __init__(self, reply: str) -> None:
        self._responses = [
            json.dumps({
                "contribution_assessment": "RESPOND",
                "intended_actions": ["ward_room_reply"],
                "composition_brief": {"situation": "Status request"},
            }),
            reply,
        ]
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        assert self._responses, "an unexpected model call (the judge or REFLECT)"
        self.requests.append(request)
        return LLMResponse(
            content=self._responses.pop(0), tier="fast", model="test-model",
            prompt_tokens=5, completion_tokens=5, tokens_used=10, usage_reported=True,
        )


async def _ward_room(tmp_path: Path) -> WardRoomService:
    """A started Ward Room whose lookup reads an empty archive, so a search completes."""
    ward = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ward.start()
    archive = tmp_path / "ward_room_archive"
    archive.mkdir()
    await ward.start_prune_loop(WardRoomConfig(prune_interval_seconds=3600.0), archive)
    await ward.stop_prune_loop()
    return ward


async def _chain_after_lookup(
    ward: WardRoomService, ref: str, reply: str,
) -> tuple[dict[str, Any], dict[str, Any], _TwoCalls]:
    """AD-1347's dispatch with ANALYZE's ``ref``, then the real ward_room_notification chain with real handlers."""
    runtime = _ChainRuntime(ward_room=ward)
    client = _TwoCalls(reply)
    agent = CognitiveAgent(
        agent_id=LOOKUP_AGENT, instructions="Report observed facts.", llm_client=client, runtime=runtime,
    )
    agent.agent_type = "science_officer"
    agent.callsign = "Kira"
    agent.department = "science"
    executor = SubTaskExecutor(config=runtime.config.sub_task)
    executor.register_handler(SubTaskType.QUERY, QueryHandler(runtime))
    executor.register_handler(SubTaskType.ANALYZE, AnalyzeHandler(llm_client=client, runtime=runtime))
    executor.register_handler(SubTaskType.COMPOSE, ComposeHandler(llm_client=client, runtime=runtime))
    executor.register_handler(SubTaskType.EVALUATE, EvaluateHandler(llm_client=client, runtime=runtime))
    executor.register_handler(SubTaskType.REFLECT, ReflectHandler(llm_client=client, runtime=runtime))
    agent.set_sub_task_executor(executor)
    channel = await ward.get_or_create_dm_channel(LOOKUP_AGENT, "peer", "Kira", "Peer")
    thread = await ward.create_thread(channel.id, "peer", "Status", "What is the status?", author_callsign="Peer")
    observation: dict[str, Any] = {
        "intent": "ward_room_notification",
        "intent_id": "intent-1",
        "context": "Thread: Status",
        "_agent_id": LOOKUP_AGENT,
        "params": {"thread_id": thread.id, "channel_id": channel.id, "author_id": "peer", "is_dm_channel": True},
    }
    triage = [SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE, name="analyze-thread", success=True,
        result={"intended_actions": ["ward_room_reply", "ward_room_lookup"], "ward_room_lookup_ref": ref},
    )]
    await agent._maybe_dispatch_ward_room_lookup(triage, observation)
    chain = agent._build_chain_for_intent(observation)
    assert chain is not None and executor.can_execute(chain)
    decision = await agent._execute_sub_task_chain(chain, observation)
    assert decision is not None
    return decision, observation, client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ref", "reply", "outcome", "echoed"),
    [
        ("7f3a9c2e-0000-0000-0000-b81d04aabbcc", "Per 7f3a9c2e and b81d04aabbcc, the backlog cleared.",
         "not_found", ("7f3a9c2e", "b81d04aabbcc")),
        ("7f3a9c2e b81d04aabbcc", "Per 7f3a9c2e and 51d91a7d, the backlog cleared.",
         "invalid_ref", ("7f3a9c2e", "51d91a7d")),
    ],
    ids=["not_found", "invalid_ref"],
)
async def test_a_failed_lookup_echo_does_not_ground_through_the_real_chain(
    tmp_path: Path, ref: str, reply: str, outcome: str, echoed: tuple[str, ...],
) -> None:
    """Round 1, M1 finding 1: the reference is ANALYZE's output and a failed lookup repeats it (an invalid one adds
    the example id 51d91a7d); M1 candidate 1 posted this reply. COMPOSE still sees the echo; it grounds nothing."""
    ward = await _ward_room(tmp_path)
    try:
        decision, observation, client = await _chain_after_lookup(ward, ref, reply)
    finally:
        await ward.stop()

    assert observation["_ward_room_lookup_outcome"] == outcome
    assert len(client.requests) == 2
    assert all(cited in client.requests[1].prompt for cited in echoed)  # the echo reached COMPOSE, as before
    assert decision["_suppressed"] is True
    assert decision["_suppression_reason"] == "confabulation_detected"


async def _lettered_thread(ward: WardRoomService, channel_id: str) -> Any:
    """A thread by the asking agent whose first 8 and last 12 hex both hold a letter, so both are cited ids."""
    for _ in range(20):
        thread = await ward.create_thread(
            channel_id, LOOKUP_AGENT, "Backlog", "Backlog cleared at 0300.", author_callsign="Kira",
        )
        if cited_ids(thread.id[:8]) and cited_ids(thread.id[-12:]):
            return thread
    raise AssertionError("no thread id with a letter in both cited segments in 20 tries")


@pytest.mark.asyncio
async def test_a_found_record_grounds_through_the_real_chain(tmp_path: Path) -> None:
    """The partner of the test above: a record the lookup found is world data, so a reply citing it is posted."""
    ward = await _ward_room(tmp_path)
    try:
        channel = await ward.get_or_create_dm_channel(LOOKUP_AGENT, "peer", "Kira", "Peer")
        record = await _lettered_thread(ward, channel.id)
        reply = f"Per {record.id[:8]} and {record.id[-12:]}, the backlog cleared."
        decision, observation, client = await _chain_after_lookup(ward, record.id, reply)
    finally:
        await ward.stop()

    assert observation["_ward_room_lookup_outcome"] == "found"
    assert len(client.requests) == 2
    assert not decision.get("_suppressed")
    assert decision["llm_output"] == reply
