"""Correction detector — distinguishes user corrections from new requests (AD-229)."""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import TaskDAG

logger = logging.getLogger(__name__)

_DETECTION_PROMPT = """\
You are analysing a user message in the context of a prior ProbOS execution.

== PRIOR EXECUTION ==
User request: {last_text}
Executed tasks:
{dag_summary}
Execution success: {success}

== NEW USER MESSAGE ==
{user_text}

== TASK ==
Is the new user message a **correction / fix** targeting the prior execution,
or an **independent new request**?

Examples of corrections:
- "use http not https" → correction (parameter_fix)
- "the URL should be http://..." → correction (url_fix)
- "that's wrong, the port should be 8080" → correction (parameter_fix)
- "no, use this URL instead" → correction (url_fix)
- "use that URL in the future" → correction (parameter_fix, referencing prior success)

Examples of new requests (NOT corrections):
- "now read the file at /tmp/foo" → new request
- "what time is it" → new request
- "count the words in README.md" → new request

Respond with a JSON object (no markdown fences):
{{
  "is_correction": true/false,
  "confidence": 0.0-1.0,
  "correction_type": "parameter_fix" | "url_fix" | "approach_fix" | null,
  "target_intent": "<intent name from prior execution>" | null,
  "target_agent_type": "<agent_type to patch>" | null,
  "corrected_values": {{"key": "value"}} | null,
  "explanation": "<short explanation>" | null
}}
"""


@dataclasses.dataclass
class CorrectionSignal:
    """A detected correction targeting a recent execution."""

    correction_type: str  # "parameter_fix", "url_fix", "approach_fix"
    target_intent: str  # Intent in the DAG to fix
    target_agent_type: str  # Agent type to patch
    corrected_values: dict[str, str]  # What should change
    explanation: str  # Human-readable explanation
    confidence: float  # 0.0–1.0


class CorrectionDetector:
    """Detects whether user input is a correction targeting a recent execution."""

    def __init__(self, llm_client: Any) -> None:
        self._llm_client = llm_client

    async def detect(
        self,
        user_text: str,
        last_execution_text: str | None,
        last_execution_dag: Any | None,
        last_execution_success: bool,
    ) -> CorrectionSignal | None:
        """Analyse user input for correction intent.

        Returns CorrectionSignal if it is a correction, None otherwise.
        Only triggers when there is a recent execution to correct.
        """
        if not last_execution_text or last_execution_dag is None:
            return None

        dag_summary = self._format_dag(last_execution_dag)
        if not dag_summary:
            return None

        prompt = _DETECTION_PROMPT.format(
            last_text=last_execution_text,
            dag_summary=dag_summary,
            success="yes" if last_execution_success else "no",
            user_text=user_text,
        )

        try:
            from probos.types import LLMRequest

            resp = await self._llm_client.complete(
                LLMRequest(prompt=prompt, tier="fast", max_tokens=512),
            )
            return self._parse_response(resp)
        except Exception:
            logger.debug("CorrectionDetector LLM call failed", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_dag(self, dag: Any) -> str:
        """Build a human-readable summary of the executed DAG."""
        nodes = getattr(dag, "nodes", None)
        if nodes is None:
            # dag might be a dict (from _last_execution)
            if isinstance(dag, dict):
                inner = dag.get("dag")
                if inner is not None:
                    nodes = getattr(inner, "nodes", None)
            if nodes is None:
                return ""

        lines: list[str] = []
        for node in nodes:
            intent = getattr(node, "intent", "?")
            status = getattr(node, "status", "?")
            result = getattr(node, "result", None)

            agent_type = ""
            if isinstance(result, dict):
                agent_type = result.get("agent_id", result.get("agent_type", ""))
            elif result is not None and hasattr(result, "agent_id"):
                agent_type = getattr(result, "agent_id", "")

            params = getattr(node, "params", {})
            lines.append(
                f"- intent={intent}  agent={agent_type}  status={status}  params={params}"
            )
        return "\n".join(lines) if lines else ""

    def _parse_response(self, text: str) -> CorrectionSignal | None:
        """Parse structured JSON from LLM response into CorrectionSignal."""
        text = text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.debug("CorrectionDetector: malformed LLM response")
            return None

        if not isinstance(data, dict):
            return None

        if not data.get("is_correction", False):
            return None

        confidence = float(data.get("confidence", 0.0))
        if confidence < 0.5:
            return None

        correction_type = data.get("correction_type") or "parameter_fix"
        target_intent = data.get("target_intent") or ""
        target_agent_type = data.get("target_agent_type") or target_intent
        corrected_values = data.get("corrected_values") or {}
        explanation = data.get("explanation") or ""

        return CorrectionSignal(
            correction_type=correction_type,
            target_intent=target_intent,
            target_agent_type=target_agent_type,
            corrected_values=corrected_values,
            explanation=explanation,
            confidence=confidence,
        )
