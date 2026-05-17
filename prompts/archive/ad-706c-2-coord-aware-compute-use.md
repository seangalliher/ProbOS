# AD-706c-2 — Coordinate-aware `compute_use` tier for DOM-less surfaces

**Status:** Draft v1.
**Closes:** #643.
**Dependencies:** AD-706c-1 (#642, Wave 162, shipped — visual `verify` primitive). AD-732 (Wave 153, shipped — vision tier infrastructure). AD-731 (Wave 152, shipped — AttachmentStore SHA-256 refs).
**Estimated tests:** +14 pytest. **0 new pip/npm deps.**

---

## Problem

The AD-706 BrowserTool action vocabulary requires stable DOM selectors. When the surface is canvas-only (HTML5 games, embedded VNC, Flash legacy, Figma-style apps, screenshot-only PDFs in `<embed>`) the agent has nothing to click — `state()` returns no interactable elements, and `click(index=...)` cannot resolve.

The Anthropic / OpenAI `computer_use` direction is to predict pixel coordinates from a screenshot. Generic vision models (qwen3.6:27b, llava) describe the screen accurately but report **wrong coordinates** when asked "where do I click?" Acting on a wrong coordinate is high-cost: destructive clicks at unintended targets, form fields filled with wrong values, navigation to wrong URLs.

The eight-guard vision stack from AD-731 + BF-268..273 + AD-732 carries over directly. Two new guards are specific to coordinate prediction.

## Solution

Introduce a dedicated `compute_use` LLM tier as the fifth peer of `fast`/`standard`/`deep`/`vision` in `_LLM_TIERS`. Operator-configurable; **default unconfigured** (mirrors AD-732). When unconfigured, the existing AD-706 + AD-706c-1 path is the operational mode — `compute_use_click` honest-degrades with a `VISION_COMPUTE_USE_UNCONFIGURED_MESSAGE`.

Add one new BrowserTool action verb: `compute_use_click(intent: str)`. Captures a fresh screenshot, stores via `AttachmentStore.write` (SHA-256), passes the ref + intent to the `compute_use` tier, parses `{x: int, y: int, confidence: float}`, executes a coordinate verification handshake against the same screenshot via AD-706c-1's vision pipeline, then either executes the click via `page.mouse.click(x, y)` or aborts with `skipped_reason`.

### Section 0 — Event Types

Add to `src/probos/event_log.py` EventType enum, inserted in source order after `BROWSER_VERIFY_OBSERVED`:

- `BROWSER_COMPUTE_USE_CLICK_PROPOSED` — coordinate predicted by the tier.
- `BROWSER_COMPUTE_USE_CLICK_VERIFIED` — verification handshake succeeded.
- `BROWSER_COMPUTE_USE_CLICK_ABORTED` — verification disagreed; click NOT executed.
- `BROWSER_COMPUTE_USE_CLICK_EXECUTED` — click sent to the page.

### Section 1 — LLM tier extension

`src/probos/cognitive/llm_client.py`:

**1a.** Extend `_LLM_TIERS` to add `"compute_use"`:

```python
===SEARCH===
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision")
===REPLACE===
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "compute_use")
===END REPLACE===
```

**1b.** Promote `_TIER_ORDER` to module-level constant (currently inside `complete()` at line ~542). Add module-level constant directly below `_LLM_TIERS` and remove the local rebinding inside `complete()`:

```python
===SEARCH===
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "compute_use")
===REPLACE===
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "compute_use")

# AD-706c-2: fallback chain is text-only. ``vision`` and ``compute_use`` are
# excluded — text tiers silently drop image content (BF-269) and coordinate
# prediction failures must surface as honest-degrade, never confident wrong
# clicks. Module-level so source-scan tests can assert membership without
# scanning function bodies.
_TIER_ORDER: tuple[str, ...] = ("fast", "standard", "deep")
===END REPLACE===
```

Inside `complete()`, remove the local `_TIER_ORDER = [...]` line and the `vision`-only branch, then expand the fallback construction to honor the new `compute_use` tier:

```python
===SEARCH===
        _TIER_ORDER = ["fast", "standard", "deep"]
        if tier == "vision":
            fallback_tiers = ["vision"]
        else:
            fallback_tiers = [tier] + [t for t in _TIER_ORDER if t != tier]
===REPLACE===
        # AD-706c-2: vision + compute_use never fall back to text tiers.
        if tier in ("vision", "compute_use"):
            fallback_tiers = [tier]
        else:
            fallback_tiers = [tier] + [t for t in _TIER_ORDER if t != tier]
===END REPLACE===
```

**1c.** ModelRouter (AD-463) must bypass `compute_use` exactly as it bypasses `vision` (BF-273 pattern). Grep `_resolve_model_for_tier` and extend whichever set/condition holds the `vision` bypass to also include `compute_use`.

**1d.** `src/probos/config.py` `CognitiveConfig` — five new fields mirroring AD-732 vision shape:
- `llm_base_url_compute_use: str = ""`
- `llm_model_compute_use: str = ""`
- `llm_api_format_compute_use: Literal["openai", "anthropic"] = "openai"`
- `llm_timeout_compute_use: int = 120` (ge=10, le=600)
- `llm_max_tokens_compute_use: int = 256` (ge=32, le=2048)

**1e.** REUSE `is_vision_tier_configured(cfg, tier_name)` from `src/probos/cognitive/vision_dispatch.py:56`. Do NOT create a new helper. Do NOT duplicate honest-degrade message constants — vision_dispatch.py owns `VISION_UNCONFIGURED_MESSAGE` / `VISION_UNHEALTHY_MESSAGE` (BF-274 lesson: one module owns these strings).

Extend `is_vision_tier_configured` to recognize the `compute_use` tier:

```python
===SEARCH===
    if tier_name != "vision":
        return True
    model = getattr(cfg, "llm_model_vision", None) or ""
    base_url = getattr(cfg, "llm_base_url_vision", None)
    return bool(model and base_url)
===REPLACE===
    if tier_name == "vision":
        model = getattr(cfg, "llm_model_vision", None) or ""
        base_url = getattr(cfg, "llm_base_url_vision", None)
        return bool(model and base_url)
    if tier_name == "compute_use":
        # AD-706c-2: opt-in coordinate-prediction tier. Same shape as vision.
        model = getattr(cfg, "llm_model_compute_use", None) or ""
        base_url = getattr(cfg, "llm_base_url_compute_use", None)
        return bool(model and base_url)
    return True
===END REPLACE===
```

### Section 2 — New action verb `compute_use_click`

New file `src/probos/tools/browser/compute_use.py` exports:

```python
async def action_compute_use_click(
    session: BrowserSession,
    params: dict,
    *,
    runtime: Any,
    emit_event: Any,
) -> dict:
```

Signature matches `action_verify(session, params, *, runtime, emit_event)` at `actions.py:376`. The handler emits four event types, so `emit_event` is required (not optional).

Pseudocode contract (not the implementation):

1. `intent = params["intent"]` (required str).
2. If `not is_vision_tier_configured(runtime.config.cognitive, "compute_use")`: return `{ok: False, skipped_reason: "compute_use_unconfigured", message: VISION_UNCONFIGURED_MESSAGE}`. Tier-2. (Import `is_vision_tier_configured` + `VISION_UNCONFIGURED_MESSAGE` from `probos.cognitive.vision_dispatch`.)
3. Trust-budget gate (Section 4). If exhausted, return `{ok: False, skipped_reason: "trust_budget_exhausted"}`.
4. Capture screenshot via the same Playwright helper AD-706c-1 uses (`_capture_screenshot_bytes` — extract into module-level helper if currently inline in `action_verify`).
5. Write to `AttachmentStore` via `runtime.attachment_store.write(sha, bytes, "image/png")`. Get back a SHA-256 ref. (AD-731 invariant: refs not blobs.)
6. Build multimodal message via existing `build_multimodal_messages(text=PROMPT_TEMPLATE.format(intent=intent), attachment_refs=[sha])` from AD-731. The resolver is `_resolve_attachment_refs_for_openai` for OpenAI-shape endpoints (BF-268 lesson).
7. `await runtime.llm_client.complete(LLMRequest(tier="compute_use", ..., max_tokens=cfg.llm_max_tokens_compute_use))` — use the **async** `complete()`, not the AD-706d `complete_sync` helper (that helper exists because the rule classifier is sync; this handler is async). **No cache** (BF-272 lesson; screenshots are time-dependent). **No fallback chain** (BF-269 lesson — text tiers can't see images, vision tiers describe but mis-coordinate).
8. Parse `{x: int, y: int, confidence: float}` from response JSON. On malformed output, honest-degrade with `skipped_reason="parse_error"`.
9. Emit `BROWSER_COMPUTE_USE_CLICK_PROPOSED`.
10. Coordinate verification handshake (Section 3). If disagreement, emit `BROWSER_COMPUTE_USE_CLICK_ABORTED` and return `{ok: False, skipped_reason: "verification_failed", ...}`.
11. Execute click: `await session.page.mouse.click(x, y)`. Emit `BROWSER_COMPUTE_USE_CLICK_EXECUTED`. Return `{ok: True, x, y, confidence, verified: True}`.

#### 2a — Register handler in `_HANDLERS`

`src/probos/tools/browser/actions.py:329`:

```python
===SEARCH===
_HANDLERS: dict[str, Any] = {
    "goto": _action_goto,
    "state": _action_state,
    "click": _action_click,
    "type": _action_type,
    "scroll": _action_scroll,
    "screenshot": _action_screenshot,
    "wait": _action_wait,
    "back": _action_back,
    "forward": _action_forward,
    "extract_text": _action_extract_text,
}
===REPLACE===
_HANDLERS: dict[str, Any] = {
    "goto": _action_goto,
    "state": _action_state,
    "click": _action_click,
    "type": _action_type,
    "scroll": _action_scroll,
    "screenshot": _action_screenshot,
    "wait": _action_wait,
    "back": _action_back,
    "forward": _action_forward,
    "extract_text": _action_extract_text,
    # AD-706c-1 ``verify`` is registered separately below at module load.
    # AD-706c-2 ``compute_use_click`` is imported from
    # ``probos.tools.browser.compute_use`` and registered via the same
    # late-bind pattern (avoids a circular import: compute_use.py imports
    # action_verify from this module).
}
===END REPLACE===
```

Late-bind registration appended at the bottom of `actions.py` (after `action_verify` is defined):

```python
===SEARCH===
def classify_action(
===REPLACE===
# AD-706c-2: register coordinate-aware click after action_verify is defined
# (compute_use_click reuses action_verify for the Guard #9 handshake).
from probos.tools.browser.compute_use import action_compute_use_click  # noqa: E402
_HANDLERS["compute_use_click"] = action_compute_use_click


def classify_action(
===END REPLACE===
```

#### 2b — Extend `classify_action` to mark `compute_use_click` as always-tier-3

`src/probos/tools/browser/actions.py:550`. AD-706c-2 owns this slot; AD-706e MUST NOT re-add the entry (AD-706e is no-op for `compute_use_click`).

```python
===SEARCH===
    silent = {"state", "screenshot", "wait", "extract_text", "scroll", "back", "forward", "verify"}
    if action in silent:
        return 1
    if action == "goto":
        return 2
    if action not in {"click", "type"}:
        return 2
===REPLACE===
    # AD-706c-2: coordinate-aware click is always tier-3 (destructive click at
    # unverified pixel coordinate). Captain ACK required every call. Checked
    # BEFORE the silent/goto bands so AD-706e's later always-tier-3 set
    # extension is purely additive.
    if action == "compute_use_click":
        return 3
    silent = {"state", "screenshot", "wait", "extract_text", "scroll", "back", "forward", "verify"}
    if action in silent:
        return 1
    if action == "goto":
        return 2
    if action not in {"click", "type"}:
        return 2
===END REPLACE===
```

If `cfg.tools.browser.llm_classifier_enabled`, ensure `classify_action_with_llm` also recognises `compute_use_click` (short-circuit since rule_tier == 3).

If `cfg.tools.browser.llm_classifier_enabled`, ensure `classify_action_with_llm` also recognises `compute_use_click` (short-circuit since rule_tier == 3).

### Section 3 — Coordinate verification handshake (Guard #9)

Before executing the click, take a second screenshot OR reuse the same screenshot ref. Call AD-706c-1's `action_verify(expectation=f"the element described as {intent!r} is visible near coordinate ({x}, {y})")`. If `verify` returns `{ok: False}` or `ok=None`, abort.

Reuse the existing `verify` machinery in `actions.py:action_verify` — do not fork. Pass the screenshot ref directly to avoid a redundant capture.

### Section 4 — Trust budget (Guard #10)

Per-session counter on `BrowserSession`:
- New attribute `self._compute_use_consecutive_autonomous: int = 0`.
- New attribute `self._compute_use_total_calls: int = 0`.

New `BrowserToolConfig` fields:
- `compute_use_max_consecutive_autonomous_actions: int = 5` (ge=0, le=20).
- `compute_use_max_per_session: int = 50` (ge=0, le=500).

Before each `compute_use_click`, check both caps. If either exhausted, honest-degrade with `skipped_reason="trust_budget_exhausted"`. Reset `_compute_use_consecutive_autonomous` on any Captain-ACKed action (the existing tier-3 ACK signal — wire via the existing `record_state_snapshot` pattern OR a new `note_captain_ack()` method on session).

v1: increment on every call; never reset within a session except on Captain ACK. AD-706c-2-trust-reset forward marker covers smarter session-level decay.

### Section 5 — Honest-degrade messaging

REUSE the existing `VISION_UNCONFIGURED_MESSAGE` / `VISION_UNHEALTHY_MESSAGE` constants from `src/probos/cognitive/vision_dispatch.py` (BF-274 lesson — one module owns these strings; routers that surface them MUST import from `cognitive.vision_dispatch`, not redefine).

The existing message text already mentions "Vision LLM is not configured" in operator-facing terms. Since the `compute_use` tier extension is a sibling of vision (both opt-in coordinate/image-aware LLM endpoints), the same operator-remediation instruction applies (configure `cognitive.llm_base_url_compute_use` + `llm_model_compute_use`). v1: ship with the shared message. AD-706c-2a forward marker covers per-tier specialization if operators report confusion.

`compute_use.py` MUST NOT define `VISION_COMPUTE_USE_UNCONFIGURED_MESSAGE` or similar — that was rejected in pass-1 review (constant duplication anti-pattern).

### Tests (`tests/test_ad706c2_compute_use.py`)

1. `test_compute_use_unconfigured_honest_degrades` — empty `llm_base_url_compute_use` → `skipped_reason="compute_use_unconfigured"`, no LLM call.
2. `test_compute_use_action_registered_in_handlers` — `_HANDLERS["compute_use_click"]` is callable.
3. `test_compute_use_always_tier_3` — `classify_action(session, "compute_use_click", {})` returns 3.
4. `test_compute_use_llm_classifier_short_circuits` — `classify_action_with_llm(rule_tier=3, action="compute_use_click", ...)` returns 3 without LLM call.
5. `test_compute_use_happy_path_writes_ref_and_executes` — stubbed `llm_client.complete` returning `'{"x":100,"y":200,"confidence":0.9}'` + stubbed `verify` returning `ok=True`. Assert `page.mouse.click(100, 200)` called.
6. `test_compute_use_verification_disagreement_aborts_click` — stubbed `verify` returning `ok=False`. Assert click NOT executed; event `BROWSER_COMPUTE_USE_CLICK_ABORTED` emitted.
7. `test_compute_use_parse_error_honest_degrades` — LLM returns non-JSON. `skipped_reason="parse_error"`.
8. `test_compute_use_no_cache` — two successive calls with identical screenshot → two LLM calls (BF-272 enforcement).
9. `test_compute_use_no_fallback_chain` — assert module-level `_TIER_ORDER` from `probos.cognitive.llm_client` does NOT include `"compute_use"` or `"vision"` (BF-269 enforcement; promoted to module-level constant in Section 1b for clean importable assertion).
10. `test_compute_use_model_router_bypass` — assert `_resolve_model_for_tier` returns None for `tier="compute_use"` (BF-273 enforcement).
11. `test_compute_use_trust_budget_consecutive_cap_exhausts` — call 6 times with `max_consecutive_autonomous=5`. Sixth call honest-degrades with `skipped_reason="trust_budget_exhausted"`.
12. `test_compute_use_trust_budget_per_session_cap` — call until `max_per_session` exhausted.
13. `test_compute_use_uses_attachment_store_refs_not_inline` — source-scan of `compute_use.py` asserts no `b64encode`/`base64.b64` (AD-731 invariant).
14. `test_compute_use_uses_openai_shape_resolver` — source-scan asserts `_resolve_attachment_refs_for_openai` import (BF-268 lesson).

All tests use real `SystemConfig()` fixtures + dataclass `_FakeRuntime` + dataclass `_FakeBrowserSession` (BF-287 — NO MagicMock at substrate boundary).

## What This Does NOT Change

- DOM-based AD-706 actions (`click`, `type`) remain primary. `compute_use_click` is for DOM-less fallback only.
- AD-706c-1 `verify` action unchanged.
- AD-706d `classify_action_with_llm` unchanged (compute_use_click short-circuits via rule_tier=3 check).
- AD-732 vision tier behavior unchanged.
- ModelRouter cost-routing logic unchanged for other tiers.
- The `verify` action is REUSED for coordinate verification — not forked.

## Tracking

- `PROGRESS.md` — add Wave 166 entry.
- `docs/development/roadmap.md` — close #643 row.
- `DECISIONS.md` — append AD-706c-2 with 10-guard catalog (8 inherited from AD-732 stack + Guards 9 & 10 specific to compute_use). State explicitly that v1 ships v1 of Guards 9/10; refinements deferred.

Forward markers (TECHNICAL triggers per AD-722c-3):
- AD-706c-2a — Native-app compute use (Windows accessibility / macOS AT-SPI). Trigger: operator-reported demand from non-browser surfaces with ≥3 distinct app categories.
- AD-706c-2b — Multi-monitor compute use. Trigger: HXI multi-display deployment lands.
- AD-706c-2c — Vision-based form filling (text into coordinate-located field). Trigger: AD-706e `type` action proves insufficient for ≥3 sites in production.
- AD-706c-2d — Demonstration learning. Trigger: ≥10 distinct `compute_use_click` sequences land in operator-recorded sessions (#517 dataset).
- AD-706c-2-trust-reset — Session-level trust-budget decay on time/idle. Trigger: operator-reported false-positive budget exhaustion in normal use.

## Acceptance Criteria

- All 14 tests green under serial (`-n 0`) and parallel (`-n 4 --dist=loadfile`) gates.
- Full pytest gate: 13762 → ≥13776.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- No new pip deps.
- License posture preserved: no AGPL/GPL absorption (OmniParser explicitly excluded per #643 body).

## Verified Against Codebase (2026-05-16)

```
grep -n "class BrowserSession" src/probos/tools/browser/session.py
  45: class BrowserSession:

grep -n "get_streaming_url" src/probos/tools/browser/session.py
  117:    def get_streaming_url(self) -> str | None:

grep -n "_HANDLERS" src/probos/tools/browser/actions.py
  329: _HANDLERS: dict[str, Any] = {

grep -n "def classify_action" src/probos/tools/browser/actions.py
  550: def classify_action(

grep -n "def action_verify" src/probos/tools/browser/actions.py
  376: async def action_verify(

grep -n "classify_action_with_llm" src/probos/tools/browser/llm_classifier.py
  79: def classify_action_with_llm(

grep -n "class BrowserToolConfig" src/probos/config.py
  936: class BrowserToolConfig(BaseModel):

grep -n "class AttachmentStore" src/probos/attachments/store.py
  14: class AttachmentStore(Protocol):
  22:     async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
```

AD-732 / AD-731 / BF-268..273 / BF-274 / BF-287 patterns confirmed in user memory at `/memories/probos-architect-learnings.md` (Eight-guard vision pipeline, Ten-guard catalog).
