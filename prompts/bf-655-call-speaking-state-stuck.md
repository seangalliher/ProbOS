# BF-655: 1:1 call — "speaking" state (voice-modulation icon, avatar head-bob, PTT lock) never clears when the TTS `end` event is missed

**One-line:** Make the TTS producer (`ui/src/audio/voice.ts`) emit exactly one terminal `end` for every `start` on every terminal path (supersede/pause, browser-cancel, error) so the three `onSpeechEvent` consumers never latch "speaking" forever — and add a bounded self-heal watchdog on the PTT lock (the only functional lockout) as belt-and-suspenders.

**Status:** Ready to build
**Type:** BF (bug fix) — assign **BF-655** (verified next free; highest shipped is **BF-654**; do NOT mint a new AD — this is one shared backend+UI BF sequence)
**GitHub issue:** seangalliher/ProbOS#1018
**Branch:** `main`
**Dependencies:** none (refines AD-1071 pause handling + BF-300 gate; additive watchdog)
**Estimated tests:** ~8 new (one new Vitest file) + existing voice/consumer suites must stay green
**Target files:**
- `ui/src/audio/voice.ts` (2 producer edits: `_synthesizeAndPlay` pause handler; `_speakBrowserFallback` terminal guard + `onerror`)
- `ui/src/components/profile/ProfileChatTab.tsx` (1 consumer edit: bounded watchdog on the BF-300 `ttsActive` gate)
- `ui/src/audio/__tests__/voice.balancedEnd.test.tsx` (new)

---

## 1. Problem (Captain repro)

In a **1:1 call** with a crew agent (Ezri): the Captain uses **PTT** (push-to-talk) to say "hello"; the agent replies (spoken via Piper TTS). After the reply finishes:

1. The **voice-modulation icon** stays active / pulsing.
2. The **avatar's head keeps bobbing** as if still speaking.
3. The **PTT mic button no longer responds to clicks** — the Captain is locked out of talking again until the panel remounts.

All three symptoms are downstream of the SAME `onSpeechEvent` `start`/`end` pair emitted by `voice.ts`. Each consumer latches "speaking" on `start` and clears **only** on a matching `end`. There is **no self-heal** — a single missed `end` latches the state permanently.

A plausible call-specific trigger: the AD-1062 call-open greeting overlaps the PTT reply (two `speakResponse` calls; the newer one **pauses** the prior audio → the prior utterance emits `start` but never `end`). But the defect is **general**: any terminal path that resolves without firing `end` strands the latch.

---

## 2. Root cause (verified against HEAD — exact cites)

### 2a. The three consumer latches (set on `start`, cleared ONLY on `end`, `agent_id`-filtered)

