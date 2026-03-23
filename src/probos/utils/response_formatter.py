"""Shared response text extraction from ProbOS dag_result dicts.

Extracted from api.py to be reusable across REST API, Discord, Slack, etc.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_response_text(dag_result: dict[str, Any] | None) -> str:
    """Extract a human-readable response string from a dag_result dict.

    Tries these sources in order:
    1. dag_result["response"] (direct LLM conversational reply)
    2. dag_result["reflection"] (LLM synthesis of execution results)
    3. dag_result["correction"]["changes"] (correction applied)
    4. dag_result["results"][node_id] (individual agent results)
    5. Fallback message
    """
    if not dag_result:
        return "(Processing failed)"

    response_text = dag_result.get("response", "") or ""

    # Extract reflection if present and no direct response
    reflection = dag_result.get("reflection", "")
    if reflection and not response_text:
        response_text = reflection

    # Extract correction info
    correction = dag_result.get("correction")
    if correction and not response_text:
        response_text = correction.get("changes", "Correction applied")

    # Extract from execution results if still no response text
    if not response_text:
        results_dict = dag_result.get("results")
        if results_dict and isinstance(results_dict, dict):
            response_text = _extract_from_results(results_dict)

    if not response_text:
        response_text = "(Empty response)"

    return response_text


def _extract_from_results(results_dict: dict[str, Any]) -> str:
    """Extract response text from individual node execution results."""
    parts: list[str] = []
    for _node_id, node_result in results_dict.items():
        if isinstance(node_result, dict):
            if "error" in node_result:
                parts.append(f"Error: {node_result['error']}")
                continue
            # Normal intent results — list of IntentResult dataclasses
            intent_results = node_result.get("results")
            if isinstance(intent_results, list):
                for r in intent_results:
                    if hasattr(r, "result") and r.result is not None:
                        val = r.result
                        if isinstance(val, dict) and "stdout" in val:
                            out = val["stdout"]
                            if val.get("stderr"):
                                out += f"\n{val['stderr']}"
                            parts.append(str(out))
                        else:
                            parts.append(str(val))
                    elif hasattr(r, "error") and r.error:
                        parts.append(f"Error: {r.error}")
                    elif isinstance(r, dict):
                        out = r.get("output") or r.get("result") or r.get("text")
                        if out:
                            parts.append(str(out))
            elif "output" in node_result:
                parts.append(str(node_result["output"]))
        elif isinstance(node_result, str) and node_result:
            parts.append(node_result)
    return "\n".join(parts)
