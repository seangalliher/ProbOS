# AD-921 — Sequenced Meeting Voice

**Phase-2 of the "Ad-hoc Crew Collaboration (group chat → meeting)" epic.**
Turn the silent AD-920 avatar gallery into a voice "call": when a meeting is active, agent replies are **spoken** — each in its own per-agent voice (AD-718) so they sound distinct, **one at a time** in the AD-915 facilitator order (no talk-over), and the speaking agent's avatar lip-syncs (AD-721b).

- **Status:** Ready to build.
- **Target repo:** OSS (`d:\ProbOS`).
- **Current highest committed AD:** **AD-920** (`23c53d79`, git-verified HEAD on `main`).
- **Dependencies:** AD-920 (meeting mode + `MeetingView` gallery + `metadata.meeting_active`), AD-915 (facilitator `speaking_order`), AD-914 (`group_chat_fanout` → `per_agent_replies`), AD-917 (send-routing branch that renders `per_agent_replies`), AD-718 (per-agent voice profiles), AD-738 (`speakResponse` dual-path TTS), AD-721b (`CrewVRM` viseme lip-sync via `useLipSyncCapture`).
- **Estimated tests:** +13 Vitest floor (2 new files). No new pytest — **the backend is untouched**.

---

## Problem

AD-920 shipped `MeetingView.tsx` — a live VRM avatar gallery that mounts one `<CrewVRM agentId={id}>` per crew participant — but its header comment is explicit: *"NO voice, NO speaking/presence indicators (AD-921/923)."* The gallery is silent.

The text path is already complete: AD-917's send-routing branch in `ProfileChatTab.tsx` posts the Captain turn to `POST /api/threads/{id}/messages`, receives `data.per_agent_replies` (`{agent_id, callsign, text}`, **already in AD-915 facilitator order**), and renders each as a callsign-prefixed agent message.

AD-921's job: when the meeting is active, **also speak** those replies — sequentially, per-agent-voiced, with the speaker's avatar lip-syncing.

### What already exists (so AD-921 builds almost nothing new)

Every primitive AD-921 needs is built and committed:

