# AD-949 — Call-scoped voice for group/meeting chat (decouple from the ship-computer `voiceEnabled`)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-949.** GitHub epic `seangalliher/ProbOS#882` (Natural
Conversation); this issue `#885`.
**Mode:** Builder. Frontend only (UI). Commit local. **No push** (the Captain decides the push).
**Builds on:** AD-921 (sequenced meeting voice, commit `fe6fbdfb`) — the `meetingVoice.ts` sequencer + the
`useMeetingVoice` hook; AD-922 (Captain meeting mic) — the `speakingAgentId` echo gate; AD-923 (meeting
presence + speaking indicator). **Wave siblings (DO NOT build — awareness only):** AD-947 (in-meeting camera),
AD-948 (group tag-strip). **Corroborating triage:** `BF-614` explicitly punted this surface as *"voice (the
AD-945 voice-output toggle in the Engineering station was likely off) — triaged, not a code bug."* AD-949 is the
actual structural fix: group/meeting voice should NOT depend on the Ship's-Computer toggle at all.

## Goal
Give group/meeting voice its **own call-scoped audio gate**, decoupled from the global Ship's-Computer
`voiceEnabled` flag, so crew speak in a live meeting the way they already do in a 1:1 — **audible by default when
a call is active** — with an **in-call mute/unmute control** on the group-chat header. Keep the AD-921/922/923
meeting-voice machinery (one-speaker-at-a-time sequencing, per-agent AD-718 voice profiles, the AD-923 speaking
indicator, the AD-922 mic echo gate) **byte-for-byte intact** — AD-949 changes ONLY the gate flag + adds the
in-call control.

## Why
Group/meeting voice is silent even though 1:1 voice works. The two paths use **different gates**:

- **1:1 chat** has a per-agent speaker override — `localStorage hxi_chat_tts_{agentId}` (the `ttsEnabled` state at
  `ProfileChatTab.tsx:282`–`289`, the speaker icon in the 1:1 composer, played at `:800`). So a 1:1 speaks
  regardless of the global flag.
- **Group/meeting voice** (`useMeetingVoice.ts:50`) gates on the **global `voiceEnabled`** — which is the
  **Ship's-Computer / IntentSurface** voice that the AD-945 Engineering → Environment "voice output" toggle sets
  (`BridgeEnvironment.tsx:21`–`22`,`130`; `IntentSurface.tsx:93`,`417`,`440`). `voiceEnabled` defaults `false`
  (`useStore.ts:930`).

Net: group/meeting voice piggybacks on the ship-computer global flag, so it is off unless the Captain enables the
Engineering voice **and** is in a meeting — the exact symptom `BF-614` saw and triaged as "toggle was likely
off." AD-949 gives the call its own flag (default ON when a meeting is active) so starting a meeting is audible
without forcing the Ship's Computer to talk.

