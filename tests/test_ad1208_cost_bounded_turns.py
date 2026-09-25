"""AD-1208 (#1154): bound a DM agentic turn by what it spends, and stop counting tier-1 steps.

The conversational (DM) agentic turn had one bound, a flat step limit
(``dm_agentic.max_iterations``). A read-only research task -- fifteen page
fetches -- therefore stopped at five steps on a small cap and asked the Captain
to approve more, although nothing it did needed approval (probe P-1).

AD-1208 gives the turn the per-turn token budget the loop has always supported
(``dm_agentic.token_budget``). While that budget is armed, an iteration whose
every call is tier 1 -- observation only -- is not counted toward
``max_iterations``; tokens and a total-iteration backstop
(``dm_agentic.max_total_iterations``) bound that work instead. Every other step
counts exactly as before. With ``token_budget`` unset, the shipped default, the
turn is byte-identical to what it was.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from probos.capability_request import CapabilityRequestStore
from probos.cognitive import agentic_dispatch, turn_cost
from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.continue_or_ask import (
    CONTINUE_ACTION,
    CONTINUE_SCOPE_KEY,
    CONTINUE_TOOL_ID,
    _CUT_OFF_LEAD_WITH_WORK,
    _CUT_OFF_SEPARATOR,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness import agentic_loop
from probos.cognitive.swe_harness.agentic_loop import (
    PARALLEL_SAFE_TOOL_IDS,
    AgenticLoop,
    _counts_toward_max_iterations,
    is_tier_1_tool_call,
)
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.cognitive.turn_promotion import _ACK_TEMPLATE, _REPORT_EMPTY
from probos.config import (
    TRUST_DEFAULT,
    TRUST_SENIOR,
    ApprovalInboxConfig,
    BrowserToolConfig,
    DmAgenticConfig,
    load_config,
)
from probos.consensus.trust import TrustNetwork
from probos.dm_reply import ToolFailures
from probos.integrations.mcp_bridge.risk import McpToolRisk
from probos.security.audit import AuditLog
from probos.tools.action_approvals import ActionApprovalStore
from probos.tools.browser.actions import classify_action
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import _AGENT_ACTIONS, BrowserTool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.workforce import WorkItem

from tests.test_ad706_browser_tool import _FakePage, _make_session_factory


# ── M1: the seam -- the real DM turn, executor and loop (probe P-1) ──

# The reference vessel's ``agentic_loop.tool_result_max_chars``.
_BODY_CHARS = 6000
_N_FETCH = 15
_FINAL_TEXT = "FIFTEEN-ROWS-DONE"
# The exact keys the DM turn passed to ``executor.run`` before AD-1208, as
# probe P-1 recorded them.
_P1_RUN_KWARGS = [
    "agent_id",
    "compaction_threshold",
    "compactor",
    "compose_disposition",
    "failure_scope",
    "instructions",
    "max_iterations",
    "owned_steps_turn_id",
    "priority",
    "runtime",
    "task_text",
    "thread_id",
    "tier",
]


class _Fetch:
    """Read-only stand-in registered under the real mesh tool id ``http_fetch``."""

    tool_id = "http_fetch"
    name = "http_fetch"
    tool_type = ToolType.UTILITY_AGENT
    description = "Perform an HTTP request against a URL and return the response."
    input_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    }
    output_schema = {"type": "object"}

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def invoke(self, params: dict, context: dict | None = None) -> ToolResult:
        url = str((params or {}).get("url", ""))
        self.calls.append(url)
        return ToolResult(output=(f"<html>{url} " + "x" * _BODY_CHARS)[:_BODY_CHARS])


class _UsageZeroResponse:
    def __init__(self, blocks: list, content: str = "") -> None:
        self.content_blocks = blocks
        self.content = content
        # The Copilot proxy reports no usage, so the loop charges BF-680 estimates.
        self.tokens_used = 0
        self.error = None
        self.model = "scripted"


class _FetchingLLM:
    """Asks for one fetch per response, ``n`` times, then answers in text."""

    def __init__(self, n: int) -> None:
        self._n = n
        self.calls = 0

    async def complete(self, req: Any, **_kwargs: Any) -> _UsageZeroResponse:
        self.calls += 1
        if self.calls <= self._n:
            i = self.calls
            return _UsageZeroResponse(
                [
                    TextBlock(text=f"Fetching package {i}."),
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id=f"c{i}",
                            name="http_fetch",
                            arguments={"url": f"https://pypi.org/project/p{i}/"},
                        )
                    ),
                ],
                content=f"Fetching package {i}.",
            )
        return _UsageZeroResponse([TextBlock(text=_FINAL_TEXT)], content=_FINAL_TEXT)


def _fetch_runtime(registry: ToolRegistry, store: Any, cfg: DmAgenticConfig) -> Any:
    # No ``trust_network``: the trust multiplier is neutral here (M5 covers trust).
    return SimpleNamespace(
        config=SimpleNamespace(
            agentic_dispatch=SimpleNamespace(enabled=True),
            dm_agentic=cfg,
        ),
        tool_registry=registry,
        tool_permission_store=ToolPermissionStore(),
        capability_gap_driver=None,
        intent_bus=None,
        attachment_store=None,
        emit_event=None,
        capability_request_store=store,
        action_approval_store=None,
        fault_report_store=None,
    )


async def _fifteen_fetch_turn(monkeypatch: Any, tmp_path: Any, cfg: DmAgenticConfig) -> dict[str, Any]:
    """One real DM turn on the fifteen-fetch task; records every ``run`` call."""
    registry = ToolRegistry()
    fetch = _Fetch()
    registry.register(fetch, provider="ad1208-test", default_permissions={"ensign": "read"})
    store = CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"))
    await store.start()
    calls: list[dict[str, Any]] = []
    outcomes: list[tuple[str, int, int, str]] = []
    real_run = agentic_dispatch.WorkItemAgenticExecutor.run

    async def _recording_run(self: Any, **kwargs: Any) -> Any:
        calls.append(dict(kwargs))
        outcome = await real_run(self, **kwargs)
        outcomes.append(
            (outcome.stopped_reason, outcome.iterations, outcome.total_tokens, outcome.token_source)
        )
        return outcome

    monkeypatch.setattr(agentic_dispatch.WorkItemAgenticExecutor, "run", _recording_run)
    try:
        agent = SimpleNamespace(
            _runtime=_fetch_runtime(registry, store, cfg),
            _llm_client=_FetchingLLM(_N_FETCH),
            id="counselor-ezri",
            department="counseling",
            rank="lieutenant",
        )
        agent._conversational_agentic_will_run = (
            lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
        )
        text = await CognitiveAgent._maybe_run_conversational_agentic(
            agent,
            {"intent": "direct_message", "params": {}},
            system_prompt="You are Ezri. " + "s" * 8000,
            user_message="Fetch the fifteen PyPI project pages one at a time and tabulate them.",
        )
        pending = await store.list_pending()
    finally:
        await store.stop()
    return {
        "text": text,
        "fetches": list(fetch.calls),
        "pending": pending,
        "calls": calls,
        "outcomes": outcomes,
    }


@pytest.mark.asyncio
async def test_m1_armed_read_only_turn_completes_at_step_limit_five(monkeypatch, tmp_path) -> None:
    """Armed, fifteen read-only fetches finish at a step limit of five, with no ask."""
    cfg = DmAgenticConfig(
        enabled=True,
        max_iterations=5,
        continue_or_ask_enabled=True,
        token_budget=500_000,
        max_total_iterations=100,
    )
    # Premise (H-1): without the field pydantic ignores the keyword, and the turn
    # below would run unarmed and prove nothing.
    assert cfg.token_budget == 500_000

    got = await _fifteen_fetch_turn(monkeypatch, tmp_path, cfg)

    assert got["fetches"] == [f"https://pypi.org/project/p{i}/" for i in range(1, _N_FETCH + 1)]
    assert got["text"] == _FINAL_TEXT
    assert got["pending"] == []
    assert len(got["calls"]) == 1
    assert got["calls"][0]["token_budget"] == 500_000
    assert got["calls"][0]["max_total_iterations"] == 100
    [(reason, iterations, total_tokens, source)] = got["outcomes"]
    assert (reason, iterations, source) == ("complete", 16, "estimated")
    assert total_tokens < 500_000


@pytest.mark.asyncio
async def test_m1_unarmed_turn_still_stops_at_five_and_asks(monkeypatch, tmp_path) -> None:
    """The control: unarmed, the same turn stops at the step limit and files one ask."""
    cfg = DmAgenticConfig(enabled=True, max_iterations=5, continue_or_ask_enabled=True)

    got = await _fifteen_fetch_turn(monkeypatch, tmp_path, cfg)

    assert len(got["fetches"]) == 5
    assert got["text"].startswith(_CUT_OFF_LEAD_WITH_WORK)
    assert [request.kind for request in got["pending"]] == ["continue"]
    assert len(got["calls"]) == 1
    assert sorted(got["calls"][0]) == _P1_RUN_KWARGS
    assert got["outcomes"][0][0] == "max_iterations"


# ── M2: config -- two default-off fields and two corrected descriptions ──

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_m2_defaults_are_off() -> None:
    cfg = DmAgenticConfig()

    assert cfg.token_budget is None
    assert cfg.max_total_iterations == 100


def test_m2_bounds_reject_at_the_field() -> None:
    for field, bad in (
        ("token_budget", 1023),
        ("max_total_iterations", 0),
        ("max_total_iterations", 251),
    ):
        with pytest.raises(ValidationError) as caught:
            DmAgenticConfig(**{field: bad})
        # A rejection about a sibling, or about the model, would not be this bound.
        locs = [tuple(error.get("loc", ())) for error in caught.value.errors()]
        assert locs and set(locs) == {(field,)}, (field, bad, locs)

    assert DmAgenticConfig(token_budget=1024).token_budget == 1024
    assert DmAgenticConfig(max_total_iterations=1).max_total_iterations == 1
    assert DmAgenticConfig(max_total_iterations=250).max_total_iterations == 250


def test_m2_descriptions_state_the_cap_and_the_exemption() -> None:
    fields = DmAgenticConfig.model_fields

    max_iterations = fields["max_iterations"].description
    assert "runaway backstop" in max_iterations
    assert "classify_action" in max_iterations
    assert "PARALLEL_SAFE_TOOL_IDS" in max_iterations
    assert "max_total_iterations" in fields["continue_or_ask_max_passes"].description
    token_budget = fields["token_budget"].description
    assert "between half and twice" in token_budget
    assert "never changes which tools" in token_budget
    assert "read_page, web_search" in token_budget
    assert "Trust does not move it" in fields["max_total_iterations"].description


def test_m2_reference_yaml_leaves_the_vessel_unarmed() -> None:
    config = load_config(_REPO_ROOT / "config" / "system.yaml")

    # Premise: the reference file's own dm_agentic section was read (default False).
    assert config.dm_agentic.enabled is True
    assert config.dm_agentic.token_budget is None


# ── M3: the loop -- tier-1 steps uncounted while armed, by one shared predicate ──

_ARMED = {"token_budget": 10**9, "max_total_iterations": 20}
# P26 / probe D-3: the browser actions the real classify_action puts at tier 1.
_BROWSER_TIER_1 = {
    "back",
    "extract_text",
    "forward",
    "mouse_move",
    "screenshot",
    "scroll",
    "state",
    "verify",
    "wait",
}
# D-3's parameter shapes: none, a plain URL, a payment URL, an element index, a
# key chord, and a download-looking target.
_BROWSER_PARAM_SHAPES: list[dict[str, Any]] = [
    {},
    {"url": "https://example.com"},
    {"url": "https://bank.example.com/checkout"},
    {"index": 0},
    {"keys": ["Control", "w"]},
    {"selector_or_url": "https://x.example/setup.exe"},
]
_BROWSER_ACTIONS = sorted(
    set(_AGENT_ACTIONS)
    | {"compute_use_click", "upload_file", "eval_js", "fill_credential", "download", "bogus", ""}
)


class _LoopResponse:
    def __init__(self, blocks: list, content: str = "", tokens: int = 1) -> None:
        self.content_blocks = blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLoopLLM:
    def __init__(self, responses: list[_LoopResponse]) -> None:
        self._responses = list(responses)

    async def complete(self, req: Any, **_kwargs: Any) -> _LoopResponse:
        if self._responses:
            return self._responses.pop(0)
        return _LoopResponse([], content="done")


class _RecordingToolExecutor:
    """Answers every tool id with a success and records each call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def invoke(self, *, agent_id: str, tool_id: str, params: Any, **_kwargs: Any) -> ToolResult:
        self.calls.append(tool_id)
        return ToolResult(output={"ok": True})