| Consumer | File:line | Latch | set (`start`) | clear (`end`) |
|---|---|---|---|---|
| Voice-modulation icon | [ui/src/components/profile/ModulationIndicator.tsx](../ui/src/components/profile/ModulationIndicator.tsx#L29) | `active` state | `setActive(true)` L30 | `setActive(false)` L31 (filter L29) |
| Avatar head-bob | [ui/src/components/profile/CrewVRM.tsx](../ui/src/components/profile/CrewVRM.tsx#L493) | `speakingRef.current` | `= true` L493 | `= false` L495 (filter L481); head-bob reads it L544 |
| PTT lock | [ui/src/components/profile/ProfileChatTab.tsx](../ui/src/components/profile/ProfileChatTab.tsx#L419) | `ttsActiveRef`/`ttsActive` | L423-424 | L426-427 (persistent sub L419-433) |

- **PTT lockout** is the persistent BF-300 subscription (L419-433). The mic `onClick` early-returns while `ttsActiveRef.current` is true: `if (ttsActiveRef.current) { … return; }` at [ProfileChatTab.tsx L1755](../ui/src/components/profile/ProfileChatTab.tsx#L1755) (logs `BF-300: mic press ignored … TTS playback in progress`). `MicIndicator` shows `muted` while `ttsActive` at [L1995](../ui/src/components/profile/ProfileChatTab.tsx#L1995).
- `ttsActiveRef` is the **synchronous** source read by the click handler; `ttsActive` **state** drives the `muted` visual. Both are set/cleared in the same handler (refs L233-234).
- **Second latch in the same file:** the hot-mic conversation path subscribes a *per-reply* `onSpeechEvent` at [L1224-1230](../ui/src/components/profile/ProfileChatTab.tsx#L1224) that calls `markAgentReplyComplete()` on `end`. A missed `end` here strands the AD-985/BF-290 conversation controller in `agent_speaking` (which also blocks the next mic press). The producer fix below fixes this path too.

### 2b. The producer does NOT guarantee a terminal `end` for every `start`

`ui/src/audio/voice.ts`. `SpeechEvent` shape = `{ type:'start'|'end'|'boundary', agent_id?, utterance, source?:'server'|'browser' }` (L40-49); `_fire` fans out to listeners (L59-64); `onSpeechEvent` subscribe (L52-55).

**Server / Piper path — `_synthesizeAndPlay` (L294-379):**
- `start` fires on the audio `'play'` event: [L354](../ui/src/audio/voice.ts#L354).
- Terminal `end` **guaranteed** on `'ended'` → `_finish(true)` (L355) and `'error'` → `_finish(true)` (L356).
- Terminal **WITHOUT** `end`: `'pause'` → `_finish(false)` at [L360](../ui/src/audio/voice.ts#L360). `_finish(false)` deliberately fires **no** `end` (AD-1071 comment L357-359). **A newer `speakResponse` pauses the prior audio** (`_activeAudio.pause()` at L231-232, after `speechSynthesis.cancel()` L230, before `myGen = ++_speakGeneration` L237) → the prior utterance's `pause` listener runs → `_finish(false)` → **`start` with no `end` → all three latches stranded.** ← PRIMARY.
- `play().then(undefined, reject)` (L368-373): on reject the `'play'` event never fired (no `start`), then `_speakBrowserFallback` runs → path below.

**Browser fallback — `_speakBrowserFallback` (L411-433):**
- `start` on `utterance.onstart` (L428); `end` on `utterance.onend` (L429). **No `onerror` handler.**
- `speakResponse` calls `speechSynthesis.cancel()` (L230) when a newer reply supersedes → many browsers fire `onerror` (`error='interrupted'`/`'canceled'`), **not** `onend` → **`end` missed.** General browser `onend` flakiness (long text, backgrounded tab) is the same class.

**Net defect:** `start`/`end` are **unbalanced** on the supersede/pause path (server) and the cancel/error path (browser). Because no consumer self-heals, one missed `end` latches the icon + head + PTT until remount.

### 2c. Every `start`-emitting path and whether `end` is guaranteed today

| Path | `start`? | `end` guaranteed? | Gap |
|---|---|---|---|
| Server `'ended'` | yes (L354) | yes `_finish(true)` L355 | — |
| Server `'error'` | yes | yes `_finish(true)` L356 | — |
| Server `'pause'` (supersede/stop) | yes | **NO** `_finish(false)` L360 | **PRIMARY** |
| Server `play()` reject | no (play never fired) | n/a; browser fallback runs | (browser gap below) |
| Browser `onend` fires | yes L428 | yes L429 | — |
| Browser cancel/interrupt (`onerror`) | yes L428 | **NO** (onerror unwired) | **SECONDARY** |
| `speakResponse` no-TTS early return (L222) | no | n/a (nothing fired) | — |

---

## 3. Fix design

### PRIMARY — producer-side balanced `end` (fixes all three consumers with one conceptual change)

Guarantee that **every `start` is followed by exactly one `end` with the same `agent_id`** on every terminal path.

**Edit A — server pause path fires `end` (`_synthesizeAndPlay`, voice.ts L360).**
Change the `'pause'` listener from `_finish(false)` to `_finish(true)` so a **superseded/paused** utterance emits its terminal `end` (same `agent_id`, `source:'server'`).
- *Before:* `audio.addEventListener('pause', () => _finish(false));` — no `end` on pause.
- *After:* `audio.addEventListener('pause', () => _finish(true));` — one `end` on pause.
- Update the AD-1071 comment block (L357-359) to state the BF-655 rationale: firing `end` when a newer reply supersedes an older utterance is **correct** — the old utterance is genuinely over, so the icon/head/PTT must reset; it is **not** a "spurious" end (a spurious end would only be one that cut a *still-playing* utterance, which pause never does here).
- **Double-fire is already prevented** by the existing `_settled` guard (L347): if `'ended'`/`'error'` already ran, the `pause` listener's `_finish` returns early.
- **Queue is unaffected:** `runSentenceQueue`'s `shouldContinue` keys off the AD-1071 generation token (`() => myGen === _speakGeneration`), **not** the `end` event; `_finish` still calls `resolve()`, so the sentence queue advances/stops exactly as before. (Verified: `voiceChunking.ts::runSentenceQueue` checks `shouldContinue` before each item; the side-effect owner returns a Promise resolved by `_finish`.)

**Edit B — browser fallback emits a single terminal `end` on `onend` OR `onerror` (`_speakBrowserFallback`, voice.ts L428-429).**
Introduce a local single-settle guard (a `let` bool captured in the closure) so that whichever of `onend`/`onerror` fires first emits exactly one `end` (`source:'browser'`), and the other is a no-op. Wire `utterance.onerror` (currently absent) to the same guarded terminal. Keep `onstart` firing `start` unchanged. This balances the browser path under `speechSynthesis.cancel()` interrupts and general `onend` flakiness.
- Do **not** change voice selection, rate/pitch/volume, or the `'boundary'` reservation comment (L430).

Together, Edits A+B make `start`/`end` balanced on every terminal path → the icon, the head-bob, the PTT gate, **and** the hot-mic conversation-controller completion (L1224-1230) all clear correctly with no consumer change.

### DEFENSE-IN-DEPTH — bounded watchdog on the PTT lock only (recommended)

Even with balanced `end`, a *future* producer regression or an audio element that fires **no** event at all would again permanently lock PTT. Because the PTT lockout is the only **functional** symptom (icon + head-bob are cosmetic and already cleared by the producer fix), add a bounded self-heal to the **BF-300 subscription in `ProfileChatTab.tsx` (L419-433) only**:

- Add a `useRef` timer handle (e.g. `ttsWatchdogRef`).
- On `start`: after setting `ttsActiveRef.current = true; setTtsActive(true)`, **clear any prior timer** then arm `setTimeout(() => { ttsActiveRef.current = false; setTtsActive(false); /* log a BF-655 self-heal warning */ }, PTT_TTS_WATCHDOG_MS)`. Clearing-then-arming gives **reset-on-fresh-`start`** (a new utterance re-arms the ceiling).
- On `end`: clear the timer (in addition to clearing the gate as today).
- In the effect cleanup: clear the timer (so unmount leaves no dangling timer — required for the `bf300` suite which uses real timers).
- **Duration source:** a **fixed generous ceiling** `PTT_TTS_WATCHDOG_MS` (recommend **45000** ms). The watchdog is a safety net, not a precise timer: it must be longer than any single legitimate utterance (so it never cuts a real one) but bounded (so a stranded gate self-heals). The `SpeechEvent` does **not** carry audio duration, and for the pipelined path `utterance.text` is the whole reply, so a text-length estimate is not more accurate here — a fixed ceiling, re-armed per `start`, is the minimal robust choice. (Do NOT derive from `visemes`; they are not on the event.)

Scope the watchdog to the PTT consumer only. Extending it to `ModulationIndicator`/`CrewVRM` is a documented FORWARD option, not needed once the producer fix balances `end` (their symptoms are cosmetic and self-clear).

### Why this over alternatives

- **Producer-first** fixes all consumers (present and future, including the hot-mic controller) with two localized edits, and keeps `speakResponse`'s public surface, the AD-1071 queue, and the BF-300 gate logic intact.
- The **watchdog** is cheap insurance targeted at the single severe (functional) symptom; it is separable — drop it if a strictly-minimal change is preferred, but it is **recommended** because the missed-`end` class has multiple sources (pause, cancel/interrupt, browser flakiness) and the lockout is user-blocking.

### Reconciliation with AD-1071 / BF-300 / BF-621

- **AD-1071 (sentence pipelining + `_speakGeneration`):** the generation-stop logic is untouched (Edit A only changes whether `end` fires, not `resolve()` or the token). No AD-1071 test pins pause→no-end (see §5).
- **BF-300 (echo-gate):** the gate's set/clear logic and the mic early-return are unchanged; the watchdog only adds a self-clear safety on top.
- **BF-621 (meeting "hear, then see" reveal):** lives in `meetingVoice.ts`/`useMeetingVoice.ts` (`onBeforeUtterance`/`onAfterUtterance` hooks), **not** the `onSpeechEvent` end path — untouched. Firing the OLD generation's `end` on supersede is exactly the behavior BF-621's "superseded batch reveals nothing" already assumes (the reveal is keyed off the batch/generation, not `end`).

---

## 4. What this does NOT change (boundaries)

- **Do NOT** change `speakResponse`'s public signature, the AD-1071 `_speakGeneration` token, `runSentenceQueue`, or `voiceChunking.ts`.
- **Do NOT** change the server happy path (`'ended'`/`'error'` already fire `end`), the visemes/lip-sync injection, `_resolveEffectiveProfile`, or the zero-HTTP-per-utterance default-config probe (AD-738).
- **Do NOT** touch `meetingVoice.ts`/`useMeetingVoice.ts` (BF-621) or the AD-922 meeting-wide echo gate.
- **Do NOT** change the BF-300 gate semantics or the mic `onClick` branch logic — the watchdog only adds a bounded self-clear; the early-return at L1755 stays.
- **Do NOT** add watchdogs to `ModulationIndicator`/`CrewVRM` in this BF (FORWARD).
- **Do NOT** rename any `?raw`-pinned source string that `ProfileChatTab.ad1062.test.tsx` / `ProfileChatTab.a2ui.test.tsx` assert on (e.g. `triggerCallGreeting`, `greetedThreadsRef`, `greetTokenRef`, `system_trigger: true`, the `renderMessageBodyWithArtifacts(msg.text, …)` call site).
- **No emoji**; the watchdog is logic-only (no new UI glyph). HXI: motion still = state (the icon/head now correctly stop on `end`).

---

## 5. Existing tests — keep green; obsolete-contract audit

Verified: **no existing test pins the AD-1071 pause→no-`end` contract.** Details:

| Test file | Exercises | Effect of this fix |
|---|---|---|
| `ui/src/audio/__tests__/voice.pipelining.test.tsx` | `FakeAudio` dispatches `play`/`ended`/`pause`, but tests assert only POST-count + queue-advance via `.end()` (never triggers a supersede-pause, never asserts `end` absence) | **Green** — queue behavior preserved |
| `ui/src/audio/__tests__/voice.serverTts.test.tsx` | `'second speakResponse cancels in-flight <audio>'` asserts `first.pause` (a `vi.fn` that does **not** dispatch the `pause` event) | **Green** — pause listener not triggered there |
| `ui/src/audio/__tests__/voice.test.ts` | AD-718 lifecycle: manually calls `u.onstart?.()` then `u.onend?.()`, asserts 2 events | **Green** — adding a guarded `onerror` does not change the onstart→onend sequence |
| `ui/src/__tests__/ModulationIndicator.test.tsx` | mocks `onSpeechEvent`, fires start/end manually | **Green** — consumer unchanged |
| `ui/src/__tests__/ProfileChatTab.bf300.test.tsx` | fully mocks `voice.ts`; real timers | **Green** — watchdog uses a 45 s `setTimeout` that never fires in-test; effect cleanup must clear it |
| `ui/src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx` | `?raw` mirror of the greeting; mocks `fetch` | **Green** — greeting logic untouched; keep pinned strings |
| `ui/src/components/profile/__tests__/ProfileChatTab.ad976.test.tsx` | BF-621 meeting reveal (mirror) | **Green** — BF-621 path untouched |
| `ui/src/__tests__/CrewVRM.realAudioFallback.test.tsx` | invokes `buildHeuristicTrack` directly | **Green** — end/pause path not exercised |
| `useLipSyncCapture.test.tsx`, `useMeetingVoice.test.tsx`, `voice.pipelining.test.tsx` | lip-sync / meeting sequencing | **Green** — no end-contract assertion touched |

If the Builder finds any assertion that a paused/superseded server utterance fires **no** `end`, that is an obsolete-contract test the fix intentionally changes — repoint it to assert the new balanced-`end` behavior (do not delete the guard). None found in the audit above.

---

## 6. Test plan

New file `ui/src/audio/__tests__/voice.balancedEnd.test.tsx`. Reuse the `voice.pipelining.test.tsx` harness pattern: a `FakeAudio` whose `play()`/`pause()` **dispatch** `'play'`/`'pause'` and an `.end()` hook dispatching `'ended'`, plus a `FakeUtterance` exposing `onstart`/`onend`/`onerror`. Capture events via `onSpeechEvent`.

1. **`test_server_ended_fires_exactly_one_start_and_one_end`** — piper probe; one `speakResponse`; dispatch `play` then `ended`; assert events `= ['start','end']` (no double-`end`), both with the passed `agent_id`.
2. **`test_supersede_pause_fires_end_for_the_older_utterance`** (HEADLINE / stuck-latch regression) — piper probe; `speakResponse('first', …, 'ezri')`; dispatch the first audio's `play` (→ `start`); then `speakResponse('second', …, 'ezri')` (which pauses the first). Assert the captured events include a terminal `{type:'end', agent_id:'ezri'}` for the FIRST utterance **before** the second's `start` — i.e. the latch would clear. (Pre-fix: no such `end`.)
3. **`test_no_double_end_when_ended_then_pause`** — dispatch `play`, `ended`, then `pause` on the same audio; assert exactly one `end` (the `_settled` guard holds).
4. **`test_browser_cancel_fires_end_via_onerror`** — force the browser fallback (`fetch` undefined or status=browser); `speakResponse`; call `utterance.onstart()` then `utterance.onerror()`; assert events `= ['start','end']` (source `'browser'`).
5. **`test_browser_onend_still_fires_single_end`** — browser fallback; `onstart()` then `onend()`; assert exactly one `end` (guard does not suppress the normal path).
6. **`test_pipelining_still_one_post_when_flag_off`** — regression mirror of `voice.pipelining.test.tsx` load-bearing case: multi-sentence, flag OFF → exactly one POST of the full text (proves Edit A didn't disturb the queue).

Watchdog (in the SAME new file or a small `ProfileChatTab`-mirror block, whichever the Builder finds cleaner given ProfileChatTab can't mount cheaply — prefer a focused mirror of the arm/clear logic like `ProfileChatTab.ad1062.test.tsx` does, plus a `?raw` source assertion):

7. **`test_ptt_watchdog_clears_gate_after_ceiling_with_no_end`** — with fake timers: fire `start` (gate set), advance timers past `PTT_TTS_WATCHDOG_MS` **without** an `end`; assert the gate cleared (`ttsActiveRef`→false / `ttsActive`→false). Proves PTT can't lock permanently.
8. **`test_ptt_watchdog_reset_on_fresh_start_and_cleared_on_end`** — fire `start`, advance < ceiling, fire another `start` (re-arm), advance < ceiling again, then `end` → gate cleared and no stale timer fires afterward; and a `?raw` assertion that the production effect contains the watchdog ref + `clearTimeout` on `end`/cleanup.

**Gate commands** (UI):
```
cd d:\ProbOS\ui
npx vitest run src/audio/__tests__/voice.balancedEnd.test.tsx src/audio/__tests__/voice.pipelining.test.tsx src/audio/__tests__/voice.serverTts.test.tsx src/audio/__tests__/voice.test.ts src/__tests__/ModulationIndicator.test.tsx src/__tests__/ProfileChatTab.bf300.test.tsx src/components/profile/__tests__/ProfileChatTab.ad1062.test.tsx src/components/profile/__tests__/ProfileChatTab.ad976.test.tsx
# then the full UI gate + type check:
npx vitest run
npm run build
```

---

## 7. Tracking

- `PROGRESS.md`: add a `**BF-655 shipped**` line (mirror the BF-654 format at PROGRESS.md L3; `LOCAL (Captain decides push)`).
- `docs/development/roadmap.md` Bug Tracker: add a BF-655 row.
- `DECISIONS.md`: **not required** for a BF (this repo batches DECISIONS/PROGRESS; add only if the Captain wants the balanced-`end` contract logged).
- Close/comment `seangalliher/ProbOS#1018` on ship (`gh` CLI, `--repo seangalliher/ProbOS`; commit body `closes #1018`).
- Do NOT stage `config/system.yaml` (Captain's local config).

---

## 8. Acceptance criteria

1. Server supersede/pause fires exactly one terminal `end` (same `agent_id`) for the older utterance (test #2); the happy `'ended'` path fires exactly one `end` and never double-fires under `ended`+`pause` (tests #1, #3).
2. The browser fallback fires exactly one `end` via `onend` **or** `onerror`, never zero and never two (tests #4, #5).
3. All three consumer latches (icon `active`, `speakingRef`, PTT `ttsActive`) clear on the now-guaranteed `end` with no consumer change; the AD-1071 flag-OFF single-POST path is byte-identical (test #6).
4. The PTT gate self-heals within `PTT_TTS_WATCHDOG_MS` if an `end` is ever missed, re-arms on a fresh `start`, and leaves no dangling timer on unmount (tests #7, #8).
5. `voice.pipelining`, `voice.serverTts`, `voice.test`, `ModulationIndicator`, `ProfileChatTab.bf300`, `ProfileChatTab.ad1062`, `ProfileChatTab.ad976`, `CrewVRM.realAudioFallback` all pass unchanged; `npm run build` (tsc -b) is clean.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 9. Verify-first checklist (grep/read evidence @ HEAD, 2026-07-07)

```
# BF ceiling
PROGRESS.md:3                          **BF-654 shipped …**            (highest; BF-655 free — git grep "BF-655" empty)
issue #1018                            OPEN, title "BF-655: 1:1 call — …"

# Consumer latches
ModulationIndicator.tsx:29             if (evt.agent_id !== agentId) return;
ModulationIndicator.tsx:30             if (evt.type === 'start') setActive(true);
ModulationIndicator.tsx:31             if (evt.type === 'end') setActive(false);
CrewVRM.tsx:481                        if (e.agent_id !== agentId) return;
CrewVRM.tsx:493                        speakingRef.current = true;
CrewVRM.tsx:495                        speakingRef.current = false;
CrewVRM.tsx:544                        const speakBob = speakingRef.current ? Math.sin(t * 5) * 0.04 : 0;
ProfileChatTab.tsx:233-234            const ttsActiveRef = useRef(false); const [ttsActive, setTtsActive] = useState(false);
ProfileChatTab.tsx:419-433            persistent onSpeechEvent gate (set 423-424, clear 426-427)
ProfileChatTab.tsx:1224-1230          hot-mic per-reply onSpeechEvent → markAgentReplyComplete on 'end'
ProfileChatTab.tsx:1755               if (ttsActiveRef.current) { … return; }   // PTT early-return
ProfileChatTab.tsx:1995               ttsActive ? 'muted' : …                    // MicIndicator

# Producer (voice.ts)
voice.ts:40-49                         SpeechEvent {type,agent_id?,utterance,source?}
voice.ts:52-64                         onSpeechEvent / _fire
voice.ts:230-237                       speechSynthesis.cancel(); _activeAudio.pause(); ++_speakGeneration  (supersede)
voice.ts:346-353                       _finish(fireEnd) with _settled guard
voice.ts:354                           addEventListener('play', … 'start')
voice.ts:355-356                       'ended'/'error' -> _finish(true)
voice.ts:360                           addEventListener('pause', () => _finish(false))   ← EDIT A -> _finish(true)
voice.ts:368-373                       play().then(undefined, reject) -> _speakBrowserFallback + _finish(false)
voice.ts:411-433                       _speakBrowserFallback
voice.ts:428-429                       utterance.onstart / onend  (no onerror)            ← EDIT B: add guarded onerror
voiceChunking.ts:runSentenceQueue      shouldContinue keys off generation token, not 'end' (queue unaffected)

# BF-621 is unrelated (meeting reveal)
useMeetingVoice.ts / meetingVoice.ts   onBeforeUtterance/onAfterUtterance (not onSpeechEvent 'end')
```
