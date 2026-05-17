# AD-706e — Browser Tool action vocabulary v2

**Status:** Draft v1.
**Closes:** #520.
**Dependencies:** AD-706 (Wave 132 v1), AD-706c-1 (Wave 162), AD-706d (Wave 163 LLM classifier), AD-706c-2 (this wave — `compute_use_click`).
**Estimated tests:** +14 pytest (1 happy + 1 error per action). **0 new pip/npm deps.**

---

## Problem

The AD-706 v1 vocabulary has 10 verbs (+1 from AD-706c-1 `verify`, +1 from AD-706c-2 `compute_use_click`). Real browser automation needs more — drag-and-drop pickers, keyboard shortcut surfaces, file uploads, downloads, and direct DOM evaluation for edge cases the indexed-element approach cannot resolve.

## Solution

Add 7 new action verbs to `_HANDLERS` in `src/probos/tools/browser/actions.py`. Every verb is classified by BOTH `classify_action` (rule-based) AND must short-circuit correctly in `classify_action_with_llm` when needed (AD-706d compat).

### New verbs and tier classification

| Verb | Tier | Params | Notes |
|------|------|--------|-------|
| `drag` | 2 | `{from_selector, to_selector}` or `{from_index, to_index}` | Tier 3 if to_selector path matches tier-3 patterns. |
| `key_combo` | 2 | `{keys: list[str]}` (e.g. `["Control", "s"]`) | Tier 3 for `Control+w`, `Alt+F4` (denylist patterns). |
| `mouse_move` | 1 | `{x: int, y: int}` | Silent observation-equivalent (no state change). |
| `mouse_button` | 2 | `{button: "left"|"right"|"middle", action: "down"|"up"|"click"}` | Tier 3 on tier-3 hosts. |
| `upload_file` | 3 always | `{selector, file_path}` | AD-706f credential-vault integration in Section 4. |
| `download` | 2 | `{selector_or_url}` | Tier 3 for `.exe`/`.dll`/`.dmg` suffixes. |
| `eval_js` | 3 always | `{script: str}` | Highest risk; Captain ACK every call. |

### Section 0 — Event Types

Add to `event_log.py` EventType enum after `BROWSER_COMPUTE_USE_CLICK_EXECUTED`:

- `BROWSER_FILE_UPLOAD_REQUESTED` — upload_file invoked.
- `BROWSER_DOWNLOAD_REQUESTED` — download invoked.
- `BROWSER_EVAL_JS_EXECUTED` — eval_js executed (with truncated script preview).

`drag`, `key_combo`, `mouse_move`, `mouse_button` reuse existing per-action telemetry; no new event types.

### Section 1 — Handler implementations

In `src/probos/tools/browser/actions.py`, add 7 new async handlers following the existing pattern (each ~15-25 lines). Each handler:

- Validates required params; raises `ValueError` on missing/bad input.
- Acquires `session.page`; raises `RuntimeError` if not started.
- Wraps the Playwright call in the existing per-action timeout pattern.
- Returns a dict with `session_id` + action-specific fields.

Register all 7 in `_HANDLERS` via the late-bind block at the bottom of `actions.py` (AD-706c-2 added the `compute_use_click` entry there; extend it):

```python
===SEARCH===
# AD-706c-2: register coordinate-aware click after action_verify is defined
# (compute_use_click reuses action_verify for the Guard #9 handshake).
from probos.tools.browser.compute_use import action_compute_use_click  # noqa: E402
_HANDLERS["compute_use_click"] = action_compute_use_click
===REPLACE===
# AD-706c-2: register coordinate-aware click after action_verify is defined
# (compute_use_click reuses action_verify for the Guard #9 handshake).
from probos.tools.browser.compute_use import action_compute_use_click  # noqa: E402
_HANDLERS["compute_use_click"] = action_compute_use_click

# AD-706e: vocabulary v2. All 7 new handlers defined above in this module.
# fill_credential is added by AD-706f via a separate late-bind block (owns
# that slot). AD-706e is NO-OP for compute_use_click and fill_credential.
_HANDLERS["drag"] = _action_drag
_HANDLERS["key_combo"] = _action_key_combo
_HANDLERS["mouse_move"] = _action_mouse_move
_HANDLERS["mouse_button"] = _action_mouse_button
_HANDLERS["upload_file"] = _action_upload_file
_HANDLERS["download"] = _action_download
_HANDLERS["eval_js"] = _action_eval_js
===END REPLACE===
```

### Section 2 — `classify_action` tier rules

