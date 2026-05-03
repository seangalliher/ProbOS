"""Combo A AD-656: Department-Specific Cognitive Profiles tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import (
    DepartmentCognitiveProfile,
    DepartmentProfilesConfig,
    SystemConfig,
)
from probos.events import EventType


def test_dept_cognitive_profile_defaults():
    profile = DepartmentCognitiveProfile()
    assert profile.recall_depth == 5
    assert profile.recall_threshold == 0.25
    assert profile.context_token_budget == 4000


def test_dept_profiles_config_empty_by_default():
    cfg = DepartmentProfilesConfig()
    assert cfg.profiles == {}
    # SystemConfig field
    sys_cfg = SystemConfig()
    assert isinstance(sys_cfg.dept_profiles, DepartmentProfilesConfig)


@pytest.mark.asyncio
async def test_evaluate_uses_profile_recall_depth_when_department_matches():
    """EvaluateHandler picks up DepartmentCognitiveProfile.recall_depth."""
    from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
    from probos.cognitive.sub_task import SubTaskSpec, SubTaskType

    fake_em = MagicMock()
    fake_em.retrieve_contrastive_episodes = AsyncMock(return_value=[])

    science_profile = DepartmentCognitiveProfile(recall_depth=8, recall_threshold=0.30)
    dept_cfg = DepartmentProfilesConfig(profiles={"science": science_profile})

    fake_runtime = SimpleNamespace()
    fake_runtime.episodic_memory = fake_em
    fake_runtime.config = SimpleNamespace(dept_profiles=dept_cfg)
    fake_runtime.emit_event = MagicMock()

    handler = EvaluateHandler(llm_client=MagicMock(), runtime=fake_runtime)
    spec = SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="t",
        prompt_template=None,
    )
    context = {"context": "test query", "_department": "science"}

    try:
        await handler(spec, context, prior_results=[])
    except Exception:
        pass

    # retrieve_contrastive_episodes called with k=8 (overridden by profile)
    assert fake_em.retrieve_contrastive_episodes.await_args.kwargs.get("k") == 8


@pytest.mark.asyncio
async def test_evaluate_emits_dept_profile_applied():
    from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
    from probos.cognitive.sub_task import SubTaskSpec, SubTaskType

    fake_em = MagicMock()
    fake_em.retrieve_contrastive_episodes = AsyncMock(return_value=[])

    profile = DepartmentCognitiveProfile(recall_depth=10)
    dept_cfg = DepartmentProfilesConfig(profiles={"medical": profile})

    rt = SimpleNamespace()
    rt.episodic_memory = fake_em
    rt.config = SimpleNamespace(dept_profiles=dept_cfg)
    rt.emit_event = MagicMock()

    handler = EvaluateHandler(llm_client=MagicMock(), runtime=rt)
    spec = SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="t",
        prompt_template=None,
    )
    context = {"context": "query", "_department": "medical"}

    try:
        await handler(spec, context, prior_results=[])
    except Exception:
        pass

    # DEPT_PROFILE_APPLIED emitted
    found = any(
        call.args[0] == EventType.DEPT_PROFILE_APPLIED
        for call in rt.emit_event.call_args_list
    )
    assert found
