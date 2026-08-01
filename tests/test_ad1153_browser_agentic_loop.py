"""AD-1153: the browser offered to the agentic loop, read-only.

No live network and no real Chromium — the ``_FakePage`` / ``_FakeSession``
stubs are reused from ``tests/test_ad706_browser_tool.py`` so every assertion
here runs offline. Real ``ToolRegistry`` / ``ToolPermissionStore`` throughout
(BF-287): the rank gate is exactly what a mock would paper over.

The load-bearing property this suite pins is DD-1's: the six offered actions
provably cannot reach the tier-3 confirmation gate, so the fact that the gate
returns a success-shaped no-op for an unattended caller never bites on this
path. If a future change admits ``click`` / ``type`` here, the tier proof and
the token-mint assertion both go red.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import (
    _BROWSER_DISPOSITION,
    _BROWSER_EGRESS_WARNING,
    _BROWSER_ELEMENTS_ELISION,
    _BROWSER_LOOP_ACTIONS,
    _BROWSER_MAX_ELEMENTS,
    _BROWSER_READ_ONLY_REFUSAL,
    _BROWSER_TEXT_ELISION,
    _BROWSER_TEXT_MAX_CHARS,
    _GATED_TOOL_IDS,
    DispatchToolExecutor,
    WorkItemAgenticExecutor,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness.tool_call import ToolCallResult
from probos.config import AgenticToolsConfig, BrowserToolConfig
from probos.security.audit import AuditLog
from probos.tools.browser.actions import classify_action
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse

from tests.test_ad706_browser_tool import _FakePage, _make_session_factory

_ALL_SIX = ("goto", "state", "extract_text", "back", "forward", "wait")
# The complement of ``_BROWSER_LOOP_ACTIONS`` within ``BrowserTool``'s own
# action enum. Named without a count (AD-1160 added ``key_type``, and the
# previous ``_EXCLUDED_FIVE`` would have had to be renamed with every such
# addition — the same stale-count drift BF-690 filed against the tool
# description).
#
# BF-706 added ``key_combo``, ``drag``, ``mouse_move`` and ``mouse_button`` to
# the tool's surface. They belong HERE, not in the loop set: that set is
# deliberately read-only, and all four act on the page exactly as ``click`` and
# ``key_type`` do. An agent reaches them only by holding ``browser`` through a
# Captain grant, which leaves ``restricted_browser_actions`` unarmed.
#
# This test is why the list is maintained by hand — it fails loudly the moment
# the tool's enum and this complement disagree, which is what caught BF-706's
# first draft before it shipped a half-wired fix.
_EXCLUDED_ACTIONS = (
    "click", "type", "key_type", "key_combo", "drag", "mouse_move",
    "mouse_button", "scroll", "screenshot", "verify",
)


# -- Harness --------------------------------------------------------------


def _make_browser_tool(
    *,
    config: BrowserToolConfig | None = None,
    page: _FakePage | None = None,
) -> tuple[BrowserTool, _FakePage]:
    """A real ``BrowserTool`` whose sessions never touch Playwright."""
    cfg = config or BrowserToolConfig(enabled=True)
    fake_page = page or _FakePage(title="Fixture", url="")
    tool = BrowserTool(config=cfg, audit_log=AuditLog(), emit_event=None)
    tool._session_factory = _make_session_factory(page=fake_page)
    return tool, fake_page


def _registry_with_browser(
    tool: BrowserTool,
    *,
    permission_store: Any = None,
) -> ToolRegistry:
    """Register ``browser`` exactly as ``_wire_browser_tool`` does (finalize.py)."""
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
    if permission_store is not None:
        registry.set_permission_store(permission_store)
    return registry


async def _armed_executor(
    *,
    config: BrowserToolConfig | None = None,
    page: _FakePage | None = None,
    arm: bool = True,
) -> tuple[DispatchToolExecutor, BrowserTool, _FakePage]:
    tool, fake_page = _make_browser_tool(config=config, page=page)
    executor = DispatchToolExecutor(registry=_registry_with_browser(tool))
    if arm:
        executor.restrict_browser_actions(_BROWSER_LOOP_ACTIONS)
    return executor, tool, fake_page


async def _invoke(
    executor: DispatchToolExecutor,
    params: dict[str, Any],
    *,
    rank: str = "lieutenant",
) -> ToolResult:
    return await executor.invoke(
        "agent-a",
        "browser",
        params,
        agent_department="engineering",
        agent_rank=rank,
    )


class _ToolIdCapturingLLM:
    """AD-1140's capture shape — records the tool names handed to the loop."""

    def __init__(self) -> None:
        self.tool_names: list[list[str]] = []

    async def complete(self, request: Any, **_kw: object) -> LLMResponse:
        from probos.cognitive.swe_harness.tool_call import TextBlock

        self.tool_names.append([
            (t.get("function") or {}).get("name")
            for t in (getattr(request, "tools", None) or [])
        ])
        return LLMResponse(
            content="done", tokens_used=1, content_blocks=[TextBlock(text="done")],
        )