def _use(name: str, arguments: dict[str, Any] | None = None) -> ToolUseBlock:
    return ToolUseBlock(tool_call=ToolCallRequest(name=name, arguments=dict(arguments or {})))


def _fetch_use(i: int = 0) -> ToolUseBlock:
    return _use("http_fetch", {"url": f"https://example.org/{i}"})


def _step(*uses: ToolUseBlock, text: str = "", tokens: int = 1) -> _LoopResponse:
    blocks = ([TextBlock(text=text)] if text else []) + list(uses)
    return _LoopResponse(blocks, content=text, tokens=tokens)


def _answer(text: str = "All done.") -> _LoopResponse:
    return _LoopResponse([TextBlock(text=text)], content=text)


async def _run_loop(
    responses: list[_LoopResponse], **loop_kwargs: Any,
) -> tuple[Any, _RecordingToolExecutor]:
    executor = _RecordingToolExecutor()
    loop = AgenticLoop(llm_client=_ScriptedLoopLLM(responses), tool_executor=executor, **loop_kwargs)
    result = await loop.run(
        system_prompt="You are Ezri.",
        user_message="Research the packages.",
        tools=[],
        context={"agent_id": "counselor-ezri"},
    )
    return result, executor


def _fresh_session(session_id: str = "s1") -> BrowserSession:
    return BrowserSession(
        config=BrowserToolConfig(enabled=True), session_id=session_id, agent_id="a1",
    )


def _bank_session() -> BrowserSession:
    session = _fresh_session("s2")
    session.set_last_url("https://bank.example.com/payment")
    return session


@pytest.mark.asyncio
async def test_m3_unarmed_loop_counts_every_read_only_step() -> None:
    result, executor = await _run_loop([_step(_fetch_use(i)) for i in range(10)], max_iterations=3)

    assert (result.stopped_reason, result.iterations) == ("max_iterations", 3)
    assert executor.calls == ["http_fetch"] * 3


@pytest.mark.asyncio
async def test_m3_armed_read_only_steps_are_not_counted() -> None:
    responses = [_step(_fetch_use(i)) for i in range(6)] + [_answer()]

    result, executor = await _run_loop(responses, max_iterations=2, **_ARMED)

    assert (result.stopped_reason, result.iterations) == ("complete", 7)
    assert executor.calls == ["http_fetch"] * 6


@pytest.mark.asyncio
@pytest.mark.parametrize("other", ["browser", "write_file", "mcp:srv:tool", "", "HTTP_FETCH"])
async def test_m3_armed_step_with_any_other_call_counts(other: str) -> None:
    # ``browser`` with no action cannot be shown to be tier 1, so it counts too.
    responses = [_step(_fetch_use(i), _use(other, {})) for i in range(6)]

    result, _ = await _run_loop(responses, max_iterations=2, **_ARMED)

    assert (result.stopped_reason, result.iterations) == ("max_iterations", 2)


@pytest.mark.asyncio
async def test_m3_armed_mixed_run_counts_only_the_other_steps() -> None:
    def write() -> ToolUseBlock:
        return _use("write_file", {"path": "notes.md", "content": "x"})

    responses = [
        _step(_fetch_use(1)),
        _step(write()),
        _step(_fetch_use(2)),
        _step(_fetch_use(3)),
        _step(write()),
        _answer("never reached"),
    ]

    result, executor = await _run_loop(responses, max_iterations=2, **_ARMED)

    assert (result.stopped_reason, result.iterations) == ("max_iterations", 5)
    assert executor.calls == ["http_fetch", "write_file", "http_fetch", "http_fetch", "write_file"]


@pytest.mark.asyncio
async def test_m3_total_backstop_ends_a_read_only_run_as_max_iterations() -> None:
    responses = [_step(_fetch_use(i), text=f"Fetching page {i}.") for i in range(1, 10)]

    result, executor = await _run_loop(
        responses, max_iterations=2, token_budget=10**9, max_total_iterations=4,
    )

    assert (result.stopped_reason, result.iterations) == ("max_iterations", 4)
    assert executor.calls == ["http_fetch"] * 4
    # BF-697: the step-limit exit reports the last thing the agent said.
    assert result.final_text == "Fetching page 4."


@pytest.mark.asyncio
async def test_m3_token_budget_still_binds_read_only_steps() -> None:
    # A budget below one call: the provider reports no usage, so the first call is
    # charged a BF-680 estimate, and that estimate already crosses it.
    result, executor = await _run_loop(
        [_step(_fetch_use(i), tokens=0) for i in range(6)],
        max_iterations=2, token_budget=1, max_total_iterations=20,
    )
    assert (result.stopped_reason, result.iterations, result.token_source) == (
        "token_budget", 1, "estimated",
    )
    assert executor.calls == []

    # Measured spend: three uncounted steps run past max_iterations=2, and the
    # budget then stops the fourth before its tools run.
    result, executor = await _run_loop(
        [_step(_fetch_use(i), tokens=1000) for i in range(6)],
        max_iterations=2, token_budget=3500, max_total_iterations=20,
    )
    assert (result.stopped_reason, result.iterations, result.total_tokens) == (
        "token_budget", 4, 4000,
    )
    assert executor.calls == ["http_fetch"] * 3


@pytest.mark.parametrize(
    ("total", "max_iterations", "budget", "sentinel"),
    [
        (3, 5, 1000, "agentic_loop_max_total_iterations_invalid"),
        (5, 5, None, "agentic_loop_max_total_iterations_requires_token_budget"),
        (5, 5, 0, "agentic_loop_max_total_iterations_requires_token_budget"),
        (True, 1, 1000, "agentic_loop_max_total_iterations_invalid"),
        (5, 0, 1000, "agentic_loop_max_total_iterations_invalid"),
        (5.0, 5, 1000, "agentic_loop_max_total_iterations_invalid"),
    ],
)
def test_m3_constructor_rejects_invalid_pairs(
    total: Any, max_iterations: int, budget: int | None, sentinel: str,
) -> None:
    with pytest.raises(ValueError) as caught:
        AgenticLoop(
            llm_client=_ScriptedLoopLLM([]),
            tool_executor=_RecordingToolExecutor(),
            max_iterations=max_iterations,
            token_budget=budget,
            max_total_iterations=total,
        )
    assert str(caught.value) == sentinel

    # The smallest valid pair constructs.
    AgenticLoop(
        llm_client=_ScriptedLoopLLM([]),
        tool_executor=_RecordingToolExecutor(),
        max_iterations=5,
        token_budget=1,
        max_total_iterations=5,
    )


@pytest.mark.asyncio
async def test_m3_exemption_reads_is_tier_1_tool_call(monkeypatch) -> None:
    monkeypatch.setattr(agentic_loop, "is_tier_1_tool_call", lambda name, arguments: False)

    result, _ = await _run_loop([_step(_fetch_use(i)) for i in range(6)], max_iterations=2, **_ARMED)

    # With the shared predicate answering "not tier 1", armed counts like unarmed.
    assert (result.stopped_reason, result.iterations) == ("max_iterations", 2)


