"""BF-901 (#1575): one owner for what a model call is charged, measured or estimated.

BF-680 built the estimator inside the agentic loop for the paths that loop runs. This module owns it now,
so the one-shot paths (the journal rows ``cognitive_agent`` and the sub-task chain write, BF-901 S2) charge
with the same estimate instead of a second one. ``_completion_is_non_empty``, ``_estimate_call_tokens`` and
AD-1142's ``_estimate_context_tokens`` were moved here from ``swe_harness/agentic_loop.py`` with their bodies
unchanged; the loop imports them by name and calls them unqualified, so a monkeypatch on the loop module
still replaces what the loop calls.

``charge_completion`` adds what the loop does not read: whether the provider's reply carried its usage counts
(``LLMResponse.usage_reported``, set by ``OpenAICompatibleClient._call_openai`` and ``_call_ollama_native``).
The loop never reads that flag, which keeps its arithmetic and labels as BF-680 left them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from probos.cognitive.swe_harness.tool_call import TextBlock, ToolUseBlock
from probos.crew_execution_usage import TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MEASURED

#: ``TokenCharge.source`` when there is nothing to account for: an error, or neither output nor reported
#: usage. Never counted as measured.
TOKEN_SOURCE_NONE = ""


def _estimate_context_tokens(messages: list[dict]) -> int:
    """AD-1142 / DD-3: approximate the tokens currently OCCUPYING the context.

    Same ``len(text) // 4`` approximation as
    ``session_compactor.estimate_tokens`` — AD-547b still owns the exact
    tokenizer and this AD does NOT discharge its forcing function (the first
    compaction false-trip whose len/4 estimate diverges >25% from real model
    context counting) — but this one ALSO counts the serialised ``tool_calls``
    payload an AD-1146 assistant turn carries. ``estimate_messages_tokens``
    reads ``content`` only, which undercounts a structured history by the whole
    tool-call array.

    Deliberately not imported from ``session_compactor``: the loop has no
    dependency on that module (the compactor arrives injected as ``Any``), and
    DD-3 keeps it that way. BF-901 moved this function out of the loop module
    into ``probos.cognitive.token_accounting``, its one owner, so the one-shot
    journal paths charge with the same estimate; DD-3's reason still holds,
    because this module does not import the compactor either.

    Non-dict entries are skipped rather than raising. The compactor is an
    injected ``Any``, so what comes back from it is a module boundary, and this
    function is called from the loop's hot path OUTSIDE the ``try`` that
    absorbs compaction failures — a raise here would escape ``run()``, which
    promises never to raise.
    """
    total = 0
    for message in messages:
        if type(message) is not dict:
            continue
        text = str(message.get("content", "") or "")
        tool_calls = message.get("tool_calls")
        if tool_calls:
            try:
                text += json.dumps(
                    tool_calls, separators=(",", ":"), default=str
                )
            except Exception:
                text += str(tool_calls)
        total += max(1, len(text) // 4)
    return total


def _completion_is_non_empty(response: Any) -> bool:
    """BF-680: did this completion actually produce output?

    The agentic loop reads no "usage was present" flag (BF-901's
    ``LLMResponse.usage_reported`` is read by :func:`charge_completion` only),
    so for the loop ``tokens_used`` collapses BOTH "the provider reported 0"
    and "the provider reported nothing" onto the same ``0``. The two are
    therefore indistinguishable at this boundary, and the disambiguation rule
    is stated HERE rather than left to fall out of the arithmetic:

        **A zero that accompanies a completion which produced output is an
        ABSENT measurement, not a measurement of zero.**

    No provider emits text or a tool call for free, so the pairing is only
    reachable when the field was never populated. The live Copilot proxy at
    ``127.0.0.1:8080`` is exactly this case: HTTP 200, real content,
    ``usage.total_tokens == 0``.

    "Produced output" deliberately includes a tool-call-only turn. Those carry
    no text, but they are the turns the agentic loop exists for, so scoring
    them as empty would leave the budget inert on precisely the path it is
    meant to bound.

    A completion with neither text nor tool calls is left alone: its reported
    zero is plausible, and substituting an estimate there would invent spend
    for a turn that produced nothing.
    """
    blocks = list(response.content_blocks or [])
    if any(isinstance(b, ToolUseBlock) for b in blocks):
        return True
    text = "".join(b.text for b in blocks if isinstance(b, TextBlock))
    return bool((text or response.content or "").strip())


def _estimate_call_tokens(outbound: list[dict], response: Any) -> int:
    """BF-680: client-side stand-in for one call's ``prompt + completion`` usage.

    Reuses the AD-1142 estimator on both halves rather than taking a tokenizer
    dependency: ``outbound`` is the history the request was assembled from, and
    the completion is measured through the same pseudo-message shape so a
    tool-calling turn's serialised arguments are counted too.

    Summing this per iteration mirrors how a provider bills an uncached
    multi-turn loop — every turn re-sends the whole history — so the running
    total stays structurally faithful even though each term is approximate.

    Its inaccuracy (``len(text) // 4``; AD-547b still owns the exact tokenizer,
    and this does NOT discharge its forcing function) is acceptable for a
    budget STOP, which only has to fire in the right order of magnitude. It is
    NOT acceptable as billing, which is why every substitution is labelled.
    """
    blocks = list(response.content_blocks or [])
    text = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))
    completion = {
        "content": text or response.content or "",
        # Plain dicts rather than the AD-1146 wire shape: this is a size
        # estimate, not a message, and ``_estimate_context_tokens`` already
        # serialises ``tool_calls`` defensively.
        "tool_calls": [
            {
                "id": b.tool_call.id,
                "name": b.tool_call.name,
                "arguments": b.tool_call.arguments,
            }
            for b in blocks
            if isinstance(b, ToolUseBlock)
        ],
    }
    return _estimate_context_tokens(outbound) + _estimate_context_tokens(
        [completion]
    )


@dataclass(frozen=True)
class TokenCharge:
    """BF-901: what one model call is charged, and where the counts came from."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    source: str = TOKEN_SOURCE_NONE  # "measured" | "estimated" | "" (nothing to account for)


