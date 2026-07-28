# AD-1160 + BF-693 — let an agent act on a canvas web app (Word Online)

**Status:** Ready for Builder.
**Depends on:** AD-706 (BrowserTool), AD-706e (mouse verbs), AD-1052c (`forward_input`), AD-1158 (session binding).
**Unblocks:** the Captain's live test — an agent types "Hello World" into a Word Online document the Captain has open and logged into.

---

## 1. The problem, concretely

Word Online renders into a canvas (`<div id="WACViewPanel">`). There is no
`contenteditable`, no input element, no accessible role inside the document body.
Every element-scoped path fails there by construction:

- `_action_type` (`actions.py`) does `page.fill(selector, text)` — needs a
  fillable element. There isn't one.
- `_action_click` does `page.click(selector)` — needs a selector. `state` cannot
  supply one (see §4).

The primitives that *do* work were verified by hand against the Captain's live
document: move the mouse to a point inside the canvas, click, then
`keyboard.type(text, delay=...)`. The `delay` is load-bearing — Word drops
keystrokes typed with no inter-key delay.

AD-1052c's `forward_input` (`session.py`) already uses exactly these primitives
for the *human* path. The agent path cannot reach them.

## 2. Deliverable A — BF-693: `mouse_button` clicks the wrong place

`_action_mouse_button` (`src/probos/tools/browser/actions.py`, in
`_action_mouse_button`) currently ends:

```python
await mouse.click(0, 0, button=button) if not hasattr(mouse, "click_button") else await mouse.click_button(button)
```

Real Playwright's `Mouse` has **no `click_button` method**, so the `hasattr`
check is always False and every `action="click"` clicks at viewport coordinate
**(0, 0)** — while the docstring promises "at the current position". A
`mouse_move(x, y)` followed by `mouse_button(action="click")` therefore moves to
the target and clicks the top-left corner.

**Fix:** implement click-at-current-position as `await mouse.down(button=...)`
then `await mouse.up(button=...)`. That is the correct Playwright idiom, needs no
coordinates, and requires no new session state. Delete the `click_button`
branch — it is dead code for a method that does not exist.

Keep the expression-statement rewritten as a normal `if/else`; the current
`await X if cond else await Y` one-liner is an expression used as a statement and
is hard to read.

## 3. Deliverable B — AD-1160: a `key_type` action

New action `key_type` in the same `_HANDLERS` table.

```
params: {"text": str, "delay_ms": int | None}
```

- Types **free text at the current keyboard focus**. No selector, no element.
- `await keyboard.type(text, delay=delay_ms)` when `delay_ms` is a positive int;
  plain `await keyboard.type(text)` otherwise, so the default path stays
  identical to `forward_input`'s.
- Bound `text` length. Reuse `_FORWARD_TEXT_MAX` from `session.py` if it is
  importable without a cycle; otherwise define a module constant here and state
  why. Do **not** silently truncate without saying so in the result.
- `delay_ms`: reject `bool` (`isinstance(True, int)` is `True`), reject
  non-`int`, reject negative, cap at a sane ceiling (250 ms) so a malformed value
  cannot stall the event loop for minutes on a long string. Log-and-degrade to
  no-delay on an out-of-range value rather than raising — the type still
  succeeds, which is the honest outcome.
- No `keyboard` handle on the page ⇒ raise `RuntimeError` exactly as
  `_action_key_combo` does for the same condition. Be consistent with the
  sibling.
- Returns `{"session_id", "url", "typed": len(text)}`.

**Tier classification.** `key_type` mutates page state. In `classify_action` it
must be classified **exactly as `type` is** — tier 2 on ordinary hosts, tier 3
when the host matches `tier_3_domain_patterns`, when the URL path contains a
`_TIER_3_PATH_TOKENS` entry, or when the element-text rule fires. It must **not**
land in the tier-1 silent set. Add it beside `type` in whatever branch already
handles `type`; do not invent a parallel branch.

**Schema.** Add `key_type` to `BrowserTool.input_schema`'s action enum and add
`delay_ms` to the properties. The tool description currently says "10-action
vocabulary" while the enum holds 11 — correct that count as part of this change
and make it accurate for the new total.

## 4. Known-adjacent, explicitly OUT of scope

`_action_state` (`actions.py`) guards on `hasattr(page, "list_elements")`. Real
Playwright `Page` has no such method, so `state` returns an empty element list
against every real page and the whole index-based `click`/`type` flow has never
functioned in production. That is filed separately as **BF-692** and is **not**
fixed here — this AD deliberately routes around element discovery rather than
depending on it. Do not touch `_action_state`.

Also out of scope: `compute_use_click` (vision-driven, always tier 3);
`_BROWSER_LOOP_ACTIONS` (unchanged — assert it byte-identical); any UI file; any
router; the workstation launcher.

## 5. Acceptance criteria

- `tests/test_ad1160_canvas_actions.py`.
- **BF-693:** a test proving `mouse_button(action="click")` no longer touches
  `(0, 0)` — use a fake mouse recording calls, assert `down`/`up` at the position
  established by a prior `mouse_move`, and assert `click` is never called with
  `(0, 0)`. Include a regression test that would have failed before the fix.
- **`key_type`:** happy path; delay passed through when valid; delay omitted when
  absent; `bool`, negative, non-int and over-ceiling delays all degrade to
  no-delay with a warning; missing/non-str `text` raises `ValueError`; over-long
  text is bounded and says so; missing keyboard handle raises `RuntimeError`.
- **Tier:** a test asserting `classify_action(session, "key_type", ...)` returns
  the same tier as `type` for (a) an ordinary host, (b) a `tier_3_domain_patterns`
  host, (c) a URL path containing `checkout`. Run against the REAL classifier.
- A test asserting `_BROWSER_LOOP_ACTIONS` is unchanged.
- A test asserting the tool description's stated action count equals the actual
  length of the schema enum — so this cannot drift again (BF-690's lesson).
- Full type annotations on new public functions; log messages carrying what
  failed, why it matters, and what happens next.
- **Run the FULL suite.** Baseline **21,839 passed, 34 skipped**. Report the new
  count. A name-filtered run cannot prove blast radius.
- **Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.**

## 6. Commit

One commit covering both BF-693 and AD-1160 — they are one coherent capability
and splitting them would leave an intermediate commit where the new action exists
but coordinate clicking is still broken. Message via `git commit -F <file>`,
never inline `-m`. **Do not `git add config/system.yaml`** — it is skip-worktree
(`S`); verify with `git ls-files -v config/system.yaml` before staging. Do not
push; the Architect reviews first.