@pytest.mark.asyncio
async def test_m3_armed_step_limit_logs_the_counts(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.swe_harness.agentic_loop")

    await _run_loop(
        [_step(_fetch_use(i)) for i in range(6)],
        max_iterations=2, token_budget=10**9, max_total_iterations=4,
    )

    assert "AD-1208: agent" in caplog.text
    assert "counted toward max_iterations=2" in caplog.text


def test_m3_is_tier_1_tool_call_equals_classify_action_on_every_browser_case() -> None:
    fresh, bank = _fresh_session(), _bank_session()
    # Premise: the session decides the click family, which is why no session-free
    # answer may ever call it tier 1.
    assert classify_action(bank, "click", {"index": 0}) == 3
    answers: set[bool] = set()
    tier_1_actions: set[str] = set()

    for action in _BROWSER_ACTIONS:
        for params in _BROWSER_PARAM_SHAPES:
            for session in (fresh, bank):
                expected = classify_action(session, action, dict(params)) == 1
                got = is_tier_1_tool_call("browser", {"action": action, **params})
                assert got is expected, (action, params, session.session_id)
                answers.add(got)
                if expected:
                    tier_1_actions.add(action)

    # Premise: the equality saw both answers, so it discriminated.
    assert answers == {True, False}
    # Golden (P26): a change to classify_action's silent band surfaces here on purpose.
    assert tier_1_actions == _BROWSER_TIER_1


def test_m3_is_tier_1_tool_call_equals_the_read_only_allowlist_elsewhere() -> None:
    names = sorted(PARALLEL_SAFE_TOOL_IDS) + [
        "write_file",
        "edit_file",
        "run_python",
        "mcp:srv:tool",
        "HTTP_FETCH",
        "http_fetch ",
        "",
        "browser_x",
        "delegate_task",
    ]
    answers = {name: is_tier_1_tool_call(name, {}) for name in names}

    assert answers == {name: name in PARALLEL_SAFE_TOOL_IDS for name in names}
    assert set(answers.values()) == {True, False}
    for bad_name in (None, 5, b"http_fetch"):
        assert is_tier_1_tool_call(bad_name, {}) is False, bad_name
    for bad_arguments in (None, [], "state", {}, {"action": None}, {"action": 5}):
        assert is_tier_1_tool_call("browser", bad_arguments) is False, bad_arguments


def test_m3_classifying_creates_no_browser_session(monkeypatch) -> None:
    created: list[Any] = []
    real_init = BrowserSession.__init__

    def _recording_init(self: Any, *args: Any, **kwargs: Any) -> None:
        created.append(self)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(BrowserSession, "__init__", _recording_init)

    for action in _BROWSER_ACTIONS:
        is_tier_1_tool_call("browser", {"action": action, "index": 0})
    assert created == []

    control = _fresh_session("control")
    # Premise: the recorder does see a construction.
    assert len(created) == 1 and created[0] is control


def test_m3_counting_predicate() -> None:
    fetch = _use("http_fetch", {"url": "u"})

    assert _counts_toward_max_iterations([]) is True
    assert _counts_toward_max_iterations([fetch, _use("http_fetch", {"url": "v"})]) is False
    assert _counts_toward_max_iterations([fetch, _use("browser", {"action": "state"})]) is False
    assert _counts_toward_max_iterations([_use("browser", {"action": "extract_text"})]) is False
    assert _counts_toward_max_iterations(
        [fetch, _use("browser", {"action": "goto", "url": "u"})]
    ) is True
    assert _counts_toward_max_iterations([fetch, _use("write_file", {})]) is True
    assert _counts_toward_max_iterations([_use("browser", {"action": "click", "index": 0})]) is True


@pytest.mark.asyncio
async def test_m3_armed_browser_observation_steps_are_not_counted() -> None:
    responses = [
        _step(_use("browser", {"action": "state"})),
        _step(_use("browser", {"action": "extract_text"})),
        # H-21: a real browser wait sleeps, so it is always zero here.
        _step(_use("browser", {"action": "wait", "milliseconds": 0})),
        _step(_use("browser", {"action": "back"})),
        _answer(),
    ]

    result, executor = await _run_loop(responses, max_iterations=1, **_ARMED)

    assert (result.stopped_reason, result.iterations) == ("complete", 5)
    assert executor.calls == ["browser"] * 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "params"),
    [("goto", {"url": "https://example.com"}), ("click", {"index": 0})],
)
async def test_m3_armed_browser_goto_and_click_count(action: str, params: dict[str, Any]) -> None:
    responses = [_step(_use("browser", {"action": action, **params})) for _ in range(6)]

    result, _ = await _run_loop(responses, max_iterations=2, **_ARMED)

    assert (result.stopped_reason, result.iterations) == ("max_iterations", 2)


@pytest.mark.asyncio
async def test_m3_unarmed_loop_never_classifies(monkeypatch) -> None:
    def _raise(name: object, arguments: object) -> bool:
        raise RuntimeError("the loop classified a call")

    monkeypatch.setattr(agentic_loop, "is_tier_1_tool_call", _raise)
    # Premise: an armed run does reach the patched predicate.
    with pytest.raises(RuntimeError, match="classified a call"):
        await _run_loop([_step(_fetch_use(1))], max_iterations=2, **_ARMED)

    result, executor = await _run_loop([_step(_fetch_use(i)) for i in range(6)], max_iterations=2)

    assert (result.stopped_reason, result.iterations) == ("max_iterations", 2)
    assert result.error == ""
    assert executor.calls == ["http_fetch"] * 2


# ── M4: the executor -- a pass-through that forwards the backstop only when set ──


def _executor_runtime() -> Any:
    registry = ToolRegistry()
    registry.register(_Fetch(), provider="ad1208-test", default_permissions={"ensign": "read"})
    return SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=True)),
        tool_registry=registry,
        tool_permission_store=ToolPermissionStore(),
        capability_gap_driver=None,
        intent_bus=None,
        attachment_store=None,
        emit_event=None,
    )


