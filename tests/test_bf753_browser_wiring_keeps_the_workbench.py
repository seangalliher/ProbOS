"""BF-753: the browser wiring discarded the MCP workbench on every boot.

The root cause of the whole MCP investigation, found only after BF-751a made the
preload say why it offered nothing -- and it then said nothing at all, because it
was never called.

``finalize_startup`` spans lines 3194-5870. Inside it:

    L4179   runtime.mcp_workbench = workbench      # the MCP block wires it
    L4894   _wire_browser_tool(runtime=..., ...)   # 715 lines later

and inside ``_wire_browser_tool``::

    # AD-1019c: MCP workbench + idle-TTL reaper attributes (default-OFF gate
    # config.mcp.agent_tools_enabled; wired in the async MCP block below).
    runtime.mcp_workbench = None
    runtime.mcp_workbench_reaper = None

The comment says "wired in the async MCP block **below**". It is not below; it is
715 lines above. So every boot built the workbench, registered ``find_mcp_tool``,
logged ``AD-1019c: MCP workbench wired`` -- and then threw the handle away.

``agentic_dispatch.run`` reads ``getattr(runtime, "mcp_workbench", None)``, got
``None``, and skipped the entire MCP block in silence. No agent has been able to
call an MCP tool since AD-1019c shipped.

Every observation fits: ``find_mcp_tool`` was in the registry with the correct
AD-1239 description (registered at wiring time, before the null); the
``/api/mcp/.../access`` router said all three tools were authorized (it builds
its own resolution and never reads ``runtime.mcp_workbench``); and the agent was
offered none of them.

The pre-declaration was also redundant. Every branch of the MCP block already
assigns the attribute -- L4179 when enabled, L4210 when agent tools are off,
L4221 when MCP is off entirely.

``mcp_workbench_reaper`` was nulled too, so ``shutdown.py`` could no longer find
the reaper it was supposed to stop: a leaked task on every boot.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from probos.config import SystemConfig
from probos.startup.finalize import _wire_browser_tool
from probos.tools.registry import ToolRegistry

_FINALIZE = Path(__file__).resolve().parent.parent / "src" / "probos" / "startup" / "finalize.py"


def _runtime(**extra: Any) -> Any:
    """A real ToolRegistry, so the function runs to the end.

    With ``tool_registry=None`` it returns early at the registry guard, before
    reaching the lines under test -- which would make every assertion here pass
    with the bug still present.
    """
    return SimpleNamespace(
        tool_registry=ToolRegistry(), audit_log=None, emit_event=None, **extra
    )


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------

def test_browser_wiring_leaves_the_mcp_workbench_alone() -> None:
    """The defect, stated directly: this ran after the MCP block and discarded
    what it had wired."""
    sentinel = object()
    runtime = _runtime(mcp_workbench=sentinel, mcp_workbench_reaper=sentinel)
    config = SystemConfig()
    config.browser_tool.enabled = True

    _wire_browser_tool(runtime=runtime, config=config)

    assert runtime.mcp_workbench is sentinel
    assert runtime.mcp_workbench_reaper is sentinel


def test_it_leaves_them_alone_on_the_disabled_early_return_too() -> None:
    """The early return is the common path -- browser_tool defaults to off."""
    sentinel = object()
    runtime = _runtime(mcp_workbench=sentinel, mcp_workbench_reaper=sentinel)
    config = SystemConfig()
    config.browser_tool.enabled = False

    assert _wire_browser_tool(runtime=runtime, config=config) is False
    assert runtime.mcp_workbench is sentinel


def test_it_still_declares_the_reapers_it_actually_owns() -> None:
    """The AD-706b/AD-733-1/AD-986d attributes are this function's own; removing
    the MCP lines must not take them with it."""
    runtime = _runtime()
    config = SystemConfig()
    config.browser_tool.enabled = True

    _wire_browser_tool(runtime=runtime, config=config)

    assert runtime.recording_reaper is None
    assert runtime.attachment_reaper is None
    assert runtime.transcript_reaper is None


# ---------------------------------------------------------------------------
# The shape, not just this instance
# ---------------------------------------------------------------------------

def test_no_wire_helper_nulls_the_mcp_workbench() -> None:
    """A ``_wire_*`` helper writing ``mcp_workbench`` is the shape of this bug.

    Ordering between two points 715 lines apart is not something a reader
    checks, so pin it structurally: only ``finalize_startup``'s own MCP block
    may assign this attribute.
    """
    tree = ast.parse(_FINALIZE.read_text(encoding="utf-8"))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == "finalize_startup":
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            for target in sub.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr in ("mcp_workbench", "mcp_workbench_reaper")
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "runtime"
                ):
                    offenders.append(f"{node.name}:{sub.lineno}")

    assert offenders == [], (
        "these helpers assign runtime.mcp_workbench outside finalize_startup's "
        f"MCP block, which is how BF-753 happened: {offenders}"
    )


def test_every_mcp_branch_assigns_the_workbench() -> None:
    """The pre-declaration was redundant as well as harmful. If that stops being
    true, the attribute could go missing rather than merely be wrong.

    ``agentic_dispatch`` uses ``getattr(..., None)`` so a missing attribute
    degrades safely, but shutdown reads the reaper directly -- so this asserts
    the assignments still exist rather than relying on that.
    """
    src = _FINALIZE.read_text(encoding="utf-8")

    assert src.count("runtime.mcp_workbench = workbench") == 1
    assert src.count("runtime.mcp_workbench = None") == 2