def _agentic_runtime(
    registry: ToolRegistry | None,
    store: ToolPermissionStore,
    *,
    browser_enabled: bool = True,
    browser_cfg: BrowserToolConfig | None = None,
) -> Any:
    return SimpleNamespace(
        tool_registry=registry, tool_permission_store=store, intent_bus=None,
        intent_grant_store=None, mcp_workbench=None, cognitive_skill_catalog=None,
        attachment_store=None, emit_event=None, registry=None, ontology=None,
        trust_network=None,
        config=SimpleNamespace(
            execution=SimpleNamespace(enabled=False),
            mcp=SimpleNamespace(agent_tools_enabled=False),
            browser_tool=browser_cfg or BrowserToolConfig(enabled=True),
            agentic_tools=SimpleNamespace(
                tool_search_enabled=False, delegation_enabled=False,
                browser_enabled=browser_enabled,
            ),
        ),
    )


async def _offered(
    *,
    browser_enabled: bool,
    rank: str = "lieutenant",
    register: bool = True,
    grant: ToolPermission | None = None,
    browser_cfg: BrowserToolConfig | None = None,
) -> list[str]:
    """Run the real dispatch and return the tool ids handed to the loop."""
    store = ToolPermissionStore(db_path=":memory:")
    await store.start()
    tool: BrowserTool | None = None
    try:
        if grant is not None:
            await store.issue_grant(
                "agent-a", "browser", grant,
                issued_by="captain", reason="captain escape hatch",
            )
        if register:
            tool, _ = _make_browser_tool(config=browser_cfg)
            registry = _registry_with_browser(tool, permission_store=store)
        else:
            registry = ToolRegistry()
            registry.set_permission_store(store)
        llm = _ToolIdCapturingLLM()
        await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="agent-a", instructions="", task_text="go",
            runtime=_agentic_runtime(
                registry, store,
                browser_enabled=browser_enabled, browser_cfg=browser_cfg,
            ),
            department="engineering", rank=rank,
        )
        return llm.tool_names[0]
    finally:
        if tool is not None:
            await tool.stop()
        await store.stop()


# -- DD-1: the tier proof -------------------------------------------------


def test_every_offered_action_classifies_at_or_below_tier_two() -> None:
    """The whole safety argument for v1. Run against the REAL classifier."""
    session = BrowserSession(
        config=BrowserToolConfig(enabled=True), session_id="s1", agent_id="a1",
    )
    tiers = {
        action: classify_action(session, action, {"url": "https://example.com"})
        for action in _ALL_SIX
    }
    assert max(tiers.values()) <= 2, tiers


def test_goto_to_a_payment_path_is_still_only_tier_two() -> None:
    """Documents WHY v1 is read-only: ``goto`` is ungated, not auto-approved."""
    session = BrowserSession(
        config=BrowserToolConfig(enabled=True), session_id="s1", agent_id="a1",
    )
    for url in (
        "https://bank.example.com/checkout",
        "https://shop.example/payment",
        "https://x.example/transfer",
    ):
        assert classify_action(session, "goto", {"url": url}) == 2