def _count(value: object) -> int:
    """A reported count as an ``int``; anything else (a test double's mock, a negative) reads as 0."""
    if type(value) is int and value >= 0:
        return value
    return 0


def charge_completion(outbound: list[dict], response: Any) -> TokenCharge:
    """BF-901: charge one completion, measured when the provider measured it, else estimated.

    ``outbound`` is the history the request was built from (:func:`request_messages` for an ``LLMRequest``).
    The rule, in order:

    * an error response (``error`` a non-empty string) carries no reply: nothing to account for;
    * ``usage_reported`` not ``False`` (``True``, or ``None`` = not stated) and not BF-680's "zero beside
      output": **measured**, the counts as the provider reported them, each read through ``_count`` (a
      count that is not a non-negative exact ``int``, such as ``-7`` or ``5.5``, is charged as 0);
    * no output (and usage absent): nothing to account for (``source ""``, never read as measured);
    * otherwise **estimated**: the prompt is ``_estimate_context_tokens(outbound)``, the total
      ``_estimate_call_tokens(outbound, response)``, the completion their difference.

    The response is read with ``getattr`` and exact types because callers pass whatever their client returns,
    test doubles included; one without ``content_blocks`` is read as having produced no output, so its
    reported counts stand.
    """
    error = getattr(response, "error", None)
    if type(error) is str and error:
        return TokenCharge()
    flag = getattr(response, "usage_reported", None)
    reported = flag if type(flag) is bool else None
    total = _count(getattr(response, "tokens_used", 0))
    try:
        produced = _completion_is_non_empty(response)
    except AttributeError:
        produced = False
    if reported is not False and not (total == 0 and produced):
        return TokenCharge(
            prompt_tokens=_count(getattr(response, "prompt_tokens", 0)),
            completion_tokens=_count(getattr(response, "completion_tokens", 0)),
            total_tokens=total,
            source=TOKEN_SOURCE_MEASURED,
        )
    if not produced:
        return TokenCharge()
    prompt = _estimate_context_tokens(outbound)
    estimate = _estimate_call_tokens(outbound, response)
    return TokenCharge(
        prompt_tokens=prompt,
        completion_tokens=estimate - prompt,
        total_tokens=estimate,
        source=TOKEN_SOURCE_ESTIMATED,
    )


def request_messages(request: Any) -> list[dict]:
    """BF-901: the outbound history of one ``LLMRequest``, in the shape the estimator reads.

    Mirrors how ``OpenAICompatibleClient._call_openai`` composes the messages it posts: ``request.messages``
    when set, with the system prompt first unless a system message leads; otherwise system, then user. The
    attachment resolution and the per-tier system suffix it adds are not counted: this feeds an estimate.
    """
    if request.messages is not None:
        messages = list(request.messages)
        first = messages[0] if messages else None
        if request.system_prompt and not (type(first) is dict and first.get("role") == "system"):
            messages.insert(0, {"role": "system", "content": request.system_prompt})
        return messages
    composed: list[dict] = []
    if request.system_prompt:
        composed.append({"role": "system", "content": request.system_prompt})
    composed.append({"role": "user", "content": request.prompt})
    return composed


def answered_model_name(response: Any) -> str:
    """BF-901: the model that answered (AD-1327's ``answered_model``), else the id sent, else ``"unknown"``.

    Never empty, so a journal row names a model or says it cannot.
    """
    for name in (getattr(response, "answered_model", None), getattr(response, "model", None)):
        if type(name) is str and name.strip():
            return name
    return "unknown"
