"""AD-706d: LLM-driven tier classifier for Browser Tool actions.

Augments the existing rule-based ``classify_action`` (at
``src/probos/tools/browser/actions.py:550``, returns int tier 1/2/3) with
an LLM-driven companion ``classify_action_with_llm``. The LLM call is
layered ON TOP — never replaces — the rule-based classifier, and can
only UPGRADE risk (1->2->3), never DOWNGRADE.

Default OFF: ``cfg.tools.browser.llm_classifier_enabled``.

REUSES the AD-722a-1 ``VisionLLMRateLimit`` primitive under a new scope
``browser_action_classifier``. The class is already used cross-module
(self_render_verify.py), so no fork to a new ``LLMCallRateLimit`` class
is needed — the AD-706d generalizability question is resolved.

The LLM classifier is text-only (fast tier). No image bytes. AD-731
invariant n/a — this code path never carries attachment refs.
"""
from __future__ import annotations

import logging
import time
from threading import RLock
from typing import Any

from probos.avatars.vision_intent_divergence import VisionLLMRateLimit

logger = logging.getLogger(__name__)


_VALID_TIERS = {1, 2, 3}
_WORD_TO_TIER = {
    "auto_run": 1,
    "ack_required": 2,
    "destructive": 3,
    # Synonyms for robustness.
    "silent": 1,
    "logged": 2,
    "captain_ack": 3,
}


# In-memory cache keyed by (action, url_prefix, element_text, page_title).
# Stored at module level so it survives across calls within a process.
_cache_lock = RLock()
_cache: dict[tuple[str, str, str, str], tuple[float, int]] = {}


def clear_cache() -> None:
    """Test helper: clear the in-memory cache."""
    with _cache_lock:
        _cache.clear()


def _cache_key(
    action: str, url: str, element_text: str, page_title: str,
) -> tuple[str, str, str, str]:
    return (action, url[:80], element_text[:120], page_title[:80])


def _read_cache(key: tuple[str, str, str, str], ttl: int) -> int | None:
    if ttl <= 0:
        return None
    with _cache_lock:
        record = _cache.get(key)
        if record is None:
            return None
        ts, tier = record
        if (time.time() - ts) > ttl:
            return None
        return tier


def _write_cache(key: tuple[str, str, str, str], tier: int) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), tier)


def classify_action_with_llm(
    *,
    runtime: Any,
    rule_tier: int,
    action: str,
    url: str = "",
    element_text: str = "",
    page_title: str = "",
    context_snippet: str = "",
) -> int:
    """Companion to ``classify_action`` (the rule-based function). Returns
    the final tier 1/2/3 after optional LLM augmentation.

    Critical safety property: this function can only UPGRADE the rule-based
    tier (auto_run -> ack_required -> destructive), never DOWNGRADE.

    Sync — the caller is on the synchronous Browser-Tool dispatch path. The
    LLM call itself is dispatched through the runtime's pre-built async
    helper ``llm_client.complete_sync`` when available; otherwise the
    classifier honest-degrades to the rule-based tier.
    """
    if rule_tier >= 3:
        # Already at maximum risk — short-circuit, do not call LLM.
        return rule_tier

    cfg = getattr(runtime, "config", None)
    browser_cfg = getattr(cfg, "browser_tool", None) if cfg is not None else None
    if browser_cfg is None or not getattr(browser_cfg, "llm_classifier_enabled", False):
        return rule_tier

    max_per_hour = int(getattr(browser_cfg, "llm_classifier_max_per_hour", 0))
    if max_per_hour <= 0:
        return rule_tier

    ttl = int(getattr(browser_cfg, "llm_classifier_cache_ttl_seconds", 0))
    key = _cache_key(action, url, element_text, page_title)
    cached = _read_cache(key, ttl)
    if cached is not None:
        return max(rule_tier, cached)

    rate = VisionLLMRateLimit(
        scope="browser_action_classifier", max_per_hour=max_per_hour,
    )
    # Use a stable agent_id-shaped key so the per-agent budget is process-wide.
    if not rate.under_limit("browser_action_classifier"):
        return rule_tier

    llm = getattr(runtime, "llm_client", None)
    if llm is None:
        return rule_tier

    # The classifier requires a sync entry point on the llm_client. Runtimes
    # that only expose async `complete` honest-degrade — Tier-2.
    complete_sync = getattr(llm, "complete_sync", None)
    if complete_sync is None:
        return rule_tier

    tier_name = str(getattr(browser_cfg, "llm_classifier_tier", "fast") or "fast")
    prompt = _build_prompt(
        action=action, url=url, element_text=element_text,
        page_title=page_title, context_snippet=context_snippet,
    )

    try:
        from probos.cognitive.llm_client import LLMRequest
        request = LLMRequest(prompt=prompt, tier=tier_name, max_tokens=8)
        response = complete_sync(request)
    except Exception:
        logger.warning(
            "AD-706d: LLM classifier call failed for action=%s; honest-degrade",
            action, exc_info=True,
        )
        return rule_tier

    rate.note_call("browser_action_classifier")
    raw = (getattr(response, "text", "") or "").strip().lower()
    llm_tier = _WORD_TO_TIER.get(raw)
    if llm_tier is None or llm_tier not in _VALID_TIERS:
        return rule_tier

    final = max(rule_tier, llm_tier)
    _write_cache(key, final)
    return final


def _build_prompt(
    *,
    action: str,
    url: str,
    element_text: str,
    page_title: str,
    context_snippet: str,
) -> str:
    return (
        "You are classifying a browser action for risk tier.\n\n"
        f"Action: {action}\n"
        f"URL: {url}\n"
        f"Element text: {element_text}\n"
        f"Page title: {page_title}\n"
        f"Surrounding text: {context_snippet[:200]}\n\n"
        "Reply with ONE word from this exact set:\n"
        "- auto_run    (safe read-only)\n"
        "- ack_required (writes data, sends message, irreversible-ish)\n"
        "- destructive  (deletes data, sends money, irreversible)\n\n"
        "Reply with ONLY the word."
    )


__all__ = [
    "classify_action_with_llm",
    "clear_cache",
]