def test_a_silent_read_on_a_payment_page_stays_tier_one() -> None:
    session = BrowserSession(
        config=BrowserToolConfig(enabled=True), session_id="s1", agent_id="a1",
    )
    session.set_last_url("https://bank.example.com/payment")
    for action in ("state", "extract_text", "back", "forward", "wait"):
        assert classify_action(session, action, {}) == 1


def test_an_excluded_action_on_the_same_page_does_reach_tier_three() -> None:
    """The contrast that makes the exclusion load-bearing rather than cosmetic."""
    session = BrowserSession(
        config=BrowserToolConfig(enabled=True), session_id="s1", agent_id="a1",
    )
    session.set_last_url("https://bank.example.com/payment")
    assert classify_action(session, "click", {"index": 0}) == 3


@pytest.mark.asyncio
async def test_the_full_offered_sequence_mints_no_confirmation_token() -> None:
    executor, tool, _ = await _armed_executor()
    try:
        await _invoke(executor, {"action": "goto", "url": "https://bank.example.com/checkout"})
        sid = None
        for action in ("state", "extract_text", "back", "forward"):
            res = await _invoke(executor, {"action": action, "session_id": sid})
            sid = (res.output or {}).get("session_id", sid)
        assert tool._pending_confirmations == {}
    finally:
        await tool.stop()


# -- DD-1: the action allowlist -------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("action", _ALL_SIX)
async def test_each_offered_action_reaches_the_tool(action: str) -> None:
    executor, tool, page = await _armed_executor()
    try:
        params: dict[str, Any] = {"action": action}
        if action == "goto":
            params["url"] = "https://example.com/"
        if action == "wait":
            params["milliseconds"] = 1
        res = await _invoke(executor, params)
        assert res.error is None, res.error
        assert type(res.output) is dict
        assert res.output["disposition"] == _BROWSER_DISPOSITION
        # A session exists ONLY if ``BrowserTool.invoke`` was entered.
        assert tool._sessions != {}
    finally:
        await tool.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", _EXCLUDED_ACTIONS)
async def test_each_mutating_action_is_refused_before_the_tool(action: str) -> None:
    executor, tool, page = await _armed_executor()
    try:
        res = await _invoke(executor, {"action": action, "index": 0, "text": "x"})
        assert res.error == _BROWSER_READ_ONLY_REFUSAL
        assert res.output is None
        # ``super().invoke`` was never called ⇒ no session, no page traffic.
        assert tool._sessions == {}
        assert page.calls == []
        tcr = ToolCallResult.from_tool_result("c1", res, 1.0)
        assert tcr.is_error is True
    finally:
        await tool.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ("eval_js", "fill_credential", "teleport"))
