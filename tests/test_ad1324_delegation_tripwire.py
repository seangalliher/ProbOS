"""AD-1324 amendment 1 tripwire: a delegated (AD-1190) child loop never carries a tier controller.

Why it matters: a delegated child's stop reason feeds ``DelegationTreeBudget.settle``, which
treats ``tier_floor_unavailable`` as a non-clean stop and charges the whole grant. That overcharge
is latent only while a child is never armed. The child is built through the same executor with
no ``inner_loop_hook`` (the delegate tool passes none), and the controller needs the hook's
``costed_case`` and ``tier_choice_armed``. If either fact changes this test fails first.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import probos.tools.delegate_task_tool as delegate_tool
from probos.cognitive import agentic_dispatch
from probos.cognitive.model_registry import ModelRegistry
from probos.cognitive.model_router import ModelRouter


def _armed_runtime() -> SimpleNamespace:
    dm = SimpleNamespace(
        enabled=True,
        economic_judgment=SimpleNamespace(
            enabled=True, verification_tool_ids=[],
            tier_choice=SimpleNamespace(enabled=True, stakes_floor={"high": "standard"}, max_upward_moves_per_turn=2),
        ),
    )
    return SimpleNamespace(
        config=SimpleNamespace(dm_agentic=dm, model_routing=SimpleNamespace(enabled=True)),
        model_router=ModelRouter(registry=ModelRegistry()),
    )


def _build(hook: object) -> object:
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=SimpleNamespace())
    return executor._build_tier_controller(
        runtime=_armed_runtime(), registry=None, agent_id="child", tier="fast",
        inner_loop_hook=hook, extra_context={"_delegation_depth": 1}, work_item_id_provider=None,
        thread_id="t",
    )


def test_delegated_child_without_hook_builds_no_tier_controller() -> None:
    assert _build(None) is None


def test_premise_the_same_armed_runtime_does_build_a_controller_for_a_hooked_run() -> None:
    hook = SimpleNamespace(costed_case=lambda: SimpleNamespace(stakes="high", signals=()))
    assert _build(hook) is not None, "premise: the runtime is armed, so the None above is the hook's doing"


def test_delegate_tool_never_hands_a_child_an_inner_loop_hook() -> None:
    source = Path(delegate_tool.__file__).read_text(encoding="utf-8")
    assert "inner_loop_hook" not in source and "tier_controller" not in source
