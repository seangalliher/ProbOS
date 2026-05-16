# AD-706d — LLM-driven tier classifier for Browser Tool actions

**Status:** Draft for Wave 163
**Dependencies:** AD-706 ✅ (Wave 132, ships rule-based `classify_action` at `src/probos/tools/browser/actions.py:550`), AD-706c-1 ✅ (Wave 162, ships `verify(expectation)` via vision tier), existing `runtime.llm_client.complete` infrastructure.
**Closes:** #519
**Estimated tests:** 10 pytest
**Build order:** Independent of the peer-observation cluster.

## Problem

`src/probos/tools/browser/actions.py:classify_action` is rule-based today: financial host-suffix globs, ToS button-text heuristics, etc. The rules are brittle (host suffix lists drift, button text changes), and they cannot reason about action-context combinations (e.g., clicking "Submit" on a tax form vs. clicking "Submit" on a comment box). AD-706d adds an LLM-driven classifier as an OPTIONAL enhancement layered ON TOP of the existing rule-based classifier.

## Scope discipline — what v1 ships

- LLM-driven classifier as an OPTIONAL augmentation. Default-OFF flag.
- When enabled, runs AFTER the rule-based classifier. If the rule classifier returns a confident answer (e.g., already in the "destructive" tier), the LLM is NOT called (cost discipline).
- LLM call uses the EXISTING fast tier via `runtime.llm_client.complete(LLMRequest(tier="fast"))`. NO new tier, NO new endpoint.
- The classifier returns a `tier: ActionTier` enum — same shape the rule-based classifier returns. Drop-in compatible.

NOT in scope:

