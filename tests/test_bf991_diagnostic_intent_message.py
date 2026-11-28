"""BF-991 (#1840): ``/diagnostic`` reaches the Diagnostician at the level it asks for, and prints the diagnosis.

Two faults on one path. ``DiagnosticianAgent.perceive`` read the level with
``intent.get("level")`` on the ``IntentMessage`` the command sends, which has no
``get``. Past that, ``IntentResult.result`` is the LLM's text (``CognitiveAgent.act``),
and the handler rendered it as if it were a dict.

These tests drive the real path: a real ``DiagnosticianAgent`` over a counting LLM
double (the construction the BF-991 premise probe measured), through
``handle_intent`` and through the real ``cmd_diagnostic`` handler. Each half was
tested before (``perceive`` over a stubbed base, the handler over a mocked agent
returning a dict); the seam between them was not.
"""

from __future__ import annotations

import uuid
from io import StringIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.agents.medical.diagnostician import DiagnosticianAgent
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.experience.commands.commands_diagnostic import cmd_diagnostic
from probos.types import IntentMessage, IntentResult

_MARKER = "W-1840"
_FOCUS = "focus-bf991"
# Text Rich rewrites unless told not to: an emoji code, and a number and a boolean it highlights on a terminal.
_LITERAL = ":warning: 42 True"
_DIAG_JSON = (
    '{"severity": "high", "category": "agent", "affected_components": ["x"], '
    '"root_cause": "marker-1840", "evidence": [], "recommended_treatment": "none", '
    '"treatment_intent": "medical_tune", "treatment_params": {}}'
)


class _Vitals:
    """The Vitals Monitor as ``perceive`` finds it: by ``agent_type`` in ``registry.all()``."""

    agent_type = "vitals_monitor"

    def __init__(self) -> None:
        self.scan_now = AsyncMock(return_value={"recent_history": [{"marker": _MARKER}]})


class _Registry:
    def __init__(self, vitals: _Vitals) -> None:
        self._vitals = vitals

    def all(self) -> list[Any]:
        return [self._vitals]

    def get_by_pool(self, pool: str) -> list[Any]:
        """The base agent's AD-568d reads ask for the counselor pool inside a ``try``; there is none."""
        return []


def _llm(reply: str) -> MagicMock:
    """The premise probe's counting double: each request is recorded on ``complete``; the reply is ``reply``."""
    return MagicMock(complete=AsyncMock(return_value=MagicMock(content=reply, tier="fast", error=None)))


def _agent(reply: str = _DIAG_JSON) -> tuple[DiagnosticianAgent, MagicMock, _Vitals]:
    vitals = _Vitals()
    llm = _llm(reply)
    agent = DiagnosticianAgent(
        agent_id=f"diag-bf991-{uuid.uuid4().hex[:8]}",
        pool="medical",
        llm_client=llm,
        runtime=SimpleNamespace(registry=_Registry(vitals)),
    )
    return agent, llm, vitals


def _requests(llm: MagicMock) -> list[Any]:
    return [call.args[0] for call in llm.complete.await_args_list]


def _sent(request: Any) -> str:
    """All the text a request sends: the prompt, the system prompt and any messages."""
    return f"{request.prompt}\n{request.system_prompt}\n{request.messages}"


async def _diagnose(agent: DiagnosticianAgent, level: str, focus: str = "") -> IntentResult | None:
    return await agent.handle_intent(
        IntentMessage(intent="diagnose_system", params={"level": level, "focus": focus})
    )


def _shell(agent: Any, *, terminal: bool = False) -> tuple[SimpleNamespace, Console, StringIO]:
    """The ship as the handler reads it: one healthy agent in the ``medical_diagnostician`` pool.

    ``terminal=True`` gives a console that writes ANSI codes whatever the environment says,
    so Rich's styles, and any highlighting, show in the buffer.
    """
    pool = SimpleNamespace(healthy_agents=[agent.id], registry=SimpleNamespace(get=lambda _agent_id: agent))
    buf = StringIO()
    if terminal:
        console = Console(
            file=buf, force_terminal=True, color_system="standard", legacy_windows=False, no_color=False, width=120
        )
    else:
        console = Console(file=buf, force_terminal=False, width=120)
    return SimpleNamespace(pools={"medical_diagnostician": pool}), console, buf


# -- the agent: the level the message carries reaches the LLM call (tests 1-5) --


async def test_l3_message_makes_one_fast_call_with_the_scan_in_its_request() -> None:
    agent, llm, vitals = _agent()
    result = await _diagnose(agent, "L3")
    assert result is not None and result.success, result
    assert llm.complete.await_count == 1
    (request,) = _requests(llm)
    assert request.tier == "fast"
    assert "Diagnostic depth: L3" in _sent(request)
    assert _MARKER in _sent(request)
    vitals.scan_now.assert_awaited_once()