async def _executor_run(**kwargs: Any) -> Any:
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=_ScriptedLoopLLM([_answer("Done.")]))
    return await executor.run(
        agent_id="counselor-ezri",
        instructions="You are Ezri.",
        task_text="Say hello.",
        runtime=_executor_runtime(),
        # The loop refuses a backstop below the step limit, and its own default is 25.
        max_iterations=5,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_m4_run_forwards_max_total_iterations_only_when_set(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    original = agentic_dispatch.WorkItemAgenticExecutor._run_reserved

    async def _record(self: Any, **kwargs: Any) -> Any:
        calls.append(dict(kwargs))
        return await original(self, **kwargs)

    monkeypatch.setattr(agentic_dispatch.WorkItemAgenticExecutor, "_run_reserved", _record)

    await _executor_run()
    await _executor_run(max_total_iterations=7, token_budget=5000)

    assert len(calls) == 2
    assert "max_total_iterations" not in calls[0]
    assert calls[1]["max_total_iterations"] == 7
    assert calls[1]["token_budget"] == 5000


@pytest.mark.asyncio
async def test_m4_loop_is_constructed_with_it_only_when_set(monkeypatch) -> None:
    constructed: list[dict[str, Any]] = []
    original = AgenticLoop.__init__

    def _record(self: Any, **kwargs: Any) -> None:
        constructed.append(dict(kwargs))
        original(self, **kwargs)

    monkeypatch.setattr(AgenticLoop, "__init__", _record)

    unarmed = await _executor_run()
    armed = await _executor_run(max_total_iterations=7, token_budget=5000)

    # Premise: both runs really constructed and ran a loop.
    assert (unarmed.stopped_reason, armed.stopped_reason) == ("complete", "complete")
    assert len(constructed) == 2
    assert "max_total_iterations" not in constructed[0]
    assert "token_budget" not in constructed[0]
    assert constructed[1]["max_total_iterations"] == 7
    assert constructed[1]["token_budget"] == 5000


# ── M5: the per-turn budget (turn_cost.py) and the DM wiring ──

_BUDGET = 500_000


def _cost_cfg(**overrides: Any) -> Any:
    # A namespace, not DmAgenticConfig: a value that skipped Pydantic must still
    # degrade at the arming site rather than fail.
    base: dict[str, Any] = {"token_budget": _BUDGET, "max_total_iterations": 100}
    base.update(overrides)
    return SimpleNamespace(**base)


def _network(alpha: float, beta: float, agent_id: str = "counselor-ezri") -> TrustNetwork:
    # H-18: a fresh network per case; create_with_prior keeps whichever prior came first.
    network = TrustNetwork()
    network.create_with_prior(agent_id, alpha, beta)
    return network


def _record(alpha: Any, beta: Any) -> Any:
    record = _network(alpha, beta).get_record("counselor-ezri")
    assert record is not None
    return record


def _unclamped(alpha: float, beta: float) -> float:
    return 1.0 + (alpha / (alpha + beta) - TRUST_DEFAULT) / (TRUST_SENIOR - TRUST_DEFAULT)


class _RecordingTrustSource:
    """A real in-memory ``TrustNetwork`` that records every read made through it."""

    def __init__(self, network: TrustNetwork) -> None:
        self._network = network
        self.reads: list[tuple[str, Any]] = []

    def get_record(self, agent_id: str) -> Any:
        self.reads.append(("get_record", agent_id))
        return self._network.get_record(agent_id)

    def get_score(self, agent_id: str) -> float:
        self.reads.append(("get_score", agent_id))
        return self._network.get_score(agent_id)

    def __getattr__(self, name: str) -> Any:
        self.reads.append((name, None))
        return getattr(self._network, name)


class _RaisingTrustSource:
    def __init__(self) -> None:
        self.calls = 0

    def get_record(self, agent_id: str) -> Any:
        self.calls += 1
        raise RuntimeError("the trust store is mid-write")


def _arm(source: Any = None, *, agent_id: str = "counselor-ezri", **cfg: Any) -> Any:
    armed = turn_cost.TurnCostBudget.from_config(
        _cost_cfg(**cfg), max_iterations=5, agent_id=agent_id, trust_source=source,
    )
    assert armed is not None
    return armed


@pytest.mark.parametrize(
    "cfg",
    [
        _cost_cfg(token_budget=None),
        _cost_cfg(token_budget=1023),
        _cost_cfg(token_budget=True),
        _cost_cfg(token_budget=1024.0),
        MagicMock(),
    ],
    ids=["none", "below-floor", "bool", "float", "magicmock-config"],
)
def test_m5_from_config_is_off_unless_the_budget_is_a_valid_int(cfg: Any) -> None:
    assert turn_cost.TurnCostBudget.from_config(cfg, max_iterations=5) is None


def test_m5_from_config_arms_at_the_floor_and_needs_a_step_limit() -> None:
    assert turn_cost.TurnCostBudget.from_config(_cost_cfg(token_budget=1024), max_iterations=0) is None

    for cfg in (_cost_cfg(token_budget=1024), DmAgenticConfig(token_budget=1024)):
        armed = turn_cost.TurnCostBudget.from_config(cfg, max_iterations=5)
        assert armed is not None
        assert armed.loop_kwargs() == {"token_budget": 1024, "max_total_iterations": 100}


@pytest.mark.parametrize(
    ("total", "expected"),
    [(3, 5), (999, 250), (0, 100), (None, 100), (True, 100), (7.0, 100), (100, 100)],
)
def test_m5_totals_are_clamped_into_what_the_loop_accepts(total: Any, expected: int) -> None:
    armed = _arm(max_total_iterations=total)

    assert armed.loop_kwargs()["max_total_iterations"] == expected
    # The loop's own validator accepts whatever the arming site hands it.
    AgenticLoop(
        llm_client=_ScriptedLoopLLM([]),
        tool_executor=_RecordingToolExecutor(),
        max_iterations=5,
        **armed.loop_kwargs(),
    )


def test_m5_a_missing_total_becomes_the_default() -> None:
    armed = turn_cost.TurnCostBudget.from_config(SimpleNamespace(token_budget=_BUDGET), max_iterations=5)

    assert armed.loop_kwargs() == {"token_budget": _BUDGET, "max_total_iterations": 100}


def test_m5_each_pass_gets_what_is_left_of_one_budget() -> None:
    armed = _arm()

    armed.record(SimpleNamespace(total_tokens=200_000, token_source="estimated"))
    assert armed.loop_kwargs()["token_budget"] == 300_000

    armed.record(SimpleNamespace(total_tokens=350_000, token_source="estimated"))
    # Overspent: the floor of 1 is a guard, never a path (Q6).
    assert armed.loop_kwargs()["token_budget"] == 1
    assert armed.spent == 550_000


@pytest.mark.parametrize("tokens", ["100", -5, None, True, 2.5])
def test_m5_record_ignores_a_malformed_count(tokens: Any) -> None:
    armed = _arm()

    armed.record(SimpleNamespace(total_tokens=tokens, token_source="estimated"))

    assert armed.spent == 0
    assert armed.loop_kwargs()["token_budget"] == _BUDGET


def test_m5_constants_match_the_config_bounds() -> None:
    def bounds(name: str) -> dict[str, Any]:
        field = DmAgenticConfig.model_fields[name]
        return {type(m).__name__: getattr(m, "ge", getattr(m, "le", None)) for m in field.metadata}

    assert bounds("token_budget") == {"Ge": turn_cost.MIN_TURN_TOKEN_BUDGET}
    assert (
        DmAgenticConfig.model_fields["max_total_iterations"].default
        == turn_cost.DEFAULT_MAX_TOTAL_ITERATIONS
    )
    assert bounds("max_total_iterations").get("Le") == turn_cost.MAX_TOTAL_ITERATIONS_CEILING


def test_m5_trust_multiplier_is_neutral_for_a_new_or_unknown_agent() -> None:
    network = _network(2, 2)

    assert turn_cost.trust_budget_multiplier(network.get_record("counselor-ezri")) == 1.0
    unknown = network.get_record("nobody")
    assert unknown is None
    assert turn_cost.trust_budget_multiplier(unknown) == 1.0
    # The read created nothing.
    assert "nobody" not in network.raw_scores()


def test_m5_trust_multiplier_is_clamped_at_both_ends() -> None:
    low, high = [(1, 9), (1, 3)], [(19, 1), (40, 5)]
    # Premise: both clamps are engaged by these valid records, not idle.
    assert all(_unclamped(a, b) < 0.5 for a, b in low)
    assert all(_unclamped(a, b) > 2.0 for a, b in high)

    assert [turn_cost.trust_budget_multiplier(_record(a, b)) for a, b in low] == [0.5, 0.5]
    assert [turn_cost.trust_budget_multiplier(_record(a, b)) for a, b in high] == [2.0, 2.0]


def test_m5_higher_trust_gives_a_larger_multiplier() -> None:
    assert 0.5 < turn_cost.trust_budget_multiplier(_record(2, 3)) < 1.0
    assert 1.0 < turn_cost.trust_budget_multiplier(_record(13, 7)) < 2.0

    means = [p / 100 for p in range(1, 100)]
    values = [turn_cost.trust_budget_multiplier(_record(100 * p, 100 * (1 - p))) for p in means]
    assert values == sorted(values)
    assert (min(values), max(values)) == (0.5, 2.0)


_INVALID_PARAMETERS = [
    (True, 2.0),
    (float("nan"), 2.0),
    (float("inf"), 2.0),
    (0, 2.0),
    (-1, 2.0),
    ("2", 2.0),
    (None, 2.0),
    (2.0, 0),
]


@pytest.mark.parametrize(
    "make",
    [
        *[(lambda a=a, b=b: _record(a, b)) for a, b in _INVALID_PARAMETERS],
        MagicMock,
        object,
        lambda: None,
    ],
    ids=[
        "alpha-bool", "alpha-nan", "alpha-inf", "alpha-zero", "alpha-negative", "alpha-str",
        "alpha-none", "beta-zero", "magicmock", "object", "none",
    ],
)
def test_m5_an_invalid_record_is_neutral(make: Any) -> None:
    assert turn_cost.trust_budget_multiplier(make()) == 1.0


def test_m5_trust_constants_are_reused_not_restated() -> None:
    assert turn_cost.TRUST_DEFAULT is TRUST_DEFAULT
    assert turn_cost.TRUST_SENIOR is TRUST_SENIOR
    assert (turn_cost.TRUST_BUDGET_MULTIPLIER_MIN, turn_cost.TRUST_BUDGET_MULTIPLIER_MAX) == (0.5, 2.0)


def test_m5_arming_scales_the_budget_by_trust() -> None:
    assert _arm(_network(2, 2)).budget == 500_000
    assert _arm(_network(19, 1)).budget == 1_000_000
    assert _arm(_network(1, 9)).budget == 250_000
    assert 500_000 < _arm(_network(13, 7)).budget < 1_000_000
    assert _arm(_network(19, 1), agent_id="nobody").budget == 500_000
    assert _arm(None).budget == 500_000

    source = _RecordingTrustSource(_network(19, 1))
    assert _arm(source, agent_id="").budget == 500_000
    assert source.reads == []
    assert _arm(source).budget == 1_000_000
    assert source.reads == [("get_record", "counselor-ezri")]


def test_m5_unreadable_trust_keeps_the_configured_budget(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="probos.cognitive.turn_cost")
    source = _RaisingTrustSource()

    armed = _arm(source)

    assert (armed.budget, armed.trust_multiplier, source.calls) == (500_000, 1.0, 1)
    warnings = [
        r for r in caplog.records
        if r.name == "probos.cognitive.turn_cost" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "could not be read" in warnings[0].getMessage()


def test_m5_the_floor_holds_under_trust() -> None:
    armed = _arm(_network(1, 9), token_budget=1024)

    assert (armed.budget, armed.trust_multiplier) == (1024, 0.5)


def test_m5_neutral_is_the_configured_value_exactly() -> None:
    budget = 10**17 + 1
    # Premise: a float round trip would lose this value.
    assert int(budget * 1.0) != budget

    armed = _arm(_network(2, 2), token_budget=budget)

    assert (armed.budget, armed.configured_budget) == (budget, budget)


def test_m5_trust_moves_only_the_token_budget() -> None:
    sources = (None, _network(2, 2), _network(19, 1), _network(1, 9), _network(13, 7))
    kwargs = [_arm(source).loop_kwargs() for source in sources]

    assert {tuple(sorted(k)) for k in kwargs} == {("max_total_iterations", "token_budget")}
    assert {k["max_total_iterations"] for k in kwargs} == {100}
    # Premise: trust really moved the budget across these levels.
    assert len({k["token_budget"] for k in kwargs}) == 4


def test_m5_remainder_uses_the_trust_scaled_budget() -> None:
    armed = _arm(_network(19, 1))

    armed.record(SimpleNamespace(total_tokens=200_000, token_source="estimated"))

    assert armed.loop_kwargs()["token_budget"] == 800_000


class _SeamExecutors:
    """Scripted ``WorkItemAgenticExecutor``: consumes each outcome once and records
    the kwargs of EVERY ``run`` call (H-4)."""

    def __init__(self, monkeypatch: Any, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        seam = self

        class _Executor:
            def __init__(self, *, llm_client: Any) -> None:
                self.llm_client = llm_client

            async def run(self, **kwargs: Any) -> Any:
                seam.calls.append(dict(kwargs))
                return seam.outcomes.pop(0)

        monkeypatch.setattr(agentic_dispatch, "WorkItemAgenticExecutor", _Executor)


def _seam_outcome(
    stopped_reason: str = "complete",
    *,
    final_text: str = "Here is the table, Captain.",
    total_tokens: int = 1000,
    token_source: str = "estimated",
) -> Any:
    return agentic_dispatch.WorkItemAgenticOutcome(
        final_text=final_text,
        stopped_reason=stopped_reason,
        total_tokens=total_tokens,
        token_source=token_source,
        # H-3, the production shape (test_ad1257:109-129): a merge-closed double
        # raises inside _accumulate_pass_failures on pass two.
        tool_failures=ToolFailures(merge_open=True),
        tool_defect_evaluated=True,
    )


def _seam_runtime(
    *, approval_store: Any = None, request_store: Any = None, trust: Any = None, **cfg: Any,
) -> Any:
    runtime = SimpleNamespace(
        config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=True, **cfg)),
        fault_report_store=None,
        action_approval_store=approval_store,
        capability_request_store=request_store,
    )
    # H-17: "no trust" is an absent attribute, never a MagicMock.
    if trust is not None:
        runtime.trust_network = trust
    return runtime


def _seam_agent(runtime: Any) -> Any:
    agent = SimpleNamespace(
        _runtime=runtime,
        _llm_client=object(),
        id="counselor-ezri",
        department="counseling",
        rank="lieutenant",
    )
    agent._conversational_agentic_will_run = (
        lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
    )
    return agent


async def _seam_turn(agent: Any) -> Any:
    return await CognitiveAgent._maybe_run_conversational_agentic(
        agent,
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.",
        user_message="Research the fifteen packages and tabulate them.",
    )


async def _standing_rule(tmp_path: Any) -> ActionApprovalStore:
    """A live continue rule, so a second pass REALLY runs (H-10, test_ad1257:183-206)."""
    store = ActionApprovalStore(db_path=str(tmp_path / "aa.db"))
    await store.start()
    await store.issue_approval(
        "counselor-ezri",
        CONTINUE_TOOL_ID,
        CONTINUE_ACTION,
        scope_key=CONTINUE_SCOPE_KEY,
        ttl_seconds=3600,
    )
    return store


def _two_passes(monkeypatch: Any, *, second: Any) -> _SeamExecutors:
    return _SeamExecutors(
        monkeypatch,
        _seam_outcome("max_iterations", final_text="Rows 1-9 so far.", total_tokens=200_000),
        second,
    )


@pytest.mark.asyncio
async def test_m5_unarmed_turn_imports_nothing_and_passes_the_p1_kwargs(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "probos.cognitive.turn_cost", raising=False)
    seam = _SeamExecutors(monkeypatch, _seam_outcome())

    text = await _seam_turn(_seam_agent(_seam_runtime()))

    assert text == "Here is the table, Captain."
    assert "probos.cognitive.turn_cost" not in sys.modules
    assert len(seam.calls) == 1
    assert sorted(seam.calls[0]) == _P1_RUN_KWARGS


@pytest.mark.asyncio
async def test_m5_armed_turn_passes_budget_and_backstop(monkeypatch) -> None:
    seam = _SeamExecutors(monkeypatch, _seam_outcome())
    runtime = _seam_runtime(max_iterations=5, token_budget=_BUDGET, max_total_iterations=3)

    await _seam_turn(_seam_agent(runtime))

    assert len(seam.calls) == 1
    assert seam.calls[0]["token_budget"] == _BUDGET
    # Raised to the step limit: an armed turn never gets fewer steps than before.
    assert seam.calls[0]["max_total_iterations"] == 5
    assert sorted(seam.calls[0]) == sorted([*_P1_RUN_KWARGS, "max_total_iterations", "token_budget"])


@pytest.mark.asyncio
async def test_m5_budget_is_shared_across_continuation_passes(monkeypatch, tmp_path) -> None:
    approvals = await _standing_rule(tmp_path)
    try:
        seam = _two_passes(monkeypatch, second=_seam_outcome(final_text="All twenty rows."))
        runtime = _seam_runtime(
            approval_store=approvals,
            continue_or_ask_enabled=True,
            continue_or_ask_max_passes=2,
            token_budget=_BUDGET,
        )

        text = await _seam_turn(_seam_agent(runtime))
    finally:
        await approvals.stop()

    assert text == "All twenty rows."
    assert len(seam.calls) == 2
    assert [call["token_budget"] for call in seam.calls] == [500_000, 300_000]
    assert [call["max_total_iterations"] for call in seam.calls] == [100, 100]


@pytest.mark.asyncio
async def test_m5_higher_trust_agent_gets_more_budget_and_nothing_else(monkeypatch) -> None:
    seam = _SeamExecutors(monkeypatch, _seam_outcome(), _seam_outcome())
    runtime = _seam_runtime(token_budget=_BUDGET, trust=_network(2, 2))
    agent = _seam_agent(runtime)

    await _seam_turn(agent)
    runtime.trust_network = _network(19, 1)
    await _seam_turn(agent)

    assert len(seam.calls) == 2
    assert [call["token_budget"] for call in seam.calls] == [500_000, 1_000_000]
    first, second = ({k: v for k, v in call.items() if k != "token_budget"} for call in seam.calls)
    # Trust moved nothing else: not the step limits, the tier, the priority or any other key.
    assert first == second


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trust", "expected"),
    [
        (lambda: _network(1, 9), 250_000),
        (lambda: _network(40, 5), 1_000_000),
        (TrustNetwork, 500_000),
        (lambda: None, 500_000),
    ],
    ids=["floor", "ceiling", "network-without-a-record", "no-trust-network"],
)
async def test_m5_trust_clamps_at_the_dm_seam(monkeypatch, trust: Any, expected: int) -> None:
    seam = _SeamExecutors(monkeypatch, _seam_outcome())

    await _seam_turn(_seam_agent(_seam_runtime(token_budget=_BUDGET, trust=trust())))

    assert [call["token_budget"] for call in seam.calls] == [expected]


@pytest.mark.asyncio
async def test_m5_trust_is_read_once_per_turn_across_passes(monkeypatch, tmp_path) -> None:
    approvals = await _standing_rule(tmp_path)
    source = _RecordingTrustSource(_network(19, 1))
    try:
        seam = _two_passes(monkeypatch, second=_seam_outcome(final_text="All twenty rows."))
        runtime = _seam_runtime(
            approval_store=approvals,
            continue_or_ask_enabled=True,
            continue_or_ask_max_passes=2,
            token_budget=_BUDGET,
            trust=source,
        )

        await _seam_turn(_seam_agent(runtime))
    finally:
        await approvals.stop()

    assert len(seam.calls) == 2
    assert [call["token_budget"] for call in seam.calls] == [1_000_000, 800_000]
    assert source.reads == [("get_record", "counselor-ezri")]


@pytest.mark.asyncio
async def test_m5_unarmed_turn_reads_no_trust(monkeypatch) -> None:
    source = _RecordingTrustSource(_network(19, 1))
    seam = _SeamExecutors(monkeypatch, _seam_outcome())

    text = await _seam_turn(_seam_agent(_seam_runtime(trust=source)))

    # Premise: the turn really ran.
    assert (text, len(seam.calls)) == ("Here is the table, Captain.", 1)
    assert source.reads == []


# ── M6: a turn its cost budget stopped says so ──


async def _cost_turn(
    monkeypatch: Any,
    tmp_path: Any,
    *outcomes: Any,
    approvals: Any = None,
    trust: Any = None,
    **cfg: Any,
) -> tuple[Any, list[Any], _SeamExecutors]:
    """One inline DM turn with continue_or_ask on and a real request store, so a
    wrongly filed ask would be visible."""
    store = CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"))
    await store.start()
    try:
        seam = _SeamExecutors(monkeypatch, *outcomes)
        cfg.setdefault("continue_or_ask_enabled", True)
        runtime = _seam_runtime(approval_store=approvals, request_store=store, trust=trust, **cfg)
        text = await _seam_turn(_seam_agent(runtime))
        pending = await store.list_pending()
    finally:
        await store.stop()
    return text, pending, seam


@pytest.mark.asyncio
async def test_m6_inline_cost_stop_leads_with_the_statement(monkeypatch, tmp_path) -> None:
    text, pending, seam = await _cost_turn(
        monkeypatch,
        tmp_path,
        _seam_outcome("token_budget", final_text="Rows 1-9 of 20 so far.", total_tokens=512_340),
        token_budget=_BUDGET,
    )

    assert len(seam.calls) == 1
    assert text.startswith(turn_cost._COST_STOP_LEAD_WITH_WORK)
    assert "512,340" in text and "500,000" in text
    assert "(usage estimated, not measured)" in text
    assert text.endswith(_CUT_OFF_SEPARATOR + "Rows 1-9 of 20 so far.")
    assert pending == []


@pytest.mark.asyncio
async def test_m6_inline_cost_stop_with_no_text_is_not_silent(monkeypatch, tmp_path) -> None:
    text, pending, _ = await _cost_turn(
        monkeypatch,
        tmp_path,
        _seam_outcome("token_budget", final_text="", total_tokens=512_340),
        token_budget=_BUDGET,
    )

    # P-2 (a) inverted: this used to return None, and the turn fell back to a
    # single-pass reply that knew nothing about the work.
    assert text is not None
    assert text.startswith(turn_cost._COST_STOP_LEAD_NO_WORK)
    assert _CUT_OFF_SEPARATOR not in text
    assert pending == []


@pytest.mark.asyncio
async def test_m6_measured_usage_carries_no_estimate_marker(monkeypatch, tmp_path) -> None:
    text, _, _ = await _cost_turn(
        monkeypatch,
        tmp_path,
        _seam_outcome(
            "token_budget", final_text="Rows 1-9.", total_tokens=512_340, token_source="measured",
        ),
        token_budget=_BUDGET,
    )

    assert text.startswith(turn_cost._COST_STOP_LEAD_WITH_WORK)
    assert "(usage estimated, not measured)" not in text


@pytest.mark.asyncio
async def test_m6_cost_stop_after_a_continuation_pass(monkeypatch, tmp_path) -> None:
    approvals = await _standing_rule(tmp_path)
    try:
        text, pending, seam = await _cost_turn(
            monkeypatch,
            tmp_path,
            _seam_outcome("max_iterations", final_text="first", total_tokens=200_000),
            _seam_outcome("token_budget", final_text="second", total_tokens=310_000),
            approvals=approvals,
            continue_or_ask_max_passes=2,
            token_budget=_BUDGET,
        )
    finally:
        await approvals.stop()

    assert len(seam.calls) == 2
    # H-11: read from the LAST pass, after continue_or_ask has returned.
    assert text.startswith(turn_cost._COST_STOP_LEAD_WITH_WORK)
    assert "It used about 510,000 tokens against a budget of 500,000" in text
    assert text.endswith(_CUT_OFF_SEPARATOR + "second")
    assert pending == []


@pytest.mark.asyncio
async def test_m6_step_limit_stop_is_unchanged_when_armed(monkeypatch, tmp_path) -> None:
    text, pending, seam = await _cost_turn(
        monkeypatch,
        tmp_path,
        _seam_outcome("max_iterations", final_text="Rows 1-9 so far.", total_tokens=200_000),
        token_budget=_BUDGET,
    )

    assert len(seam.calls) == 1
    assert text.startswith(_CUT_OFF_LEAD_WITH_WORK)
    assert [request.kind for request in pending] == ["continue"]
    assert "cost budget" not in text


@pytest.mark.asyncio
async def test_m6_unarmed_token_budget_outcome_is_unchanged(monkeypatch, tmp_path) -> None:
    text, pending, _ = await _cost_turn(
        monkeypatch, tmp_path, _seam_outcome("token_budget", final_text="Rows 1-9 of 20 so far."),
    )

    # P-2 (b), kept: without dm_agentic.token_budget this is not AD-1208's stop.
    assert text == "Rows 1-9 of 20 so far."
    assert pending == []


class _FakeWorkItemStore:
    """Records create/transition calls on the REAL ``WorkItem`` (test_ad1165:61)."""

    def __init__(self) -> None:
        self.created: list[WorkItem] = []
        self.transitions: list[tuple[str, str, str]] = []

    async def create_work_item(self, **kwargs: Any) -> WorkItem:
        item = WorkItem(status="open", **kwargs)
        self.created.append(item)
        return item

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system",
    ) -> None:
        self.transitions.append((work_item_id, new_status, source))