async def test_an_action_outside_the_tools_own_enum_is_refused_by_the_allowlist(
    action: str,
) -> None:
    """Fail-safe direction: unknown ⇒ refused HERE, before the tool sees it."""
    executor, tool, page = await _armed_executor()
    try:
        res = await _invoke(executor, {"action": action})
        assert res.error == _BROWSER_READ_ONLY_REFUSAL
        assert tool._sessions == {}
        assert page.calls == []
    finally:
        await tool.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [{}, {"action": None}, {"action": 7}, {"action": {"nested": "goto"}},
     {"action": ["goto"]}, {"action": b"goto"}],
    ids=["absent", "none", "int", "dict", "list", "bytes"],
)
async def test_a_non_string_action_is_refused_through_the_same_framed_path(
    params: dict[str, Any],
) -> None:
    """Builder check 3 — LLM-produced JSON, so never KeyError, never truthiness."""
    executor, tool, page = await _armed_executor()
    try:
        res = await _invoke(executor, dict(params))
        assert res.error == _BROWSER_READ_ONLY_REFUSAL
        assert tool._sessions == {}
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_a_non_dict_params_payload_is_refused_rather_than_raising() -> None:
    executor, tool, _ = await _armed_executor()
    try:
        res = await executor.invoke(
            "agent-a", "browser", "goto",  # type: ignore[arg-type]
            agent_department="engineering", agent_rank="lieutenant",
        )
        assert res.error == _BROWSER_READ_ONLY_REFUSAL
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_an_unarmed_executor_passes_a_mutating_action_straight_through() -> None:
    """Default ⇒ byte-identical to AD-856: the guard is opt-in."""
    page = _FakePage(list_elements=[{"tag": "button", "text": "Go", "selector": "button#go"}])
    executor, tool, page = await _armed_executor(arm=False, page=page)
    try:
        enumerated = await _invoke(executor, {"action": "state"})
        sid = enumerated.output["session_id"]
        assert "disposition" not in enumerated.output

        res = await _invoke(executor, {"action": "click", "index": 0, "session_id": sid})
        assert res.error is None
        assert ("click", ("button#go",), {}) in page.calls
        assert res.output is not None
        assert "disposition" not in res.output
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_the_guard_never_touches_a_non_browser_tool() -> None:
    """Armed for ``browser`` only — a sibling tool id is unaffected."""

    class _Echo:
        tool_id = "echo"
        name = "Echo"
        tool_type = ToolType.UTILITY_AGENT
        description = "echo"
        input_schema: dict[str, Any] = {"type": "object"}
        output_schema: dict[str, Any] = {"type": "object"}

        async def invoke(self, params, context=None):
            return ToolResult(output={"action": params.get("action"), "text": "y" * 50_000})

    registry = ToolRegistry()
    registry.register(_Echo(), domain="*", provider="test")  # type: ignore[arg-type]
    executor = DispatchToolExecutor(registry=registry)
    executor.restrict_browser_actions(_BROWSER_LOOP_ACTIONS)
    res = await executor.invoke("agent-a", "echo", {"action": "click"})
    assert res.error is None
    assert len(res.output["text"]) == 50_000
    assert "disposition" not in res.output


# -- DD-3: output bounds --------------------------------------------------


@pytest.mark.asyncio
async def test_a_long_extract_text_is_head_truncated_with_a_counted_marker() -> None:
    page = _FakePage(inner_text="Z" * 20_000)
    executor, tool, _ = await _armed_executor(page=page)
    try:
        res = await _invoke(executor, {"action": "extract_text"})
        text = res.output["text"]
        omitted = 20_000 - _BROWSER_TEXT_MAX_CHARS
        assert text.startswith("Z" * _BROWSER_TEXT_MAX_CHARS)
        assert text == "Z" * _BROWSER_TEXT_MAX_CHARS + _BROWSER_TEXT_ELISION.format(
            omitted=omitted
        )
        assert str(omitted) in text
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_a_long_element_list_is_capped_with_a_counted_marker() -> None:
    page = _FakePage(list_elements=[{"tag": "a", "text": f"e{i}"} for i in range(250)])
    executor, tool, _ = await _armed_executor(page=page)
    try:
        res = await _invoke(executor, {"action": "state"})
        elements = res.output["elements"]
        assert len(elements) == _BROWSER_MAX_ELEMENTS + 1
        assert all(type(e) is dict for e in elements[:_BROWSER_MAX_ELEMENTS])
        assert elements[-1] == _BROWSER_ELEMENTS_ELISION.format(
            omitted=250 - _BROWSER_MAX_ELEMENTS
        )
        assert "150" in elements[-1]
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_under_limit_values_are_carried_through_unmodified() -> None:
    """The bound must not silently rewrite a small page."""
    page = _FakePage(
        inner_text="short body",
        list_elements=[{"tag": "a", "text": f"e{i}"} for i in range(3)],
    )
    executor, tool, _ = await _armed_executor(page=page)
    raw_tool, raw_page = _make_browser_tool(
        page=_FakePage(
            inner_text="short body",
            list_elements=[{"tag": "a", "text": f"e{i}"} for i in range(3)],
        ),
    )
    try:
        bounded = await _invoke(executor, {"action": "state"})
        raw = await raw_tool.invoke({"action": "state"}, {"agent_id": "agent-a"})
        assert bounded.output["elements"] == raw.output["elements"]

        bounded_text = await _invoke(executor, {"action": "extract_text"})
        raw_text = await raw_tool.invoke({"action": "extract_text"}, {"agent_id": "a"})
        assert bounded_text.output["text"] == raw_text.output["text"] == "short body"
    finally:
        await tool.stop()
        await raw_tool.stop()


