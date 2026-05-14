"""AD-725: targeted sub-intent dispatch on the DM one-shot path.

Contract:
  * AT MOST ONE lookup per DM turn. No chains.
  * Read-only — no episodic store, trust update, Hebbian edge, consensus.
  * Hard timeout (config.dm_targeted_lookup.timeout_ms). Timeout -> None.
  * No intent_bus broadcast — direct method calls only.

Classifier is a Protocol so v1 regex can be swapped for embedding routing
later (AD-725-2 forward marker).
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from probos.config import DmTargetedLookupConfig

logger = logging.getLogger(__name__)

LookupType = Literal["oracle", "episodic", "codebase", "knowledge", "none"]


@dataclass(frozen=True)
class TargetedLookupResult:
    """Returned to the caller. ``None`` for the whole optional means "no
    lookup ran"; ``content=""`` with a non-none ``lookup_type`` means
    "lookup ran but returned empty" — caller treats both the same.
    """
    lookup_type: LookupType
    query: str
    content: str
    elapsed_ms: float


class SubintentClassifier(Protocol):
    """Pre-LLM intent-router. Returns at most one lookup_type + query."""

    def classify(self, message: str, *, agent_id: str) -> tuple[LookupType, str]:
        ...


# v1 regex ladder
_EPISODIC_PATTERNS = [
    re.compile(r"\b(last|previous|recent|earlier)\s+(time|conversation|chat|1:1|meeting)\b", re.I),
    re.compile(r"\bdid (we|you|i) (talk|discuss|mention)\b", re.I),
    re.compile(r"\bwhat (did|was) (we|you|i)\b.*\b(say|discuss|talk)\b", re.I),
    re.compile(r"\bremember when\b", re.I),
]

_CODEBASE_PATTERNS = [
    re.compile(r"\b(where|how)\s+(is|do|does|are)\b.*\b(implement|defined|located|coded)\b", re.I),
    re.compile(r"\b(grep|find|search)\s+(the\s+)?codebase\b", re.I),
    re.compile(r"\b(file|module|class|function)\s+(named|called)\b", re.I),
    re.compile(r"\bwhich (file|module|class)\b", re.I),
]

_KNOWLEDGE_PATTERNS = [
    re.compile(r"\b(ship'?s?\s+records?|knowledge\s+base|manual|standing\s+order)\b", re.I),
    re.compile(r"\baccording to\b.*\b(record|doc|manual|policy)\b", re.I),
]

_ORACLE_PATTERNS = [
    re.compile(r"\b(time|date|today|now|current)\b", re.I),
    re.compile(r"\bwhat (time|day|date)\b", re.I),
]


class RegexSubintentClassifier:
    """v1 ladder. Order: episodic -> codebase -> knowledge -> oracle -> none."""

    def classify(self, message: str, *, agent_id: str) -> tuple[LookupType, str]:
        if not message:
            return "none", ""
        for pats, name in (
            (_EPISODIC_PATTERNS, "episodic"),
            (_CODEBASE_PATTERNS, "codebase"),
            (_KNOWLEDGE_PATTERNS, "knowledge"),
            (_ORACLE_PATTERNS, "oracle"),
        ):
            for pat in pats:
                if pat.search(message):
                    return name, message  # type: ignore[return-value]
        return "none", ""


class LookupDispatcher:
    """Runs the classifier, dispatches at most one read-only lookup."""

    def __init__(
        self,
        *,
        runtime: Any,
        config: "DmTargetedLookupConfig",
        classifier: SubintentClassifier | None = None,
    ) -> None:
        self._runtime = runtime
        self._cfg = config
        self._classifier = classifier or RegexSubintentClassifier()

    async def maybe_lookup(
        self, message: str, *, agent_id: str,
    ) -> TargetedLookupResult | None:
        """Returns a result OR None (no-op). Tier-2 — never raises."""
        if not self._cfg.enabled:
            return None
        try:
            lookup_type, query = self._classifier.classify(message, agent_id=agent_id)
        except Exception:
            logger.warning("AD-725: classifier raised; degrading", exc_info=True)
            return None
        if lookup_type == "none":
            return None
        if not self._is_lookup_enabled(lookup_type):
            return None
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            content = await asyncio.wait_for(
                self._dispatch(lookup_type, query, agent_id),
                timeout=self._cfg.timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            logger.info(
                "AD-725: lookup %s timed out for agent=%s after %d ms",
                lookup_type, agent_id, self._cfg.timeout_ms,
            )
            return None
        except Exception:
            logger.warning(
                "AD-725: lookup %s raised for agent=%s; degrading",
                lookup_type, agent_id, exc_info=True,
            )
            return None
        elapsed_ms = (loop.time() - t0) * 1000.0
        if not isinstance(content, str):
            logger.warning(
                "AD-725: lookup %s returned non-str (%s) — dropping",
                lookup_type, type(content).__name__,
            )
            return None
        truncated = content[: self._cfg.max_lookup_chars]
        return TargetedLookupResult(
            lookup_type=lookup_type,
            query=query[:500],
            content=truncated,
            elapsed_ms=elapsed_ms,
        )

    def _is_lookup_enabled(self, lookup_type: LookupType) -> bool:
        return {
            "oracle": self._cfg.enable_oracle,
            "episodic": self._cfg.enable_episodic,
            "codebase": self._cfg.enable_codebase,
            "knowledge": self._cfg.enable_knowledge,
        }.get(lookup_type, False)

    async def _dispatch(
        self, lookup_type: LookupType, query: str, agent_id: str,
    ) -> str:
        """Dispatch to the appropriate read-only surface. NO side effects.

        Defensive: missing methods log INFO and return "" — the AD-725
        contract is "degrade silently to no recall block."
        """
        if lookup_type == "oracle":
            oracle = getattr(self._runtime, "oracle", None)
            if oracle is None or not hasattr(oracle, "query"):
                logger.info(
                    "AD-725: oracle lookup unavailable on runtime (no runtime.oracle.query)",
                )
                return ""
            res = oracle.query(query, agent_id=agent_id)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        if lookup_type == "episodic":
            em = getattr(self._runtime, "episodic_memory", None)
            if em is None or not hasattr(em, "recall_for_agent"):
                logger.info(
                    "AD-725: episodic lookup unavailable (no runtime.episodic_memory.recall_for_agent)",
                )
                return ""
            res = em.recall_for_agent(agent_id, query, k=3)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        if lookup_type == "codebase":
            ci = getattr(self._runtime, "codebase_index", None)
            if ci is None or not hasattr(ci, "query"):
                logger.info(
                    "AD-725: codebase lookup unavailable (no runtime.codebase_index.query)",
                )
                return ""
            res = ci.query(query)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        if lookup_type == "knowledge":
            rs = getattr(self._runtime, "records_store", None)
            if rs is None or not hasattr(rs, "search"):
                logger.info(
                    "AD-725: knowledge lookup unavailable (no runtime.records_store.search)",
                )
                return ""
            res = rs.search(query)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        return ""

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(
                        " ".join(f"{k}={v}" for k, v in item.items())
                    )
                else:
                    parts.append(repr(item))
            return "\n".join(parts)
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        return repr(value)