class _FakeThreadStore:
    """Records every thread post (test_ad1165:89)."""

    def __init__(self) -> None:
        self.appended: list[dict[str, Any]] = []

    def append_message(self, thread_id: str, *, author_id: str, role: str, body: str, metadata: Any = None) -> Any:
        return self.append_message_once(
            thread_id, message_id=f"m{len(self.appended)}", author_id=author_id, role=role,
            body=body, created_at=0.0, metadata=metadata,
        )

    def append_message_once(
        self, thread_id: str, *, message_id: str, author_id: str, role: str, body: str,
        created_at: float, metadata: Any = None,
    ) -> Any:
        self.appended.append({"thread_id": thread_id, "body": body, "metadata": metadata})
        return SimpleNamespace(id=message_id, thread_id=thread_id, body=body)


async def _drain(hold: set) -> None:
    """Await every task the agent holds, then let callbacks settle (H-13)."""
    while hold:
        await asyncio.gather(*tuple(hold), return_exceptions=True)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_m6_promoted_cost_stop_reports_the_statement(monkeypatch) -> None:
    release = asyncio.Event()
    calls: list[dict[str, Any]] = []
    outcome = _seam_outcome("token_budget", final_text="", total_tokens=512_340)

    class _SlowExecutor:
        def __init__(self, *, llm_client: Any) -> None:
            self.llm_client = llm_client

        async def run(self, **kwargs: Any) -> Any:
            calls.append(dict(kwargs))
            await release.wait()
            return outcome

    monkeypatch.setattr(agentic_dispatch, "WorkItemAgenticExecutor", _SlowExecutor)
    work_items, threads = _FakeWorkItemStore(), _FakeThreadStore()
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            dm_agentic=DmAgenticConfig(
                enabled=True, promote_to_task_after_seconds=0.01, token_budget=_BUDGET,
            ),
        ),
        work_item_store=work_items,
        chat_thread_store=threads,
    )
    agent = _seam_agent(runtime)
    agent._promoted_turn_tasks = set()

    ack = await CognitiveAgent._maybe_run_conversational_agentic(
        agent,
        {
            "intent": "direct_message",
            "thread_id": "threadone",
            "params": {"captain_message": "Tabulate the fifteen packages."},
        },
        system_prompt="You are Ezri.",
        user_message="a long assembled prompt",
    )
    # Premise: the turn promoted while the run was still going.
    assert len(work_items.created) == 1
    item = work_items.created[0]
    assert ack == _ACK_TEMPLATE.format(work_item_id=item.id)

    release.set()
    await _drain(agent._promoted_turn_tasks)

    assert [call["token_budget"] for call in calls] == [_BUDGET]
    [post] = threads.appended
    assert post["body"].startswith(turn_cost._COST_STOP_LEAD_NO_WORK)
    assert post["body"] != _REPORT_EMPTY
    # R-1, pinned as today's behaviour rather than a goal: token_budget is an
    # incomplete stop, so the row gets no terminal transition. Its one transition is
    # promotion's own move to in_progress (the test_ad1165:548 shape).
    assert work_items.transitions == [(item.id, "in_progress", "counselor-ezri")]


