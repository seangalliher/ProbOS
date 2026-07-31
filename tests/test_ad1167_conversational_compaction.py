"""AD-1167: compaction for the conversational agentic path.

``AgenticLoop`` re-flattens its entire message history into one prompt every
iteration. `WorkItemAgenticExecutor.run` has accepted `compactor` /
`compaction_threshold` / `token_budget` since AD-1142 and forwards them to the
loop when they are not None -- but the conversational caller passed only
`max_iterations` and `tier`, so this path has never compacted anything.

Measured on the reference vessel, raising `max_iterations` from 10 to 20 took
one turn from 218,957 to 474,736 tokens: more than double the cost for twice
the steps, because each added step re-pays for every step before it. The answer
got *worse*, not better -- the early `state()` result that had located the
target was buried under twenty rounds of re-flattened history, and the agent
regressed from "I can see the document content area at index 90/91" to "it's
canvas-based, use coordinates".

More room to flail is not more capability.
"""

from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.swe_harness.session_compactor import SessionCompactor
from probos.config import DmAgenticConfig


class _FakeOutcome:
    final_text = "Done, Captain."
    stopped_reason = "complete"


class _RecordingExecutor:
    """Records the kwargs the conversational path hands the executor."""

    last_kwargs: dict | None = None

    def __init__(self, *, llm_client) -> None:
        self.llm_client = llm_client

    async def run(self, **kwargs):
        _RecordingExecutor.last_kwargs = kwargs
        return _FakeOutcome()


def _agent(runtime):
    agent = SimpleNamespace(
        _runtime=runtime,
        _llm_client=object(),
        id="agent-1",
        department="science",
        rank="lieutenant",
    )
    agent._conversational_agentic_will_run = (
        lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
    )
    return agent


def _runtime(**cfg):
    return SimpleNamespace(
        config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=True, **cfg)),
    )


async def _run(monkeypatch, **cfg) -> dict:
    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor",
        _RecordingExecutor,
    )
    _RecordingExecutor.last_kwargs = None
    await CognitiveAgent._maybe_run_conversational_agentic(
        _agent(_runtime(**cfg)),
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.",
        user_message="drive the browser for a while",
    )
    assert _RecordingExecutor.last_kwargs is not None, "the loop never ran"
    return _RecordingExecutor.last_kwargs


# ── the headline ──────────────────────────────────────────────────


async def test_compaction_is_wired_when_enabled(monkeypatch) -> None:
    """THE AD-1167 regression: the compactor reaches the executor."""
    kwargs = await _run(
        monkeypatch, compaction_enabled=True, compaction_threshold_tokens=60_000,
    )
    assert isinstance(kwargs["compactor"], SessionCompactor)
    assert kwargs["compaction_threshold"] == 60_000


async def test_default_is_off_and_passes_nothing(monkeypatch) -> None:
    """Default-OFF must be byte-identical to the pre-AD-1167 call.

    ``agentic_dispatch`` only forwards these kwargs to the loop when they are
    not None, so passing None builds the same kwarg dict as omitting them.
    """
    kwargs = await _run(monkeypatch)
    assert kwargs["compactor"] is None
    assert kwargs["compaction_threshold"] is None


async def test_a_zero_threshold_disables_compaction_even_when_enabled(
    monkeypatch,
) -> None:
    """0 is an explicit opt-out and must not be treated as "use the default"."""
    kwargs = await _run(
        monkeypatch, compaction_enabled=True, compaction_threshold_tokens=0,
    )
    assert kwargs["compactor"] is None
    assert kwargs["compaction_threshold"] is None


async def test_the_rest_of_the_call_is_unchanged(monkeypatch) -> None:
    """Wiring compaction must not disturb what was already being passed."""
    kwargs = await _run(
        monkeypatch, compaction_enabled=True, compaction_threshold_tokens=1_000,
    )
    assert kwargs["agent_id"] == "agent-1"
    assert kwargs["tier"] == "standard"
    assert kwargs["max_iterations"] == DmAgenticConfig().max_iterations
    assert kwargs["task_text"] == "drive the browser for a while"


# ── config contract ───────────────────────────────────────────────


def test_the_config_defaults_off() -> None:
    cfg = DmAgenticConfig()
    assert cfg.compaction_enabled is False
    assert cfg.compaction_threshold_tokens == 60_000


def test_a_negative_threshold_is_rejected_at_parse_time() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DmAgenticConfig(compaction_threshold_tokens=-1)


def test_the_compactor_is_constructible_with_no_arguments() -> None:
    """The wiring constructs one per turn; that must stay free.

    If ``SessionCompactor`` ever grows required constructor arguments, this
    fails here rather than at runtime inside a Captain's turn.
    """
    assert SessionCompactor() is not None
