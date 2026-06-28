"""AD-1065: conversational agentic turn (tool-calling loop in 1:1 chat).

The 1:1 ``direct_message`` reply path can run the AgenticLoop (tools) instead of
a single LLM pass, so a crew agent can perform tasks for the Captain mid-chat
(Claude Cowork / Codex / Copilot parity). Default OFF; honest-degrades to the
single-pass path on any miss/failure. These tests exercise the gate +
honest-degrade of ``CognitiveAgent._maybe_run_conversational_agentic`` (called as
an unbound method with a ``SimpleNamespace`` self, per the AD-912 pattern) and
the config flag defaults + the executor's new chat-tuning params.
"""

from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.config import DmAgenticConfig, SystemConfig


class _FakeOutcome:
    def __init__(self, final_text: str) -> None:
        self.final_text = final_text


class _FakeExecutor:
    """Stand-in for WorkItemAgenticExecutor — records run() kwargs."""

    last_kwargs: dict | None = None

    def __init__(self, *, llm_client) -> None:
        self.llm_client = llm_client

    async def run(self, **kwargs):
        _FakeExecutor.last_kwargs = kwargs
        return _FakeOutcome("Done — I created the document for you, Captain.")


class _RaisingExecutor:
    def __init__(self, *, llm_client) -> None:
        pass

    async def run(self, **kwargs):
        raise RuntimeError("loop blew up")


class _EmptyExecutor:
    def __init__(self, *, llm_client) -> None:
        pass

    async def run(self, **kwargs):
        return _FakeOutcome("   ")  # whitespace-only -> treated as empty


def _agent(runtime):
    agent = SimpleNamespace(
        _runtime=runtime,
        _llm_client=object(),
        id="agent-1",
        department="science",
        rank="lieutenant",
    )
    # AD-1070a: _maybe_run_conversational_agentic now delegates its gate to
    # self._conversational_agentic_will_run; bind the real method so the
    # unbound-method-with-SimpleNamespace-self pattern resolves it.
    agent._conversational_agentic_will_run = (
        lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
    )
    return agent


def _runtime(*, enabled: bool, **cfg):
    return SimpleNamespace(
        config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=enabled, **cfg)),
    )


def _dm_obs(**params):
    return {"intent": "direct_message", "params": params}


async def _call(agent, observation):
    return await CognitiveAgent._maybe_run_conversational_agentic(
        agent, observation, system_prompt="You are Ezri.", user_message="make me a doc",
    )


# ── Gate: returns None (fall through to single-pass) ───────────────

async def test_flag_off_returns_none() -> None:
    agent = _agent(_runtime(enabled=False))
    assert await _call(agent, _dm_obs()) is None


async def test_no_runtime_returns_none() -> None:
    agent = _agent(None)
    assert await _call(agent, _dm_obs()) is None


async def test_non_direct_message_returns_none() -> None:
    agent = _agent(_runtime(enabled=True))
    assert await _call(agent, {"intent": "proactive_think", "params": {}}) is None


async def test_group_chat_returns_none() -> None:
    agent = _agent(_runtime(enabled=True))
    assert await _call(agent, _dm_obs(is_group_chat=True)) is None


async def test_vision_turn_returns_none() -> None:
    agent = _agent(_runtime(enabled=True))
    obs = _dm_obs(vision_messages=[{"role": "user", "content": []}])
    assert await _call(agent, obs) is None


# ── Flag ON: runs the loop ────────────────────────────────────────

async def test_flag_on_1to1_runs_loop_and_returns_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _FakeExecutor,
    )
    _FakeExecutor.last_kwargs = None
    agent = _agent(_runtime(enabled=True, max_iterations=4, tier="fast"))

    result = await _call(agent, _dm_obs())

    assert result == "Done — I created the document for you, Captain."
    # The chat path passes the config's iteration cap + tier (NOT the task
    # defaults), the agent identity as instructions, and the Captain text.
    kw = _FakeExecutor.last_kwargs
    assert kw["agent_id"] == "agent-1"
    assert kw["instructions"] == "You are Ezri."
    assert kw["task_text"] == "make me a doc"
    assert kw["max_iterations"] == 4
    assert kw["tier"] == "fast"


async def test_loop_failure_honest_degrades_to_none(monkeypatch) -> None:
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _RaisingExecutor,
    )
    agent = _agent(_runtime(enabled=True))
    assert await _call(agent, _dm_obs()) is None


async def test_empty_loop_result_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _EmptyExecutor,
    )
    agent = _agent(_runtime(enabled=True))
    assert await _call(agent, _dm_obs()) is None


# ── Config defaults (real config, BF-287) ─────────────────────────

def test_dm_agentic_config_defaults() -> None:
    cfg = DmAgenticConfig()
    assert cfg.enabled is False
    assert cfg.max_iterations == 5
    assert cfg.tier == "standard"


def test_system_config_wires_dm_agentic_default_off() -> None:
    sc = SystemConfig()
    assert isinstance(sc.dm_agentic, DmAgenticConfig)
    assert sc.dm_agentic.enabled is False