def _rendered_cost_stops() -> dict[str, str]:
    def armed(sources: list[str], *, network: Any = None, budget: int = _BUDGET) -> Any:
        ledger = _arm(network, token_budget=budget)
        for source in sources:
            ledger.record(SimpleNamespace(total_tokens=260_000, token_source=source))
        return ledger

    ledgers = {
        "estimated": armed(["estimated"]),
        "measured": armed(["measured"]),
        "mixed": armed(["measured", "estimated"]),
        "unknown": armed([]),
        "trust-raised": armed(["estimated"], network=_network(19, 1)),
        "trust-lowered": armed(["estimated"], network=_network(1, 9)),
        "floor-held": armed(["estimated"], network=_network(1, 9), budget=1024),
    }
    variants: dict[str, str] = {}
    for label, ledger in ledgers.items():
        variants[f"{label}/with-work"] = ledger.render_stop("Rows 1-9 of 20 so far.")
        variants[f"{label}/no-work"] = ledger.render_stop("")
        variants[f"{label}/blank-work"] = ledger.render_stop("  \n ")
    return variants


def test_m6_every_cost_stop_variant_is_gap_clean_and_distinct() -> None:
    # Premise: the real detector does flag a gap phrase.
    assert is_capability_gap("I cannot do that") is True
    variants = _rendered_cost_stops()
    assert len(variants) == 21

    for label, text in variants.items():
        work = label.endswith("/with-work")
        lead = turn_cost._COST_STOP_LEAD_WITH_WORK if work else turn_cost._COST_STOP_LEAD_NO_WORK
        assert is_capability_gap(text) is False, (label, text)
        assert "step limit" not in text, label
        assert "cost budget" in text, label
        assert text.startswith(lead), label
        assert (_CUT_OFF_SEPARATOR in text) is work, label
        assert ("(usage estimated, not measured)" in text) is not label.startswith("measured/"), label
        assert ("adjusted by my trust record" in text) is label.startswith("trust-"), label


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("network", "budget", "expected"),
    [
        (
            lambda: _network(19, 1),
            _BUDGET,
            "against a budget of 1,000,000 (the configured 500,000, adjusted by my trust record).",
        ),
        (
            lambda: _network(1, 9),
            _BUDGET,
            "against a budget of 250,000 (the configured 500,000, adjusted by my trust record).",
        ),
        (lambda: _network(2, 2), _BUDGET, "against a budget of 500,000."),
        (lambda: _network(1, 9), 1024, "against a budget of 1,024."),
    ],
    ids=["trust-raised", "trust-lowered", "neutral", "floor-held"],
)
async def test_m6_a_trust_moved_budget_names_the_configured_value(
    monkeypatch, tmp_path, network: Any, budget: int, expected: str,
) -> None:
    text, _, _ = await _cost_turn(
        monkeypatch,
        tmp_path,
        _seam_outcome(
            "token_budget", final_text="Rows 1-9.", total_tokens=1_012_000, token_source="measured",
        ),
        trust=network(),
        token_budget=budget,
    )

    assert text.startswith(turn_cost._COST_STOP_LEAD_WITH_WORK)
    assert expected in text
    assert ("adjusted by my trust record" in text) is ("adjusted" in expected)


# ── M7: tier 3 still gated under the armed loop (acceptance 3) ──

_TIER_3_URL = "https://bank.example/transfer"
_M7_ARMED = {"max_iterations": 1, "token_budget": 10**6, "max_total_iterations": 10}
_M7_UNARMED = {"max_iterations": 1}


