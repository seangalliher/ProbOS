"""Shared response text extraction from ProbOS dag_result dicts.

Extracted from api.py to be reusable across REST API, Discord, Slack, etc.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from probos.types import IntentResult

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
                node_start = len(parts)
                contributions: list[tuple[Any, str | None]] = []
                for r in intent_results:
                    contribution_start = len(parts)
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
                    contributions.append((
                        r, parts[-1] if len(parts) > contribution_start else None,
                    ))
                parts[node_start:] = _equivalent_node_parts(
                    contributions, parts[node_start:],
                )
            elif "output" in node_result:
                parts.append(str(node_result["output"]))
        elif isinstance(node_result, str) and node_result:
            parts.append(node_result)
    return "\n".join(parts)


_RESULT_FIELDS = frozenset({
    "intent_id", "agent_id", "success", "result", "error", "confidence",
    "timestamp", "metadata",
})


class _IneligibleNode(Exception):
    pass


class _EquivalenceBudget:
    def __init__(self) -> None:
        self.values = 0
        self.characters = 0
        self.active: set[int] = set()

    def _consume(self, value: Any, depth: int = 0) -> None:
        self.values += 1
        if depth > 32 or self.values > 4096:
            raise _IneligibleNode
        if type(value) is str:
            self.characters += len(value)
            if len(value) > 65536 or self.characters > 1048576:
                raise _IneligibleNode
        elif type(value) is int and value.bit_length() > 4096:
            raise _IneligibleNode

    def _freeze(self, value: Any, depth: int = 0) -> tuple[Any, ...]:
        self._consume(value, depth)
        value_type = type(value)
        if any(value_type is scalar_type for scalar_type in (type(None), bool, int, str)):
            return (value_type, value)
        if value_type is float:
            if not math.isfinite(value):
                raise _IneligibleNode
            return (float, value.hex())
        if not any(value_type is container_type for container_type in (list, tuple, dict)) or id(value) in self.active:
            raise _IneligibleNode
        self.active.add(id(value))
        try:
            if value_type is dict:
                entries = []
                for key, member in value.items():
                    if type(key) is not str:
                        raise _IneligibleNode
                    entries.append((
                        self._freeze(key, depth + 1),
                        self._freeze(member, depth + 1),
                    ))
                return (dict, tuple(entries))
            return (value_type, tuple(
                self._freeze(member, depth + 1) for member in value
            ))
        finally:
            self.active.remove(id(value))

    def _candidate(self, record: Any, text: str | None) -> tuple[Any, ...]:
        self._consume(record)
        if type(record) is IntentResult:
            fields = vars(record)
        elif type(record) is dict:
            fields = record
        else:
            raise _IneligibleNode
        if (type(fields) is not dict or len(fields) != 8
                or any(type(key) is not str for key in fields)
                or fields.keys() != _RESULT_FIELDS):
            raise _IneligibleNode
        for key in fields:
            self._freeze(key)
        if (type(text) is not str or not text
                or fields["success"] is not True or fields["error"] is not None
                or not any(type(fields["confidence"]) is number_type for number_type in (int, float))
                or type(fields["metadata"]) is not dict):
            raise _IneligibleNode
        for name in ("intent_id", "agent_id"):
            identity = fields[name]
            if type(identity) is not str:
                raise _IneligibleNode
            self._freeze(identity)
            if not identity.strip():
                raise _IneligibleNode
        self._freeze(fields["success"])
        self._freeze(fields["error"])
        confidence = self._freeze(fields["confidence"])
        timestamp = fields["timestamp"]
        self._consume(timestamp)
        if type(timestamp) is str:
            try:
                timestamp = datetime.fromisoformat(timestamp)
            except ValueError:
                raise _IneligibleNode from None
        if type(timestamp) is not datetime or type(timestamp.tzinfo) is not timezone:
            raise _IneligibleNode
        result = self._freeze(fields["result"])
        metadata = self._freeze(fields["metadata"])
        self._consume(text)
        return (fields["intent_id"], confidence, result, metadata, text)

    def select(self, contributions: list[tuple[Any, str | None]]) -> list[str]:
        groups: dict[tuple[Any, ...], list[tuple[int, str]]] = {}
        for index, (record, text) in enumerate(contributions):
            key = self._candidate(record, text)
            agent_id = record.agent_id if type(record) is IntentResult else record["agent_id"]
            groups.setdefault(key, []).append((index, agent_id))
        omitted: set[int] = set()
        for group in groups.values():
            if len({agent_id for _, agent_id in group}) == len(group):
                omitted.update(index for index, _ in group[1:])
        return [
            text for index, (_, text) in enumerate(contributions)
            if index not in omitted and text is not None
        ]


def _equivalent_node_parts(
    contributions: list[tuple[Any, str | None]], original: list[str],
) -> list[str]:
    try:
        return _EquivalenceBudget().select(contributions)
    except _IneligibleNode:
        return original