1. **`speakResponse(text, profile?, agent_id?, emotion?)`** ([ui/src/audio/voice.ts](../ui/src/audio/voice.ts#L201)) already takes a per-call `VoiceProfile` **and** an `agent_id`, and applies AD-735 volume + AD-737 emotion modulation per-agent. **It is fire-and-forget (returns `void`)** — it does **not** resolve on speech end (AD-738 kept it "still synchronous, still fires 'start'/'end' events").
2. **`onSpeechEvent(fn) → unsubscribe`** ([voice.ts:51](../ui/src/audio/voice.ts#L51)) emits `{type: 'start'|'end', agent_id?, utterance, source?}`. The `'end'` event fires on both the browser `onend` path and the server `<audio>` `'ended'`/`'error'` path ([voice.ts:288](../ui/src/audio/voice.ts#L288)). **This is how AD-921 awaits each utterance** — the exact one-shot subscribe-before-speak pattern BF-290 already uses at [ProfileChatTab.tsx:338](../ui/src/components/profile/ProfileChatTab.tsx#L338).
3. **Per-avatar lip-sync is already wired.** `CrewVRM` mounts `useLipSyncCapture({ enabled: true, agentId })` ([CrewVRM.tsx:258](../ui/src/components/profile/CrewVRM.tsx#L258)) and its own `onSpeechEvent` listener short-circuits on `if (e.agent_id !== agentId) return` ([CrewVRM.tsx:459](../ui/src/components/profile/CrewVRM.tsx#L459)), building the viseme track from `e.utterance.text` on `'start'`. **Passing the speaking agent's `agent_id` to `speakResponse` animates exactly that avatar in the gallery — AD-921 builds no lip-sync.**
4. **`per_agent_replies` is in facilitator order.** `group_chat_fanout` returns `await asyncio.gather(*[_send_one(a) for a in speaking_order])` ([thread_fanout.py:325](../src/probos/routers/thread_fanout.py#L325)); `asyncio.gather` preserves input order regardless of completion order. **The UI just speaks the array in order — no order metadata to add, no backend change.**
5. **Per-agent voice profiles** are seeded per `agent_type` in [voice_profile_defaults.py](../src/probos/voice_profile_defaults.py) (pitch/rate offsets → distinct on the browser path even when `voice_name=""`) and surfaced via `GET /api/agent/{id}/profile` → `.voiceProfile` — the same endpoint `ProfileChatTab` already fetches the host's profile from ([ProfileChatTab.tsx:537](../ui/src/components/profile/ProfileChatTab.tsx#L537)).
6. **Gating signals exist.** The `meetingActive` selector (`metadata.meeting_active`) is already in `ProfileChatTab` ([ProfileChatTab.tsx:481](../ui/src/components/profile/ProfileChatTab.tsx#L481)); the global `voiceEnabled` store flag is read at [ProfileChatTab.tsx:262](../ui/src/components/profile/ProfileChatTab.tsx#L262).

### The honest gaps AD-921 fills

- **`speakResponse` does not resolve-on-end.** AD-921 does **not** modify it — it wraps it in a Promise resolved on the matching `onSpeechEvent('end')` (the BF-290 pattern) plus a per-utterance safety timeout (so the queue never deadlocks when TTS is unavailable and `'end'` never fires).
- **`ProfileChatTab` only fetches the *host* agent's `voiceProfile`.** A meeting has *many* speakers. AD-921 adds a small per-`agent_id` resolver over the **same** `GET /api/agent/{id}/profile` endpoint, cached. On fetch failure it degrades to `undefined` (the agent speaks in the global default voice, still emotion-modulated by `agent_id`) — distinct-voice degrades to same-voice, never to silence.
- **Nothing sequences the replies into speech.** That is the one genuinely new thing: a small queue.

---

## Solution

Three pieces. **Zero changes to `voice.ts`, `useLipSyncCapture.ts`, `CrewVRM.tsx`, `MeetingView.tsx`, or any backend file.**

1. **NEW `ui/src/audio/meetingVoice.ts`** — a pure, dependency-injected sequencer (`speakRepliesSequentially`) + the per-utterance `onSpeechEvent('end')` await wrapper + a cached per-agent `VoiceProfile` resolver. No React, no WebAudio — unit-testable with injected fakes.
2. **NEW `ui/src/audio/useMeetingVoice.ts`** — a thin React hook that injects the real `speakResponse`/`onSpeechEvent`/`stripMarkdownForSpeech`, self-gates on `meetingActive && voiceEnabled`, exposes `speakingAgentId` state (the AD-923 indicator seam) and a reference-stable `speakReplies`, and supersedes an in-flight batch when the Captain sends again (generation token → no talk-over across re-sends).
3. **EDIT `ui/src/components/profile/ProfileChatTab.tsx`** — mount the hook; in the existing AD-917 group send branch, after the text-render loop, call `speakMeetingReplies(replies)`. The text render is unchanged; voice is additive and self-gating.

### The speaking → lip-sync binding (be precise)

AD-921 sets the speaking agent two ways, in lockstep, around each utterance:

- It passes the speaking `agent_id` to `speakResponse(text, profile, agent_id)`. **This is what actually drives lip-sync**: `speakResponse` fires `onSpeechEvent({agent_id, ...})`, and only the `CrewVRM` whose `agentId` matches reacts (CrewVRM.tsx:459). One speaker at a time means exactly one avatar animates.
- It calls `onSpeakingChange(agent_id)` before the utterance and `onSpeakingChange(null)` after `'end'`, surfaced by the hook as `speakingAgentId`. This is the hook's own tracking + the **AD-923** presence-indicator seam — it is *not* the lip-sync driver (that's the `agent_id` → `onSpeechEvent` → `CrewVRM` path above), but it is set with the same `agent_id` at the same moment, which is what the tests assert.

Because `speakResponse` cancels any in-flight audio at its top (`speechSynthesis.cancel()` + `_activeAudio.pause()`, voice.ts:208–215), a strictly one-at-a-time queue is both **required** (two utterances would cancel each other) and **sufficient** (each utterance is `agent_id`-tagged → routes to exactly one avatar). The existing single global audio element / global lip-sync analyser is fine *because* AD-921 serializes the utterances.

---

## Section 1 — NEW `ui/src/audio/meetingVoice.ts`

```ts
/** AD-921: Sequenced meeting voice. When a meeting is active, the per-agent
 *  replies returned by the AD-914 fan-out (already in AD-915 facilitator
 *  order) are SPOKEN one at a time — each in its own per-agent voice (AD-718)
 *  — with NO talk-over. The speaking agent_id is passed straight to
 *  ``speakResponse`` (AD-718/AD-738), whose ``onSpeechEvent`` stream the
 *  speaker's ``CrewVRM`` already consumes (filtered by agentId, CrewVRM.tsx)
 *  to drive viseme lip-sync (AD-721b). This module builds NO TTS and NO
 *  lip-sync engine — it is purely a sequencer over existing primitives.
 *
 *  ``speakResponse`` is fire-and-forget (returns void) and fires a matching
 *  ``'end'`` ``onSpeechEvent`` when the utterance finishes. We await that
 *  event per utterance (the BF-290 subscribe-before-speak one-shot pattern).
 *  When TTS is unavailable ``speakResponse`` no-ops and never fires ``'end'``;
 *  a per-utterance safety timeout resolves so the queue always drains (the
 *  meeting still shows avatars + transcript). */

import type { VoiceProfile, SpeechEvent } from './voice';

/** One entry of the AD-914 ``per_agent_replies`` array. */
export interface PerAgentReply {
  agent_id: string;
  callsign?: string;
  text: string;
}

/** Dependency-injected so the sequencer is unit-testable without WebAudio. */
export interface MeetingVoiceDeps {
  /** = ``speakResponse``: (text, profile, agent_id). Fire-and-forget. */
  speak: (text: string, profile: VoiceProfile | undefined, agentId: string) => void;
  /** = ``onSpeechEvent``: subscribe to TTS lifecycle; returns an unsubscribe fn. */
  subscribe: (fn: (e: SpeechEvent) => void) => () => void;
  /** Resolve an agent's per-agent VoiceProfile (AD-718). ``undefined`` => the
   *  global default voice (still emotion-modulated by agent_id inside
   *  ``speakResponse``). */
  resolveProfile: (agentId: string) => Promise<VoiceProfile | undefined>;
  /** Called with the agent_id immediately before each utterance and ``null``
   *  after it ends. Drives the hook's ``speakingAgentId`` (AD-923 seam). */
  onSpeakingChange?: (agentId: string | null) => void;
  /** Strip markdown for cleaner speech (= ``stripMarkdownForSpeech``). */
  strip?: (s: string) => string;
  /** Abort check evaluated before each utterance — lets a newer batch
   *  supersede an in-flight one (no talk-over across Captain re-sends). */
  shouldContinue?: () => boolean;
  /** Safety cap (ms) for the case where ``'end'`` never fires (TTS
   *  unavailable). Default 20000. ``0`` disables the timeout (tests). */
  utteranceTimeoutMs?: number;
}

const _DEFAULT_UTTERANCE_TIMEOUT_MS = 20000;

/** Speak ONE reply and resolve when its matching ``'end'`` fires (or the
 *  safety timeout elapses). Subscribe BEFORE speaking so we never race the
 *  event (BF-290). Never throws. */
function _speakAndWait(
  reply: PerAgentReply,
  profile: VoiceProfile | undefined,
  deps: MeetingVoiceDeps,
): Promise<void> {
  return new Promise<void>((resolve) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const finish = (): void => {
      if (settled) return;
      settled = true;
      try { off(); } catch { /* Tier-2: never let teardown break the queue */ }
      if (timer !== null) clearTimeout(timer);
      resolve();
    };
    const off = deps.subscribe((e: SpeechEvent) => {
      if (e.type !== 'end') return;
      // A bare 'end' with no agent_id (legacy) matches; an 'end' for a
      // DIFFERENT agent_id must NOT advance this utterance.
      if (e.agent_id && e.agent_id !== reply.agent_id) return;
      finish();
    });
    const timeoutMs = deps.utteranceTimeoutMs ?? _DEFAULT_UTTERANCE_TIMEOUT_MS;
    if (timeoutMs > 0) timer = setTimeout(finish, timeoutMs);
    const text = deps.strip ? deps.strip(reply.text) : reply.text;
    try {
      deps.speak(text, profile, reply.agent_id);
    } catch {
      // Tier-2: a throwing speak must not deadlock the queue.
      finish();
    }
  });
}

/** Speak ``replies`` strictly one at a time, in array order (AD-915
 *  facilitator order). Resolves when the queue drains. Never throws. */
export async function speakRepliesSequentially(
  replies: PerAgentReply[],
  deps: MeetingVoiceDeps,
): Promise<void> {
  for (const reply of replies) {
    if (deps.shouldContinue && !deps.shouldContinue()) break;
    const text = (reply?.text ?? '').trim();
    if (!text) continue;
    let profile: VoiceProfile | undefined;
    try {
      profile = await deps.resolveProfile(reply.agent_id);
    } catch {
      profile = undefined; // Tier-2: distinct-voice -> same-voice degrade.
    }
    if (deps.shouldContinue && !deps.shouldContinue()) break;
    deps.onSpeakingChange?.(reply.agent_id);
    try {
      await _speakAndWait(reply, profile, deps);
    } finally {
      deps.onSpeakingChange?.(null);
    }
  }
}

/** AD-921: per-agent ``VoiceProfile`` resolver backed by the existing AD-718
 *  ``GET /api/agent/{id}/profile`` endpoint (the same source ProfileChatTab
 *  uses for the host). Caches per agent_id; Tier-2 — any failure resolves to
 *  ``undefined`` (the agent speaks in the global default voice). ``fetchImpl``
 *  is injectable for tests. */
export function createVoiceProfileResolver(
  fetchImpl: typeof fetch = (typeof fetch === 'function' ? fetch : (async () => { throw new Error('no fetch'); }) as unknown as typeof fetch),
): (agentId: string) => Promise<VoiceProfile | undefined> {
  const cache = new Map<string, VoiceProfile | undefined>();
  return async (agentId: string): Promise<VoiceProfile | undefined> => {
    if (cache.has(agentId)) return cache.get(agentId);
    let profile: VoiceProfile | undefined;
    try {
      const resp = await fetchImpl(`/api/agent/${agentId}/profile`, { method: 'GET' });
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.voiceProfile) profile = data.voiceProfile as VoiceProfile;
      }
    } catch {
      profile = undefined;
    }
    cache.set(agentId, profile);
    return profile;
  };
}
```

> **Note on imports:** `SpeechEvent` and `VoiceProfile` are both exported from `voice.ts` (verified: voice.ts:11 `export interface VoiceProfile`, voice.ts:40 `export interface SpeechEvent`). Import them as **types** only (`import type { ... }`) so this module pulls in no runtime side-effects from `voice.ts`.

---

## Section 2 — NEW `ui/src/audio/useMeetingVoice.ts`

```ts
/** AD-921: thin React wrapper over the meetingVoice sequencer. Injects the
 *  real ``speakResponse`` / ``onSpeechEvent`` / ``stripMarkdownForSpeech``,
 *  gates on the meeting being active AND voice being enabled, exposes
 *  ``speakingAgentId`` (the AD-923 indicator seam), and supersedes an
 *  in-flight batch when the Captain sends again (generation token — no
 *  talk-over across re-sends). */

import { useCallback, useEffect, useRef, useState } from 'react';
import { speakResponse, onSpeechEvent, stripMarkdownForSpeech } from './voice';
import {
  speakRepliesSequentially,
  createVoiceProfileResolver,
  type PerAgentReply,
} from './meetingVoice';
import { useStore } from '../store/useStore';

export interface UseMeetingVoiceOptions {
  /** True when the active thread's ``metadata.meeting_active`` is set. */
  meetingActive: boolean;
}

export interface UseMeetingVoiceResult {
  /** Speak the AD-914 ``per_agent_replies`` in facilitator (array) order,
   *  one at a time. Self-gates on ``meetingActive && voiceEnabled``;
   *  no-ops otherwise. Reference-stable. */
  speakReplies: (replies: PerAgentReply[]) => void;
  /** The agent currently speaking (``null`` between utterances / when idle).
   *  AD-923 presence-indicator seam. */
  speakingAgentId: string | null;
}

export function useMeetingVoice(opts: UseMeetingVoiceOptions): UseMeetingVoiceResult {
  const [speakingAgentId, setSpeakingAgentId] = useState<string | null>(null);

  // Hold gating in a ref so ``speakReplies`` can stay reference-stable and be
  // called imperatively from ProfileChatTab's send callback without churning
  // its dependency array (BF-292 stale-closure discipline: read live state at
  // call time, not from closure).
  const meetingActiveRef = useRef(opts.meetingActive);
  useEffect(() => { meetingActiveRef.current = opts.meetingActive; }, [opts.meetingActive]);

  // One generation per batch: a newer batch supersedes the older one so two
  // Captain sends never talk over each other, and a stale onSpeakingChange
  // from a superseded batch can't clobber the current speakingAgentId.
  const genRef = useRef(0);
  const resolverRef = useRef(createVoiceProfileResolver());

  const speakReplies = useCallback((replies: PerAgentReply[]): void => {
    if (!meetingActiveRef.current) return;
    if (!useStore.getState().voiceEnabled) return;
    if (!Array.isArray(replies) || replies.length === 0) return;
    const myGen = ++genRef.current;
    void speakRepliesSequentially(replies, {
      speak: speakResponse,
      subscribe: onSpeechEvent,
      resolveProfile: resolverRef.current,
      strip: stripMarkdownForSpeech,
      onSpeakingChange: (id) => { if (genRef.current === myGen) setSpeakingAgentId(id); },
      shouldContinue: () => genRef.current === myGen,
    });
  }, []);

  return { speakReplies, speakingAgentId };
}
```

> **Gating decision (v1):** the meeting gate is `meetingActive && voiceEnabled` (the global store flag). The per-agent localStorage TTS override that the 1:1 conversation path uses ([ProfileChatTab.tsx:333](../ui/src/components/profile/ProfileChatTab.tsx#L333)) is intentionally **not** applied in meeting mode — a meeting has many speakers and a single per-agent key doesn't map cleanly; the meeting-level `voiceEnabled` governs. Document this in the DECISIONS.md entry.

---

## Section 3 — EDIT `ui/src/components/profile/ProfileChatTab.tsx`

Three additive edits. No existing behavior changes; the text render stays byte-identical.

### 3a — Imports

**SEARCH:**
```ts
import { speakResponse, stripMarkdownForSpeech, type VoiceProfile } from '../../audio/voice';
```
**REPLACE:**
```ts
import { speakResponse, stripMarkdownForSpeech, type VoiceProfile } from '../../audio/voice';
import { useMeetingVoice } from '../../audio/useMeetingVoice';
import type { PerAgentReply } from '../../audio/meetingVoice';
```

### 3b — Mount the hook next to the existing `meetingActive` selector

**SEARCH** (the existing AD-920 selector at ProfileChatTab.tsx:481):
```ts
  const meetingActive = useStore((s) =>
    !!(activeThreadId && (s.chatThreads.get(activeThreadId)?.metadata as Record<string, unknown> | undefined)?.meeting_active),
  );
```
**REPLACE:**
```ts
  const meetingActive = useStore((s) =>
    !!(activeThreadId && (s.chatThreads.get(activeThreadId)?.metadata as Record<string, unknown> | undefined)?.meeting_active),
  );
  // AD-921: sequenced meeting voice. speakReplies self-gates on
  // meetingActive && voiceEnabled; speakingAgentId is the AD-923 seam.
  const { speakReplies: speakMeetingReplies } = useMeetingVoice({ meetingActive });
```

### 3c — Speak the replies after the existing text-render loop

**SEARCH** (the AD-917 group send branch at ProfileChatTab.tsx:619):
```ts
          const replies = Array.isArray(data?.per_agent_replies) ? data.per_agent_replies : [];
          for (const r of replies) {
            const replyText = typeof r?.text === 'string' ? r.text : '';
            if (!replyText) continue;
            const prefix = typeof r?.callsign === 'string' && r.callsign ? `${r.callsign}: ` : '';
            useStore.getState().addAgentMessage(agentId, 'agent', `${prefix}${replyText}`);
          }
```
**REPLACE:**
```ts
          const replies = Array.isArray(data?.per_agent_replies) ? data.per_agent_replies : [];
          for (const r of replies) {
            const replyText = typeof r?.text === 'string' ? r.text : '';
            if (!replyText) continue;
            const prefix = typeof r?.callsign === 'string' && r.callsign ? `${r.callsign}: ` : '';
            useStore.getState().addAgentMessage(agentId, 'agent', `${prefix}${replyText}`);
          }
          // AD-921: when the meeting is live, ALSO speak the replies in
          // facilitator order (one at a time, per-agent voice). The text
          // render above is unchanged; voice is additive and self-gates on
          // meeting_active + voiceEnabled, so non-meeting sends stay silent.
          speakMeetingReplies(replies as PerAgentReply[]);
```

### 3d — Keep `speakMeetingReplies` in the `sendText` dependency array

`speakMeetingReplies` is reference-stable (`useCallback([])`). Add it to the `sendText` `useCallback` dependency array so the lint rule is satisfied without churn. (Locate the existing `sendText = useCallback(async (textArg: string) => { ... }, [ ... ])` deps and append `speakMeetingReplies`.)

---

## Tests

Mock the audio layer — **no real TTS / WebAudio**. Follow the existing `vi.hoisted` + `vi.mock('../voice', ...)` idiom from [ProfileChatTabVoice.test.tsx](../ui/src/__tests__/ProfileChatTabVoice.test.tsx#L7) (note `onSpeechEvent: vi.fn(() => () => {})`). Each new test file carries the epic's no-emoji guard (`expect(source).not.toMatch(/\p{Extended_Pictographic}/u)` over the new source modules).

Run with `cd ui && npx vitest run`.

### NEW `ui/src/audio/__tests__/meetingVoice.test.ts` (pure sequencer — inject fakes; ~10 tests)

Drive a fake `subscribe` that records its listener so the test can fire synthetic `'end'` events, and a fake `speak` that records `(text, profile, agentId)` calls.

1. `test_speaks_replies_in_facilitator_array_order` — three replies; assert `speak` is invoked with `agent_id`s in the **array order** given (fire each `'end'` to advance).
2. `test_waits_for_previous_end_before_next` (await-each) — after the 1st `speak`, assert the 2nd `speak` has **not** been called until the 1st `'end'` is fired; then it is. Proves strict serialization.
3. `test_end_for_other_agent_does_not_advance` — fire an `'end'` with a different `agent_id`; assert the current utterance is **not** resolved (no next `speak`); then fire the matching `'end'` and it advances.
4. `test_per_agent_profile_passed_to_speak` — `resolveProfile` returns a distinct `VoiceProfile` per `agent_id`; assert each `speak` call receives that agent's profile as the `profile` arg and the matching `agent_id`.
5. `test_speaking_change_set_then_cleared_around_each_utterance` — assert `onSpeakingChange` is called with the `agent_id` **before** `speak` and with `null` **after** the `'end'`, per utterance, in order.
6. `test_safety_timeout_drains_queue_when_end_never_fires` — `vi.useFakeTimers()`; a `speak` that never fires `'end'` + a short `utteranceTimeoutMs`; advance timers; assert the queue resolves and moves on (no deadlock). Honest-degrade for TTS-unavailable.
7. `test_should_continue_false_supersedes_remaining` — `shouldContinue` returns false after the first utterance; assert the remaining replies are **not** spoken (no talk-over on re-send).
8. `test_empty_or_whitespace_text_skipped` — a reply with `text: '   '` is skipped (no `speak`, no `onSpeakingChange`).
9. `test_resolve_profile_rejection_degrades_to_undefined` — `resolveProfile` rejects; assert `speak` is still called with `profile === undefined` (same-voice degrade, never silence).
10. `test_strip_applied_to_spoken_text` — `strip` is applied; assert `speak` receives the stripped text (and **not** the callsign prefix — the voice conveys the speaker).

Plus a tiny resolver test (can live in the same file): `test_resolver_caches_and_degrades` — `createVoiceProfileResolver(fakeFetch)` returns `data.voiceProfile`, caches (second call → no second fetch), and resolves `undefined` on `!resp.ok` / throw.

### NEW `ui/src/audio/__tests__/useMeetingVoice.test.tsx` (hook — mock sequencer + voice + store; ~5 tests)

Mock `./meetingVoice`'s `speakRepliesSequentially` (assert it's called / not called + capture its deps) and `./voice`. Seed `useStore` via `useStore.setState({ voiceEnabled })` (real store, BF-287 — **not** MagicMock).

1. `test_no_speak_when_meeting_inactive` — `meetingActive: false`; `speakReplies([...])` → `speakRepliesSequentially` **not** called.
2. `test_speaks_when_meeting_active_and_voice_enabled` — `meetingActive: true`, `voiceEnabled: true`; `speakReplies([...])` → sequencer called once with the replies.
3. `test_no_speak_when_voice_disabled` — `meetingActive: true`, `voiceEnabled: false`; sequencer **not** called (TTS-disabled honest-degrade).
4. `test_speaking_agent_id_reflects_sequencer` — invoke the captured `onSpeakingChange('bones')` then `(null)`; assert the hook's `speakingAgentId` follows.
5. `test_second_batch_supersedes_first` — call `speakReplies` twice; assert a stale `onSpeakingChange` from the first batch's generation does **not** overwrite `speakingAgentId` after the second batch started (generation-token guard).

> **Optional (recommended, not in the floor):** extend the existing `ProfileChatTab.groupsend` harness with one assertion that a meeting-active send reaches `speakMeetingReplies` and a non-meeting send does not. Keep it out of the floor to avoid the heavy-render flakiness the AD-917/920 notes call out; the hook + queue tests already cover the gating.

**Floor: +13 Vitest across the two new files.**

---

## Do NOT build (explicit non-goals)

- **NO Captain STT / voice input to the group** — that is **AD-922** (offline STT AD-705a + VAD → AD-914 fan-out). Do not add a mic, recognizer, or any speech-*input* path.
- **NO meeting presence / raise-hand / speaking indicator / transcript writeback** — that is **AD-923**. `speakingAgentId` is exposed by the hook as a forward seam, but **do not render any indicator** and do not write transcript rows from the voice path.
- **NO change to the text fan-out.** `thread_fanout.py`, `group_chat_fanout`, `per_agent_replies` shape/order, and `POST /api/threads/{id}/messages` stay byte-identical. **No backend file is touched. No new pytest.**
- **NO new TTS engine and NO new lip-sync engine.** Reuse `speakResponse` (AD-738) and the existing `CrewVRM` + `useLipSyncCapture` (AD-721b). Do **not** modify `voice.ts`, `useLipSyncCapture.ts`, `CrewVRM.tsx`, or `MeetingView.tsx`.
- **NO change to `speakResponse`'s signature or contract** (it stays fire-and-forget). Sequencing is achieved by *wrapping* it with `onSpeechEvent('end')`, not by adding a resolve-on-end return.
- **NO change to `MeetingView`'s gallery** — its `CrewVRM`s already lip-sync from `onSpeechEvent`; AD-921 only makes the speech happen.
- **NO new config field, NO new store slice, NO consensus, NO `Glyphs.tsx` change.**

---

## Tracking (same commit)

- **`PROGRESS.md`** — prepend an AD-921 block (sequencer design, reuse list, test counts, gate results).
- **`docs/development/roadmap.md`** — flip the AD-921 row (line 376) to `SHIPPED <date> gate-verified`.
- **`DECISIONS.md`** — add the AD-921 entry above AD-920: the `onSpeechEvent('end')` await wrap (no `speakResponse` change), the per-agent resolver over `GET /api/agent/{id}/profile`, the `meetingActive && voiceEnabled` gate (per-agent localStorage override intentionally not applied in meeting mode), and the generation-token no-talk-over guard.
- Stage **only** the explicit paths (NOT `git add -A`); run the deletion audit (`git diff --numstat`) — expect additive-only except the roadmap row swap. One AD = one commit (`AD-921: sequenced meeting voice`). Do not push.

---

## Acceptance criteria

- Focused: `ui/src/audio/__tests__/meetingVoice.test.ts` (≥10) and `ui/src/audio/__tests__/useMeetingVoice.test.tsx` (≥5) green — **+13 Vitest floor**.
- Full UI suite green: `cd ui && npx vitest run` → **≥ 1172 passing / 1 skipped** (AD-920 baseline 1159 / 1, +13).
- `cd ui && npm run build` (tsc -b + vite) green — no TS errors (watch the `appearance`/`department` runtime-field cast traps the AD-920 notes flag; AD-921 touches none of those, but `tsc -b` is the real gate the editor language service misses).
- No-emoji guard present and passing in each new test file.
- Sequencing verified: replies are spoken **in facilitator (array) order**, strictly one at a time (next utterance only after the previous `'end'`), each in its per-agent voice (`agent_id` + resolved `VoiceProfile`), with `speakingAgentId` set/cleared around each; voice fires **only** when `meeting_active && voiceEnabled`; TTS-unavailable degrades silently (queue drains via the safety timeout; gallery + transcript still render).
- **No backend change** — no new pytest; the Python suite count is unchanged. (Sanity: `git diff --name-only` shows only the 2 new `ui/src/audio/*.ts(x)` modules, their 2 test files, the `ProfileChatTab.tsx` edit, and the 3 tracker files.)
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-07, HEAD `23c53d79` AD-920)

```
git rev-parse HEAD
  23c53d79  (AD-920: meeting mode + avatar gallery)

# speakResponse is fire-and-forget (void), takes profile + agent_id
ui/src/audio/voice.ts:201   export function speakResponse(text, profile?, agent_id?, emotion?): void
ui/src/audio/voice.ts:206   if (!('speechSynthesis' in window) && typeof Audio !== 'function') return;   # the only no-'end' path
ui/src/audio/voice.ts:208   speechSynthesis.cancel();   # cancels in-flight => one-at-a-time required

# onSpeechEvent + SpeechEvent shape; 'end' fires on both paths
ui/src/audio/voice.ts:11    export interface VoiceProfile
ui/src/audio/voice.ts:40    export interface SpeechEvent { type; agent_id?; utterance; source? }
ui/src/audio/voice.ts:51    export function onSpeechEvent(fn): () => void
ui/src/audio/voice.ts:288   audio.addEventListener('ended', ... _fire({ type: 'end', agent_id, ... }))
ui/src/audio/voice.ts:355   utterance.onend = () => _fire({ type: 'end', agent_id, ... })   # browser fallback

# per-avatar lip-sync already wired (no AD-921 work)
ui/src/components/profile/CrewVRM.tsx:258   const lipsync = useLipSyncCapture({ enabled: true, agentId });
ui/src/components/profile/CrewVRM.tsx:459   if (e.agent_id !== agentId) return;   # onSpeechEvent filter
ui/src/components/profile/CrewVRM.tsx:468   currentTrackRef.current = buildHeuristicTrack(text, { rate });

# per_agent_replies IS in facilitator order; backend untouched
src/probos/routers/thread_fanout.py:325     replies = await asyncio.gather(*[_send_one(a) for a in speaking_order])
src/probos/routers/thread_fanout.py:333     return {"agent_id": agent_id, "callsign": callsign, "text": reply_text}

# per-agent voice profiles (agent_type seeds) + the resolver endpoint
src/probos/voice_profile_defaults.py:43     def default_voice_for(agent_type) -> VoiceProfile
ui/src/components/profile/ProfileChatTab.tsx:537   fetch(`/api/agent/${agentId}/profile`) ... data.voiceProfile

# gating signals already present in ProfileChatTab
ui/src/components/profile/ProfileChatTab.tsx:262   const globalVoiceEnabled = useStore((s) => s.voiceEnabled);
ui/src/components/profile/ProfileChatTab.tsx:481   const meetingActive = useStore((s) => ...metadata...meeting_active);

# the BF-290 one-shot subscribe-before-speak await pattern AD-921 reuses
ui/src/components/profile/ProfileChatTab.tsx:338   // Subscribe BEFORE speakResponse so we don't race the 'start' event.
ui/src/components/profile/ProfileChatTab.tsx:346   speakResponse(stripMarkdownForSpeech(replyText), voiceProfile ?? undefined, agentId);

# the group send branch AD-921 edits (text render stays unchanged)
ui/src/components/profile/ProfileChatTab.tsx:622   const replies = Array.isArray(data?.per_agent_replies) ? data.per_agent_replies : [];

# AD-920 gallery: silent, marks AD-921/923 as the voice/presence owner
ui/src/components/profile/MeetingView.tsx:6   // ... NO voice, NO speaking/presence indicators (AD-921/923).

# mock idiom for tests
ui/src/__tests__/ProfileChatTabVoice.test.tsx:15   vi.mock('../audio/voice', () => ({ speakResponse, onSpeechEvent: vi.fn(() => () => {}), ... }))

# roadmap row (canonical scope) + Phase-2 header
docs/development/roadmap.md:376   | AD-921 | Sequenced meeting voice — ... ordered by the AD-915 facilitator (no talk-over), driving viseme lip-sync (AD-721b) ... |
```

Every concrete claim above maps to one of these greps. No phantom API; the resolve-on-end TTS primitive is **not required** (the `onSpeechEvent('end')` wrap supplies sequencing) and per-avatar lip-sync **already exists** (`CrewVRM` + `useLipSyncCapture` agentId filter).