Reference: the 11 HXI Design Principles in `.github/copilot-instructions.md` (esp. #3 no-emoji stroke-SVG glyphs,
amber active; #4 motion = state).

---

## Verified current shape (grep evidence in the footer)

**The hook's gate is one line, and the meeting self-gate runs FIRST** (`useMeetingVoice.ts:48`–`60`):

```tsx
  const speakReplies = useCallback((replies: PerAgentReply[]): void => {
    if (!meetingActiveRef.current) return;              // :49  meeting self-gate (STAYS — runs first)
    if (!useStore.getState().voiceEnabled) return;      // :50  THE GATE TO CHANGE
    if (!Array.isArray(replies) || replies.length === 0) return;
    const myGen = ++genRef.current;
    void speakRepliesSequentially(replies, { … });      // :52+ AD-921/922/923 sequencer — UNCHANGED
  }, []);
```

> Because the `meetingActive` self-gate (`:49`) already runs before the flag check, and the **sequencer**
> (`speakRepliesSequentially`, `createVoiceProfileResolver` in `meetingVoice.ts`) is invoked *after* both gates,
> swapping which store flag gates the call **does not touch the sequencer, the per-agent voice profiles, the
> `speakingAgentId` seam, or the echo gate**. It is a pure gate-flag swap.

**The store slice to mirror** (`voiceEnabled`, all in `ui/src/store/useStore.ts`):

| Part | Line | Code |
|---|---|---|
| field decl (`// Audio state` group) | `:454` | `voiceEnabled: boolean;` |
| setter decl | `:588` | `setVoiceEnabled: (v: boolean) => void;` |
| default (initial state) | `:930` | `voiceEnabled: false,` |
| setter impl | `:1638`–`1641` | `setVoiceEnabled: (v) => { set({ voiceEnabled: v }); localStorage.setItem('hxi_voice_enabled', v ? '1' : '0'); }` |

**The in-call control's home** — `GroupChatHeader.tsx` already owns the Start/End **meeting-toggle** button
(`:210`–`231`, `data-testid="meeting-toggle"`, shown when `crewParticipants.length >= 1`), derives
`meetingActive` from the thread metadata (`:49`), and reads the store via `useStore((s) => …)` selectors
(`:22`–`24`). The new mute control mounts right after the meeting toggle, gated on `meetingActive`.

**The hook mount is unchanged** — `ProfileChatTab.tsx:520`
`const { speakReplies: speakMeetingReplies, speakingAgentId } = useMeetingVoice({ meetingActive });`. The hook
self-gates, so the call site needs **no** edit. `speakMeetingReplies(replies)` fires at `:719` after the group
fan-out renders.

**The ONLY meeting/group voice gate is `useMeetingVoice.ts:50`.** Every other `voiceEnabled` reader is the
Ship's-Computer / 1:1 surface and is **out of scope** (fenced below): `IntentSurface.tsx:93`,`417`,`440`;
`BridgeEnvironment.tsx:21`,`22`,`130`; the 1:1 `hxi_chat_tts_{agentId}` path `ProfileChatTab.tsx:282`–`289`,`800`.

---

## Design decision (documented)

**New flag: `callAudioEnabled` (boolean), default `true`.** A dedicated store flag — NOT a reuse of
`voiceEnabled`. Rationale:
- **Name:** `callAudioEnabled` (not `meetingVoiceEnabled`) — it reads naturally for a mute control ("call audio
  enabled / muted"), generalises beyond meetings (future 1:1 voice calls), and stays clearly distinct from
  `meetingActive` (the mode flag) and `voiceEnabled` (the Ship's Computer). Grep-confirmed unused in `ui/src`.
- **Default `true`:** the hook's `meetingActive` self-gate (`:49`) already silences everything when no meeting is
  active, so a default-ON `callAudioEnabled` means *starting a call is audible by default* (meetingActive &&
  callAudioEnabled) **without** turning on the Ship's-Computer voice. This is the single decoupling that fixes
  the bug.
- **No `localStorage` in v1 (session-scoped).** The setter is a plain `set({ callAudioEnabled: v })` — the
  closest mirror of `setVoiceEnabled` minus the persistence line. A fresh page load is audible; the Captain can
  mute mid-session. Persisting the mute preference across sessions (with default-ON hydration) is a **forward
  marker (AD-949a)** — kept out of v1 to avoid the default-true hydration wrinkle.

**In-call control home: `GroupChatHeader`, gated on `meetingActive`.** It is where Start/End meeting already
lives, is already wired to the store, and renders above the transcript whenever a thread exists — the natural
"in-call control" slot. (Also surfacing it on `MeetingView`'s gallery is a **forward marker, AD-949b** — rejected
for v1 to avoid duplicating the store wiring and adding a controls row the gallery doesn't have today.)

**Per-agent overrides (secondary, deferred):** also honoring the 1:1 `hxi_chat_tts_{agentId}` overrides inside
the meeting sequencer (so the exact agents the Captain enabled 1:1 speak in group) would require a per-reply gate
inside `meetingVoice.ts` — more than v1 needs. **Forward marker (AD-949c).**

**Expected interaction (NOT a regression):** now that group voice actually plays, `speakingAgentId` becomes
non-null during agent speech, so the AD-922 meeting-mic echo gate (`speaking: speakingAgentId != null`,
`ProfileChatTab.tsx:823`) finally engages as designed (the mic refuses to arm while an agent speaks). This is the
intended AD-922 behavior being exercised for the first time, not a new bug.

---

## Section 1 — MODIFY: `ui/src/store/useStore.ts` — add the `callAudioEnabled` slice

Mirror the `voiceEnabled` slice (field / setter-decl / default / setter-impl), with two deliberate differences:
default `true` (vs `false`) and **no** `localStorage` line (v1 session-scoped).

**1a. Field declaration** (after `voiceEnabled: boolean;` in the `// Audio state` group):
```
SEARCH:
  // Audio state
  soundEnabled: boolean;
  voiceEnabled: boolean;
  // AD-705: always-on wake-word voice loop opt-in. Default OFF — the

REPLACE:
  // Audio state
  soundEnabled: boolean;
  voiceEnabled: boolean;
  // AD-949: call-scoped audio gate for group/meeting voice, decoupled from the
  // Ship's-Computer ``voiceEnabled``. Default ON so a live call is audible; the
  // in-call mute control (GroupChatHeader) flips it. Session-scoped (no
  // localStorage in v1 — persistence is AD-949a).
  callAudioEnabled: boolean;
  // AD-705: always-on wake-word voice loop opt-in. Default OFF — the
```

**1b. Setter declaration** (after `setVoiceEnabled`):
```
SEARCH:
  setSoundEnabled: (v: boolean) => void;
  setVoiceEnabled: (v: boolean) => void;
  // AD-705: opt-in toggle for the always-on wake-word voice loop.

REPLACE:
  setSoundEnabled: (v: boolean) => void;
  setVoiceEnabled: (v: boolean) => void;
  // AD-949: call-scoped meeting/group audio mute.
  setCallAudioEnabled: (v: boolean) => void;
  // AD-705: opt-in toggle for the always-on wake-word voice loop.
```

**1c. Default (initial state)** — default ON:
```
SEARCH:
  soundEnabled: false,
  voiceEnabled: false,
  // AD-705: hydrate wake-word toggle from localStorage; default OFF.

REPLACE:
  soundEnabled: false,
  voiceEnabled: false,
  // AD-949: call audio ON by default — combined with the hook's meetingActive
  // self-gate, a freshly started call is audible without enabling the
  // Ship's-Computer voice.
  callAudioEnabled: true,
  // AD-705: hydrate wake-word toggle from localStorage; default OFF.
```

**1d. Setter implementation** (after the `setVoiceEnabled` block; plain `set`, no `localStorage`):
```
SEARCH:
  setVoiceEnabled: (v) => {
    set({ voiceEnabled: v });
    localStorage.setItem('hxi_voice_enabled', v ? '1' : '0');
  },

REPLACE:
  setVoiceEnabled: (v) => {
    set({ voiceEnabled: v });
    localStorage.setItem('hxi_voice_enabled', v ? '1' : '0');
  },
  // AD-949: call-scoped mute. No localStorage in v1 — the default-ON store
  // value makes a fresh call audible; persisting the preference is AD-949a.
  setCallAudioEnabled: (v) => {
    set({ callAudioEnabled: v });
  },
```

> One store field + one setter, both additive. No change to `voiceEnabled`/`setVoiceEnabled`, no `localStorage`
> key, no other slice.

---

## Section 2 — MODIFY: `ui/src/audio/useMeetingVoice.ts` — swap the gate flag

**2a. The gate** (the one functional line):
```
SEARCH:
    if (!meetingActiveRef.current) return;
    if (!useStore.getState().voiceEnabled) return;
    if (!Array.isArray(replies) || replies.length === 0) return;

REPLACE:
    if (!meetingActiveRef.current) return;
    // AD-949: gate on the call-scoped ``callAudioEnabled`` (default ON) instead
    // of the Ship's-Computer ``voiceEnabled`` — group/meeting voice is now
    // audible by default in a live call and muted only via the in-call control.
    if (!useStore.getState().callAudioEnabled) return;
    if (!Array.isArray(replies) || replies.length === 0) return;
```

**2b. JSDoc accuracy** (the hook's return-value doc):
```
SEARCH:
  /** Speak the AD-914 ``per_agent_replies`` in facilitator (array) order,
   *  one at a time. Self-gates on ``meetingActive && voiceEnabled``;
   *  no-ops otherwise. Reference-stable. */

REPLACE:
  /** Speak the AD-914 ``per_agent_replies`` in facilitator (array) order,
   *  one at a time. Self-gates on ``meetingActive && callAudioEnabled``;
   *  no-ops otherwise. Reference-stable. */
```

**2c. Top-of-file block comment** (accuracy only):
```
SEARCH:
 *  real ``speakResponse`` / ``onSpeechEvent`` / ``stripMarkdownForSpeech``,
 *  gates on the meeting being active AND voice being enabled, exposes

REPLACE:
 *  real ``speakResponse`` / ``onSpeechEvent`` / ``stripMarkdownForSpeech``,
 *  gates on the meeting being active AND call audio being enabled, exposes
```

> Do **not** touch the `speakRepliesSequentially(...)` call, the generation-token logic, `onSpeakingChange`,
> `shouldContinue`, or `createVoiceProfileResolver`. Only the flag the gate reads changes.

---

## Section 3 — MODIFY: `ui/src/components/profile/GroupChatHeader.tsx` — in-call mute toggle

**3a. Add the two store selectors** (after `setChatThread`):
```
SEARCH:
  const thread = useStore((s) => s.chatThreads.get(threadId));
  const agents = useStore((s) => s.agents);
  const setChatThread = useStore((s) => s.setChatThread);

REPLACE:
  const thread = useStore((s) => s.chatThreads.get(threadId));
  const agents = useStore((s) => s.agents);
  const setChatThread = useStore((s) => s.setChatThread);
  // AD-949: call-scoped audio mute (default ON). The in-call toggle below flips
  // it; useMeetingVoice gates group/meeting speech on this flag.
  const callAudioEnabled = useStore((s) => s.callAudioEnabled);
  const setCallAudioEnabled = useStore((s) => s.setCallAudioEnabled);
```

**3b. Render the toggle** — insert immediately AFTER the meeting-toggle block (the `)}` that closes
`{crewParticipants.length >= 1 && ( … )}` at `:231`) and BEFORE the AD-937 Add-control comment at `:233`. Gate on
`meetingActive` so it appears only during a live call. Local inline speaker SVG (HXI #3 — no emoji, no
`Glyphs.tsx` export, so the `Glyphs.test.tsx` count is untouched; amber `#f0b060` when audible, dim `#666680`
when muted; two sound-wave arcs when on, a slash-cross when muted):
```
SEARCH:
            <rect x="1.5" y="4" width="9" height="8" rx="1.5" />
            <path d="M10.5 7 L14.5 5 V11 L10.5 9 Z" />
          </svg>
        </button>
      )}

      {/* AD-937: Add control branches on the thread shape. On a GROUP (>=2 crew)

REPLACE:
            <rect x="1.5" y="4" width="9" height="8" rx="1.5" />
            <path d="M10.5 7 L14.5 5 V11 L10.5 9 Z" />
          </svg>
        </button>
      )}

      {/* AD-949: in-call audio mute/unmute. Group/meeting voice is gated by the
          call-scoped ``callAudioEnabled`` (decoupled from the Ship's-Computer
          ``voiceEnabled``); this flips it so the Captain can silence a live call
          without muting the Ship's Computer. Shown only while a meeting is
          active. Local inline speaker SVG (HXI #3 — no emoji, no Glyphs.tsx
          export; amber when audible, dim when muted). */}
      {meetingActive && (
        <button
          type="button"
          data-testid="call-audio-toggle"
          aria-label={callAudioEnabled ? 'Mute call audio' : 'Unmute call audio'}
          aria-pressed={callAudioEnabled}
          title={callAudioEnabled ? 'Mute call audio' : 'Unmute call audio'}
          onClick={() => setCallAudioEnabled(!callAudioEnabled)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: callAudioEnabled ? '#f0b060' : '#666680',
            display: 'inline-flex', alignItems: 'center', padding: 2,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
               strokeLinejoin="round">
            <path d="M2.5 6 H5 L8.5 3.5 V12.5 L5 10 H2.5 Z" />
            {callAudioEnabled ? (
              <>
                <path d="M11 6.2 Q12.2 8 11 9.8" />
                <path d="M12.8 4.8 Q15 8 12.8 11.2" />
              </>
            ) : (
              <path d="M11.5 6 L14.5 10 M14.5 6 L11.5 10" />
            )}
          </svg>
        </button>
      )}

      {/* AD-937: Add control branches on the thread shape. On a GROUP (>=2 crew)
```

> The toggle reads + writes the store directly (no `threadApi`, no backend). `meetingActive` (`:49`) is already
> in scope.

---

## Section 4 — UPDATE tests

### 4a. `ui/src/audio/__tests__/useMeetingVoice.test.tsx` — migrate the gate flag

The hook's unit tests seed the gate flag via `useStore.setState` (`:30` beforeEach + `:37`,`:44`,`:53`,`:60`,`:71`
in the cases) and name two cases after "voice." The gate semantics are **identical** (same self-gate, same
no-op-when-off) — only the flag name changes, so this is a **verbatim rename**, no behavior change:

- Replace **all six** `useStore.setState({ voiceEnabled: … })` → `useStore.setState({ callAudioEnabled: … })`
  (keep each `true`/`false` value exactly as-is, including the `beforeEach` `false`).
- Rename the case `test_speaks_when_meeting_active_and_voice_enabled` (`:43`) →
  `test_speaks_when_meeting_active_and_call_audio_enabled`.
- Rename the case `test_no_speak_when_voice_disabled` (`:52`) → `test_no_speak_when_call_audio_disabled`.
- The `?raw` no-emoji source-hygiene test is unaffected (no emoji introduced).

> Net Vitest delta in this file: **0** (renames only). The `beforeEach` still seeds the gate `false`, so each case
> stays deterministic against the new default-`true` store value.

### 4b. `ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx` — add 3 call-audio cases

This file already mocks `../../sidebar/threadApi` and seeds the REAL store via `useStore.setState({ agents,
chatThreads })` (BF-287), with `mkAgent`/`mkThread`/`seed` helpers and an `afterEach` reset. The new toggle reads
the store directly, so the existing `threadApi` mock is sufficient.

- **Extend `afterEach`** to also reset the new flag to its default so cases don't bleed:
  ```
  SEARCH:
    useStore.setState({ agents: new Map(), chatThreads: new Map() });
  REPLACE:
    useStore.setState({ agents: new Map(), chatThreads: new Map(), callAudioEnabled: true });
  ```
- **Add a `describe('AD-949 GroupChatHeader call-audio toggle', …)` block** with 3 cases (reuse the file's
  `seed`/`mkThread`/`mkAgent`):
  1. **hidden when no meeting** — `seed(mkThread({ id:'t1', participants:['captain','a1'] }), [mkAgent({ id:'a1',
     callsign:'Vex' })])` (no `meeting_active`); `render(<GroupChatHeader threadId="t1" />)`; assert
     `screen.queryByTestId('call-audio-toggle')` is `null`.
  2. **shown + audible by default in a meeting** — seed a thread with `metadata:{ meeting_active:true }` and
     `useStore.setState({ callAudioEnabled:true })`; render; assert `getByTestId('call-audio-toggle')` exists and
     its `aria-pressed` === `'true'`.
  3. **click mutes** — same meeting seed with `callAudioEnabled:true`; `fireEvent.click(getByTestId(
     'call-audio-toggle'))`; assert `useStore.getState().callAudioEnabled === false` and the button's
     `aria-pressed` flips to `'false'`.
- Keep the existing AD-920 meeting-toggle cases and the no-emoji guard **verbatim** (the no-emoji guard now also
  renders the new SVG button on the `meeting_active:true` thread — confirm it stays green; SVG only, no emoji).

> Floor: **+3** Vitest in this file. No new test file.

---

## Gates
- `cd d:\ProbOS\ui; npx vitest run` → green. **Run FIRST to confirm the live baseline before editing** (per the
  Captain, ≈ **1373 passed / 1 skipped** after AD-947/BF-614 — confirm the exact number on your tree). AD-949
  adds **+3** GroupChatHeader cases (4a is renames = +0), so expect **≈ baseline + 3 passed / 1 skipped, zero
  regressions.** Report the exact pass + file count. **Run the FULL suite, not just the touched files** — adding
  a button to the shared `GroupChatHeader` can ripple into sibling specs (`GroupChatHeader.test.tsx`,
  `GroupChatHeader.transcript.test.tsx`); the AD-923 lesson is that a change to a shared header surfaces in the
  full run, not the focused one.
- `cd d:\ProbOS\ui; npm run build` → clean (`tsc -b` + `vite`). The new store field + setter must type-check; no
  unused-symbol drift.
- `cd d:\ProbOS\ui; npx playwright test` → green. The **4** AD-941 specs drive panels through the DEV
  `window.__store` seam and never touch the meeting voice gate or the group-chat header, so they are **expected
  unaffected** — run them to confirm. (Requires `vite dev` on :5173 per the AD-941 harness.)
- No backend change → **no pytest.**

## Acceptance
- A new store flag `callAudioEnabled: boolean` (default **`true`**) + `setCallAudioEnabled` setter exist, mirroring
  the `voiceEnabled` slice minus the `localStorage` line. `voiceEnabled`/`setVoiceEnabled` are **unchanged**.
- `useMeetingVoice.ts:50` gates group/meeting voice on `callAudioEnabled` (not `voiceEnabled`); the
  `meetingActive` self-gate (`:49`) and the `speakRepliesSequentially(...)` call (the AD-921/922/923 sequencer)
  are **untouched** — so a live meeting is audible by default without enabling the Ship's-Computer voice.
- `GroupChatHeader` renders a `data-testid="call-audio-toggle"` mute/unmute button **only while `meetingActive`**,
  stroke-SVG (no emoji), amber `#f0b060` when audible / dim `#666680` when muted, `aria-pressed` reflecting
  `callAudioEnabled`, flipping it via `setCallAudioEnabled`. The AD-920 meeting-toggle is unchanged.
- The 1:1 per-agent TTS (`hxi_chat_tts_{agentId}`), the Ship's-Computer / wake-word voice (`IntentSurface`,
  `BridgeEnvironment` AD-945 toggle, the global `voiceEnabled`), and all STT/TTS engines are **byte-for-byte
  unchanged**.
- Gates green (Vitest ≈ baseline + 3 / 1, build clean, Playwright 4 passed).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Do NOT build (scope fence)
- **Do NOT change the STT/TTS engines** — `audio/voice.ts` (`speakResponse` / `onSpeechEvent` /
  `stripMarkdownForSpeech`), `transformersStt`, `speechInput`, `soundEngine`. AD-949 is a gate-flag swap.
- **Do NOT change the AD-921/922/923 sequencer** — `meetingVoice.ts` (`speakRepliesSequentially`,
  `createVoiceProfileResolver`, `_speakAndWait`), the `speakingAgentId` seam, the AD-923 speaking indicator, or
  the AD-922 meeting-mic echo gate. Only the store flag the hook's gate reads changes.
- **Do NOT change the 1:1 per-agent TTS path** — `ProfileChatTab.tsx` `hxi_chat_tts_{agentId}` / `ttsEnabled`
  (`:282`–`289`) and the 1:1 `speakResponse` at `:800`. (Honoring per-agent overrides in group is **AD-949c**.)
- **Do NOT touch the Ship's-Computer / wake-word voice** — `IntentSurface.tsx` (`:93`,`417`,`440`),
  `BridgeEnvironment.tsx` AD-945 voice-output toggle, and the global `voiceEnabled` flag / `setVoiceEnabled` /
  `hxi_voice_enabled` localStorage. Leave them exactly as-is.
- **Do NOT persist `callAudioEnabled` to `localStorage`** in v1 (session-scoped; persistence = **AD-949a**), and
  **do NOT** add a per-call reset-on-start effect (default-ON already makes a fresh call audible).
- **Do NOT mount the toggle in `MeetingView`** for v1 — `GroupChatHeader` is the single home (`MeetingView`
  placement = **AD-949b**).
- **Do NOT** edit the `useMeetingVoice({ meetingActive })` call site in `ProfileChatTab.tsx` — the hook self-gates.
- No backend / REST / FastAPI / pytest. No push. Stage explicit paths (NOT `git add -A`); deletion-audit before
  commit.

## Forward markers (do NOT build now)
- **AD-949a** — persist the call-audio mute preference across sessions (`localStorage`, default-ON hydration).
- **AD-949b** — also surface the mute control on `MeetingView`'s avatar gallery (a controls row above the slots).
- **AD-949c** — honor per-agent `hxi_chat_tts_{agentId}` overrides inside the meeting sequencer, so the exact
  agents the Captain enabled 1:1 speak in group.

## Trackers (after gates green — match where AD-946b went)
- `docs/development/roadmap.md`: add an AD-949 row — SHIPPED + date + gate note; tag the epic (`#882`) /
  issue (`#885`).
- `PROGRESS.md`: prepend an AD-949 block (call-scoped `callAudioEnabled` gate; the `useMeetingVoice.ts:50` swap;
  the GroupChatHeader in-call toggle; the test renames + 3 new cases; the Vitest delta + suite count; note it is
  the structural fix for what BF-614 triaged as "voice toggle was likely off").
- `DECISIONS.md`: add an AD-949 entry — the decouple-from-`voiceEnabled` decision, the default-ON rationale, the
  no-localStorage-in-v1 choice, the GroupChatHeader single-home placement, and the AD-949a/b/c forward markers.

---

## Verified Against Codebase (2026-06-09)
```
PROGRESS.md:1-6                         BF-614 (1373/1) / BF-613 (1369/1) / AD-946b (1366/1); BF-614 triaged group voice as "AD-945 toggle likely off, not a code bug" -> AD-949 is the fix
docs/development/roadmap.md:383-388     AD-943..AD-946b rows present; NO AD-947/948/949 row yet (947/948 in-flight this wave; 949 free)
ui/src/audio/useMeetingVoice.ts:18      iface doc "metadata.meeting_active"
ui/src/audio/useMeetingVoice.ts:24      JSDoc "Self-gates on meetingActive && voiceEnabled"  (2b)
ui/src/audio/useMeetingVoice.ts:49      if (!meetingActiveRef.current) return;               (meeting self-gate — STAYS, runs first)
ui/src/audio/useMeetingVoice.ts:50      if (!useStore.getState().voiceEnabled) return;       (THE GATE — 2a)
ui/src/audio/useMeetingVoice.ts:52+     void speakRepliesSequentially(replies, { … })        (AD-921/922/923 sequencer — UNCHANGED)
ui/src/store/useStore.ts:453-454        // Audio state \n soundEnabled / voiceEnabled (field decls)  (1a anchor)
ui/src/store/useStore.ts:588            setVoiceEnabled: (v: boolean) => void;               (1b anchor)
ui/src/store/useStore.ts:929-930        soundEnabled:false / voiceEnabled:false (defaults)    (1c anchor)
ui/src/store/useStore.ts:1638-1641      setVoiceEnabled: set + localStorage hxi_voice_enabled (1d anchor)
ui/src/components/profile/GroupChatHeader.tsx:22-24   thread/agents/setChatThread selectors (3a anchor)
ui/src/components/profile/GroupChatHeader.tsx:49      const meetingActive = !!(thread.metadata…)?.meeting_active
ui/src/components/profile/GroupChatHeader.tsx:210-231 meeting-toggle block (data-testid="meeting-toggle", crew>=1)  (3b inserts after :231)
ui/src/components/profile/GroupChatHeader.tsx:233     {/* AD-937: Add control … */} (3b insert-before anchor)
ui/src/components/profile/ProfileChatTab.tsx:282-289  per-agent hxi_chat_tts_{agentId} ttsEnabled (1:1 — FENCE)
ui/src/components/profile/ProfileChatTab.tsx:508-510  meetingActive selector
ui/src/components/profile/ProfileChatTab.tsx:520      useMeetingVoice({ meetingActive }) (hook self-gates — UNCHANGED)
ui/src/components/profile/ProfileChatTab.tsx:719      speakMeetingReplies(replies as PerAgentReply[]) (UNCHANGED)
ui/src/components/profile/ProfileChatTab.tsx:800      if (ttsEnabled && reply…) speakResponse (1:1 TTS — FENCE)
ui/src/components/profile/ProfileChatTab.tsx:823      useMeetingMic({ speaking: speakingAgentId != null }) (AD-922 echo gate — now exercised)
ui/src/components/IntentSurface.tsx:93,417,440        Ship's-Computer voiceEnabled (FENCE)
ui/src/components/bridge/BridgeEnvironment.tsx:21,22,130  AD-945 ship-computer voice-output toggle (FENCE)
ui/src/audio/__tests__/useMeetingVoice.test.tsx:30,37,44,53,60,71  voiceEnabled setState sites -> callAudioEnabled (4a)
ui/src/audio/__tests__/useMeetingVoice.test.tsx:43,52  test_speaks_…_voice_enabled / test_no_speak_when_voice_disabled (rename, 4a)
ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx:11-19  vi.mock threadApi (all wrappers)
ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx:51-57  seed() real store useStore.setState({agents,chatThreads})
ui/src/components/profile/__tests__/GroupChatHeader.meeting.test.tsx:59-63  afterEach reset (extend +callAudioEnabled, 4b)
grep callAudioEnabled|setCallAudioEnabled|meetingVoiceEnabled  ui/src/**  -> 0 matches (name free; same glob returns 20 voiceEnabled hits, so the empty result is real)
```
