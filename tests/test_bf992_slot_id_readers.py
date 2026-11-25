"""BF-992 (#1324): the episodic-recall probe and the consolidated profile hold a slot id and count episodes
under the agent's sovereign id, through ``resolve_sovereign_id_from_registry``.

Real ``MockEpisodicMemory`` over real ``Episode`` rows, a real ``AgentCapitalService``, and the probe's own
scoring path with a judge that answers a real ``LLMResponse``. Nothing stands in for ``count_for_agent``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.acm import AgentCapitalService
from probos.cognitive.episodic import resolve_sovereign_id_from_registry
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.qualification_tests import EpisodicRecallProbe
from probos.types import Episode, LLMResponse
from tests.test_ad566b_baseline_tests import MockAgent, MockRegistry

_SLOT = "security_officer-0"
_SOVEREIGN = "3f9c2a1e-sovereign"


async def _memory(*owners: tuple[str, int]) -> MockEpisodicMemory:
    memory = MockEpisodicMemory()
    for owner, count in owners:
        await memory.seed([
            Episode(user_input=f"{owner} watch report {i}", timestamp=float(i + 1), agent_ids=[owner])
            for i in range(count)
        ])
    return memory


class _Judge:
    """Answers every judge prompt with a score, as ``BaseLLMClient.complete`` does."""

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        return LLMResponse(content="0.9")


def _crew_agent(sovereign_id: str | None) -> MockAgent:
    agent = MockAgent(agent_id=_SLOT, response="I filed the watch report.")
    if sovereign_id is not None:
        agent.sovereign_id = sovereign_id
    return agent


def _probe_runtime(agent: MockAgent, memory: MockEpisodicMemory) -> SimpleNamespace:
    return SimpleNamespace(registry=MockRegistry(agent), episodic_memory=memory, llm_client=_Judge())


async def test_the_recall_probe_measures_episodes_held_under_the_sovereign_id() -> None:
    runtime = _probe_runtime(_crew_agent(_SOVEREIGN), await _memory((_SOVEREIGN, 3)))
    result = await EpisodicRecallProbe().run(_SLOT, runtime)

    assert result.error is None
    assert result.details["skipped"] is False
    assert result.details["episodes_tested"] == 3
    assert result.score == pytest.approx(0.9)
    assert result.agent_id == _SLOT  # the qualification store keeps results by slot id


async def test_the_recall_probe_skips_when_only_the_slot_id_holds_episodes() -> None:
    runtime = _probe_runtime(_crew_agent(_SOVEREIGN), await _memory((_SLOT, 3)))
    result = await EpisodicRecallProbe().run(_SLOT, runtime)

    assert result.details == {"skipped": True, "reason": "insufficient_episodes", "episode_count": 0}


async def test_the_recall_probe_counts_an_agent_with_no_sovereign_id_by_its_slot_id() -> None:
    runtime = _probe_runtime(_crew_agent(None), await _memory((_SLOT, 3)))
    result = await EpisodicRecallProbe().run(_SLOT, runtime)

    assert result.details["episodes_tested"] == 3


@pytest.fixture
async def acm(tmp_path: Path):
    service = AgentCapitalService(data_dir=str(tmp_path))
    await service.start()
    yield service
    await service.stop()


async def test_the_profile_counts_episodes_under_the_sovereign_id(acm: AgentCapitalService) -> None:
    await acm.onboard(_SLOT, "security_officer", "security", "security")
    member = SimpleNamespace(id=_SLOT, agent_type="security_officer", sovereign_id=_SOVEREIGN)
    runtime = SimpleNamespace(
        registry=SimpleNamespace(get={_SLOT: member}.get),
        episodic_memory=await _memory((_SOVEREIGN, 4), (_SLOT, 2)),
    )

    profile = await acm.get_consolidated_profile(_SLOT, runtime)

    assert profile["agent_id"] == _SLOT
    assert profile["episode_count"] == 4  # the sovereign id's 4: not the slot id's 2, not both


@pytest.mark.parametrize(
    ("agent_id", "registry", "expected"),
    [
        (_SLOT, MockRegistry(_crew_agent(_SOVEREIGN)), _SOVEREIGN),
        (_SLOT, MockRegistry(_crew_agent(None)), _SLOT),
        (_SOVEREIGN, MockRegistry(_crew_agent(_SOVEREIGN)), _SOVEREIGN),  # an id the registry does not hold
        (_SLOT, None, _SLOT),
    ],
    ids=["sovereign", "no-sovereign", "unknown-id", "no-registry"],
)
def test_the_shared_reader_maps_a_slot_id_to_the_memory_id(agent_id: str, registry: Any, expected: str) -> None:
    assert resolve_sovereign_id_from_registry(agent_id, registry) == expected