@pytest.mark.asyncio
async def test_the_bounded_value_is_what_the_durable_trace_records() -> None:
    """AD-1151: bound BEFORE ``from_tool_result``, so the trace agrees."""
    import json

    from probos.cognitive.swe_harness.agentic_loop import (
        build_tool_trace_payload,
        resolve_tool_trace_bounds,
    )
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest

    page = _FakePage(inner_text="Z" * 20_000)
    executor, tool, _ = await _armed_executor(page=page)
    try:
        res = await _invoke(executor, {"action": "extract_text"})
        tcr = ToolCallResult.from_tool_result("call-1", res, 1.0)
        _entries, blob = build_tool_trace_payload(
            [ToolCallRequest(id="call-1", name="browser", arguments={"action": "extract_text"})],
            [tcr],
            **resolve_tool_trace_bounds(None),
        )
        recorded = json.loads(blob.decode())[0]["output"]
        assert "Z" * 20_000 not in recorded
        assert _BROWSER_DISPOSITION in recorded
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_an_error_result_is_returned_unframed_and_unbounded() -> None:
    """A refusal or a policy denial is not an observation — no disposition."""
    cfg = BrowserToolConfig(enabled=True, domain_denylist=["evil.example"])
    executor, tool, _ = await _armed_executor(config=cfg)
    try:
        res = await _invoke(executor, {"action": "goto", "url": "https://evil.example/x"})
        assert res.error is not None
        assert res.output is None
        assert _BROWSER_DISPOSITION not in str(res.error)
    finally:
        await tool.stop()


# -- DD-4: framing --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        _BROWSER_DISPOSITION,
        _BROWSER_READ_ONLY_REFUSAL,
        _BROWSER_TEXT_ELISION.format(omitted=1234),
        _BROWSER_ELEMENTS_ELISION.format(omitted=150),
        _BROWSER_EGRESS_WARNING,
    ],
    ids=["disposition", "refusal", "text_elision", "elements_elision", "egress"],
)
def test_every_authored_string_is_clean_under_the_real_capability_gap_regex(
    text: str,
) -> None:
    """Imported, never re-typed — ``lack`` is a BARE substring in that pattern."""
    match = _CAPABILITY_GAP_RE.search(text)
    assert match is None, f"trips the gap regex on {match.group(0)!r}: {text!r}"


@pytest.mark.asyncio
async def test_every_rendered_result_is_clean_under_the_gap_regex() -> None:
    page = _FakePage(
        inner_text="Q" * 20_000,
        list_elements=[{"tag": "a", "text": f"e{i}"} for i in range(250)],
    )
    executor, tool, _ = await _armed_executor(page=page)
    try:
        rendered: list[str] = []
        for params in (
            {"action": "goto", "url": "https://example.com/"},
            {"action": "state"},
            {"action": "extract_text"},
            {"action": "click", "index": 0},
        ):
            res = await _invoke(executor, params)
            rendered.append(ToolCallResult.from_tool_result("c", res, 1.0).output)
        for blob in rendered:
            match = _CAPABILITY_GAP_RE.search(blob)
            assert match is None, f"gap phrase {match.group(0)!r} in {blob[:200]!r}"
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_a_successful_read_carries_the_disposition_and_a_refusal_does_not() -> None:
    executor, tool, _ = await _armed_executor(page=_FakePage(inner_text="hello"))
    try:
        ok = await _invoke(executor, {"action": "extract_text"})
        assert _BROWSER_DISPOSITION in str(ok.output)
        refused = await _invoke(executor, {"action": "click", "index": 0})
        assert _BROWSER_DISPOSITION not in str(refused.error)
    finally:
        await tool.stop()