class _CountingBrowserTool(BrowserTool):
    """A REAL ``BrowserTool`` that records every entry into ``invoke`` (test_ad1154:100).

    The pin is a CALL COUNT: a parked click must never enter the tool.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.invocations: list[dict[str, Any]] = []

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.invocations.append(dict(params))
        return await super().invoke(params, context)


def _counting_browser() -> _CountingBrowserTool:
    tool = _CountingBrowserTool(
        config=BrowserToolConfig(enabled=True), audit_log=AuditLog(), emit_event=None,
    )
    tool._session_factory = _make_session_factory(
        page=_FakePage(list_elements=[{"role": "button", "text": "Pay now"}])
    )
    return tool


async def _gated_executor(
    tmp_path: Any, tool: Any, *others: Any,
) -> tuple[agentic_dispatch.DispatchToolExecutor, CapabilityRequestStore]:
    """An executor with the AD-1154 inbox armed as ``WorkItemAgenticExecutor.run`` arms it."""
    registry = ToolRegistry()
    registry.register(
        tool,
        domain="*",
        tags=["browser", "computer_use"],
        provider="ship_computer",
        enabled=True,
        default_permissions={
            "ensign": "none",
            "lieutenant": "read",
            "commander": "write",
            "senior_officer": "full",
        },
        concurrency="concurrent",
    )
    for other in others:
        # Readable at the loop's rank: the rank gate maps an unlisted rank to "none".
        registry.register(
            other,
            provider="ad1208-test",
            default_permissions={rank: "read" for rank in ("ensign", "lieutenant", "commander")},
        )
    executor = agentic_dispatch.DispatchToolExecutor(registry=registry)
    store = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"))
    await store.start()
    executor.arm_approval_inbox(
        request_store=store, approval_store=None, config=ApprovalInboxConfig(enabled=True),
    )
    return executor, store


async def _open_tier_3_session(tool: _CountingBrowserTool) -> str:
    """Navigate once, so a real session exists whose ``last_url`` is a payment page."""
    nav = await tool.invoke({"action": "goto", "url": _TIER_3_URL}, {"agent_id": "agent-a"})
    tool.invocations.clear()
    return nav.metadata["session_id"]


async def _run_gated_loop(executor: Any, responses: list[_LoopResponse], **loop_kwargs: Any) -> Any:
    loop = AgenticLoop(llm_client=_ScriptedLoopLLM(responses), tool_executor=executor, **loop_kwargs)
    # The loop hands department and rank to the executor from this context.
    return await loop.run(
        system_prompt="You are the engineer.",
        user_message="Finish the payment.",
        tools=[],
        context={"agent_id": "agent-a", "department": "engineering", "rank": "commander"},
    )


def _parked(pending: list[Any]) -> list[tuple[Any, ...]]:
    return [
        (r.kind, r.payload["tool_id"], r.payload["action"], r.payload["scope_key"], r.payload["params"])
        for r in pending
    ]


_PARKED_CLICK = ("action", "browser", "click", "bank.example")


@pytest.mark.asyncio
@pytest.mark.parametrize("loop_kwargs", [_M7_ARMED, _M7_UNARMED], ids=["armed", "unarmed"])
async def test_m7_armed_loop_still_parks_a_tier3_browser_click(tmp_path, loop_kwargs) -> None:
    tool = _counting_browser()
    executor, store = await _gated_executor(tmp_path, tool)
    try:
        sid = await _open_tier_3_session(tool)
        click = _use("browser", {"action": "click", "index": 0, "session_id": sid})

        result = await _run_gated_loop(executor, [_step(click), _answer()], **loop_kwargs)
        pending = await store.list_pending()
    finally:
        await store.stop()
        await tool.stop()

    # The tool was never entered, armed or not.
    assert tool.invocations == []
    assert _parked(pending) == [(*_PARKED_CLICK, {"index": 0, "session_id": sid})]
    # The browser step counted: both configurations stop at the same place.
    assert (result.stopped_reason, result.iterations) == ("max_iterations", 1)


@pytest.mark.asyncio
async def test_m7_armed_loop_routes_an_mcp_consensus_tool_through_the_quorum(tmp_path) -> None:
    quorum_calls: list[tuple[Any, ...]] = []
    bridge_calls: list[tuple[Any, ...]] = []

    async def _consensus_invoke(url: str, tool_name: str, args: dict) -> dict:
        quorum_calls.append((url, tool_name, args))
        return {"committed": False, "outcome": "rejected"}

    class _RecordingBridge:
        async def invoke(self, *args: Any, **kwargs: Any) -> Any:
            bridge_calls.append((args, kwargs))
            raise AssertionError("CONSENSUS must not reach the bridge directly")

    mcp_tool = agentic_dispatch._McpTool(
        bridge=_RecordingBridge(),
        server_url="http://srv",
        server_name="srv",
        server_id="srv-1",
        tool_name="danger",
        name="Danger",
        description="a consensus-tier MCP tool",
        input_schema={"type": "object"},
        server_default_risk=McpToolRisk.CONSENSUS.value,
        risk_store=None,
        consensus_invoke=_consensus_invoke,
        authorize=lambda _agent_id: True,
    )
    registry = ToolRegistry()
    registry.register(mcp_tool, domain="*", provider="mcp", enabled=True)
    executor = agentic_dispatch.DispatchToolExecutor(registry=registry)
    store = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"))
    await store.start()
    executor.arm_approval_inbox(
        request_store=store, approval_store=None, config=ApprovalInboxConfig(enabled=True),
    )
    try:
        result = await _run_gated_loop(
            executor, [_step(_use(mcp_tool.tool_id, {"x": 1})), _answer()], **_M7_ARMED,
        )
        pending = await store.list_pending()
    finally:
        await store.stop()

    assert mcp_tool.effective_risk() is McpToolRisk.CONSENSUS
    assert quorum_calls == [("http://srv", "danger", {"x": 1})]
    assert bridge_calls == []
    assert pending == []
    # The MCP step counted toward max_iterations.
    assert (result.stopped_reason, result.iterations) == ("max_iterations", 1)


@pytest.mark.asyncio
async def test_m7_a_read_only_call_beside_a_tier3_call_does_not_exempt_the_step(tmp_path) -> None:
    tool, fetch = _counting_browser(), _Fetch()
    executor, store = await _gated_executor(tmp_path, tool, fetch)
    try:
        sid = await _open_tier_3_session(tool)
        both = _step(
            _fetch_use(1), _use("browser", {"action": "click", "index": 0, "session_id": sid}),
        )

        result = await _run_gated_loop(executor, [both, _answer()], **_M7_ARMED)
        pending = await store.list_pending()
    finally:
        await store.stop()
        await tool.stop()

    # Premise: the read-only call really ran beside the click.
    assert fetch.calls == ["https://example.org/1"]
    assert tool.invocations == []
    assert _parked(pending) == [(*_PARKED_CLICK, {"index": 0, "session_id": sid})]
    assert (result.stopped_reason, result.iterations) == ("max_iterations", 1)


@pytest.mark.asyncio
async def test_m7_an_uncounted_tier1_browser_step_does_not_let_a_tier3_click_through(tmp_path) -> None:
    tool = _counting_browser()
    executor, store = await _gated_executor(tmp_path, tool)
    try:
        sid = await _open_tier_3_session(tool)
        state = _use("browser", {"action": "state", "session_id": sid})
        click = _use("browser", {"action": "click", "index": 0, "session_id": sid})

        result = await _run_gated_loop(
            executor, [_step(state), _step(click), _answer()], **_M7_ARMED,
        )
        pending = await store.list_pending()
    finally:
        await store.stop()
        await tool.stop()

    # The observation ran; the click never entered the tool.
    assert tool.invocations == [{"action": "state", "session_id": sid}]
    assert _parked(pending) == [(*_PARKED_CLICK, {"index": 0, "session_id": sid})]
    # The state step was not counted and the click step was: the stop is at iteration 2.
    assert (result.stopped_reason, result.iterations) == ("max_iterations", 2)


# ── Review F-1: an armed answer that reaches the budget is the answer, not a cost stop ──

# Every call in these runs is MEASURED at this cost, so the crossing is exact: the
# fifteen fetch calls spend 15 x _PER_CALL and the answer's own call reaches the budget.
_PER_CALL = 1_000
_F1_BUDGET = (_N_FETCH + 1) * _PER_CALL


class _MeasuredFetchingLLM(_FetchingLLM):
    """``_FetchingLLM`` on a provider that reports usage; it can hold the answer back."""

    def __init__(self, n: int, *, hold_answer: asyncio.Event | None = None) -> None:
        super().__init__(n)
        self._hold_answer = hold_answer

    async def complete(self, req: Any, **kwargs: Any) -> _UsageZeroResponse:
        if self._hold_answer is not None and self.calls == self._n:
            await self._hold_answer.wait()
        response = await super().complete(req, **kwargs)
        response.tokens_used = _PER_CALL
        return response


async def _answer_at_the_budget_turn(
    monkeypatch: Any, tmp_path: Any, *, promoted: bool,
) -> dict[str, Any]:
    """The review's reproduction through the real DM turn, executor and loop, armed:
    fifteen fetches, then a text answer whose own call brings the spend to the budget."""
    cfg = DmAgenticConfig(
        enabled=True,
        max_iterations=5,
        continue_or_ask_enabled=True,
        token_budget=_F1_BUDGET,
        max_total_iterations=100,
        promote_to_task_after_seconds=0.01 if promoted else 0.0,
    )
    registry = ToolRegistry()
    fetch = _Fetch()
    registry.register(fetch, provider="ad1208-test", default_permissions={"ensign": "read"})
    store = CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"))
    await store.start()
    outcomes: list[tuple[str, int, int, str]] = []
    real_run = agentic_dispatch.WorkItemAgenticExecutor.run

    async def _recording_run(self: Any, **kwargs: Any) -> Any:
        outcome = await real_run(self, **kwargs)
        outcomes.append(
            (outcome.stopped_reason, outcome.iterations, outcome.total_tokens, outcome.token_source)
        )
        return outcome

    monkeypatch.setattr(agentic_dispatch.WorkItemAgenticExecutor, "run", _recording_run)
    hold = asyncio.Event() if promoted else None
    work_items, threads = _FakeWorkItemStore(), _FakeThreadStore()
    runtime = _fetch_runtime(registry, store, cfg)
    observation: dict[str, Any] = {"intent": "direct_message", "params": {}}
    if promoted:
        runtime.work_item_store = work_items
        runtime.chat_thread_store = threads
        observation = {
            "intent": "direct_message",
            "thread_id": "threadone",
            "params": {"captain_message": "Tabulate the fifteen packages."},
        }
    llm = _MeasuredFetchingLLM(_N_FETCH, hold_answer=hold)
    agent = SimpleNamespace(
        _runtime=runtime,
        _llm_client=llm,
        id="counselor-ezri",
        department="counseling",
        rank="lieutenant",
        _promoted_turn_tasks=set(),
    )
    agent._conversational_agentic_will_run = (
        lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
    )
    try:
        text = await CognitiveAgent._maybe_run_conversational_agentic(
            agent,
            observation,
            system_prompt="You are Ezri.",
            user_message="Fetch the fifteen PyPI project pages one at a time and tabulate them.",
        )
        created = list(work_items.created)
        if hold is not None:
            hold.set()
            await _drain(agent._promoted_turn_tasks)
        pending = await store.list_pending()
    finally:
        await store.stop()
    return {
        "text": text,
        "fetches": list(fetch.calls),
        "llm_calls": llm.calls,
        "outcomes": outcomes,
        "pending": pending,
        "created": created,
        "posts": list(threads.appended),
        "transitions": list(work_items.transitions),
    }


@pytest.mark.asyncio
async def test_f1_armed_answer_at_the_budget_is_the_reply(monkeypatch, tmp_path) -> None:
    got = await _answer_at_the_budget_turn(monkeypatch, tmp_path, promoted=False)

    # Premise: every fetch ran under the budget, and the answer's own call reached it.
    assert got["fetches"] == [f"https://pypi.org/project/p{i}/" for i in range(1, _N_FETCH + 1)]
    assert got["llm_calls"] == _N_FETCH + 1
    [(reason, iterations, total_tokens, source)] = got["outcomes"]
    assert (iterations, total_tokens, source) == (_N_FETCH + 1, _F1_BUDGET, "measured")
    assert got["text"] == _FINAL_TEXT
    assert reason == "complete"
    assert got["pending"] == []


@pytest.mark.asyncio
async def test_f1_armed_answer_at_the_budget_closes_the_promoted_item_done(
    monkeypatch, tmp_path,
) -> None:
    got = await _answer_at_the_budget_turn(monkeypatch, tmp_path, promoted=True)

    # Premise: the turn promoted while the answer was held back, then the answer's
    # own call reached the budget.
    [item] = got["created"]
    assert got["text"] == _ACK_TEMPLATE.format(work_item_id=item.id)
    assert len(got["fetches"]) == _N_FETCH
    [(reason, iterations, total_tokens, source)] = got["outcomes"]
    assert (iterations, total_tokens, source) == (_N_FETCH + 1, _F1_BUDGET, "measured")
    [post] = got["posts"]
    assert post["body"] == _FINAL_TEXT
    assert got["transitions"] == [
        (item.id, "in_progress", "counselor-ezri"),
        (item.id, "done", "counselor-ezri"),
    ]
    assert reason == "complete"
    assert got["pending"] == []


def _f1_run(last: _LoopResponse) -> list[_LoopResponse]:
    # Three measured fetches under a 3,500 budget; ``last`` is the call that reaches it.
    return [*(_step(_fetch_use(i), tokens=_PER_CALL) for i in range(1, 4)), last]


def _two_block_answer() -> _LoopResponse:
    return _LoopResponse(
        [TextBlock(text="Here is the table."), TextBlock(text="Sources: pypi.org.")],
        content="Here is the table.",
        tokens=_PER_CALL,
    )


@pytest.mark.asyncio
async def test_f1_armed_answer_past_the_budget_takes_the_completion_path() -> None:
    result, executor = await _run_loop(
        _f1_run(_two_block_answer()), max_iterations=5, token_budget=3500, max_total_iterations=20,
    )

    assert executor.calls == ["http_fetch"] * 3
    assert (result.iterations, result.total_tokens) == (4, 4000)
    # The completion path's text (every text block), not the budget exit's first block.
    assert (result.stopped_reason, result.final_text) == (
        "complete", "Here is the table.\nSources: pypi.org.",
    )


@pytest.mark.asyncio
async def test_f1_unarmed_answer_past_the_budget_still_stops_at_the_budget() -> None:
    """Control: without max_total_iterations every other budgeted caller keeps the base order."""
    result, executor = await _run_loop(
        _f1_run(_two_block_answer()), max_iterations=5, token_budget=3500,
    )

    assert executor.calls == ["http_fetch"] * 3
    assert (result.iterations, result.total_tokens) == (4, 4000)
    # The budget exit reports the first text block only.
    assert (result.stopped_reason, result.final_text) == ("token_budget", "Here is the table.")


@pytest.mark.asyncio
async def test_f1_armed_tool_call_past_the_budget_still_stops_at_the_budget() -> None:
    pending_call = _step(_fetch_use(4), text="One more page.", tokens=_PER_CALL)
    result, executor = await _run_loop(
        [*_f1_run(pending_call), _answer("never reached")],
        max_iterations=5,
        token_budget=3500,
        max_total_iterations=20,
    )

    # The fourth fetch was pending when the budget was reached, so it never ran.
    assert executor.calls == ["http_fetch"] * 3
    assert (result.stopped_reason, result.iterations, result.total_tokens) == (
        "token_budget", 4, 4000,
    )
    assert result.final_text == "One more page."


class _EmptyAnswerLLM(_MeasuredFetchingLLM):
    """Measured fetches, then ``answer`` as the final response: empty, or whitespace only. Any
    later call is the single-pass fallback."""

    def __init__(self, n: int, *, answer: str = "") -> None:
        super().__init__(n)
        self._answer = answer

    async def complete(self, req: Any, **kwargs: Any) -> Any:
        if self.calls > self._n:
            self.calls += 1
            return SimpleNamespace(
                content="SINGLE-PASS-REPLY",
                content_blocks=[],
                tokens_used=10,
                prompt_tokens=5,
                completion_tokens=5,
                tier="standard",
                model="scripted",
                error=None,
            )
        response = await super().complete(req, **kwargs)
        if self.calls > self._n:
            # What the real client builds: a text block only for non-empty content, unstripped.
            response.content_blocks = [TextBlock(text=self._answer)] if self._answer else []
            response.content = self._answer
        return response


def _real_dm_agent(runtime: Any, llm: Any) -> CognitiveAgent:
    # A real agent, so ``_decide_via_llm`` runs its own single-pass fallback (test_ad700c pattern).
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.instructions = "You are Ezri."
    agent.agent_type = "test_agent"
    agent.id = "counselor-ezri"
    agent.callsign = "Ezri"
    agent.confidence = 0.8
    agent._llm_client = llm
    agent._runtime = runtime
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    agent.tool_context = None
    agent._sub_task_executor = None
    agent._pending_sub_task_chain = None
    agent._working_memory = AgentWorkingMemory()
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["", " \n\t "], ids=["empty", "whitespace-only"])
async def test_f1_armed_empty_answer_at_the_budget_keeps_the_cost_stop(
    monkeypatch, tmp_path, answer,
) -> None:
    """Armed, a final response with no answer text (none, or whitespace only) whose own call
    reaches the budget keeps the cost stop: the no-work statement, and no further model call.
    Driven through ``_decide_via_llm``, whose single-pass fallback a completed turn with no
    answer text (``None``) would reach."""
    cfg = DmAgenticConfig(
        enabled=True,
        max_iterations=5,
        continue_or_ask_enabled=True,
        token_budget=_F1_BUDGET,
        max_total_iterations=100,
    )
    registry = ToolRegistry()
    fetch = _Fetch()
    registry.register(fetch, provider="ad1208-test", default_permissions={"ensign": "read"})
    store = CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"))
    await store.start()
    outcomes: list[tuple[str, int, int, str, str]] = []
    real_run = agentic_dispatch.WorkItemAgenticExecutor.run

    async def _recording_run(self: Any, **kwargs: Any) -> Any:
        outcome = await real_run(self, **kwargs)
        outcomes.append(
            (
                outcome.stopped_reason,
                outcome.iterations,
                outcome.total_tokens,
                outcome.token_source,
                outcome.final_text,
            )
        )
        return outcome

    monkeypatch.setattr(agentic_dispatch.WorkItemAgenticExecutor, "run", _recording_run)
    llm = _EmptyAnswerLLM(_N_FETCH, answer=answer)
    agent = _real_dm_agent(_fetch_runtime(registry, store, cfg), llm)
    try:
        decision = await agent._decide_via_llm(
            {"intent": "direct_message", "params": {"text": "Tabulate the fifteen packages."}},
        )
        pending = await store.list_pending()
    finally:
        await store.stop()

    # Premise: every fetch ran under the budget, the answer's own call reached it, and that
    # answer, unstripped, is the loop's final text.
    assert len(fetch.calls) == _N_FETCH
    [(reason, iterations, total_tokens, source, final_text)] = outcomes
    assert (iterations, total_tokens, source, final_text) == (
        _N_FETCH + 1, _F1_BUDGET, "measured", answer,
    )
    statement = (
        turn_cost._COST_STOP_LEAD_NO_WORK
        + f" It used about {_F1_BUDGET:,} tokens against a budget of {_F1_BUDGET:,}."
        + turn_cost._COST_STOP_TAIL
    )
    assert (reason, decision["llm_output"], decision["tier_used"], llm.calls) == (
        "token_budget", statement, "agentic", _N_FETCH + 1,
    )
    assert pending == []
