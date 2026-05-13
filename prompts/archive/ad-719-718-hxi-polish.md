# AD-719c + AD-718d-1 — HXI Polish (Picker Keyboard Nav + Modulation Indicator)

**ADs:** AD-719c, AD-718d-1.
**GH issues closed:** [#548](https://github.com/seangalliher/ProbOS/issues/548), [#553](https://github.com/seangalliher/ProbOS/issues/553).
**Parent ADs:** AD-719 (mention picker v1), AD-718d (emotional voice modulation).
**Wave:** 154. **Estimated tests:** +6 Vitest. **Estimated wall-time:** ~2h.

---

## Solution Overview

Two small UI-only polish items, both already drafted as forward markers by their parent ADs:

1. **AD-719c (#548) — @-picker keyboard nav.** Today the picker has Enter + Esc (`IntentSurface.tsx:312-325`). The parent comment at line 1853 explicitly defers ↑/↓/Tab to AD-719c. Add `ArrowUp` / `ArrowDown` to move `pickerIndex`, `Tab` to confirm the highlighted match, plus visual scroll-into-view for the highlighted row.

2. **AD-718d-1 (#553) — modulation activity indicator.** AD-718d shipped the modulation logic but explicitly deferred the indicator (`decisions-era-4-evolution.md:5261-5265`: "shipping the indicator inside ProfileChatTab introduced enough Vitest harness scope to push the wave past blast-radius. Logic ships, indicator polish lands as AD-718d-1."). Add a small SVG dim-pulse overlay next to the speak surface in `ProfileChatTab` that pulses when `onSpeechEvent` fires `start` for the agent and fades on `end`. No backend signal needed — `voice.ts:speakResponse` already calls `applyEmotionalModulation` and emits start/end with `agent_id` (`voice.ts:144-145`).

Both items honor HXI Design Principles (no emoji; SVG glyphs only; motion communicates state).

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `ui/src/components/IntentSurface.tsx` | ~310–325 (handleKeyDown) | Add ArrowUp/ArrowDown/Tab cases. |
| `ui/src/components/IntentSurface.tsx` | ~1855–1900 (picker render) | Add `data-picker-index` + `ref` for scroll-into-view. |
| `ui/src/components/profile/ModulationIndicator.tsx` | NEW | ~50 LOC small SVG overlay. |
| `ui/src/components/profile/ProfileChatTab.tsx` | ~118–125 (around the existing `speakResponse` call) | Mount `<ModulationIndicator agentId={agentId} />` near the speak button. |
| `ui/src/__tests__/IntentSurface.pickerKeyboard.test.tsx` | NEW | 4 keyboard-nav tests. |
| `ui/src/__tests__/ModulationIndicator.test.tsx` | NEW | 2 indicator tests. |

No backend, no Python, no API additions.

---

## Section 1 — AD-719c: Keyboard nav in `handleKeyDown`

In `ui/src/components/IntentSurface.tsx`, the existing `handleKeyDown` (search for `function handleKeyDown(e: React.KeyboardEvent)`, currently at line 302) handles Esc + Enter. Insert ArrowDown/ArrowUp/Tab handling between Esc and Enter:

```typescript
function handleKeyDown(e: React.KeyboardEvent) {
  if (e.key === 'Escape') {
    // ... existing wake-word / picker close logic unchanged ...
    if (pickerOpen) {
      setPickerOpen(false);
      return;
    }
    setActive(false);
    setInput('');
    inputRef.current?.blur();
  }
  // AD-719c: Arrow keys cycle through matches.
  if (pickerOpen && pickerMatches.length > 0) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setPickerIndex((i) => (i + 1) % pickerMatches.length);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setPickerIndex((i) => (i - 1 + pickerMatches.length) % pickerMatches.length);
      return;
    }
    if (e.key === 'Tab') {
      e.preventDefault();
      confirmPickerSelection(pickerMatches[pickerIndex]?.callsign ?? pickerMatches[0].callsign);
      return;
    }
  }
  if (e.key === 'Enter' && pickerOpen && pickerMatches.length > 0) {
    e.preventDefault();
    confirmPickerSelection(pickerMatches[pickerIndex]?.callsign ?? pickerMatches[0].callsign);
  }
}
```

In the picker render block (search `pickerMatches.map((m, i)` at line 1878), tag each row with `data-picker-index={i}` so the test can assert highlight movement, and add a `useEffect` that scrolls the highlighted row into view:

```typescript
// AD-719c: scroll the highlighted row into view as ArrowUp/ArrowDown advance.
useEffect(() => {
  if (!pickerOpen) return;
  const el = document.querySelector(`[data-picker-index="${pickerIndex}"]`);
  if (el && typeof (el as HTMLElement).scrollIntoView === 'function') {
    (el as HTMLElement).scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}, [pickerOpen, pickerIndex]);
```

(Place the `useEffect` near the other component effects, not inside the JSX.)

---

## Section 2 — AD-718d-1: Modulation indicator

Create `ui/src/components/profile/ModulationIndicator.tsx`:

```typescript
import { useEffect, useState } from 'react';
import { onSpeechEvent } from '../../audio/voice';

interface Props {
  agentId: string;
}

/**
 * AD-718d-1: small SVG dim-pulse overlay that signals when the voice
 * modulation logic from AD-718d is actively shaping a speech utterance
 * for the given agent. Subscribes to onSpeechEvent — pulses on `start`
 * fades on `end`. Tier-2 log-and-degrade: subscription failures fall
 * through silently and the indicator stays in idle state.
 *
 * HXI principles:
 *  - No emoji; stroke-only SVG glyph.
 *  - Motion communicates state (pulse = active, fade = idle).
 *  - Amber active (#f0b060), dim inactive (#666680).
 */
export function ModulationIndicator({ agentId }: Props) {
  const [active, setActive] = useState(false);

  useEffect(() => {
    let unsub: (() => void) | null = null;
    try {
      unsub = onSpeechEvent((evt) => {
        if (evt.agent_id !== agentId) return;
        if (evt.type === 'start') setActive(true);
        if (evt.type === 'end') setActive(false);
      });
    } catch {
      // Subscription unavailable — stay idle.
    }
    return () => {
      if (unsub) {
        try { unsub(); } catch { /* noop */ }
      }
    };
  }, [agentId]);

  const stroke = active ? '#f0b060' : '#666680';
  const filter = active ? 'drop-shadow(0 0 4px #f0b060)' : 'none';
  return (
    <span
      data-testid="modulation-indicator"
      data-active={active ? 'true' : 'false'}
      title={active ? 'voice modulation active' : 'voice modulation idle'}
      style={{
        display: 'inline-flex',
        width: 14,
        height: 14,
        marginLeft: 6,
        opacity: active ? 1 : 0.5,
        transition: 'opacity 200ms ease',
        animation: active ? 'modulation-pulse 1.2s ease-in-out infinite' : 'none',
        filter,
      }}
    >
      <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true">
        {/* Three vertical bars, the middle taller — a generic "audio" glyph. */}
        <line x1="3"  y1="9" x2="3"  y2="5" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="7"  y1="11" x2="7"  y2="3" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="11" y1="9" x2="11" y2="5" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <style>{`
        @keyframes modulation-pulse {
          0%, 100% { transform: scale(1); }
          50%      { transform: scale(1.18); }
        }
      `}</style>
    </span>
  );
}
```

In `ui/src/components/profile/ProfileChatTab.tsx`, import the indicator and place it next to the existing speak surface. The current `speakResponse(...)` call is at line 123. Find the visible affordance (likely a button/icon labeled "Speak" or similar in JSX nearby) and append `<ModulationIndicator agentId={agentId} />` adjacent to it. If the file has no visible speak button, mount the indicator in the chat header next to the agent's name so the operator always sees it during a session.

Update the import section near line 3:

```typescript
import { ModulationIndicator } from './ModulationIndicator';
```

---

## What This Does NOT Change

- The `applyEmotionalModulation` logic (AD-718d). The indicator is a passive observer.
- `voice.ts` API surface. `onSpeechEvent` is already a stable export (used by `ProfileChatTab` and tests).
- Picker filtering / dedup / display logic. Only keyboard handlers and the highlighted-row scroll change.
- Picker visual layout. No new icons, no color changes.
- No emoji introduced (HXI Principle #3).
- No new event types, no backend changes.

---

## Test Plan

### `ui/src/__tests__/IntentSurface.pickerKeyboard.test.tsx` (4 tests)

Render `<IntentSurface />` with a Zustand store seeded with at least 3 crew agents (so `pickerMatches.length >= 3`). Type `@e` to open the picker.

1. **`ArrowDown advances pickerIndex`** — happy path. Fire `keyDown({ key: 'ArrowDown' })`; assert the `data-picker-index="1"` row has the active style class (or the `pickerIndex` derived attribute).
2. **`ArrowUp wraps to last when at top`** — edge. From index 0, ArrowUp → expect index `pickerMatches.length - 1`.
3. **`Tab confirms highlighted match`** — happy path. ArrowDown twice, Tab → assert `confirmPickerSelection` was called with the third callsign and the picker closed.
4. **`Enter still confirms (backward compat)`** — regression: ArrowDown, Enter → confirm.

### `ui/src/__tests__/ModulationIndicator.test.tsx` (2 tests)

Use Vitest's fake timers. Stub `onSpeechEvent` via the existing `voice` module mock pattern (search `vi.mock('../audio/voice'` in existing tests for the shape).

1. **`pulses while speech is active for the agent`** — fire a `start` event with matching `agent_id` → assert `data-active="true"`. Fire `end` → assert `data-active="false"`.
2. **`ignores events for other agents`** — fire `start` with a different `agent_id` → assert `data-active` stays `"false"`.

---

## Verification commands

```powershell
cd ui
npx vitest run src/__tests__/IntentSurface.pickerKeyboard.test.tsx src/__tests__/ModulationIndicator.test.tsx
npx vitest run
```

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` AND the HXI Design Principles in the same file (no emoji; SVG stroke-only glyph; motion communicates state; amber active / dim idle).

---

## Tracker Updates

- **PROGRESS.md**: bump UI Vitest count; bullet under Wave 154.
- **DECISIONS.md**: append `### AD-719c` and `### AD-718d-1` (one paragraph each).
- **docs/development/roadmap.md**: mark #548 and #553 closed.

---

## Verified Against Codebase (2026-05-12)

```
grep -n "function handleKeyDown" ui/src/components/IntentSurface.tsx
  302:  function handleKeyDown(e: React.KeyboardEvent) {
grep -n "AD-719: Esc on the input also closes the @-picker" ui/src/components/IntentSurface.tsx
  312:      // AD-719: Esc on the input also closes the @-picker (a no-op for v1
grep -n "pickerMatches.map((m, i)" ui/src/components/IntentSurface.tsx
  1878:                  {pickerMatches.map((m, i) => (
grep -n "import.*speakResponse" ui/src/components/profile/ProfileChatTab.tsx
  3: import { speakResponse, stripMarkdownForSpeech, type VoiceProfile } from '../../audio/voice';
grep -n "speakResponse(stripMarkdownForSpeech" ui/src/components/profile/ProfileChatTab.tsx
  123:        speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId);
grep -n "applyEmotionalModulation" ui/src/audio/voice.ts
  3:   import { applyEmotionalModulation } from './voiceModulation';
  123:       effective = applyEmotionalModulation(
grep -n "onSpeechEvent" ui/src/audio/__tests__/voice.test.ts
  93:    const { speakResponse, onSpeechEvent } = await import('../voice');
grep -n "AD-718d-1 - modulation activity indicator" decisions-era-4-evolution.md
  5264: deferred forward marker
```
