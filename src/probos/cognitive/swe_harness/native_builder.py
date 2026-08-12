"""AD-546 v1: NativeBuilderHarness wrapping AgenticLoop for build execution."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from probos.cognitive.swe_harness.agentic_loop import (
    PARALLEL_TOOL_CALLS_DEFAULT,
    TOOL_RESULT_HEAD_CHARS,
    TOOL_RESULT_TAIL_CHARS,
    AgenticLoop,
    AgenticResult,
)
from probos.cognitive.swe_harness.tool_call import (
    dedupe_llm_definitions,
    tool_registration_to_llm_definition,
)

if TYPE_CHECKING:
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.runtime import ProbOSRuntime
    from probos.tools.executor import ToolExecutor
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_HARNESS_TOOL_IDS_BUILD = [
    "read_file",
    "edit_file",
    "write_file",
    "list_files",
    "run_command",
    "codebase_query",
    "codebase_find_callers",
    "codebase_find_tests",
    "codebase_read_source",
]


class NativeBuilderHarness:
    """Multi-turn agentic builder. Wraps AgenticLoop with build-specific config."""

    def __init__(
        self,
        *,
        runtime: "ProbOSRuntime",
        llm_client: "BaseLLMClient",
        tool_executor: "ToolExecutor",
        tool_registry: "ToolRegistry",
        max_iterations: int = 25,
        max_fix_iterations: int = 5,
        token_budget: int | None = None,
        compactor: Any | None = None,
        compaction_threshold: int | None = None,
        structured_tool_messages: bool = False,
        tool_result_max_chars: int = 0,
        tool_result_head_chars: int = TOOL_RESULT_HEAD_CHARS,
        tool_result_tail_chars: int = TOOL_RESULT_TAIL_CHARS,
        parallel_tool_calls_enabled: bool = False,
        max_parallel_tool_calls: int = PARALLEL_TOOL_CALLS_DEFAULT,
    ) -> None:
        self._runtime = runtime
        self._llm = llm_client
        self._executor = tool_executor
        self._registry = tool_registry
        self._max_iter = max_iterations
        self._max_fix_iter = max_fix_iterations
        self._budget = token_budget
        self._compactor = compactor
        self._compaction_threshold = compaction_threshold
        # AD-1146: forwarded to AgenticLoop. Default-OFF keeps the AD-545
        # flattened prompt shape byte-identical.
        self._structured_tool_messages = structured_tool_messages
        # AD-1148: forwarded to AgenticLoop. 0 = unbounded (default-OFF).
        self._tool_result_max_chars = tool_result_max_chars
        self._tool_result_head_chars = tool_result_head_chars
        self._tool_result_tail_chars = tool_result_tail_chars
        # AD-1147: forwarded to AgenticLoop. Default-OFF keeps every build tool
        # sequential; note that none of _HARNESS_TOOL_IDS_BUILD is on the
        # read-only allowlist, so the build path stays sequential either way.
        self._parallel_tool_calls_enabled = parallel_tool_calls_enabled
        self._max_parallel_tool_calls = max_parallel_tool_calls

    async def run_build(
        self,
        spec: "BuildSpec",
        work_dir: str,
        *,
        agent_id: str = "swe",
        department: str = "engineering",
        rank: str = "lieutenant",
    ) -> dict[str, Any]:
        """Run an agentic build. Returns a dict with ``file_changes`` + metadata."""
        tools_definitions = self._select_build_tools()
        system_prompt = self._compose_system_prompt(spec)
        user_message = self._format_build_message(spec, work_dir)

        loop = AgenticLoop(
            llm_client=self._llm,
            tool_executor=self._executor,
            max_iterations=self._max_iter,
            token_budget=self._budget,
            event_emit_fn=getattr(self._runtime, "emit_event", None),
            compactor=self._compactor,
            compaction_threshold=self._compaction_threshold,
            structured_tool_messages=self._structured_tool_messages,
            tool_result_max_chars=self._tool_result_max_chars,
            tool_result_head_chars=self._tool_result_head_chars,
            tool_result_tail_chars=self._tool_result_tail_chars,
            parallel_tool_calls_enabled=self._parallel_tool_calls_enabled,
            max_parallel_tool_calls=self._max_parallel_tool_calls,
        )

        agentic_result: AgenticResult = await loop.run(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools_definitions,
            context={
                "agent_id": agent_id,
                "department": department,
                "rank": rank,
            },
        )

        from probos.build_pipeline import BuildPipeline

        file_changes = BuildPipeline.parse_file_blocks(agentic_result.final_text)

        return {
            "file_changes": file_changes,
            "llm_output": agentic_result.final_text,
            "builder_source": "native_harness",
            "metadata": {
                "builder_type": "native_harness",
                "iterations": agentic_result.iterations,
                "tools_used": [tc.name for tc in agentic_result.tool_calls],
                "compactions": 0,
                "stopped_reason": agentic_result.stopped_reason,
                "total_tokens": agentic_result.total_tokens,
                # BF-680: qualifies the figure directly above it. Reported as
                # ``measured`` / ``estimated`` / ``mixed`` — the loop charges a
                # client-side estimate when the provider populates no ``usage``,
                # and this telemetry must not present that as a measurement.
                "token_source": agentic_result.token_source,
            },
        }

    def _select_build_tools(self) -> list[dict]:
        """Select code-generation-relevant tools and convert to LLM definitions."""
        defs: list[dict] = []
        for tool_id in _HARNESS_TOOL_IDS_BUILD:
            reg = self._registry.get(tool_id) if hasattr(self._registry, "get") else None
            if reg is None:
                logger.debug(
                    "AD-546: Build harness tool '%s' not registered; skipping",
                    tool_id,
                )
                continue
            defs.append(tool_registration_to_llm_definition(reg))
        # BF-757: these ids are a fixed in-repo constant so they cannot collide
        # today. The guard is here so that stays true if the list ever becomes
        # dynamic -- a duplicate name fails the provider request entirely.
        return dedupe_llm_definitions(defs, agent_id="builder")

    def _compose_system_prompt(self, spec: "BuildSpec") -> str:
        """Compose Standing Orders + BuildSpec constraints + tool-usage instructions."""
        base = ""
        try:
            from probos.cognitive.standing_orders import compose_instructions

            base = compose_instructions(
                "builder",
                "",
                department="engineering",
            ) or ""
        except Exception:
            logger.debug(
                "AD-546: compose_instructions unavailable; using inline base prompt",
                exc_info=True,
            )
            base = ""
        constraints = "\n".join(f"- {c}" for c in (spec.constraints or []))
        return (
            f"{base}\n\n"
            "You are the SWE crew agent executing a build via the native agentic harness.\n"
            "Use the provided tools to inspect the codebase before writing. "
            "Use `read_file` and `codebase_*` tools to understand existing code. "
            "Use `edit_file` for surgical changes within existing files; use `write_file` "
            "for new files. Use `run_command pytest <path>` to validate before claiming "
            "completion. End your final response with the final file content as either "
            "===FILE: path=== blocks (new files) or ===MODIFY: path=== blocks "
            "(with ===SEARCH===/===REPLACE===/===END REPLACE=== triples for changes).\n\n"
            f"Build constraints:\n{constraints or '- (none specified)'}\n"
        )

    def _format_build_message(self, spec: "BuildSpec", work_dir: str) -> str:
        return (
            f"# Build Spec: {spec.title}\n"
            f"AD Number: AD-{spec.ad_number}\n\n"
            f"## Description\n{spec.description}\n\n"
            f"## Target Files\n"
            + "\n".join(f"- {f}" for f in (spec.target_files or []))
            + "\n\n"
            f"## Reference Files\n"
            + "\n".join(f"- {f}" for f in (spec.reference_files or []))
            + "\n\n"
            f"## Test Files\n"
            + "\n".join(f"- {f}" for f in (spec.test_files or []))
            + "\n\n"
            f"Working directory: {work_dir}\n"
        )
