"""AD-647 v1 — process-chain primitives + Scout migration."""
from __future__ import annotations

import json
import pytest

from probos.cognitive.process_chains import (
    ProcessChainDefinition,
    ProcessChainExecutionError,
    ProcessChainExecutor,
    ProcessChainStep,
    ProcessChainStepKind,
)


@pytest.mark.asyncio
async def test_definition_step_name_uniqueness_enforced():
    """ProcessChainDefinition rejects duplicate step names at construction."""
    async def _h(ctx): return {}
    with pytest.raises(ValueError, match="duplicate step name"):
        ProcessChainDefinition(
            name="dup",
            steps=(
                ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="a", handler=_h),
                ProcessChainStep(kind=ProcessChainStepKind.STORE, name="a", handler=_h),
            ),
        )


@pytest.mark.asyncio
async def test_definition_rejects_prompt_template_id_in_v1():
    """v1 supports callable handlers only — prompt_template_id reserved for AD-647b."""
    async def _h(ctx): return {}
    with pytest.raises(ValueError, match="reserved for AD-647b"):
        ProcessChainDefinition(
            name="bad",
            steps=(
                ProcessChainStep(
                    kind=ProcessChainStepKind.TRANSFORM, name="x",
                    handler=_h, prompt_template_id="future_template",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_executor_runs_steps_sequentially_and_threads_context():
    """Each step's returned dict is merged before the next step runs."""
    order: list[str] = []

    async def step1(ctx):
        order.append("s1")
        assert ctx == {"seed": 1}
        return {"a": "alpha"}

    async def step2(ctx):
        order.append("s2")
        assert ctx == {"seed": 1, "a": "alpha"}
        return {"b": "beta"}

    async def step3(ctx):
        order.append("s3")
        assert ctx == {"seed": 1, "a": "alpha", "b": "beta"}
        return {"c": "gamma"}

    chain = ProcessChainDefinition(
        name="ordered",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="s1", handler=step1),
            ProcessChainStep(kind=ProcessChainStepKind.TRANSFORM, name="s2", handler=step2),
            ProcessChainStep(kind=ProcessChainStepKind.STORE, name="s3", handler=step3),
        ),
    )
    final = await ProcessChainExecutor().run(chain, context={"seed": 1})
    assert order == ["s1", "s2", "s3"]
    assert final == {"seed": 1, "a": "alpha", "b": "beta", "c": "gamma"}


@pytest.mark.asyncio
async def test_executor_rejects_empty_chain():
    """Empty chain is a configuration error — fail fast at run()."""
    chain = ProcessChainDefinition(name="empty", steps=())
    with pytest.raises(ProcessChainExecutionError) as ei:
        await ProcessChainExecutor().run(chain)
    assert ei.value.chain_name == "empty"


@pytest.mark.asyncio
async def test_executor_surfaces_handler_exception_with_metadata():
    """Handler raises → executor wraps in ProcessChainExecutionError, no swallow."""
    async def ok_step(ctx): return {"x": 1}

    async def boom(ctx):
        raise RuntimeError("simulated failure")

    chain = ProcessChainDefinition(
        name="boomchain",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="ok", handler=ok_step),
            ProcessChainStep(kind=ProcessChainStepKind.NOTIFY, name="boom", handler=boom),
        ),
    )
    with pytest.raises(ProcessChainExecutionError) as ei:
        await ProcessChainExecutor().run(chain)
    assert ei.value.chain_name == "boomchain"
    assert ei.value.step_name == "boom"
    assert isinstance(ei.value.cause, RuntimeError)


@pytest.mark.asyncio
async def test_executor_rejects_non_dict_handler_return():
    """Handler must return dict | None — anything else is a contract violation."""
    async def bad(ctx):
        return "not a dict"  # type: ignore[return-value]

    chain = ProcessChainDefinition(
        name="badret",
        steps=(ProcessChainStep(kind=ProcessChainStepKind.TRANSFORM, name="bad", handler=bad),),
    )
    with pytest.raises(ProcessChainExecutionError) as ei:
        await ProcessChainExecutor().run(chain)
    assert isinstance(ei.value.cause, TypeError)


@pytest.mark.asyncio
async def test_executor_treats_none_return_as_empty_dict():
    """Handler returning None is shorthand for 'no context update' — must not crash."""
    async def silent(ctx):
        return None

    async def follower(ctx):
        return {"ok": True}

    chain = ProcessChainDefinition(
        name="nonechain",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="silent", handler=silent),
            ProcessChainStep(kind=ProcessChainStepKind.NOTIFY, name="follower", handler=follower),
        ),
    )
    final = await ProcessChainExecutor().run(chain, context={"seed": 1})
    assert final == {"seed": 1, "ok": True}


@pytest.mark.asyncio
async def test_scout_act_runs_through_process_chain(tmp_path, monkeypatch):
    """End-to-end Scout migration: act() invokes SCOUT_REPORT_CHAIN handlers and produces a report file."""
    from probos.cognitive.scout import ScoutAgent

    agent = ScoutAgent.__new__(ScoutAgent)  # bypass spawner ctor — we wire the minimum we need
    agent.id = "scout-test"
    agent._runtime = None  # no notification queue, no discord
    agent._last_findings = []
    agent._pending_seen_repos = []  # already marked / nothing to mark
    agent._repo_metadata = {
        "octo/agent": {"language": "Python", "license": "MIT", "topics": ["ai-agents"]},
    }

    # Redirect data dir to tmp_path so report write + seen file are isolated.
    monkeypatch.setattr(
        type(agent),
        "_data_dir",
        property(lambda self: tmp_path),
    )

    llm_output = (
        "===SCOUT_REPORT===\n"
        "REPO: octo/agent\n"
        "STARS: 1500\n"
        "URL: https://github.com/octo/agent\n"
        "CLASS: absorb\n"
        "RELEVANCE: 4\n"
        "CREDIBILITY: 4\n"
        "RELIABILITY: 4\n"
        "SUMMARY: Multi-agent orchestration\n"
        "INSIGHT: Demonstrates governed delegation\n"
        "===END===\n"
    )
    decision = {
        "intent": "scout_search",
        "llm_output": llm_output,
        "duty": {"duty_id": "scout_report"},
    }
    out = await agent.act(decision)

    assert out["success"] is True
    assert "octo/agent" in out["result"]  # digest contains the finding
    # Report file landed in tmp_path/scout_reports/<date>.json
    report_files = list((tmp_path / "scout_reports").glob("*.json"))
    assert len(report_files) == 1
    payload = json.loads(report_files[0].read_text(encoding="utf-8"))
    assert payload["total_classified"] == 1
    assert payload["total_relevant"] == 1
    assert payload["findings"][0]["repo_full_name"] == "octo/agent"
    assert payload["findings"][0]["language"] == "Python"  # enrichment ran