`src/probos/tools/browser/actions.py:550`. AD-706c-2 already inserted the `compute_use_click` short-circuit. AD-706f will insert the `fill_credential` short-circuit. AD-706e adds the other 6 verbs' tier rules and is NO-OP for `compute_use_click` and `fill_credential` (do NOT re-add).

```python
===SEARCH===
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
===REPLACE===
    # AD-706c-2: coordinate-aware click is always tier-3 (destructive click at
    # unverified pixel coordinate). Captain ACK required every call. Checked
    # BEFORE the silent/goto bands so AD-706e's later always-tier-3 set
    # extension is purely additive.
    if action == "compute_use_click":
        return 3
    # AD-706e: additional always-tier-3 verbs. Each verb has its own
    # short-circuit (vs a set membership) so AD-706f's fill_credential add
    # is a single new branch with no merge conflict on the set literal.
    if action == "upload_file":
        return 3
    if action == "eval_js":
        return 3
    silent = {"state", "screenshot", "wait", "extract_text", "scroll", "back", "forward", "verify", "mouse_move"}
    if action in silent:
        return 1
    if action == "goto":
        return 2
    # AD-706e: key_combo destructive-pattern check (Control+W, Alt+F4, etc.).
    if action == "key_combo":
        keys = params.get("keys") or []
        if isinstance(keys, list):
            joined = "+".join(str(k).lower() for k in keys)
            if joined in _KEY_COMBO_TIER_3_PATTERNS:
                return 3
        return 2
    # AD-706e: download URL/suffix check for executable types.
    if action == "download":
        target = params.get("selector_or_url") or ""
        if isinstance(target, str) and any(
            target.lower().endswith(suf) for suf in (".exe", ".dll", ".dmg", ".msi")
        ):
            return 3
        return 2
    # AD-706e: drag uses to_selector for tier-3 host/path checks below.
    if action not in {"click", "type", "drag", "mouse_button"}:
        return 2
===END REPLACE===
```

Add the new module constant near `_TIER_3_PATH_TOKENS` (verified at line 26):

```python
===SEARCH===
_TIER_3_PATH_TOKENS: tuple[str, ...] = (
===REPLACE===
# AD-706e: destructive keyboard combinations that always require Captain ACK.
_KEY_COMBO_TIER_3_PATTERNS: frozenset[str] = frozenset({
    "control+w", "control+q", "alt+f4", "control+shift+w",
})

_TIER_3_PATH_TOKENS: tuple[str, ...] = (
===END REPLACE===
```

**Ordering summary** (preserve current first-match semantics):

