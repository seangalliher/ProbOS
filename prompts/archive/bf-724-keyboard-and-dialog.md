# BF-724: the approvals entry path cannot be operated from a keyboard

**Issue:** #1169 · **Epic:** #1162 · **Repo:** OSS (`d:\ProbOS`), branch `main`

## The defect

The only route to a pending approval is unreachable without a mouse.

`BridgePanel.tsx` — the collapsible header (`:44`), the expand affordance (`:75`) and the
approval row (`:148`) are clickable `div`/`span` elements with no role, no tab stop, no key
handler and no `aria-expanded`.

`ApprovalsCenterPanel.tsx:47` — the overlay root has no `role="dialog"`, no `aria-modal`, no
focus transfer or trap, and no Escape handling.

So a keyboard user reaches BRIDGE, and then cannot focus the approval or its expand control.
Approve and Deny are unreachable.

Verify each of those line numbers before editing — this file has changed since the finding was
written (AD-1201, BF-716, BF-723 all touched it).

## Why this is not merely a compliance checkbox

HXI Design Principle #1: the system understands the human, not the reverse. Principle #9: the
layout surfaces a pending decision so the Captain never has to dig for it. **A decision surface
that can be seen but not reached fails both.**

Approvals are also the highest-stakes control in the HXI — the one place a human authorises an
agent to act. AD-1211 just made approving actually *do* something for every request kind, which
raises the cost of an unreachable control rather than lowering it.

This is my gap: I shipped that section in AD-1201 and did not make it operable.

## Required change

1. Semantic `<button>` for the collapsible header, the expand affordance and the row action,
   with `aria-expanded` reflecting collapse state and an accessible name on each.
2. `role="dialog"` + `aria-modal="true"` on the approvals overlay, with an accessible name.
3. Focus moves into the overlay on open, is trapped while open, and returns to the control that
   opened it on close.
4. Escape dismisses the overlay.

## Preserve the visual language exactly

This is semantics and focus, not a restyle. Per HXI Principle #3 the aesthetic is
stroke-based SVG glyphs and the amber/blue/violet trust spectrum — **no emoji**, and no default
browser focus ring that breaks it. Use the existing amber (`#f0b060`) active treatment for the
focus indicator.

A `<button>` carries UA styles that a `<div>` does not (background, border, padding, font
inheritance). Reset them deliberately so the rendered output is unchanged — do not let the
markup change drag the appearance with it.

## Out of scope

- No backend changes. Zero `.py` staged.
- Do not change what the approval rows show or what the decision posts — #1166 owns the payload
  surfacing and #1167/#1164 own the decision semantics.
- Do not restyle, reorder or re-lay-out anything. If a visual test changes, that is a signal
  something went wrong, not something to update.

## Tests

Keyboard-driven, in the production mount path. **No `fireEvent.click` shortcuts** — the issue
notes every existing reachability test uses one, which is exactly why this was never caught.

1. Tab from BRIDGE to a pending approval, expand it, and activate Approve entirely by keyboard.
2. Both Enter and Space activate the semantic controls, per native button behaviour.
3. `aria-expanded` tracks the collapse state in both directions.
4. Escape closes the overlay.
5. Focus moves into the overlay on open and returns to the invoking control on close.
6. Focus does not escape the overlay while it is open — tab from the last focusable wraps.
7. The dialog and both decision controls have accessible names.
8. Rendered output is visually unchanged — assert the existing appearance/structure tests still
   pass untouched.

**Mutation-check every fix:** revert production, confirm the matching test fails, restore.

## Gates

- `cd ui && npx vitest run` — baseline **2,325 passed / 1 skipped across 320 files** (post-BF-723).
- `cd ui && npm run build` — **both required.** `tsc -b` has caught real errors repeatedly.
- Zero `.py` ⇒ Python gate correctly skipped. If any `.py` is staged, stop.

## Report back

- Which elements became buttons, and how the UA styles were neutralised.
- Both UI gate numbers.
- Any test that pinned the old markup — `App.bf710.test.tsx` asserts the BridgePanel JSX tree via
  a `?raw` import, so check it before editing. Update and explain inline, never delete.
- **Anything in this prompt that turned out to be untrue** — including any line number that has
  moved. The last four prompts each contained a wrong claim and saying so was the most valuable
  part of the report; one was disproved by mutation, which caught a guard I had wrongly called
  load-bearing.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
