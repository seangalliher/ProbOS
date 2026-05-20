# BF-317 — Share-screen button discoverability in DM thread

**Status:** drafted (Wave 180, builds **first** in the slate).
**Issue:** [#681](https://github.com/seangalliher/ProbOS/issues/681).
**Prior-art:** `prompts/RESEARCH-issues-2026-05-19.md` (Issue A — Slack /
Discord / Teams composer pattern, architecture-only absorption).
**Estimated work:** 1-2 h.
**Dependencies:** none (UI-only; ships ahead of BF-318 / AD-746 / AD-747).
**License posture:** zero new deps; pattern-level absorption from closed-
source composer UX. **0-line diff on all 5 license files.**

---

## Problem

The AD-744 "Share screen to {agent}" button **exists** in
`ui/src/components/wardroom/WardRoomThreadDetail.tsx` at the verified
anchor `data-testid="wardroom-dm-share-screen-button"` (line 397, button
element; `onClick={onShareScreen}` line 398; `aria-label="share screen
to agent"` line 400). The Captain didn't find it because:

1. The icon is a 14×14 stroke-SVG monitor glyph — visually identical
   in size + stroke weight + position to the paperclip attach button
   (`data-testid="wardroom-dm-attach-button"`, line 374; `aria-label=
   "attach file"`, line 376).
2. There is no visible text label — only `title` tooltip-on-hover.
3. The two buttons sit adjacent in the same composer toolbar with no
   separator or color cue distinguishing "attach a file" from
   "transmit my live screen."

This is **discoverability**, not absence. HXI Design Principle #1
("the system understands the human, not the reverse") is violated:
the operator should not have to hover every glyph to learn what the
composer can do.

## Scope (v1)

Three changes to `ui/src/components/wardroom/WardRoomThreadDetail.tsx`
only:

1. **Size + visual differentiation.** The share-screen button becomes
   visibly distinct from the attach button — larger (18×18 vs 14×14
   attach), filled monitor base + stroked screen surface (vs paperclip
   line-only), and amber active-state glow (`#f0b060`) per HXI #3.
2. **Persistent text label.** Render a `Share screen` text label
   beside the icon at all viewport widths. The attach button stays
   icon-only (file attach is a familiar pattern; screen-share is not).
3. **Position separator.** Insert a 1px vertical divider
   (`rgba(255,255,255,0.06)`) between the attach button and the
   share-screen button so the operator reads them as two distinct
   affordances.

All three changes are inside the existing share-screen `<button>`
element block at lines ~397-410; the surrounding chip-strip + textarea
+ submit-button layout is untouched.

## Non-scope

- NO new composer tool palette (forward marker BF-317-1 — only fires
  if more share-class affordances queue up, e.g. share-audio, share-
  clipboard).
- NO change to `onShareScreen` business logic at line 188.
- NO change to backend (`POST /api/perception/camera/frame` shipped by
  AD-733-2; `captureScreenShareFrame` shipped by AD-744 stays untouched).
- NO change to the `wardroom-dm-attach-button` glyph or `aria-label`.
- NO change to other `WardRoomThreadDetail.tsx` consumers (post list,
  attachment chip strip, paste/drop handlers, share-error fade).

## File targets

| File | Change |
|---|---|
| `ui/src/components/wardroom/WardRoomThreadDetail.tsx` | Three visual changes inside the existing share-screen button block (lines ~397-410). |
| `ui/src/__tests__/WardRoomThreadDetail.shareScreen.test.tsx` | +3 vitest. Existing file (verified present); extend, don't replace. |

**Zero backend changes.** Zero new files. Zero new deps.

## Test targets

**+3 vitest** in `ui/src/__tests__/WardRoomThreadDetail.shareScreen.test.tsx`:

1. `renders persistent "Share screen" text label beside the icon` —
   `getByText('Share screen')` resolves AND is inside the same button
   element as the existing `data-testid="wardroom-dm-share-screen-button"`.
2. `share-screen button is visually distinct from attach button` —
   asserts the share-screen button's computed `width` and the attach
   button's computed `width` differ (size differentiation) AND that the
   share-screen button's SVG has at least one `fill` attribute that is
   NOT `none` (the attach paperclip is stroke-only, line-only).
3. `divider element separates attach button from share-screen button` —
   between the two buttons, query for an element with `role="separator"`
   OR a `<span>` with explicit divider styling, and assert it is in the
   DOM tree between the two button anchors.

All three tests assert positive presence; none gates the existing
share-screen happy-path tests (the icon-click → callback wire-up is
preserved).

## Acceptance criteria

1. `cd ui; npx vitest run -t "ShareScreen"` — all existing tests pass +
   the 3 new tests pass.
2. `cd ui; npx vitest run` — full vitest gate green; no pre-existing
   test regressions.
3. `cd ui; npm run build` — exit 0; new UI bundle hash recorded.
   (BF-279 / AD-738b: `vitest` alone is insufficient.)
4. **Manual HXI smoke**: open a DM thread, glance at the composer
   without hovering, confirm the share-screen affordance is visible
   and labeled. Captain hard-refreshes (Ctrl+Shift+R) per the stale-
   bundle lesson.
5. **No changes outside the share-screen button block.** Reviewer
   confirms via `git diff` that the attach button, chip strip,
   textarea, submit button, and paste/drop handlers are byte-identical.
6. Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.

## Forward markers

- **BF-317-1** — Composer tool palette (collapsible `[+]` palette for
  attach/share-screen/share-audio/share-clipboard). Triggers when
  share-class affordances ≥ 3.

## Verified Against Codebase (2026-05-19)

```
grep -n "wardroom-dm-share-screen-button" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  397:              data-testid="wardroom-dm-share-screen-button"

grep -n "onClick={onShareScreen}" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  398:              onClick={onShareScreen}

grep -n 'aria-label="share screen to agent"' ui/src/components/wardroom/WardRoomThreadDetail.tsx
  400:              aria-label="share screen to agent"

grep -n "wardroom-dm-attach-button" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  374:              data-testid="wardroom-dm-attach-button"

grep -n 'aria-label="attach file"' ui/src/components/wardroom/WardRoomThreadDetail.tsx
  376:              aria-label="attach file"

grep -n "function onShareScreen" ui/src/components/wardroom/WardRoomThreadDetail.tsx
  188:  async function onShareScreen() {

ls ui/src/__tests__/WardRoomThreadDetail.shareScreen.test.tsx
  (file present)
```

All anchors confirmed at HEAD (`4beaba7e`).
