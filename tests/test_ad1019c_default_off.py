"""AD-1019c: default-OFF byte-identity + the enabled wiring path.

``agent_tools_enabled=False`` (the default) must be byte-identical to AD-1019b:
no workbench, no find_mcp_tool tool, no consensus proposer pool, no reaper. The
enabled path proves the full wiring lights up under the flag.
"""

from __future__ import annotations

import pytest

from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime


@pytest.mark.asyncio
async def test_default_off_no_workbench_no_search_tool_no_pool(tmp_path):
    rt = ProbOSRuntime(data_dir=tmp_path / "data")
    await rt.start()
    try:
        # The flag is default-OFF.
        assert rt.config.mcp.agent_tools_enabled is False
        # No workbench / reaper.
        assert rt.mcp_workbench is None
        assert rt.mcp_workbench_reaper is None
        # find_mcp_tool is absent from the registry.
        if rt.tool_registry is not None:
            assert rt.tool_registry.get("find_mcp_tool") is None
        # No consensus proposer pool.
        assert "mcp_consensus" not in rt.pools
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_enabled_wires_workbench_pool_and_search_tool(tmp_path):
    cfg = SystemConfig()
    cfg.mcp.agent_tools_enabled = True
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=cfg)
    await rt.start()
    try:
        assert rt.mcp_workbench is not None
        assert rt.mcp_workbench_reaper is not None
        # The search tool is registered and the proposer pool exists.
        assert rt.tool_registry is not None
        assert rt.tool_registry.get("find_mcp_tool") is not None
        assert "mcp_consensus" in rt.pools
    finally:
        await rt.stop()