1. `compute_use_click` short-circuit (AD-706c-2 — slot owner; AD-706e/706f NO-OP).
2. `upload_file` / `eval_js` short-circuits (AD-706e — slot owner).
3. `fill_credential` short-circuit (AD-706f — slot owner; AD-706e NO-OP).
4. `silent` set (extended with `mouse_move`).
5. `goto`.
6. `key_combo` destructive-combo check.
7. `download` suffix check.
8. Drop-out gate (verbs that don't reach the URL/text checks below).
9. Existing `click` / `type` URL+text+host checks (now extended to `drag` and `mouse_button`).
10. Default tier 2.

### Section 3 — `classify_action_with_llm` compatibility

In `src/probos/tools/browser/llm_classifier.py`, no signature change. Verify behavior:

- Verbs that ALWAYS rule out as tier 3 (`upload_file`, `eval_js`, `compute_use_click`) short-circuit (the existing `if rule_tier >= 3: return rule_tier` gate handles it).
- New tier-1/2 verbs (`drag`, `key_combo`, `mouse_move`, `mouse_button`, `download`) flow through the LLM classifier and can be upgraded.

No code changes in `llm_classifier.py` required if the rule-based classifier is the gate (preferred). Add a single test asserting the new verbs are accepted by `classify_action_with_llm` without raising.

### Section 4 — `upload_file` + credential vault hook

`upload_file` accepts an optional `credential_ref: str | None` param. When set, the file path is **not** taken from disk directly. Instead, the handler calls `runtime.credential_vault.materialize_to_temp(credential_ref)` (AD-706f) which:

1. Decrypts the credential.
2. Writes to a `tempfile.NamedTemporaryFile(delete=False)`.
3. Returns the temp path.

The handler then uses that path with `page.set_input_files()` and deletes the temp file in `finally`. If `credential_vault` is None on runtime (AD-706f not shipped or disabled), the handler honest-degrades when `credential_ref` is set with `skipped_reason="credential_vault_unavailable"`.

This is a **forward-compatible hook** — AD-706f does not need to be merged before AD-706e; the `credential_ref` param simply degrades if the vault is missing. Build sequencing: AD-706f lands second; until then, `upload_file` accepts a literal `file_path` only.

### Section 5 — `eval_js` safety

Captain ACK is required (tier 3). Script length cap of 4096 chars at the handler boundary (raise ValueError above). Execution via `await page.evaluate(script)`. Result serialized through `json.dumps(default=str)`. Emit `BROWSER_EVAL_JS_EXECUTED` with truncated script preview (first 200 chars).

NO sandbox isolation in v1; the script runs in the Playwright page context. Operator's responsibility — `eval_js` is documented as Captain-supervised escape hatch only.

### Tests (`tests/test_ad706e_action_vocab_v2.py`)

For each new verb: happy path + error path = 14 tests minimum.

1-2. `test_drag_happy_path` + `test_drag_missing_selector_raises`
3-4. `test_key_combo_happy_path` + `test_key_combo_missing_keys_raises`
5-6. `test_mouse_move_happy_path` + `test_mouse_move_invalid_coord_raises`
7-8. `test_mouse_button_happy_path` + `test_mouse_button_invalid_action_raises`
9-10. `test_upload_file_happy_path_literal_path` + `test_upload_file_credential_ref_degrades_when_vault_missing`
11-12. `test_download_happy_path` + `test_download_missing_target_raises`
13-14. `test_eval_js_happy_path` + `test_eval_js_script_too_long_raises`

Additional classification tests (+6):

15. `test_classify_mouse_move_is_tier_1`
16. `test_classify_drag_default_tier_2`
17. `test_classify_drag_to_tier_3_host_is_tier_3`
18. `test_classify_key_combo_destructive_combo_is_tier_3` (Control+w)
19. `test_classify_upload_file_always_tier_3`
20. `test_classify_eval_js_always_tier_3`
21. `test_classify_action_with_llm_accepts_new_verbs` — sanity, no LLM call.
22. `test_classify_download_exe_suffix_is_tier_3`

Tests use real `BrowserToolConfig()` + dataclass `_FakeBrowserSession` (BF-287 — no MagicMock at substrate boundary). Playwright Page calls are stubbed via a `_FakePage` with assertable call recorders.

## What This Does NOT Change

- The existing 10 verbs (+ `verify`, + `compute_use_click`) unchanged.
- `classify_action` int 1/2/3 contract unchanged.
- `classify_action_with_llm` upgrade-only contract unchanged.
- AD-706f credential vault — `upload_file.credential_ref` is the hook; the vault itself ships in AD-706f.
- BrowserSession lifecycle, rate limiting, TTL unchanged.

## Tracking

- `PROGRESS.md` — Wave 166 entry.
- `docs/development/roadmap.md` — close #520.
- `DECISIONS.md` — append AD-706e listing the 7 new verbs + tier classifications.

Forward markers:
- AD-706e-1 — Vision-based form filling (text into coord-located field). Trigger per AD-706c-2c.
- AD-706e-2 — `eval_js` sandbox isolation via headless context isolation. Trigger: operator-reported eval_js misuse incident OR commercial-overlay request.
- AD-706e-3 — `download` to `AttachmentStore` (auto-write SHA-256). Trigger: AD-720b chat-attach lands and downloads need to surface as attachments.

## Acceptance Criteria

- 22 new tests green under serial + parallel gates.
- Full pytest gate: previous +N → ≥+22 from AD-706c-2 baseline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- BOTH `classify_action` AND `classify_action_with_llm` recognise all 7 new verbs (Wave 162 lesson — both classifiers must be updated; per `.github/copilot-instructions.md` AD-706d compat note).
- BF-274 standing rule: use single `replace_string_in_file` for adjacent edits in `_HANDLERS` and `classify_action`.
- No new pip/npm deps.

## Verified Against Codebase (2026-05-16)

```
grep -n "_HANDLERS" src/probos/tools/browser/actions.py
  329: _HANDLERS: dict[str, Any] = {

grep -n "def classify_action" src/probos/tools/browser/actions.py
  550: def classify_action(

grep -n "_TIER_3_PATH_TOKENS" src/probos/tools/browser/actions.py
  26: _TIER_3_PATH_TOKENS: tuple[str, ...] = (

grep -n "def classify_action_with_llm" src/probos/tools/browser/llm_classifier.py
  79: def classify_action_with_llm(

grep -n "if rule_tier >= 3:" src/probos/tools/browser/llm_classifier.py
  (in function body, line ~100 — short-circuit gate for already-destructive tier)
```

AD-706d compat note from `.github/copilot-instructions.md`: "AD-706d (Wave 162): `classify_action` unchanged; `classify_action_with_llm` companion. AD-706e new action verbs must be classified by both — verify they're added to both classifiers."