# -- DD-2 / DD-6: the offer ----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("rank", ["lieutenant", "commander", "senior_officer"])
async def test_a_rank_at_or_above_lieutenant_is_offered_the_browser(rank: str) -> None:
    assert "browser" in await _offered(browser_enabled=True, rank=rank)


@pytest.mark.asyncio
async def test_an_ensign_is_silently_not_offered_the_browser() -> None:
    """DD-2: ``ensign`` is trust < 0.5, not a caste. Denied, with no error and
    no capability-gap phrasing anywhere in the loop input."""
    offered = await _offered(browser_enabled=True, rank="ensign")
    assert "browser" not in offered
    for tid in offered:
        assert _CAPABILITY_GAP_RE.search(tid) is None


@pytest.mark.asyncio
async def test_the_flag_on_but_the_tool_unregistered_offers_nothing() -> None:
    assert "browser" not in await _offered(browser_enabled=True, register=False)


@pytest.mark.asyncio
async def test_flag_off_leaves_the_offered_tool_set_byte_identical() -> None:
    off = await _offered(browser_enabled=False)
    on = await _offered(browser_enabled=True)
    # Literal recomputation: with every sibling block off and no grants, the
    # AD-1140 set is empty, so the AD-1153 delta is exactly one id.
    assert off == []
    assert on == ["browser"]
    assert on == [*off, "browser"]


def test_the_default_config_leaves_the_flag_off() -> None:
    assert AgenticToolsConfig().browser_enabled is False


def test_browser_is_not_in_the_gated_tool_ids() -> None:
    """DD-2: it carries no ``allowed_departments``, so the gate would have
    nothing to protect and would only remove the Captain escape hatch."""
    assert "browser" not in _GATED_TOOL_IDS


@pytest.mark.asyncio
async def test_a_captain_grant_still_surfaces_the_browser_to_an_ensign() -> None:
    """Layer-4 grant-up. The escape hatch works today and must keep working."""
    with_grant = await _offered(
        browser_enabled=True, rank="ensign", grant=ToolPermission.READ,
    )
    assert "browser" in with_grant


@pytest.mark.asyncio
async def test_a_captain_grant_surfaces_the_browser_even_with_the_flag_off() -> None:
    assert "browser" in await _offered(
        browser_enabled=False, rank="ensign", grant=ToolPermission.READ,
    )


# -- DD-1: arming is offer-scoped, never grant-scoped ---------------------


async def _armed_during_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    browser_enabled: bool,
    rank: str,
    grant: ToolPermission | None = None,
) -> list[frozenset[str]]:
    """Return the ``restrict_browser_actions`` calls one real dispatch made."""
    armed: list[frozenset[str]] = []

    class _Recording(DispatchToolExecutor):
        def restrict_browser_actions(self, actions: frozenset[str]) -> None:
            armed.append(actions)
            super().restrict_browser_actions(actions)

    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.DispatchToolExecutor", _Recording,
    )
    await _offered(browser_enabled=browser_enabled, rank=rank, grant=grant)
    return armed


@pytest.mark.asyncio
async def test_the_guard_arms_when_the_tool_arrives_through_the_new_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    armed = await _armed_during_dispatch(
        monkeypatch, browser_enabled=True, rank="lieutenant",
    )
    assert armed == [_BROWSER_LOOP_ACTIONS]


