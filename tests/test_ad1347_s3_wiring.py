"""AD-1347 S3 (#1627): finalize builds the agent-work runner only with the service, and shutdown releases it.

Real boots, as ``tests/test_ad1347_s1_wiring.py`` (its config and its two fixtures: the Ship's Archive off, the local
embedding backend).
"""

from __future__ import annotations

from pathlib import Path

from probos.agent_work import AgentWorkService
from probos.agent_work_runner import AgentWorkRunner
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from tests.test_ad1347_s1_wiring import (  # noqa: F401  (fixtures are found by name)
    _assert_no_embedding_model_loaded,
    _boot_config,
    archive_resolutions,
    local_embeddings,
)


def _config(*, enabled: bool) -> SystemConfig:
    """S1's boot shape with the Ward Room on: the runner posts its notices and reports there, and finalize wires AD-855's driver only with it."""
    config = _boot_config(enabled=enabled)
    config.ward_room.enabled = True
    return config


# W3
async def test_the_runner_is_wired_only_with_the_service_and_released_at_stop(
    tmp_path: Path, archive_resolutions: list[object], local_embeddings: Path,
) -> None:
    off = ProbOSRuntime(config=_config(enabled=False), data_dir=tmp_path / "off", llm_client=MockLLMClient())
    await off.start()
    try:
        assert off.agent_work is None and off.agent_work_runner is None
    finally:
        await off.stop()
    on = ProbOSRuntime(config=_config(enabled=True), data_dir=tmp_path / "on", llm_client=MockLLMClient())
    await on.start()
    try:
        assert isinstance(on.agent_work, AgentWorkService)
        assert on.capability_gap_driver is not None and on.capability_request_store is not None and on.ward_room is not None, (
            "premise: the runner's collaborators exist on this boot"
        )
        assert isinstance(on.agent_work_runner, AgentWorkRunner)
    finally:
        await on.stop()
    assert on.agent_work_runner is None, "a clean stop releases the runner"
    assert archive_resolutions == []
    _assert_no_embedding_model_loaded(local_embeddings)
