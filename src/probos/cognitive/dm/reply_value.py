"""AD-1248: the cognitive-layer PRODUCER for :mod:`probos.dm_reply`.

BF-801 moved the value itself to foundation ``probos/dm_reply.py`` -- it is a
contract about ``IntentResult`` and two lower layers need it. What stays here
is the half that is genuinely cognitive-layer knowledge: correlating an agentic
run's tool calls and results into a :class:`~probos.dm_reply.ToolFailures`.

The value names are re-exported so existing cognitive callers keep working.
This is a namespace alias, NOT a second definition -- there is exactly one
``DmReply`` and it lives in ``probos.dm_reply``.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from probos.dm_reply import (
    DM_REPLY_METADATA_KEY,
    UNKNOWN_TOOL_LABEL,
    DmReply,
    RenderedDmText,
    ToolFailures,
    ToolFailuresMergeClosed,
    call_signature,
    collapse_to_names,
    failure_key,
    key_scope,
    mint_scope,
    require_rendered,
    scope_from_source,
)

logger = logging.getLogger(__name__)

#: Exactly the surface this module exported before BF-801 moved the value out.
#: ``key_scope`` and ``collapse_to_names`` are imported above so existing
#: attribute access keeps working, but they are deliberately NOT re-added here:
#: widening a compatibility shim's wildcard export is an API change nobody
#: asked for. Import them from ``probos.dm_reply``.
__all__ = [
    "RenderedDmText",
    "ToolFailures",
    "ToolFailuresMergeClosed",
    "DmReply",
    "correlate_tool_outcomes",
    "mint_scope",
    "scope_from_source",
    "call_signature",
    "failure_key",
    "offered_display_name",
    "require_rendered",
    "UNKNOWN_TOOL_LABEL",
    "DM_REPLY_METADATA_KEY",
]


def offered_display_name(name: str, offered: Iterable[str]) -> str:
    """DD-1a. Render a name only if it came from the OFFER.

    A registry id is not what the model receives: AD-1019c ids shaped
    ``mcp:{server}:{tool}`` are rewritten to ``mcp_{server}_{tool}_{16hex}``
    before they reach the provider, so keying disclosure off the registry id
    names a tool the Captain never saw offered.
    """
    return name if name in set(offered) else UNKNOWN_TOOL_LABEL


def correlate_tool_outcomes(
    result: Any,
    *,
    root: str,
    scope: str,
    known_tools: Iterable[str] = (),
    excluded_tools: Iterable[str] = (),
) -> ToolFailures:
    """Build the merge-open :class:`ToolFailures` for ONE agentic run.

    The value for a key is the display name when that call's final outcome was
    an error, and ``""`` when it succeeded -- the success tombstone that makes
    supersession expressible (DD-1).

    ``known_tools`` is the set of PROVIDER-FACING names actually offered this
    run; anything else renders as :data:`UNKNOWN_TOOL_LABEL` (DD-1a).

    ``excluded_tools`` are PERMISSION DENIALS, and they are dropped rather than
    disclosed: AD-855's capability-gap driver already surfaces them to the
    Captain as a tracked request naming the exact tool, which is strictly better
    than "an unrecognised tool returned an error". Disclosing both reports one
    event twice, in the worse wording. They arrive as registry ids, so they are
    translated to provider-facing names before comparison -- comparing the two
    namespaces directly is what made the discarded BF-773 build both duplicate
    and conceal, depending on which way the mismatch fell.

    Correlation is request-order pairing with an id agreement check, because the
    producer appends each call and its result together. A pair whose ids
    disagree is malformed rather than meaningful: logged and skipped, not
    surfaced as a third Captain-visible state.
    """
    try:
        calls = getattr(result, "tool_calls", None) or []
        results = getattr(result, "tool_results", None) or []
        if not calls or not results:
            return ToolFailures(merge_open=True)

        offered = {n for n in known_tools if isinstance(n, str) and n}
        denied = _denied_provider_names(excluded_tools)

        state: dict[str, str] = {}
        for call, res in zip(calls, results):
            call_id = getattr(call, "id", None)
            res_id = getattr(res, "id", None)
            if not isinstance(call_id, str) or call_id != res_id:
                logger.debug(
                    "AD-1248: tool call/result correlation mismatch (%r vs %r); "
                    "skipping this pair", call_id, res_id,
                )
                continue
            name = getattr(call, "name", None)
            if not isinstance(name, str) or not name:
                continue
            if name in denied:
                continue
            failed = getattr(res, "is_error", False) is True
            key = failure_key(
                root, scope, call_signature(name, getattr(call, "arguments", None)),
            )
            state[key] = offered_display_name(name, offered) if failed else ""
        return ToolFailures.from_mapping(state, merge_open=True)
    except Exception:
        logger.warning(
            "AD-1248: tool-outcome correlation raised; this turn discloses "
            "nothing rather than guessing", exc_info=True,
        )
        return ToolFailures(merge_open=True)


def _denied_provider_names(excluded_tools: Iterable[str]) -> set[str]:
    """Registry ids -> the names the model actually saw, for denial matching."""
    out: set[str] = set()
    try:
        from probos.cognitive.swe_harness.tool_call import llm_function_name
    except Exception:  # pragma: no cover - import guard only
        llm_function_name = None  # type: ignore[assignment]
    for tid in excluded_tools:
        if not isinstance(tid, str) or not tid:
            continue
        out.add(tid)
        if llm_function_name is not None:
            try:
                out.add(llm_function_name(tid))
            except Exception:
                logger.debug(
                    "AD-1248: could not derive the provider name for denied "
                    "tool %r; matching on the registry id alone", tid,
                )
    return out