async def test_l5_message_makes_no_call_and_no_scan() -> None:
    agent, llm, vitals = _agent()
    result = await _diagnose(agent, "L5")
    assert result is not None and result.success, result
    assert llm.complete.await_count == 0
    vitals.scan_now.assert_not_awaited()


async def test_l1_message_requests_the_deep_tier() -> None:
    agent, llm, vitals = _agent()
    result = await _diagnose(agent, "L1")
    assert result is not None and result.success, result
    assert llm.complete.await_count == 1
    (request,) = _requests(llm)
    assert request.tier == "deep"
    assert "Diagnostic depth: L1" in _sent(request)
    assert _MARKER in _sent(request)


async def test_l4_message_scans_without_a_call() -> None:
    agent, llm, vitals = _agent()
    result = await _diagnose(agent, "L4")
    assert result is not None and result.success, result
    vitals.scan_now.assert_awaited_once()
    assert llm.complete.await_count == 0


async def test_the_focus_reaches_the_request() -> None:
    agent, llm, _ = _agent()
    await _diagnose(agent, "L3", focus=_FOCUS)
    (request,) = _requests(llm)
    assert _FOCUS in _sent(request)


# -- the flat-dict form, through the real base perceive (tests 6-7) -------------


async def test_a_flat_dict_level_survives_the_real_base_perceive() -> None:
    agent = DiagnosticianAgent(agent_id=f"diag-bf991-{uuid.uuid4().hex[:8]}", pool="medical")
    flat = {"intent": "diagnose_system", "level": "L5"}
    base = await CognitiveAgent.perceive(agent, dict(flat))
    assert "level" not in base, "premise: the base's dict branch keeps no top-level level"
    out = await agent.perceive(dict(flat))
    assert out["level"] == "L5"
    assert out["level_llm_tier"] is None


async def test_params_win_over_a_top_level_level() -> None:
    agent = DiagnosticianAgent(agent_id=f"diag-bf991-{uuid.uuid4().hex[:8]}", pool="medical")
    out = await agent.perceive({"intent": "diagnose_system", "params": {"level": "L1"}, "level": "L5"})
    assert out["level"] == "L1"
    assert out["level_llm_tier"] == "deep"


# -- the real handler over the real agent (tests 8-13) --------------------------


async def test_the_handler_prints_the_parsed_diagnosis() -> None:
    agent, llm, _ = _agent()
    runtime, console, buf = _shell(agent)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "marker-1840" in out, out
    assert "Diagnostic L3" in out, out
    assert llm.complete.await_count == 1


async def test_the_handler_at_l4_prints_the_panel_and_the_no_llm_line() -> None:
    agent, llm, vitals = _agent()
    runtime, console, buf = _shell(agent)
    await cmd_diagnostic(runtime, console, "L4")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "Diagnostic L4" in out, out
    assert "No LLM analysis at this depth (AD-700c)" in out, out
    assert llm.complete.await_count == 0
    vitals.scan_now.assert_awaited_once()


@pytest.mark.parametrize(
    ("reply", "shown"),
    [
        (f"Ship nominal [x] {_LITERAL} no JSON here", f"Ship nominal [x] {_LITERAL} no JSON here"),
        ("```json\n[1, 2]\n```", "[1, 2]"),
    ],
    ids=["text-with-brackets", "fenced-json-array"],
)
async def test_a_reply_that_is_not_a_diagnosis_is_printed_as_text(reply: str, shown: str) -> None:
    agent, llm, _ = _agent(reply)
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert "Root cause" in out, out
    assert shown in out, out
    assert llm.complete.await_count == 1


async def test_a_failed_result_prints_its_error_and_no_panel() -> None:
    failed = IntentResult(
        intent_id="i-bf991", agent_id="diag-bf991", success=False, error=f"boom [/x] {_LITERAL}"
    )
    agent = SimpleNamespace(id="diag-bf991", handle_intent=AsyncMock(return_value=failed))
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert f"Diagnostic failed: boom [/x] {_LITERAL}" in out, out
    assert "Root cause" not in out, out


async def test_llm_text_in_the_panel_is_shown_as_text_not_markup() -> None:
    reply = (
        '{"severity": "low", "category": "agent", "root_cause": "[/x] '
        + _LITERAL
        + ' stray tag", "evidence": ["pool [core] low"], "recommended_treatment": "none"}'
    )
    agent, _, _ = _agent(reply)
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" not in out, out
    assert f"[/x] {_LITERAL} stray tag" in out, out
    assert "[core]" in out, out


async def test_an_error_text_that_looks_like_markup_is_printed_not_raised() -> None:
    error = RuntimeError(f"bad [/x] {_LITERAL} tag")
    agent = SimpleNamespace(id="diag-bf991", handle_intent=AsyncMock(side_effect=error))
    runtime, console, buf = _shell(agent, terminal=True)
    await cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert f"Diagnostic error: bad [/x] {_LITERAL} tag" in out, out
