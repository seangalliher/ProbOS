"""AD-1179: the emitted LLM tool definitions are byte-identical to a frozen golden.

Deriving each schema vocabulary from a named constant is supposed to change
*nothing on the wire*. That claim is only worth anything if something checks it,
so this file freezes what every tool emits through the **real** producer --
``tool_registration_to_llm_definition``, the single function that builds the
LLM-API shape, with two callers (``agentic_dispatch`` and ``native_builder``) --
and compares byte for byte.

Three things this harness has to get right, or it proves less than it looks:

* **Real producer, not a reimplementation.** A local copy of the adapter would
  freeze what this test thinks the wire shape is, not what the model receives.
* **Pinned instance inputs.** Three tools read instance or environment state into
  their description/schema (``publish_finding``'s content cap, ``find_mcp_tool``'s
  connected-server list, ``run_python``'s config + importable-library probe). Left
  unpinned the fixture is flaky, and a flaky golden gets deleted rather than read.
* **Its own coverage set.** A capture that silently covers 18 of 23 tools and one
  that covers all 23 look identical from the outside, so the covered id set is
  asserted against an explicit expected set -- a tool dropping out of the harness
  fails the test instead of shrinking it.

The fixture was captured at ``adfb46d3`` -- **before** any AD-1179 source change --
so it is evidence about HEAD, not a snapshot of the change describing itself. To
regenerate after a *reviewed, intended* wire change, dump
``build_pinned_definitions()`` into the ``definitions`` key with
``json.dumps(..., ensure_ascii=False, indent=2)`` and update
``_captured_at_commit``. Regenerating to make a failure go away defeats the
entire point of the file.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tool_call import tool_registration_to_llm_definition
from probos.tools.protocol import ToolRegistration

_FIXTURE = Path(__file__).parent / "fixtures" / "ad1179_tool_definition_golden.json"

# Every tool the harness must cover. Asserted, not derived: a derived set would
# shrink silently when a tool stops being constructible.
EXPECTED_TOOL_IDS: frozenset[str] = frozenset({
    # probos.cognitive.swe_harness.tools
    "read_file",
    "list_files",
    "codebase_query",
    "codebase_find_callers",
    "codebase_find_tests",
    "codebase_get_imports",
    "codebase_read_source",
    "standing_orders_lookup",
    "system_self_model",
    "write_file",
    "edit_file",
    "run_command",
    # probos.tools
    "browser",
    "run_python",
    "delegate_task",
    "event_log_query",
    "oracle_query",
    "publish_finding",
    "recall_artifact",
    "search_capabilities",
    "use_skill",
    "work_item_status",
    # probos.cognitive.mcp_workbench
    "find_mcp_tool",
})

# ── pinned instance inputs ────────────────────────────────────────
# Each of these feeds a description or a schema. They are frozen here so the
# fixture is reproducible on any host, in any venv, on any platform.

PINNED_MAX_CONTENT_CHARS = 4000
PINNED_MCP_SERVERS: tuple[str, ...] = ()
PINNED_ARTIFACT_LIBRARIES = [("python-docx", "Word documents")]
PINNED_ANALYSIS_LIBRARIES = [("pandas", "tabular analysis")]
# ``max_memory_mb`` is pinned to 0 deliberately: the description only names the
# memory bound ``if memory_mb and sys.platform != "win32"``, so a non-zero value
# would make the golden PLATFORM-DEPENDENT -- permanently stale on the other OS,
# which is exactly how BF-683 reddened CI for three commits. Zero takes the same
# branch on every platform.
PINNED_EXECUTION_CONFIG = SimpleNamespace(
    timeout_seconds=30.0,
    max_output_bytes=65_536,
    max_memory_mb=0,
    fetch_broker_enabled=False,
)


def _pinned_runtime() -> Any:
    """A runtime stub carrying only what a schema/description property reads."""
    return SimpleNamespace(config=SimpleNamespace(execution=PINNED_EXECUTION_CONFIG))


def build_pinned_instances() -> list[Any]:
    """Every tool in :data:`EXPECTED_TOOL_IDS`, constructed with pinned inputs.

    Shared with ``test_ad1179_schema_vocabulary_guards`` so the guards' coverage
    set is the same set the golden freezes — a guard whose coverage is derived
    separately is a guard that can quietly cover less.
    """
    from probos.cognitive import mcp_workbench
    from probos.cognitive.swe_harness import tools as native
    from probos.config import BrowserToolConfig
    from probos.tools import code_execution_tool as cet
    from probos.tools.browser.tool import BrowserTool
    from probos.tools.delegate_task_tool import DelegateTaskTool
    from probos.tools.event_log_query_tool import EventLogQueryTool
    from probos.tools.oracle_query_tool import OracleQueryTool
    from probos.tools.publish_finding_tool import PublishFindingTool
    from probos.tools.recall_artifact_tool import RecallArtifactTool
    from probos.tools.search_capabilities_tool import SearchCapabilitiesTool
    from probos.tools.use_skill_tool import UseSkillTool
    from probos.tools.work_item_status_tool import WorkItemStatusTool

    runtime = _pinned_runtime()
    return [
        native.ReadFileTool(runtime),
        native.ListFilesTool(runtime),
        native.CodebaseQueryTool(runtime),
        native.CodebaseFindCallersTool(runtime),
        native.CodebaseFindTestsTool(runtime),
        native.CodebaseGetImportsTool(runtime),
        native.CodebaseReadSourceTool(runtime),
        native.StandingOrdersLookupTool(runtime),
        native.SystemSelfModelTool(runtime),
        native.WriteFileTool(runtime),
        native.EditFileTool(runtime),
        native.RunCommandTool(runtime),
        BrowserTool(config=BrowserToolConfig(enabled=True)),
        cet.CodeExecutionTool(runtime=runtime),
        DelegateTaskTool(
            runtime=runtime,
            llm_client=None,
            max_depth=1,
            max_iterations=5,
            tier="standard",
        ),
        EventLogQueryTool(reader=None, audit_sink=None),
        OracleQueryTool(oracle=None),
        PublishFindingTool(
            records_store=None,
            callsign_resolver=None,
            max_content_chars=PINNED_MAX_CONTENT_CHARS,
        ),
        RecallArtifactTool(runtime=runtime),
        SearchCapabilitiesTool(runtime=runtime),
        UseSkillTool(runtime=runtime),
        WorkItemStatusTool(runtime=runtime),
        mcp_workbench._FindMcpToolTool(  # noqa: SLF001 — pinned server list
            SimpleNamespace(enabled_server_names=PINNED_MCP_SERVERS)
        ),
    ]


def build_pinned_definitions() -> dict[str, str]:
    """Emit ``{tool_id: serialized definition}`` through the real wire producer.

    Serialization is order-preserving and separator-pinned on purpose: a key
    reorder is a wire change and must fail, not be normalised away.
    """
    from probos.tools import code_execution_tool as cet

    instances = build_pinned_instances()

    # Pin the two environment probes ``run_python``'s description derives from.
    # Restored in ``finally`` so a failure here cannot leak into a later test.
    real_artifact = cet._available_artifact_libraries  # noqa: SLF001
    real_analysis = cet._available_analysis_libraries  # noqa: SLF001
    cet._available_artifact_libraries = lambda: list(PINNED_ARTIFACT_LIBRARIES)  # noqa: SLF001
    cet._available_analysis_libraries = lambda: list(PINNED_ANALYSIS_LIBRARIES)  # noqa: SLF001
    try:
        out: dict[str, str] = {}
        for tool in instances:
            definition = tool_registration_to_llm_definition(
                ToolRegistration(tool=tool)
            )
            out[tool.tool_id] = json.dumps(
                definition, ensure_ascii=False, separators=(",", ":")
            )
        return out
    finally:
        cet._available_artifact_libraries = real_artifact  # noqa: SLF001
        cet._available_analysis_libraries = real_analysis  # noqa: SLF001


# BF-867 is the ONE permitted difference from the golden, named rather than
# tolerated. ``mouse_button`` was offered, advertised, and refused on every call
# because the handler read the DISPATCH key as its own sub-verb; the repair moves
# that sub-verb to ``press``, which the schema now declares. This is a single
# property insertion immediately after ``button``. Nothing else in the browser
# definition may move -- its description is derived from ``_AGENT_ACTIONS`` and
# is unaffected.
_BF867_PRESS_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": ["down", "up", "click"],
    "description": (
        "BF-706/BF-867: 'mouse_button' action — whether to press ('down'), "
        "release ('up'), or press-and-release ('click'). Defaults to click."
    ),
}


def _golden() -> dict[str, str]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return payload["definitions"]


def _with_bf867_press(serialized: str) -> str:
    """The golden browser definition plus exactly the ``press`` insertion."""
    definition = json.loads(serialized)
    props = definition["function"]["parameters"]["properties"]
    rebuilt: dict[str, Any] = {}
    for key, value in props.items():
        rebuilt[key] = value
        if key == "button":
            rebuilt["press"] = _BF867_PRESS_PROPERTY
    definition["function"]["parameters"]["properties"] = rebuilt
    return json.dumps(definition, ensure_ascii=False, separators=(",", ":"))


# ── the harness must not pass vacuously ───────────────────────────


def test_the_golden_fixture_is_populated() -> None:
    """A fixture capturing zero tools must fail loudly, not pass by agreeing
    with an equally empty capture."""
    golden = _golden()
    assert golden, "golden fixture is empty"
    assert set(golden) == EXPECTED_TOOL_IDS


def test_the_capture_covers_every_expected_tool() -> None:
    """The coverage-set assertion. A tool the harness can no longer construct
    fails here rather than quietly leaving the comparison below."""
    built = set(build_pinned_definitions())
    assert built == EXPECTED_TOOL_IDS, {
        "missing": sorted(EXPECTED_TOOL_IDS - built),
        "unexpected": sorted(built - EXPECTED_TOOL_IDS),
    }


def test_the_capture_is_deterministic() -> None:
    """Two captures in one process must agree, or the fixture is unusable as a
    drift signal regardless of what it holds."""
    assert build_pinned_definitions() == build_pinned_definitions()


# ── byte identity ─────────────────────────────────────────────────


@pytest.mark.parametrize("tool_id", sorted(EXPECTED_TOOL_IDS - {"browser"}))
def test_definition_is_byte_identical_to_the_golden(tool_id: str) -> None:
    assert build_pinned_definitions()[tool_id] == _golden()[tool_id]


def test_browser_gained_exactly_the_bf867_press_property() -> None:
    """The single named exception. Asserted as a *reconstruction* of the golden,
    so any other movement in the browser definition still fails."""
    assert build_pinned_definitions()["browser"] == _with_bf867_press(
        _golden()["browser"]
    )


def test_the_press_exception_is_not_a_blanket_tolerance() -> None:
    """Guard on the guard: the reconstruction above must actually differ from
    the raw golden, or the exception is silently doing nothing."""
    golden = _golden()["browser"]
    assert _with_bf867_press(golden) != golden
    assert '"press"' not in golden
