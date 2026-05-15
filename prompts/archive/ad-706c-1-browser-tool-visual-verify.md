# AD-706c-1 — Visual verification of Browser Tool actions (local vision tier)

**Wave:** 162
**Closes:** #642
**Status:** ready to build
**Dependencies:** AD-706 (Wave 132 — BrowserTool); AD-731 (AttachmentStore refs); BF-268 (`_resolve_attachment_refs_for_openai` OpenAI shape); AD-732 + BF-269..273 (vision tier ten-guard stack).
**Estimated tests:** +9 pytest.
**Scope tag:** Server-only. No new pip/npm deps. Apache 2.0. Local vision tier only (qwen3.6:27b per Wave 153 default); no cloud API key.

---

## Problem

[Issue #642](https://github.com/seangalliher/ProbOS/issues/642) — the original AD-706c (#518) was OmniParser-style vision extraction, split 2026-05-12 into:
- **AD-706c-1** (this AD) — read-only verification: "did the expected outcome appear after my last action?"
- **AD-706c-2** (#643, future) — click-target prediction with coordinate output (out of scope here).

Per the issue body: *"v1 is read-only verification: the vision model never tells the agent where to click — only whether the prior click had the intended effect."*

All prerequisites are already in production:
- AD-731 — screenshots cross the bus as `attachment_ref` SHA-256, not inline bytes.
- BF-268 — `_resolve_attachment_refs_for_openai` produces the OpenAI `image_url + data: URL` shape Ollama vision accepts.
- AD-732 + 10-guard stack — vision tier with honest-degrade, no fallback to text tiers, cost gating, ModelRouter bypass.

---

## Solution overview

1. New action verb `verify(expectation: str) -> {ok: bool, observation: str}` on the BrowserTool action vocab.
2. Action flow: take a fresh screenshot → store in AttachmentStore (returns SHA-256 ref) → call vision tier with prompt `"Did the following expectation hold for this page? <expectation>. Respond with JSON: {ok: bool, observation: \"<≤200 char description>\"}".`
3. Audit logging: every `verify` action emits `EventType.BROWSER_ACTION_EXECUTED` with `action="verify"`, plus a new `EventType.BROWSER_VERIFY_OBSERVED` for the verification result + screenshot ref + confidence.
4. ChainOfThought integration: agent plans can mix `click(...)` and `verify(...)` natively — same action-vocab dispatch.
5. Tier-2 honest degrade: when vision tier is unavailable / unhealthy / over-budget, `verify` returns `{ok: null, observation: "vision tier unavailable; verification skipped"}` and the agent narrates the gap. The browser action sequence continues — verification is observational, never blocking.

### What this does NOT change

- AD-706 BrowserTool primitives (`navigate`, `click`, `fill`, `screenshot`).
- AD-706 audit/event emit (this AD ADDS a new event type, doesn't modify existing).
- AD-731 attachment-ref invariant — screenshots stay as refs.
- AD-732 vision tier configuration.
- Click-target prediction (out of scope; #643).
- Cloud vision API integration (forward marker AD-706c-3 for Anthropic computer-use beta).
- DOM-less surfaces (Flash, Canvas-heavy SPAs) — out of scope.

---

## Section 0 — New EventType

In `src/probos/events.py`:

```python
BROWSER_VERIFY_OBSERVED = "browser_verify_observed"  # AD-706c-1: vision-LLM verification result
```

Adjacent to existing `BROWSER_ACTION_EXECUTED` / `BROWSER_SESSION_OPENED` (events.py:198-201).

---

## Section 1 — `verify` action handler

In `src/probos/tools/browser/actions.py` (or wherever `classify_action` / `dispatch_action` live — read `src/probos/tools/browser/tool.py:34` to find the exact import). Add:

```python
async def action_verify(
    session,
    params: dict,
    *,
    attachment_store,
    vision_client,
    emit_event,
) -> dict:
    """AD-706c-1: vision-LLM verification of the current page state.

    params:
      expectation: str (≤500 chars) — natural language "what should be true now"

    Returns:
      {ok: bool | None, observation: str, screenshot_ref: str | None,
       skipped_reason: str | None}

    Honest-degrade: vision tier unavailable -> ok=None, skipped_reason set.
    """
    expectation = params.get("expectation", "")
    if not isinstance(expectation, str) or not expectation.strip():
        return {"ok": None, "observation": "missing expectation",
                "screenshot_ref": None, "skipped_reason": "missing_expectation"}
    if len(expectation) > 500:
        expectation = expectation[:500]

    # Take screenshot; AD-731 ref shape preserved.
    png_bytes = await session.page.screenshot()
    screenshot_ref = await attachment_store.put(png_bytes, mime="image/png")

    # Vision tier honest-degrade check.
    try:
        from probos.cognitive.vision_dispatch import is_vision_tier_configured
        if not is_vision_tier_configured(vision_client.config):
            return {"ok": None, "observation": "vision tier unconfigured",
                    "screenshot_ref": screenshot_ref,
                    "skipped_reason": "vision_unconfigured"}
    except Exception:
        return {"ok": None, "observation": "vision tier check failed",
                "screenshot_ref": screenshot_ref,
                "skipped_reason": "vision_check_error"}

    prompt = (
        f"You are verifying a browser action outcome. The agent expected: "
        f"\"{expectation}\". Look at the screenshot and answer in JSON: "
        f"{{ok: bool, observation: \"<≤200 char description of what is shown>\"}}."
    )
    try:
        resp = await vision_client.call_with_attachments(
            tier="vision",
            prompt=prompt,
            attachment_refs=[screenshot_ref],
        )
    except Exception:
        return {"ok": None, "observation": "vision tier call failed",
                "screenshot_ref": screenshot_ref,
                "skipped_reason": "vision_unavailable"}

    parsed = _parse_verify_response(resp)  # JSON.loads + key checks; honest-degrade on parse failure
    parsed["screenshot_ref"] = screenshot_ref
    parsed["skipped_reason"] = None

    emit_event(
        EventType.BROWSER_VERIFY_OBSERVED,
        {"session_id": session.id, "expectation": expectation,
         "ok": parsed["ok"], "screenshot_ref": screenshot_ref,
         "observation": parsed["observation"]},
    )
    return parsed
```

Builder: verify the exact method names on `attachment_store` (e.g., `put`, `store`, `write_bytes` — read `src/probos/attachments/store.py:14` `class AttachmentStore(Protocol):` for the real surface) and `vision_client` (read `src/probos/cognitive/llm_client.py:769-880`). Adjust signatures to match. Do NOT invent new client methods — reuse the BF-268 path.

---

## Section 2 — Register `verify` in the action dispatch

In `src/probos/tools/browser/actions.py` `classify_action` / `dispatch_action`:

- Add `"verify"` to the action enum / valid set.
- Classify tier: tier-1 (read-only, no Captain ACK needed; same tier as `screenshot`).
- Dispatch route to `action_verify`.

Single `replace_string_in_file` per edit (BF-274).

---

## Section 3 — Telemetry integration

The existing AD-706 audit log records `BROWSER_ACTION_EXECUTED` for every action. `verify` emits both:
1. `BROWSER_ACTION_EXECUTED` with `action="verify"` (the existing emit path).
2. `BROWSER_VERIFY_OBSERVED` with the result (new event from Section 0).

Add a verification-success-rate aggregation to the cognitive journal (per the issue body: *"Verification telemetry: pass/fail rate per agent + per task type surfaces into the Cognitive Journal as a new field. Useful for AD-674 graduated initiative calibration."*).

This is a single-line additive field on the journal entry — read `src/probos/cognitive/journal.py` (or wherever the journal lives) and add a `verifications_passed: int` / `verifications_failed: int` counter. If the journal aggregation is more invasive than a 5-line patch, defer to forward marker AD-706c-1a — DO NOT scope-creep this AD.

---

## Section 4 — Honest-degrade behavior

When vision tier is unavailable, `verify` returns `{ok: None, observation: "...", skipped_reason: "..."}`. The chain-of-thought integration should treat `ok=None` as "no information" — neither pass nor fail. The agent's next-cycle prompt receives the observation string in a `<BROWSER_VERIFICATION>` block so the agent can narrate the gap to the Captain.

NEVER raise from `verify`. The browser action sequence is the load-bearing primitive; verification is observability.

---

## Tests

`tests/test_ad706c_1_browser_verify.py` — 9 tests, real `SystemConfig()` per AD-722b-1a:

1. `test_verify_happy_path_ok_true` — fake vision LLM returns `{ok: true, observation: "Banner visible"}`; result correct, screenshot_ref non-None, event emitted.
2. `test_verify_happy_path_ok_false` — `{ok: false, observation: "Spinner still showing"}`.
3. `test_verify_missing_expectation_returns_skipped` — empty string → `skipped_reason="missing_expectation"`, no LLM call.
4. `test_verify_expectation_truncated_at_500_chars`.
5. `test_verify_vision_tier_unconfigured_returns_none` — `is_vision_tier_configured` returns False → `ok=None`.
6. `test_verify_llm_call_raises_returns_none` — fake LLM raises; `ok=None`, `skipped_reason="vision_unavailable"`.
7. `test_verify_screenshot_stored_as_ref_not_inline` — AD-731 invariant: screenshot stored via `AttachmentStore.put`, returned ref is a SHA-256 string.
8. `test_verify_emits_both_events` — `BROWSER_ACTION_EXECUTED` AND `BROWSER_VERIFY_OBSERVED` both emitted in happy path.
9. `test_verify_classified_as_tier_1` — `classify_action(session, "verify", params)` returns tier 1 (no Captain ACK).

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet.
- `docs/development/roadmap.md` — flip AD-706c-1 row to SHIPPED Wave 162. File forward markers: AD-706c-1a (journal aggregation for verification pass/fail rates — technical trigger: when AD-674 graduated-initiative calibration needs the signal), AD-706c-3 (cloud vision API integration — Anthropic computer-use beta — technical trigger: when an operator configures a cloud key AND opts in via explicit flag).
- `DECISIONS.md` — append entry.

---

## Acceptance criteria

- `verify` action lands in the BrowserTool action vocab; tier-1 classification.
- AD-731 invariant preserved (screenshot via `AttachmentStore.put`, ref returned, no inline bytes through the bus).
- BF-268 path reused (`_resolve_attachment_refs_for_openai` resolves the ref for the LLM call).
- Vision tier honest-degrade — `ok=None` when unavailable.
- New `EventType.BROWSER_VERIFY_OBSERVED` registered.
- 9 new pytest tests green at `-n 0` and parallel.
- Click-target prediction NOT introduced (defer #643).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `src/probos/tools/browser/tool.py:59-60` — `class BrowserTool` confirmed.
- `src/probos/tools/browser/tool.py:34` — `from probos.tools.browser.actions import classify_action, dispatch_action` confirmed.
- `src/probos/tools/browser/tool.py:212-260` — action dispatch path confirmed (`params.get("action")` → `classify_action` → `dispatch_action`).
- `src/probos/events.py:198-201` — existing BROWSER_* event types confirmed (BROWSER_ACTION_EXECUTED, BROWSER_SESSION_OPENED, BROWSER_SESSION_CLOSED).
- `src/probos/attachments/store.py:14` — `class AttachmentStore(Protocol):` confirmed.
- `src/probos/cognitive/llm_client.py:769` — `_resolve_attachment_refs_for_openai` confirmed.
- `src/probos/cognitive/vision_dispatch.py` — `is_vision_tier_configured` confirmed (referenced in `routers/agents.py:1447`).
- Roadmap AD-706c-1 line 338 confirms scope: read-only verification, builds on shipped primitives.
