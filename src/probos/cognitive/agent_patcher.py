"""Agent patcher — applies corrections to self-mod'd agent code (AD-230)."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.code_validator import CodeValidator
    from probos.cognitive.correction_detector import CorrectionSignal
    from probos.cognitive.sandbox import SandboxRunner
    from probos.cognitive.self_mod import DesignedAgentRecord

logger = logging.getLogger(__name__)

_PATCH_PROMPT = """\
You are modifying a ProbOS agent's source code to apply a user correction.

== ORIGINAL SOURCE CODE ==
{source_code}

== USER'S ORIGINAL REQUEST ==
{original_text}

== CORRECTION ==
Type: {correction_type}
Corrected values: {corrected_values}
Explanation: {explanation}

== INSTRUCTIONS ==
Modify the source code to apply the correction. Return ONLY the complete
modified Python source code. Do not change the class structure, imports,
class name, or agent_type — only fix what the correction targets.

Return the complete Python file content with the fix applied.
Do not wrap in markdown fences. Do not include explanations.
"""


@dataclasses.dataclass
class PatchResult:
    """Result of an agent patching operation."""

    success: bool
    patched_source: str = ""
    agent_class: type | None = None
    handler: Any | None = None
    error: str | None = None
    original_source: str = ""
    changes_description: str = ""


@dataclasses.dataclass
class CorrectionResult:
    """Result of applying a correction to the runtime."""

    success: bool
    agent_type: str = ""
    strategy: str = ""  # "new_agent" or "skill"
    changes_description: str = ""
    retried: bool = False
    retry_result: dict | None = None


class AgentPatcher:
    """Patches self-mod'd agent source code based on correction signals."""

    def __init__(
        self,
        llm_client: Any,
        code_validator: CodeValidator,
        sandbox: SandboxRunner,
    ) -> None:
        self._llm_client = llm_client
        self._validator = code_validator
        self._sandbox = sandbox

    async def patch(
        self,
        record: DesignedAgentRecord,
        correction: CorrectionSignal,
        original_execution_text: str,
    ) -> PatchResult:
        """Generate a patched version of the agent source code.

        1. Send the original source + correction to the LLM
        2. Validate the patched code (same CodeValidator as self-mod)
        3. Test in sandbox (same SandboxRunner as self-mod)
        4. Return PatchResult with the new source + compiled class/handler
        """
        import json as _json

        original_source = record.source_code
        strategy = record.strategy

        # 1. Generate patched source via LLM
        prompt = _PATCH_PROMPT.format(
            source_code=original_source,
            original_text=original_execution_text,
            correction_type=correction.correction_type,
            corrected_values=_json.dumps(correction.corrected_values),
            explanation=correction.explanation,
        )

        try:
            from probos.types import LLMRequest

            patched_source = await self._llm_client.complete(
                LLMRequest(
                    prompt=prompt,
                    tier="standard",
                    max_tokens=4096,
                ),
            )
        except Exception as exc:
            logger.warning("AgentPatcher LLM call failed: %s", exc)
            return PatchResult(
                success=False,
                error=f"LLM call failed: {exc}",
                original_source=original_source,
            )

        patched_source = self._clean_source(patched_source)

        if not patched_source.strip():
            return PatchResult(
                success=False,
                error="LLM returned empty patched source",
                original_source=original_source,
            )

        # 2. Validate
        errors = self._validator.validate(patched_source)
        if errors:
            return PatchResult(
                success=False,
                error=f"Validation failed: {'; '.join(errors)}",
                original_source=original_source,
                patched_source=patched_source,
            )

        # 3. Sandbox test
        if strategy == "skill":
            return await self._patch_skill(
                record, patched_source, original_source, correction,
            )
        else:
            return await self._patch_agent(
                record, patched_source, original_source, correction,
            )

    # ------------------------------------------------------------------
    # Strategy-specific patching
    # ------------------------------------------------------------------

    async def _patch_agent(
        self,
        record: DesignedAgentRecord,
        patched_source: str,
        original_source: str,
        correction: CorrectionSignal,
    ) -> PatchResult:
        """Patch and sandbox-test an agent (strategy=new_agent)."""
        sandbox_result = await self._sandbox.test_agent(
            patched_source,
            record.intent_name,
        )

        if not sandbox_result.success:
            return PatchResult(
                success=False,
                error=f"Sandbox failed: {sandbox_result.error}",
                original_source=original_source,
                patched_source=patched_source,
            )

        return PatchResult(
            success=True,
            patched_source=patched_source,
            agent_class=sandbox_result.agent_class,
            original_source=original_source,
            changes_description=correction.explanation or "Agent patched",
        )

    async def _patch_skill(
        self,
        record: DesignedAgentRecord,
        patched_source: str,
        original_source: str,
        correction: CorrectionSignal,
    ) -> PatchResult:
        """Patch and compile a skill (strategy=skill)."""
        import importlib.util
        import tempfile
        import os
        import sys

        handler = None
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False,
            ) as f:
                f.write(patched_source)
                tmp_path = f.name

            mod_name = f"_patch_skill_{record.intent_name}"
            spec = importlib.util.spec_from_file_location(mod_name, tmp_path)
            if spec is None or spec.loader is None:
                return PatchResult(
                    success=False,
                    error="Could not create module spec for patched skill",
                    original_source=original_source,
                    patched_source=patched_source,
                )

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            fn_name = f"handle_{record.intent_name}"
            handler = getattr(module, fn_name, None)
            if handler is None:
                return PatchResult(
                    success=False,
                    error=f"Patched skill missing handler function '{fn_name}'",
                    original_source=original_source,
                    patched_source=patched_source,
                )
        except Exception as exc:
            return PatchResult(
                success=False,
                error=f"Skill compilation failed: {exc}",
                original_source=original_source,
                patched_source=patched_source,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            sys.modules.pop(f"_patch_skill_{record.intent_name}", None)

        return PatchResult(
            success=True,
            patched_source=patched_source,
            handler=handler,
            original_source=original_source,
            changes_description=correction.explanation or "Skill patched",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_source(source: str) -> str:
        """Strip markdown fences and think blocks from LLM output."""
        source = source.strip()
        # Remove <think>...</think>
        import re

        source = re.sub(r"<think>.*?</think>", "", source, flags=re.DOTALL).strip()
        # Remove markdown fences
        if source.startswith("```"):
            lines = source.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            source = "\n".join(lines).strip()
        return source
