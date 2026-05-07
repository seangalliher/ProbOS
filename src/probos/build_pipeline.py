"""BuildPipeline — Ship's Computer service for build execution (AD-521).

Extracted from cognitive/builder.py as part of AD-521 SWE/Build Pipeline
Separation Model A. The pipeline is infrastructure (no agent identity);
the SoftwareEngineerAgent crew agent (formerly BuilderAgent) delegates
to this service for build execution.

Architecture (AD-521):

    Architect → SoftwareEngineerAgent (Scotty, crew tier)
                    ↓
                BuildPipeline (this module — infrastructure)
                    ↓
                { native execute_approved_build | visiting builder }

The pipeline is composable, runtime-injected, and shareable across
multiple SWE crew members for parallel workstreams.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from probos.cognitive.builder import BuildResult, BuildSpec
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.runtime import ProbOSRuntime


logger = logging.getLogger(__name__)


class BuildPipeline:
    """Ship's Computer service for executing approved build specifications.

    The pipeline owns no agent identity. It accepts file changes from a
    SWE crew agent (or any caller), writes them to disk under a git
    branch, runs targeted + full pytest gates with a fix-loop, and
    returns a structured BuildResult.

    Constructor injection (per AD-521 / copilot-instructions Engineering
    Principles): the runtime handle is passed at construction time.
    Optional pre-flight, llm_client, escalation_hook, and emit_event
    are accessed through the runtime via `getattr` defensive lookups
    (the runtime attributes are populated by `startup/finalize.py` and
    other startup modules; ordering between `BuildPipeline.__init__`
    and those startup hooks is therefore irrelevant).
    """

    def __init__(self, runtime: ProbOSRuntime | None = None) -> None:
        self._runtime = runtime

    async def execute_approved_build(
        self,
        file_changes: list[dict[str, Any]],
        spec: BuildSpec,
        work_dir: str,
        run_tests: bool = True,
        max_fix_attempts: int = 2,
        llm_client: BaseLLMClient | None = None,
        escalation_hook: Callable | None = None,
        builder_source: str = "native",
        specialty: str = "general",
    ) -> BuildResult:
        """Execute an approved build (write files, run tests, create git branch).

        Delegates to the existing module-level coroutine in
        `cognitive/builder.py` for now; v1 of AD-521 is structural
        separation only. The behaviour, prompts, parsing, fix loop, and
        pre-flight gates are unchanged. Future ADs (AD-543–549, the SWE
        Tool Harness wave) will migrate the implementation into this
        class as instance methods.
        """
        # Local import avoids circular dependency at module load time:
        # cognitive/builder.py imports nothing from this module, but the
        # shim direction means we want to defer the import.
        from probos.cognitive.builder import (
            execute_approved_build as _legacy_execute_approved_build,
        )

        logger.info(
            "AD-476: BuildPipeline routing build '%s' as specialty=%s "
            "(builder_source=%s)",
            getattr(spec, "title", "<unknown>"), specialty, builder_source,
        )
        return await _legacy_execute_approved_build(
            file_changes=file_changes,
            spec=spec,
            work_dir=work_dir,
            run_tests=run_tests,
            max_fix_attempts=max_fix_attempts,
            llm_client=llm_client,
            escalation_hook=escalation_hook,
            builder_source=builder_source,
            runtime=self._runtime,
            specialty=specialty,
        )

    @staticmethod
    def parse_file_blocks(text: str) -> list[dict[str, Any]]:
        """Parse LLM-emitted ===FILE:===/===MODIFY:=== blocks into change dicts.

        Re-exposes the existing parser as a stable public method on the
        pipeline service. Existing callers using the
        `BuilderAgent._parse_file_blocks(...)` static method continue to
        work; new callers should prefer this method.
        """
        from probos.cognitive.builder import BuilderAgent

        return BuilderAgent._parse_file_blocks(text)
