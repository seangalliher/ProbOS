# AD-718d — Emotional voice modulation (v1)

**Wave:** 136
**Depends on:** AD-718 (SHIPPED Wave 133, voice-profile baseline), AD-721 (SHIPPED Wave 133, `AgentSignals` selector), AD-718a (paired AD, ships FIRST in this wave at commit N — see §10)
**Issue:** [#525](https://github.com/seangalliher/ProbOS/issues/525)
**Risk:** LOW (browser-only pure-function modulation + small integration with existing call sites)
**Estimated tests:** ≥ 10 Vitest. Zero Python tests.

> **Build order is HARD:** AD-718a ships at commit N. This prompt ships at commit N+1. Do NOT begin this prompt until the AD-718a gate is fully green.
>
> **Builder:** read `prompts/WAVE-136-DISPATCH.md` for cross-AD context, license posture, and the engineering-principles checklist. Read `prompts/BUILDER-EXECUTION-PLAN.md` for the standing test-gate command. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

At speak-time, modulate `pitch` / `rate` / `volume` based on the live `AgentSignals` channel that AD-721 already feeds the avatar (`trust_delta`, `load`, `working_state`, `tier3_alert`). Voice and avatar **align by sourcing the same selector** — when Counselor's `trust_delta > 0.2`, her avatar smiles AND her voice pitches up slightly; same input, two surfaces.

**Browser-only.** Zero server changes. Modulation is a multiplicative factor on top of the agent's baseline `VoiceProfile`, **clamped** to Web Speech API bounds (`pitch ∈ [0, 2]`, `rate ∈ [0.1, 10]`, `volume ∈ [0, 1]`) AND to `VoiceProfile` validator bounds before the utterance is constructed.

## 2. Why now

- Wave 133 closed AD-721 and exposed `AgentSignals` as the canonical signal channel.
- AD-718a (paired AD, commit N) has just landed agent-authored voice profiles. Modulation closes the loop: the agent picks its baseline voice, and the runtime channel tints it with live emotional state.
- Voice + avatar alignment was a Cluster A goal; AD-718d is the surface that closes it.

## 3. Verified Against Codebase (2026-05-09)

```
grep -n "speakResponse" ui/src/audio/voice.ts
   20: agent_id?: string;     // present iff caller passed one to speakResponse
   92: export function speakResponse(
   94:   profile?: VoiceProfile,
   95:   ... agentId?: string)
  103: utterance.rate   = profile?.rate   ?? 0.95;
  104: utterance.pitch  = profile?.pitch  ?? 0.9;
  105: utterance.volume = profile?.volume ?? 0.8;

grep -n "AgentSignals\|deriveAgentSignals" ui/src/components/profile/avatarSignals.ts
   11: export interface AgentSignals {
   12:   trust_delta: number;       // last cycle trust delta, [-1, +1]
   13:   load: number;              // 0..1 (1 = LLM call active)
   14:   working_state: 'idle' | 'responding' | 'blocked';
   15:   tier3_alert: boolean;
   26: export function deriveAgentSignals(agentId, store): AgentSignals

grep -rn "speakResponse(" ui/src --include=*.tsx --exclude-dir=__tests__
  ProfileChatTab.tsx:98       speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId);
  ProfileInfoTab.tsx:297      (voice-test sample button)
  DecisionSurface.tsx:207
  IntentSurface.tsx:201
  IntentSurface.tsx:225

grep -n "applyExpressionsFromSignals" ui/src/components/profile/CrewVRM.tsx
   95: function applyExpressionsFromSignals(signals: AgentSignals, ...)
```

**Dispatch corrections folded in:**

- Dispatch §2 row claimed `working_state: 'idle' | 'thinking' | 'busy' | 'responding'` (4 values). **HEAD reality:** `'idle' | 'responding' | 'blocked'` (3 values, defined at `avatarSignals.ts:14`). Captain's modulation table uses `'responding'` and `'blocked'` only — both present at HEAD. ✓
- Dispatch §2 row called the selector `selectAgentSignals(state, agentId)` at L41-L48. **HEAD reality:** the exported helper is `deriveAgentSignals(agentId, store)` at `avatarSignals.ts:26`, and there is no `selectAgentSignals` symbol. The prompt cites `deriveAgentSignals` and the existing `useStore` snapshot pattern.
- Dispatch §5 E2 specified gain-based constants (e.g. `TRUST_DELTA_PITCH_GAIN = 0.15`). **Captain override (per dispatch reply Q on scope):** Captain's modulation table is **threshold-based multiplicative factors**, not gain proportional to signal magnitude. See §5 for the canonical rule set.

## 4. Scope (v1 only)

E1–E7 below. Pure-function modulation in a new module; small integration into `speakResponse`; tiny stroke-based amber indicator next to the per-agent speaker icon when modulation diverges meaningfully from baseline.

## 5. Non-goals (deferred forward markers)

- **AD-718d-1** — modulation activity indicator polish if v1 indicator UX needs more work (e.g. dwell time, multi-axis visualization, threshold tuning). v1 ships a single stroke-based amber dot that brightens when ANY of pitch / rate / volume diverge > 5% from baseline.
- **AD-722** ([#545](https://github.com/seangalliher/ProbOS/issues/545)) — agent self-state telemetry. AD-718d does NOT depend on it; AD-722 will deepen the channel later without changing the contract (Captain Q3 ruling: selector-agnostic).
- **Per-domain emotional profiles** (e.g. Engineering louder than Medical) — out of scope.
- **Modulation history / replay** — modulation is transient per utterance; not persisted.
- **Server-side modulation** (e.g. trust-delta-aware `propose_voice_profile`) — out of scope; modulation is browser-only.

## 6. Deliverables

### E1 — Pure modulation function

**New file:** `ui/src/audio/voiceModulation.ts`.

```ts
import type { VoiceProfile } from './voice';
import type { AgentSignals } from '../components/profile/avatarSignals';

/**
 * AD-718d: Apply emotional modulation to a baseline VoiceProfile.
 *
 * Pure function. No DOM access, no store access, no side effects.
 * Returns a NEW profile-shaped object. Input is never mutated.
 *
 * Rules (Captain-canonical, see §5 of prompt):
 *   working_state === 'responding' → rate × 1.05
 *   working_state === 'blocked'    → rate × 0.92, pitch × 0.95
 *   trust_delta > 0.2              → pitch × 1.03
 *   trust_delta < -0.2             → pitch × 0.97
 *   tier3_alert                    → rate × 1.15, volume × 1.05
 *
 * All output values are clamped to BOTH:
 *   - Web Speech API bounds: pitch ∈ [0, 2], rate ∈ [0.1, 10], volume ∈ [0, 1]
 *   - VoiceProfile validator bounds (same numbers — single source of truth).
 *
 * `voice_name` is passed through unchanged.
 */
export function applyEmotionalModulation(
  profile: VoiceProfile,
  signals: AgentSignals,
): VoiceProfile;
```

**Constants** (defined at the top of the module, exported for the test file and the indicator in E5):

```ts
export const MODULATION_DIVERGENCE_THRESHOLD = 0.05; // 5% — see E5
export const PITCH_BOUNDS: readonly [number, number] = [0, 2];
export const RATE_BOUNDS: readonly [number, number] = [0.1, 10];
export const VOLUME_BOUNDS: readonly [number, number] = [0, 1];
```

**Implementation rules:**

- Read defaults from the input profile via `profile.pitch ?? 0.9`, `profile.rate ?? 0.95`, `profile.volume ?? 0.8`. Captain-baseline matches `VoiceProfile` defaults at `voice.ts:9-11`.
- Apply each rule in §5 multiplicatively (rules compose — `working_state === 'responding'` AND `tier3_alert` BOTH apply rate gains).
- Clamp every output number with `Math.max(min, Math.min(max, value))` against the bounds constants above.
- Return a fresh object: `{ voice_name, pitch, rate, volume }`. Do NOT mutate `profile`.

**Forbidden:** `eval`, `Function(...)`, dynamic import, store access, DOM access, `console.*`. Module is pure data-in / data-out.

### E2 — `hasMeaningfulModulation` helper for the indicator

In the same `voiceModulation.ts` module:

```ts
/**
 * AD-718d: Returns true iff the modulated profile diverges from the baseline
 * by more than MODULATION_DIVERGENCE_THRESHOLD in pitch, rate, or volume.
 *
 * Used by the modulation indicator (E5) to flicker only when modulation
 * is perceptible. Pure function.
 */
export function hasMeaningfulModulation(
  baseline: VoiceProfile,
  modulated: VoiceProfile,
): boolean;
```

Returns `true` if `Math.abs(modulated.pitch - baseline.pitch) / baseline.pitch > 0.05` OR same for rate / volume. Guards against zero-division on weirdly-defaulted baselines (treat zero baseline as "always meaningful if modulated is non-zero").

### E3 — `speakResponse` integration

**Modify:** `ui/src/audio/voice.ts` `speakResponse` at L92-L110.

```
===SEARCH===
export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agentId?: string,
): void {
  // ... existing utterance assembly ...
  utterance.rate   = profile?.rate   ?? 0.95;
  utterance.pitch  = profile?.pitch  ?? 0.9;
  utterance.volume = profile?.volume ?? 0.8;
===REPLACE===
export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agentId?: string,
): void {
  // ... existing utterance assembly ...
  // AD-718d: read AgentSignals from store and apply emotional modulation
  // before assigning to the utterance. Read ONLY when an agentId is passed.
  let effective: VoiceProfile = profile ?? { voice_name: '', pitch: 0.9, rate: 0.95, volume: 0.8 };
  if (agentId) {
    try {
      const store = useStore.getState();
      const signals = deriveAgentSignals(agentId, store);
      effective = applyEmotionalModulation(effective, signals);
    } catch {
      // Tier-2 log-and-degrade: any signals-read failure falls back to
      // unmodulated baseline. Speaking should NEVER fail because of
      // modulation. (Existing tests must pass without store wiring.)
    }
  }
  utterance.rate   = effective.rate   ?? 0.95;
  utterance.pitch  = effective.pitch  ?? 0.9;
  utterance.volume = effective.volume ?? 0.8;
===END REPLACE===
```

Add the necessary imports at the top of `voice.ts`:

```ts
import { applyEmotionalModulation } from './voiceModulation';
import { deriveAgentSignals } from '../components/profile/avatarSignals';
import { useStore } from '../store/store';  // verify exact path at HEAD before writing
```

**Verify** the `useStore` import path at HEAD before committing — if it differs from `../store/store`, follow the path used by other UI modules that read store snapshots outside React components.

**Backward compatibility:**

- Calls without `agentId` → unchanged behavior (no modulation, no signals lookup).
- Calls with an `agentId` but no store wiring (existing tests in `ui/src/__tests__/voice.test.ts` and `ui/src/audio/__tests__/voice.test.ts`) → the `try/catch` swallows the missing-store error and falls back to unmodulated values. Existing tests must remain green.

### E4 — Wire signals at the call site (no-op for v1)

**HEAD reality:** `speakResponse` already accepts `agentId` as the third argument. Existing call sites that already pass an `agentId` (`ProfileChatTab.tsx:98`) automatically get modulation through E3's internal lookup. **No code change required at the call sites.** This deliverable is a documentation marker — Builder confirms in the build report that the four production call sites (`ProfileChatTab.tsx:98`, `ProfileInfoTab.tsx:297`, `DecisionSurface.tsx:207`, `IntentSurface.tsx:201,225`) were inspected and either:

- Already pass an `agentId` → modulation lights up automatically.
- Cannot determine an `agentId` (e.g. Ship's Computer fallback) → pass `undefined`, behavior unchanged.

If any call site needs to start passing `agentId` AND it has the value in scope, the Builder may add it; if it requires plumbing `agentId` through new prop/state surfaces, defer that to its own AD.

### E5 — Modulation indicator

**Modify:** `ui/src/components/profile/ProfileChatTab.tsx`. Add a tiny stroke-based amber indicator next to the per-agent speaker toggle (the comment at L185 marks the location).

Indicator semantics:

- **Inactive (no meaningful modulation):** dim `#666680`, low opacity (`0.3`), static. The dot is barely visible — present but receding.
- **Active (meaningful modulation):** amber `#f0b060`, full opacity, breathing animation (CSS `@keyframes` 1.2s loop, opacity `0.6 ↔ 1.0`). Per HXI Design Principle #4 — motion communicates state.
- **Threshold:** `hasMeaningfulModulation(baseline, modulated)` returns `true`. Use `MODULATION_DIVERGENCE_THRESHOLD = 0.05` (5% in any of pitch / rate / volume).

Implementation pattern:

- Compute `signals = deriveAgentSignals(agentId, useStore())` reactively in the component.
- Compute `modulated = applyEmotionalModulation(currentVoiceProfile, signals)`.
- Render a 6×6px inline SVG circle with `strokeWidth: 1.5`, `strokeLinecap: round`, NO fill. Color and animation per state above.
- Place adjacent to (within ~8px of) the per-agent speaker toggle.

**No emoji.** Reviewer greps the diff for emoji codepoints (U+1F000–U+1FFFF, U+2600–U+27BF) and fails on any hit.

If wiring the indicator into `ProfileChatTab.tsx` materially complicates the Vitest harness or pushes the Builder past the wave's blast-radius, **defer to AD-718d-1** and ship the rest of E1–E4 + E6–E7. Document the defer in the build report; file the AD-718d-1 forward marker.

### E6 — Tests (pure function)

**New file:** `ui/src/__tests__/voiceModulation.test.ts` (≥ 8 tests).

- `test_idle_signals_return_baseline` — `signals = {trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false}` → output numerically equal to input (no rules trigger). `voice_name` preserved.
- `test_responding_state_increases_rate` — `working_state: 'responding'` → `rate = baseline.rate * 1.05`. Pitch / volume unchanged (within float tolerance).
- `test_blocked_state_lowers_rate_and_pitch` — `working_state: 'blocked'` → `rate = baseline.rate * 0.92`, `pitch = baseline.pitch * 0.95`. Volume unchanged.
- `test_high_trust_delta_raises_pitch` — `trust_delta: 0.3` → `pitch = baseline.pitch * 1.03`.
- `test_low_trust_delta_lowers_pitch` — `trust_delta: -0.3` → `pitch = baseline.pitch * 0.97`.
- `test_trust_delta_within_threshold_no_change` — `trust_delta: 0.15` → no pitch change (threshold is `> 0.2` and `< -0.2`).
- `test_tier3_alert_raises_rate_and_volume` — `tier3_alert: true` → `rate = baseline.rate * 1.15`, `volume = baseline.volume * 1.05` (clamped if needed).
- `test_combined_signals_compose_multiplicatively` — `working_state: 'responding'` + `tier3_alert: true` → `rate = baseline.rate * 1.05 * 1.15`.
- `test_clamp_pitch_upper` — baseline `pitch: 1.95`, rule that pushes to 2.5 → output clamped to `2.0`.
- `test_clamp_pitch_lower` — baseline `pitch: 0.05`, rule that pushes negative → output clamped to `0`.
- `test_clamp_rate_lower` — baseline `rate: 0.11`, blocked + low rate → output clamped to `0.1`.
- `test_clamp_volume_upper` — baseline `volume: 0.99`, tier3 → output clamped to `1.0`.
- `test_input_not_mutated` — input profile reference is structurally unchanged after call.
- `test_voice_name_passed_through` — `voice_name: "Aria"` preserved unchanged.
- `test_counselor_worked_example` — **Captain-canonical worked example.** Baseline (Counselor / Echo / Troi): `{voice_name: "", pitch: 1.05, rate: 0.92, volume: 0.85}`. Signals: `{trust_delta: 0.3, load: 0, working_state: 'responding', tier3_alert: false}`. Expected: pitch ≈ `1.05 * 1.03 ≈ 1.0815`, rate ≈ `0.92 * 1.05 ≈ 0.966`, volume = `0.85` (unchanged). All values within Web Speech API bounds. **This is the Builder's smoke test for "did the math come out right."**
- `test_hasMeaningfulModulation_below_threshold_returns_false` — modulated diverges 3% in pitch only → `false`.
- `test_hasMeaningfulModulation_above_threshold_returns_true` — modulated diverges 6% in rate only → `true`.

### E7 — Tests (integration with `speakResponse`)

**New file:** `ui/src/__tests__/voice.speakResponse.modulation.test.ts` (≥ 3 tests).

- `test_speakResponse_without_agentId_unmodulated` — `speakResponse('hello', {pitch: 1.0, rate: 1.0, volume: 1.0})` → utterance receives `pitch=1.0, rate=1.0, volume=1.0` (no modulation path taken).
- `test_speakResponse_with_agentId_applies_modulation` — wire a mock store (Vitest `vi.mock('../store/store', ...)` or equivalent) so `useStore.getState()` returns a state with `agents` containing an agent in `state: 'active'` and `processing: true` (drives `working_state: 'responding'`). `speakResponse('hi', {pitch: 1.0, rate: 1.0, volume: 1.0}, 'counselor')` → utterance receives modulated `rate ≈ 1.05`.
- `test_speakResponse_with_agentId_but_no_store_falls_back` — mock `useStore.getState()` to throw; `speakResponse(...)` does NOT throw, utterance receives unmodulated baseline. (Tier-2 log-and-degrade verification.)

If the existing Vitest harness for `voice.test.ts` already mocks Web Speech API plumbing (`SpeechSynthesisUtterance`), reuse that pattern. Verify before drafting test code.

## 7. Hard-stop conditions (verbatim from `WAVE-136-DISPATCH.md` §8)

1. **Phantom API.** A grep of any asserted method/class/endpoint at HEAD returns zero matches AND the prompt does not introduce it. The NEW symbols introduced by this prompt (`applyEmotionalModulation`, `hasMeaningfulModulation`, `MODULATION_DIVERGENCE_THRESHOLD` and bounds constants) are **introduced by this prompt**; flagging them as missing is a false positive.
2. **Architectural contract change required.** Any change to `VoiceProfile`'s public shape, to `AgentSignals` (`avatarSignals.ts:11-23`), to `speakResponse`'s signature beyond the internal modulation step, or to `CognitiveAgent`'s base contract is a **hard stop**. AD-718d layers ON TOP of `AgentSignals` and `speakResponse`; it does NOT modify their public types.
3. **Pydantic vs dataclass tension.** N/A — no server-side change.
4. **Working tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5`. Any tracked file with > 200 lines deleted that the Builder did not author is a stop-the-line event.
5. **Test gate failure under `-n 0` after passing under `-n 16`.** Order-dependent test pollution. Quarantine via BF entry pointing at AD-682; do NOT block the wave.
6. **License creep.** Any new third-party JS dep is a hard stop. Wave 136's license posture is "zero new deps."
7. **Emoji in diff.** Any emoji literal in `*.tsx` / `*.ts` of the diff is a hard stop. The indicator MUST be inline SVG. HXI Design Principle #3.
8. **Modulation writes to trust.** Any import of `consensus/trust`, `consensus/quorum`, or any trust-update helper from `voice.ts` / `voiceModulation.ts` is a hard stop. Modulation is read-only on signals; trust state is NEVER updated by modulation.
9. **`exec` / `eval` / `Function(...)` / dynamic import in `voiceModulation.ts`.** Hard stop. The module is pure data-in / data-out.
10. **Modulation pushes a value past Web Speech API bounds without clamping.** If a test inputs a baseline at `pitch: 1.99` plus signals that push it to `2.05` and the resulting utterance receives `2.05` (un-clamped), hard stop — defense-in-depth has been weakened.

## 8. Forward markers

- **AD-718d-1** — modulation indicator polish if v1 indicator (E5) is deferred or feedback indicates UX needs more work (e.g. dwell time, multi-axis visualization, threshold tuning, animation language). File at gate-3 if indicator was deferred OR if Captain feedback flags v1 indicator as insufficient.
- **AD-722** ([#545](https://github.com/seangalliher/ProbOS/issues/545)) — agent self-state telemetry. AD-718d benefits silently if AD-722 deepens `AgentSignals` (selector contract unchanged per Captain Q3 ruling).

## 9. What this AD does NOT change

- `VoiceProfile` shape (consumed read-only).
- `AgentSignals` shape (consumed read-only via `deriveAgentSignals`).
- `speakResponse` signature — already accepts `(text, profile?, agentId?)` at HEAD (voice.ts:92-95). The internal body changes; the public type does NOT.
- Any server-side endpoint, dataclass, or persistence layer.
- The avatar expression layer (`applyExpressionsFromSignals` at `CrewVRM.tsx:95-129`) — voice modulation is a sibling consumer, not a coupled consumer.
- Trust state. Modulation is purely a read consumer of signals; never writes back.

## 10. Build order

**This prompt ships SECOND (commit N+1).** AD-718a is commit N. Do NOT begin this prompt until:

1. AD-718a's Python and Vitest gates are green.
2. AD-718a commit has landed.
3. `PROGRESS.md` and `decisions-era-4-evolution.md` reflect AD-718a as shipped.

After AD-718d ships, both ADs in Wave 136 are complete and the wave dispatch is closed.

## 11. Engineering principles compliance

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Specific checkpoints (Builder confirms each in the build report):

- **Defense in Depth** — modulation output clamped against Web Speech API bounds AND `VoiceProfile` validator bounds (same numbers — single source of truth in the bounds constants).
- **Three-tier exceptions** — `try/catch` around store-snapshot read in `speakResponse` (Tier-2 log-and-degrade): a missing/throwing store MUST NOT prevent speech; falls back to unmodulated baseline. Pure-function modulation propagates nothing — it never throws because all inputs are bounded numbers and operations are arithmetic.
- **No private-attr access** — UI reads `useStore.getState()` (public API) and `deriveAgentSignals` (public selector helper). No reach into `state.agents[id]._private`.
- **HXI Design Principles** — indicator is stroke-based SVG with `strokeWidth: 1.5`, `strokeLinecap: round`. Active amber, inactive dim. Breathing animation per Principle #4. NO emoji.
- **Type annotations** — all new public functions fully typed (`VoiceProfile`, `AgentSignals`, return types). Constants declared `readonly` where appropriate.
- **Logging quality** — N/A in pure-function module; integration `try/catch` is intentionally silent (speech failure surfaces elsewhere; modulation degradation is silent-by-design per Tier-2).
- **Trust + Hebbian alignment** — modulation is a **read-only** consumer of signals. NO import of `consensus/trust`, `consensus/quorum`, or any trust-update path from `voice.ts` or `voiceModulation.ts`. Reviewer fails the prompt if any such import appears.
- **Storage abstraction** — N/A; no persistence.
- **Configuration via Pydantic** — N/A; constants are TypeScript compile-time values; not runtime-configurable in v1.

## 12. Acceptance criteria

- All ≥ 10 Vitest tests pass (E6 ≥ 8 + E7 ≥ 3 — minor overlap acceptable as long as E6 covers all E1/E2 branches and E7 covers E3 integration).
- Per-prompt gate green: `cd ui && npx vitest run` (no Python tests added by this prompt).
- Full Python gate still green (regression check): `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile` (fall back to `-n 8`). No Python source was modified, but the gate must remain green.
- `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-718d-emotional-voice-modulation-v1.md` — accepted false positives (introduced by this prompt: `applyEmotionalModulation`, `hasMeaningfulModulation`, `voiceModulation.ts`) noted in build report. The known `.ts`-filename / `Class.method`-shape false positives may surface; document them as such.
- Files touched (target list):
  - **New:** `ui/src/audio/voiceModulation.ts`, `ui/src/__tests__/voiceModulation.test.ts`, `ui/src/__tests__/voice.speakResponse.modulation.test.ts`.
  - **Modified:** `ui/src/audio/voice.ts` (extend `speakResponse` body only; signature unchanged), `ui/src/components/profile/ProfileChatTab.tsx` (add modulation indicator next to per-agent speaker toggle — defer to AD-718d-1 if Vitest harness materially complicated), `PROGRESS.md` (Wave 136 entry — append AD-718d alongside the AD-718a entry from commit N).
- `decisions-era-4-evolution.md` (or current DECISIONS-era file owning AD-718) appended with AD-718d entry.
- GH issue [#525](https://github.com/seangalliher/ProbOS/issues/525) closed.
- AD-718d-1 forward marker filed at gate-3 if indicator (E5) was deferred or needs polish.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