@pytest.mark.asyncio
async def test_the_guard_does_not_arm_and_so_does_not_narrow_a_captain_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Layer-4 inversion this AD must not commit: an agent holding
    ``browser`` through a grant keeps the unrestricted surface even with the
    flag on."""
    armed = await _armed_during_dispatch(
        monkeypatch, browser_enabled=True, rank="lieutenant",
        grant=ToolPermission.WRITE,
    )
    assert armed == []


@pytest.mark.asyncio
async def test_the_guard_does_not_arm_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    armed = await _armed_during_dispatch(
        monkeypatch, browser_enabled=False, rank="lieutenant",
    )
    assert armed == []


@pytest.mark.asyncio
async def test_the_guard_does_not_arm_for_a_rank_that_was_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    armed = await _armed_during_dispatch(
        monkeypatch, browser_enabled=True, rank="ensign",
    )
    assert armed == []


# -- Guardrails still bind ------------------------------------------------


@pytest.mark.asyncio
async def test_the_domain_denylist_still_blocks_a_goto_on_the_loop_path() -> None:
    cfg = BrowserToolConfig(enabled=True, domain_denylist=["evil.example"])
    executor, tool, _ = await _armed_executor(config=cfg)
    direct_tool, _ = _make_browser_tool(config=cfg)
    try:
        looped = await _invoke(executor, {"action": "goto", "url": "https://evil.example/x"})
        direct = await direct_tool.invoke(
            {"action": "goto", "url": "https://evil.example/x"}, {"agent_id": "a"},
        )
        assert looped.error == direct.error
        assert "in denylist" in looped.error
    finally:
        await tool.stop()
        await direct_tool.stop()


@pytest.mark.asyncio
async def test_the_domain_allowlist_still_blocks_an_off_list_goto_on_the_loop_path() -> None:
    cfg = BrowserToolConfig(enabled=True, domain_allowlist=["good.example"])
    executor, tool, _ = await _armed_executor(config=cfg)
    try:
        res = await _invoke(executor, {"action": "goto", "url": "https://other.example/x"})
        assert res.error is not None
        assert "allowlist" in res.error
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_destructive_url_patterns_is_not_consulted_by_the_tool() -> None:
    """Negative guard documenting WHY DD-1 is read-only. If a future AD moves
    that check into ``BrowserTool``, this goes red and forces a DD revisit."""
    cfg = BrowserToolConfig(
        enabled=True, destructive_url_patterns=[r".*/checkout.*"],
    )
    executor, tool, page = await _armed_executor(config=cfg)
    session = BrowserSession(config=cfg, session_id="s1", agent_id="a1")
    try:
        res = await _invoke(
            executor, {"action": "goto", "url": "https://x.example/checkout"},
        )
        assert res.error is None
        assert ("goto", ("https://x.example/checkout",), {}) in page.calls
        assert classify_action(session, "goto", {"url": "https://x.example/checkout"}) == 2
    finally:
        await tool.stop()


@pytest.mark.asyncio
async def test_the_browser_tool_config_is_never_mutated_by_the_loop_path() -> None:
    cfg = BrowserToolConfig(enabled=True)
    before = cfg.model_dump()
    executor, tool, _ = await _armed_executor(config=cfg)
    try:
        await _invoke(executor, {"action": "goto", "url": "https://example.com/"})
        await _invoke(executor, {"action": "click", "index": 0})
        assert cfg.model_dump() == before
    finally:
        await tool.stop()


# -- DD-5: parallelism is deliberately unchanged --------------------------


def test_browser_is_not_parallel_safe() -> None:
    from probos.cognitive.swe_harness.agentic_loop import PARALLEL_SAFE_TOOL_IDS

    assert "browser" not in PARALLEL_SAFE_TOOL_IDS


def test_a_browser_call_is_partitioned_onto_the_sequential_side() -> None:
    from probos.cognitive.swe_harness.agentic_loop import partition_tool_uses
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    uses = [
        ToolUseBlock(tool_call=ToolCallRequest(id="1", name="http_fetch", arguments={})),
        ToolUseBlock(tool_call=ToolCallRequest(id="2", name="browser", arguments={})),
    ]
    parallel, sequential = partition_tool_uses(uses)
    assert parallel == [0]
    assert sequential == [1]


# -- DD-7: egress warning -------------------------------------------------


@pytest.mark.asyncio
async def test_the_open_egress_warning_fires_once_per_executor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = ToolPermissionStore(db_path=":memory:")
    await store.start()
    tool, _ = _make_browser_tool()
    try:
        registry = _registry_with_browser(tool, permission_store=store)
        runtime = _agentic_runtime(registry, store)
        executor = WorkItemAgenticExecutor(llm_client=_ToolIdCapturingLLM())
        with caplog.at_level("WARNING", logger="probos.cognitive.agentic_dispatch"):
            for _ in range(2):
                await executor.run(
                    agent_id="agent-a", instructions="", task_text="go",
                    runtime=runtime, department="engineering", rank="lieutenant",
                )
        hits = [r for r in caplog.records if _BROWSER_EGRESS_WARNING in r.getMessage()]
        assert len(hits) == 1
    finally:
        await tool.stop()
        await store.stop()


@pytest.mark.asyncio
async def test_a_non_empty_allowlist_suppresses_the_egress_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = BrowserToolConfig(enabled=True, domain_allowlist=["good.example"])
    with caplog.at_level("WARNING", logger="probos.cognitive.agentic_dispatch"):
        offered = await _offered(browser_enabled=True, browser_cfg=cfg)
    assert "browser" in offered
    assert not [r for r in caplog.records if _BROWSER_EGRESS_WARNING in r.getMessage()]


# -- Drift guards ---------------------------------------------------------


def test_the_allowlist_is_a_subset_of_the_tools_own_action_enum() -> None:
    """Builder check 6 — a rename in ``browser/tool.py`` fails loudly here
    instead of silently refusing a valid verb."""
    tool = BrowserTool(config=BrowserToolConfig(enabled=True))
    enum = set(tool.input_schema["properties"]["action"]["enum"])
    assert _BROWSER_LOOP_ACTIONS <= enum
    assert _BROWSER_LOOP_ACTIONS == frozenset(_ALL_SIX)
    assert enum - _BROWSER_LOOP_ACTIONS == set(_EXCLUDED_ACTIONS)


# -- HEADLINE -------------------------------------------------------------


@pytest.mark.asyncio
async def test_headline_navigate_enumerate_extract_then_a_refused_click() -> None:
    """A lieutenant is offered the browser, navigates a fixture page, enumerates
    it, extracts its text carrying the disposition — and is refused a click
    without the tool ever being entered."""
    offered = await _offered(browser_enabled=True, rank="lieutenant")
    assert "browser" in offered

    page = _FakePage(
        title="Fixture Page",
        inner_text="The fixture page body.",
        list_elements=[
            {"tag": "a", "text": "Docs", "selector": "a#docs"},
            {"tag": "button", "text": "Buy now", "selector": "button#buy"},
        ],
    )
    executor, tool, _ = await _armed_executor(page=page)
    try:
        nav = await _invoke(executor, {"action": "goto", "url": "https://fixture.example/"})
        assert nav.error is None
        sid = nav.output["session_id"]
        assert nav.output["page_title"] == "Fixture Page"

        enumerated = await _invoke(executor, {"action": "state", "session_id": sid})
        assert enumerated.error is None
        assert [e["text"] for e in enumerated.output["elements"]] == ["Docs", "Buy now"]

        read = await _invoke(executor, {"action": "extract_text", "session_id": sid})
        assert read.error is None
        assert read.output["text"] == "The fixture page body."
        assert read.output["disposition"] == _BROWSER_DISPOSITION

        page.calls.clear()
        clicked = await _invoke(
            executor, {"action": "click", "index": 1, "session_id": sid},
        )
        assert clicked.error == _BROWSER_READ_ONLY_REFUSAL
        assert page.calls == []
        assert tool._pending_confirmations == {}
    finally:
        await tool.stop()