- Replacing the rule-based classifier wholesale. Both coexist; the LLM is additive.
- Counselor InterventionType pattern from AD-561 (the issue body mentions this as a "may share" — Wave 163 keeps it separate; AD-706d-2 forward marker).
- ValidationFrameworkConfig surface (the issue body says "composes with: AD-451 once that surfaces a real classifier API" — that API still isn't present; AD-706d wires through `BrowserToolConfig`).

## Section 0: Config

Extend `BrowserToolConfig` (verified to exist in `config.py`):

```python
llm_classifier_enabled: bool = Field(
    default=False,
    description="AD-706d LLM-driven tier classifier for Browser Tool actions. Augments the rule-based classifier; default OFF.",
)
llm_classifier_tier: Literal["fast", "standard"] = Field(
    default="fast",
    description="AD-706d LLM tier for classification calls. Fast is cheapest and adequate for tier classification.",
)
llm_classifier_max_per_hour: int = Field(
    default=60,
    ge=0,
    description="AD-706d per-runtime hourly cap on LLM classifier calls. 0 disables.",
)
llm_classifier_cache_ttl_seconds: int = Field(
    default=300,
    ge=0,
    description="AD-706d in-memory cache TTL for identical (action, url-prefix, button-text) tuples. 0 disables caching.",
)
```

## Section 1: Classifier function

`src/probos/tools/browser/llm_classifier.py` (new module):

```python
def classify_action_llm(
    runtime: ProbOSRuntime,
    action: BrowserAction,
    *,
    context: ActionContext,
) -> ActionTier | None:
    """LLM-driven tier classifier. Returns ActionTier on happy path,
    None on honest-degrade (caller falls back to rule-based result).

    Hard gates:
      1. cfg.tools.browser.llm_classifier_enabled (default False).
      2. Rate-limit slot available (hourly cap).
      3. Cache miss (cache hit returns immediately).

    Honest-degrades on:
      - LLM unavailable / call failure.
      - LLM output unparseable.
      - LLM output outside the valid ActionTier enum range.
    """
```

`ActionContext` is a small dataclass with the action-relevant signals: URL, element-text, page-title, surrounding-context-snippet (≤200 chars). NO screenshot — this is the fast-tier text classifier; vision-tier classification is handled separately by AD-706c-1.

## Section 2: Integration with existing `classify_action`

Keep `classify_action` at `src/probos/tools/browser/actions.py:550` (verified by Architect grep — the rule-based function is named `classify_action`, NOT `_rule_based_classify_action`). The LLM-assisted variant is a NEW companion function `classify_action_with_llm` that wraps the rule-based path:

```python
# Existing rule-based function at actions.py:550 stays as-is, unchanged signature:
def classify_action(action, context) -> ActionTier: ...

# NEW companion function (additive, layered ON TOP):
def classify_action_with_llm(action, context, *, runtime=None) -> ActionTier:
    # 1. Run existing rule-based classifier.
    rule_tier = classify_action(action, context)

    # 2. If rule classifier returned a CONFIDENT high-risk tier (destructive / ack_required),
    #    short-circuit. We never UPGRADE risk via LLM beyond what rules already detected.
    if rule_tier in (ActionTier.DESTRUCTIVE, ActionTier.ACK_REQUIRED):
        return rule_tier

    # 3. If LLM classifier disabled or runtime not provided, return rule tier.
    if runtime is None or not runtime.config.tools.browser.llm_classifier_enabled:
        return rule_tier

    # 4. LLM call. None return → fall back to rule tier.
    llm_tier = classify_action_llm(runtime, action, context=context)
    if llm_tier is None:
        return rule_tier

    # 5. LLM can UPGRADE risk (auto-run → ack_required) but NEVER DOWNGRADE.
    return _max_tier(rule_tier, llm_tier)
```

**Critical safety property**: the LLM can only INCREASE the perceived risk, never decrease it. The rule-based classifier's existing safety floor is preserved. The original `classify_action` is NOT renamed — call sites that want LLM augmentation opt in by calling `classify_action_with_llm`.

## Section 3: Prompt template

The LLM prompt is a SINGLE compact template, NOT free-form:

```
You are classifying a browser action for risk tier.

Action: {action_type}  (one of: click, navigate, fill, submit, ...)
URL: {url}
Element text: {element_text}
Page title: {page_title}
Surrounding text: {context_snippet}

Reply with ONE word from this exact set:
- auto_run    (safe read-only)
- ack_required (writes data, sends message, irreversible-ish)
- destructive  (deletes data, sends money, irreversible)

Reply with ONLY the word.
```

Output parsing is strict — single-word match against the three-value enum. Anything else → None (honest-degrade).

## Section 4: Cache

In-memory cache keyed by `(action_type, url_prefix_first_80_chars, element_text, page_title)`. TTL configurable. Cache returns the prior `ActionTier` decision. NO persistence to disk in v1 (forward marker AD-706d-3 for persistent cache).

## Section 5: Rate limit

Reuse `VisionLLMRateLimit` from AD-722a-1 directly. Verified by Architect grep: `VisionLLMRateLimit` is already used cross-module (`src/probos/cognitive/self_render_verify.py:32,67` imports and instantiates it for non-vision-coupled use). "Generalizable beyond vision" is the answered state — no fork, no rename. New scope key `browser_action_classifier`.

## Section 6: Tests (≥10 pytest)

`tests/test_ad706d_llm_action_classifier.py`:

1. `llm_classifier_enabled=False` → only rule-based result returned.
2. Rule returns `DESTRUCTIVE` → LLM NOT called (short-circuit).
3. Rule returns `AUTO_RUN`, LLM returns `ACK_REQUIRED` → tier upgraded to `ACK_REQUIRED`.
4. Rule returns `ACK_REQUIRED`, LLM returns `AUTO_RUN` → tier stays `ACK_REQUIRED` (no downgrade).
5. LLM call fails → honest-degrade, rule tier returned.
6. LLM returns malformed output → honest-degrade.
7. LLM returns string outside the enum → honest-degrade.
8. Rate limit exceeded → honest-degrade.
9. Cache hit: second identical classification within TTL → no LLM call, prior tier returned.
10. Cache miss after TTL: third call past TTL → LLM called again.

Use **real `SystemConfig()` fixtures**. Use a stub LLM client that returns canned text — NOT MagicMock at config boundary (BF-287).

## Section 7: Builder Standing Rules

- BF-274: single replace for adjacent edits, ESPECIALLY in `actions.py` which has multiple `ActionTier` references.
- BF-280: no `asyncio.create_subprocess_*`.
- BF-282: no binary stdout.
- BF-286: test scaffolding mirrors production.
- BF-287: real Config + real LLM client stub (not MagicMock at the boundary).
- AD-738b: no UI in this AD; no `npm run build` gate.
- AD-731 invariant: n/a (browser-tool LLM classifier processes TEXT only; no image bytes flow through this code path). Vision-tier verify already lives in AD-706c-1.
- AD-722c-3: forward markers use TECHNICAL triggers.

## What this does NOT change

- The existing `classify_action` rule-based logic — preserved as-is, unrenamed. LLM augmentation is opt-in via new `classify_action_with_llm` companion.
- The existing AD-706c-1 vision-tier `verify()` action.
- `ActionTier` enum values.
- BrowserTool's 11-action vocab.
- Any HXI surface.

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #519.
- `docs/development/roadmap.md`: move AD-706d from forward markers; sub-AD forward markers filed.
- `DECISIONS.md`: append AD-706d entry — additive LLM classifier; rules stay authoritative on high-risk tiers.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-706d-2 — Counselor InterventionType integration.** Trigger: when AD-561 InterventionType API is stable AND surfaces a generic intervention-tier shape. Issue filed.
- **AD-706d-3 — Persistent classifier cache.** Trigger: when in-memory cache hit rate exceeds 60% over a 24h window AND cache miss rate from restart is identified as cost driver. Issue filed.
- **AD-706d-4 — `llm_classifier_enabled` default True.** Trigger: when the LLM classifier has run ≥1000 classifications AND manual review confirms ≥95% agreement with operator expectation. Issue filed.

## Acceptance Criteria

1. All Section 0-5 deliverables landed.
2. ≥10 pytest tests pass.
3. Full gate green.
4. Source-scan: the LLM classifier can only UPGRADE risk (verified by Test 4).
5. Zero new pip deps confirmed.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
grep -n "def classify_action" src/probos/tools/browser/actions.py
  550

grep -n "class BrowserToolConfig" src/probos/config.py
  (present per config-class enumeration)

grep -n "VisionLLMRateLimit" src/probos/avatars/vision_intent_divergence.py
  (AD-722a-1 ships this scope-keyed class — reuse candidate per PROGRESS.md line 18)
```

**Builder verify-first flags:**
- `ActionTier` enum exact values — VERIFY before Section 3 prompt template.

## License posture

Zero new pip/npm deps. The LLM call uses existing `runtime.llm_client` infrastructure (existing provider pluggable). Confirmed.
