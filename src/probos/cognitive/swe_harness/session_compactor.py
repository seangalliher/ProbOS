"""AD-547 v1: Session compaction for long agentic-loop conversations.

v1 ships a char-count token approximation (``len(text) // 4``). Exact
tokenizer is deferred to AD-547b — forcing function: first compaction
false-trip where the len/4 estimate diverges >25% from actual model
context counting.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """v1 char-count approximation. AD-547b ships exact tokenizer."""
    if not text:
        return 1
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Sum estimated tokens across message contents."""
    return sum(estimate_tokens(str(m.get("content", ""))) for m in messages)


class SessionCompactor:
    """AD-547: Compact older messages via fast-tier LLM summarisation."""

    SYSTEM_PROMPT = (
        "Summarise the following tool interactions concisely. Preserve: "
        "(1) key findings the LLM produced, (2) decisions made, "
        "(3) files changed and the rationale, (4) any errors that informed "
        "later choices. Output a single paragraph, no preamble."
    )

    async def compact(
        self,
        messages: list[dict],
        *,
        preserve_count: int = 5,
        budget_tokens: int | None = None,
        fast_llm: "BaseLLMClient",
    ) -> list[dict]:
        """Compact messages while preserving system prompt + last preserve_count exchanges.

        Args:
            messages: Full message list including system prompt at index 0.
            preserve_count: Number of trailing assistant+tool exchanges to keep verbatim.
            budget_tokens: Token budget the result must fit within. Re-compaction
                is triggered if first pass result still exceeds budget.
            fast_llm: LLMClient using fast-tier (Sonnet via Copilot proxy).

        Returns:
            Compacted message list. System prompt + summary + preserved tail.
        """
        if len(messages) <= preserve_count + 2:
            return messages

        system_msg = (
            messages[0]
            if messages and messages[0].get("role") == "system"
            else None
        )
        original_user = None
        for m in messages[1:]:
            if m.get("role") == "user":
                original_user = m
                break

        tail = messages[-preserve_count:] if preserve_count > 0 else []
        preserved_ids: set[int] = set()
        if system_msg is not None:
            preserved_ids.add(id(system_msg))
        if original_user is not None:
            preserved_ids.add(id(original_user))
        preserved_ids.update(id(m) for m in tail)

        older = [m for m in messages if id(m) not in preserved_ids]
        if not older:
            return messages

        older_text = "\n\n".join(
            f"[{m.get('role','?')}] {m.get('content','')}" for m in older
        )

        try:
            req = LLMRequest(
                prompt=older_text,
                system_prompt=self.SYSTEM_PROMPT,
                tier="fast",
                max_tokens=1024,
            )
            response = await fast_llm.complete(req)
            summary = response.content or "[compaction summary unavailable]"
        except Exception:
            logger.warning(
                "AD-547: Compaction LLM call failed; returning original messages",
                exc_info=True,
            )
            return messages

        compacted: list[dict] = []
        if system_msg is not None:
            compacted.append(system_msg)
        if original_user is not None and (
            system_msg is None or id(original_user) != id(system_msg)
        ):
            compacted.append(original_user)
        compacted.append(
            {
                "role": "user",
                "content": f"[CONTEXT SUMMARY — earlier exchanges]\n{summary}",
            }
        )
        compacted.extend(tail)

        if budget_tokens is not None:
            current = estimate_messages_tokens(compacted)
            if current > budget_tokens and len(compacted) > 3:
                logger.info(
                    "AD-547: First pass still over budget (%d > %d); re-compacting",
                    current,
                    budget_tokens,
                )
                if len(compacted) > 4:
                    compacted = [compacted[0], compacted[2]] + compacted[-2:]
        return compacted
