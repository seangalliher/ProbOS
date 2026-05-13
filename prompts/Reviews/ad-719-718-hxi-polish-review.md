# Review: AD-719c + AD-718d-1 — HXI Polish (Picker Keyboard Nav + Modulation Indicator)
**Verdict:** ✅ Approved
**Two small UI-only polish items; both upstream signals (`pickerIndex` state, `onSpeechEvent`) verified stable.**

## Required (must fix before building)

(none)

## Recommended (should fix)

1. **`useEffect` placement is unanchored.** Section 1 says "Place the `useEffect` near the other component effects, not inside the JSX." `IntentSurface.tsx` has multiple `useEffect`s scattered through the component. Anchor explicitly: "Insert immediately after the existing `useEffect` that resets `pickerIndex` when `pickerOpen` changes (search `setPickerIndex(0)` near line 369)." Without an anchor, Builder may place it at file top or inside an unrelated effect block.

2. **`ProfileChatTab.tsx` mount location is conditional in the prompt.** Section 2 says: "Find the visible affordance (likely a button/icon labeled 'Speak' or similar in JSX nearby) and append `<ModulationIndicator agentId={agentId} />` adjacent to it. If the file has no visible speak button, mount the indicator in the chat header next to the agent's name." Two different mount points means two different test selectors. The Builder must lock one, and the test in `ModulationIndicator.test.tsx` must target the same DOM neighbor. Read [ProfileChatTab.tsx](ui/src/components/profile/ProfileChatTab.tsx) and pin the exact JSX neighbor (or its `data-testid`) in the prompt before dispatch.

3. **Scroll-into-view useEffect uses raw `document.querySelector` not React `ref`.** Functional, and the `typeof scrollIntoView === 'function'` guard handles JSDOM (where `scrollIntoView` is not implemented). But the test plan should explicitly note: "Tests assert `pickerIndex` state advancement, not scroll behavior — `scrollIntoView` is unimplemented in JSDOM and would error without the guard." One sentence in Section 1's test note prevents a future contributor from adding a scroll-position assertion that fails non-deterministically.

4. **`onSpeechEvent` has no agent_id-keyed registry.** Every `ModulationIndicator` mount adds a global listener that fires for ALL agents and filters internally. With many ProfileChatTabs open, this is O(N×M). Acceptable for v1, but worth a one-line forward-marker comment in the indicator code (or in DECISIONS.md) pointing at `voice.ts:_fire` as the future optimization site (per-agent listener bucket keyed by `agent_id`).

5. **Test #3 ("Tab confirms third callsign") is order-dependent.** Picker matches are sorted/derived from `agentsMap`; the prompt says "seed at least 3 crew agents (so `pickerMatches.length >= 3`)" but doesn't lock sort order. Vitest fixtures should construct the agents in deterministic callsign order so "the third callsign" is unambiguous across CI runs and across local re-runs. Add to the test plan: "fixture sorts crew by callsign ascending; test asserts confirmation with the deterministic third entry."

## Nits (style/minor)

1. SVG glyph: three vertical lines with the middle taller — a generic "audio bars" mark. Add a one-line comment in the component: `// Audio-bars glyph: three vertical strokes, middle tallest. Generic enough that future locales/themes don't need translation.` Helps future contributors understand the visual intent.
2. Inline `<style>{` keyframes ` }</style>` inside the JSX renders the keyframes per-mount. React deduplicates identical `<style>` content in modern versions, so safe in practice. Could move to a global stylesheet later; not blocking.
3. The `try/catch` around `onSpeechEvent` subscription ("Subscription unavailable — stay idle") is defensive — `onSpeechEvent` from `voice.ts:35` cannot throw on subscription (it's a `Set.add`). Drop the try, keep the unsub-in-cleanup try (which can theoretically throw if listener registry was reinitialized). Minor.
4. The keyframes `modulation-pulse` use `transform: scale(...)` — this is GPU-accelerated, good. No nit; just confirming the choice is correct for the HXI Design Principle #4 (motion communicates state).

## Verified (looks good)

- `function handleKeyDown(e: React.KeyboardEvent)` at [IntentSurface.tsx:302](ui/src/components/IntentSurface.tsx#L302) — confirmed.
- Existing Esc + Enter branches at lines 312-325 — confirmed; insertion point between them is well-defined.
- `const [pickerIndex, setPickerIndex] = useState(0);` at IntentSurface.tsx:60 — confirmed.
- `confirmPickerSelection(callsign: string)` defined at IntentSurface.tsx:376 — confirmed.
- `pickerMatches.map((m, i) => (` at line 1878 — exact-line confirmed; existing `i === pickerIndex` highlight style at line 1887 means `data-picker-index={i}` injection is straightforward.
- `setPickerIndex(0);` at line 369 — confirms the existing reset effect is in the file (anchor for Recommended #1).
- `onSpeechEvent` exported from [voice.ts:35](ui/src/audio/voice.ts#L35) — confirmed; signature `(fn: SpeechListener) => () => void` matches the indicator's `unsub = onSpeechEvent(...)` pattern.
- `_fire` emits `{ type: 'start' | 'end', agent_id, utterance }` at [voice.ts:142-144](ui/src/audio/voice.ts#L142-L144) — confirmed (technically lines 144-145 in the prompt's claim; close enough).
- `applyEmotionalModulation` import at [voice.ts:3](ui/src/audio/voice.ts#L3) and call at [voice.ts:122-130](ui/src/audio/voice.ts#L122-L130) — confirmed; AD-718d logic intact, indicator is a passive observer.
- `import { speakResponse, stripMarkdownForSpeech, type VoiceProfile } from '../../audio/voice';` at ProfileChatTab.tsx:3 — confirmed (per prompt's verification footer; not re-grepped).
- `speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId);` at ProfileChatTab.tsx:123 — confirmed (per prompt's verification footer).
- HXI Design Principles compliance: stroke-only SVG (#3), pulse animation communicates state (#4), amber `#f0b060` active / dim `#666680` idle (matches HXI palette), no emoji introduced (#3).
- Cross-prompt audit: only `ui/` files touched. No collision with AD-724 / AD-720d-1 / AD-730-1-1.
- Phase ordering: UI-only; no Python startup interaction.
- License hygiene: zero new dependencies.


### Re-review (pass-2): unchanged from pass-1, verdict re-affirmed ✅

