# AD-1291 / BF-858 — One device, one owner

**Status:** Ready to build
**Issue:** #1328 (BF-858)
**Dependencies:** none (BF-764 #1222 and BF-767 already landed)
**Estimated tests:** 14–18 new (Vitest, `ui/`)
**AD ceiling when allocated:** AD-1290 — from **GitHub issue titles** (#1333–#1337 under epic #1332). `git log --all --format='%s'` and `prompts/ad-*.md` both cap at AD-1285 and cannot see the epic's unbuilt allocations.

---

## 1. The premise, verified by execution

#1328 says the cross-producer collision was **"not reproduced end to end"** and asks whoever picks it up to reproduce it first. Done — two throwaway Vitest probes, run against the live tree at `e25a1b1f`, then deleted.

### Probe A — cross-producer collision (component level, real component + real store)

```
PROBE premise OK: drain parked mid-utterance, spoken = [ 'ARRIVAL ONE.' ]
PROBE RESULT: spoken order = ["ARRIVAL ONE.","SEND PATH REPLY."]
```

A transcript burst admits two arrivals; the BF-764 drain speaks #1 and parks awaiting its `'end'`. The Captain then sends a message, and the send path calls `speakResponse` **while #1 is still in flight**. The probe asserts its own premise first (`spokenTexts() === ['ARRIVAL ONE.']`) so a drain that never parked would fail loudly rather than pass vacuously.

### Probe B — the cancel mechanism (real `voice.ts`, unmocked)

```
PROBE2a ids: 1 2  cancels after 1st: 1  after 2nd: 2
```

The second `speakResponse` issues an **additional** `speechSynthesis.cancel()` and bumps the generation token 1→2. So the collision in Probe A truncates the first utterance. Mechanism confirmed.

### Probe C — the cascade (this is the part #1328 gets wrong)

```
PROBE CASCADE: spoken order = ["ARRIVAL ONE.","SEND PATH REPLY.","ARRIVAL TWO."]
```

`voice.ts` emits the terminal `'end'` carrying the **superseded** utterance's id (BF-767). The BF-764 drain correlates on exactly that id — so a foreign producer's cancel **resolves the drain and advances it**, which starts `ARRIVAL TWO` on top of the send reply, cancelling *it* in turn.

**The failure is a mutual-cancellation cascade, not a truncation.** BF-764's own correlation guard is the mechanism that propagates it. Three utterances, none heard whole.

### Corrections to #1328

| # | Issue says | Live code at `e25a1b1f` |
|---|---|---|
| 1 | "four speech producers" (title) | Title undercounts its own body. Body describes five. **Seven** are live; nine counting voice previews. |
| 2 | send path `~L1699` | `ProfileChatTab.tsx:1732` |
| 3 | BF-290 callback `~L1882` | `ProfileChatTab.tsx:1915` |
| 4 | "three other producers **in the same component**" | False. `IntentSurface.tsx:447` and `:475` are two more producers in a **separate, always-mounted** component (`App.tsx:113`). |
| 5 | Open question: "arbiter in `voice.ts` or in the chat component?" | **Settled by (4).** A component-level queue cannot arbitrate against a sibling component. It must be `voice.ts`. |
| 6 | "burst-overlap … still reachable across producers" | Understates it. It is a **cascade** (Probe C), because the BF-764 guard converts a foreign cancel into an advance. |

Correct in the issue: `voice.ts ~L246` (actual `:248`), greeting `~L984` (exact), and "not a regression" (it is pre-existing).

### Verified producer inventory

| # | Producer | Anchor | Serialised today |
|---|---|---|---|
| 1 | BF-764 arrival drain | `ProfileChatTab.tsx:1309` | within itself only |
| 2 | Send path (1:1 reply) | `ProfileChatTab.tsx:1732` | no |
| 3 | AD-1062 call greeting | `ProfileChatTab.tsx:984` | no |
| 4 | BF-290 conversation mode | `ProfileChatTab.tsx:1915` | no |
| 5 | AD-921 meeting sequencer | `ProfileChatTab.tsx:1582` → `meetingVoice.ts:125` | within itself only |
| 6 | IntentSurface fan-out reply | `IntentSurface.tsx:447` | no |
| 7 | IntentSurface Ship's Computer | `IntentSurface.tsx:475` | no |
| – | Voice previews | `ProfileInfoTab.tsx:500,612`, `BridgeEnvironment.tsx:176` | no |

`defersToMeetingSequencer` (`ProfileChatTab.tsx:1239`) is read at **one** site — `:1341`, inside the arrivals effect. It does **not** gate producers 2, 3 or 4, so a greeting or send reply can cancel a meeting utterance mid-sequence.

---

## 2. The decision

### 2.1 Owner

**A deterministic `SpeechArbiter`, module-level, inside `ui/src/audio/voice.ts`.** One arbiter per document, because there is one audio output device per document.

**Why a service and not an agent negotiation (AD-1231).** The boundary test is *who decides what*. The audio device is a single physical resource with a hard concurrency bound of one. "Only one utterance occupies the speaker", "utterances start in admission order", "each completion is delivered exactly once", "cancellation drains deterministically" are **guarantees**, not judgements — precisely the class AD-1231 assigns to a deterministic service. Seven independent producers cannot promise that by negotiation, and the cascade above is what their negotiation actually produces.

**Why `voice.ts` and not the chat component.** Determined by evidence, not preference: `IntentSurface` is mounted at `App.tsx:113` for the whole session, concurrently with `ProfileChatTab`, and both reach the same module-level `_activeAudio` (`voice.ts:205`) and `_speakGeneration` (`:215`). An arbiter inside the chat component cannot see producers 6 and 7.

### 2.2 What the arbiter may NOT decide

This is the guard that keeps it a device owner rather than a central cognitive dispatcher. The arbiter must **not**:

1. decide **whether** an utterance is worth saying — that stays with the producer and the BF-718 ledger (`claimSpeech`, `isSpeakableAgentMessage`, `isOutputAudioEnabledNow`);
2. score, rank, prioritise or reorder by content, topic, importance, recency-of-subject, or agent;
3. choose **which agent** speaks, or attribute an utterance;
4. drop anything as redundant — deduplication belongs to the ledger;
5. read, parse, merge, summarise or rewrite utterance text;
6. consult trust, Hebbian weights, attention scores, episodic memory, or any LLM.

The **only** non-FIFO input it accepts is a two-valued class **declared by the caller**, never computed by the arbiter:

- `narration` (default) — narrates text already rendered in a visible transcript;
- `interactive` — a live conversational turn.

The entire policy is: **interactive pre-empts narration; within a class, strict FIFO.** No content is inspected to apply it. Choosing the class is the producer's decision ("what kind of thing am I saying"), which keeps the cognitive half with the caller and leaves the arbiter with ordering and delivery only.

Class assignment (fixed, not inferred):

| Producer | Class |
|---|---|
| 3 greeting, 4 BF-290 conversation mode | `interactive` |
| 2 send path **while a call is live**, else `narration` | see §3.2 |
| 1 arrivals, 5 meeting sequencer, 6, 7, previews | `narration` |

### 2.3 What happens to a losing utterance

| Case | Outcome | Why |
|---|---|---|
| `narration` behind `narration` | **Queued** | It already passed the claim ledger and the audio gate, so the system has already decided the Captain should hear it. BF-764 settled that converting an audio-quality defect into a silence defect is strictly worse. |
| `narration` behind `interactive` | **Dropped** | See below — justified, not convenient. |
| `interactive` behind `interactive` | **Queued** | Two live turns are both current; neither is redundant with visible text. |
| Any `interactive` utterance | **Never dropped** | It fails the test below. |

**The drop test: does the channel still carry the information?**

A `narration` utterance is, by construction, narration of text that is *already rendered in the transcript the Captain is looking at*. Dropping it loses the audio rendition, not the content. The alternative is worse than silence: speaking it after the live turn narrates stale text as though it were current, which actively misleads about ordering — the Captain hears an answer, then hears older narration on top of it.

So the drop is correct because the information survives on another channel. **Any drop that fails that test is forbidden**, which is exactly why an `interactive` utterance is never dropped: nothing else carries it.

**No silent drops.** Every drop emits a `dropped` record on the existing speech-event bus (a **new** event type — see §2.4), carrying the utterance id and the reason. A drop the Captain's tooling cannot observe is the failure mode this clause exists to prevent.

### 2.4 The `SpeechEvent` contract must not change

Nine consumers subscribe to `onSpeechEvent` (`voice.ts:60`). **Two of them gate the microphone:**

- `wakeWord.ts:187` — sets `_bargedIn` on `'start'`, clears on `'end'` (barge-in suppression);
- `ProfileChatTab.tsx:487` — sets `ttsActiveRef` on `'start'` (PTT echo-loop guard + BF-655 watchdog).

Therefore **`'start'` and `'end'` fire only when audio actually plays.** A queued utterance emits nothing. If the arbiter emitted `'start'` at enqueue time, the microphone would be gated while the room is silent — a new defect worse than the one being fixed.

The new `dropped` event must be **additive**: existing consumers filter on `type`, so adding a variant is inert to them. Do not repurpose `'end'` for a drop — the drain, BF-290 and the meeting sequencer all treat `'end'` as "audio finished", and a dropped utterance never started.

**`speakResponse` must keep returning the utterance id synchronously.** Both the BF-764 drain (`:1309`) and BF-290 (`:1915`) capture the return value and correlate on it *before* awaiting; BF-764's GUARD 1 additionally treats `undefined` as "nothing will ever speak". So:

> **id at enqueue, audio at dispatch, events at audio.**

`undefined` must continue to mean *only* "no TTS engine exists at all". A queued utterance returns a real id.

### 2.5 Barge-in — a regression this fix would otherwise introduce

Today, the Captain pressing the mic stops the current utterance and nothing follows it. **With a queue, stopping the current utterance lets the next one start immediately** — the Captain gets talked over by a backlog the moment they try to speak.

So the arbiter must export `flushSpeechQueue(reason)` and the existing barge-in / mic-arm paths must call it. This is named explicitly because it is a defect *the fix creates*, in the seam between the new queue and an existing consumer — the dominant defect shape in this repo.

Turn-taking answer to the issue's open question: a live call **pre-empts** rather than joins the tail. That is what `interactive` encodes; it is not a separate mechanism.

### 2.6 Relationship to the AD-921 meeting sequencer

The sequencer keeps the reveal clock. It decides **when text is revealed** relative to speech (BF-621 "hear, then see"), which is a product decision about pacing and sits above the device layer — the arbiter must not absorb it (that would be the arbiter deciding *what the Captain experiences*, not *what occupies the speaker*).

The sequencer becomes an ordinary **client**: it enqueues `narration` and keeps awaiting completion as it does now. Because the arbiter serialises, its utterances can no longer be cancelled by producers 2/3/4 mid-sequence.

`defersToMeetingSequencer` (`:1341`) stays. It is no longer needed for *device* safety, but it still selects who narrates a group room, which is a routing decision, not a device one.

---

## 3. Implementation

### Section 1 — the arbiter (`ui/src/audio/voice.ts`)

Introduce a module-level queue in front of the existing device work. Extract the current body of `speakResponse` (from the cancel block at `:246`–`:252` through the `_synthesizeAndPlay` dispatch) into a private `_playNow(...)`, and make `speakResponse` an enqueue that:

1. returns `undefined` **only** when no engine exists (`!('speechSynthesis' in window) && typeof Audio !== 'function'`) — unchanged from `:243`;
2. mints and returns the utterance id synchronously (`++_speakGeneration`), so BF-767 correlation is preserved;
3. appends `{ id, text, profile, agent_id, emotion, class }` to the queue;
4. if `class === 'interactive'`, first removes every queued-but-unstarted `narration` entry, emitting `dropped` for each;
5. kicks the drain if idle.

The drain plays one entry at a time via `_playNow`, awaiting the terminal `'end'` for that entry's id before dispatching the next.

Add a new optional fifth parameter `speechClass?: 'narration' | 'interactive'` defaulting to `'narration'`, so all existing call sites keep compiling and behave as narration until updated.

**Two guards, carried over from BF-764 verbatim in intent:**

- an entry whose `_playNow` yields no terminal `'end'` (no engine on that path) resolves immediately, or the queue wedges on entry one;
- a lost `'end'` releases on a bounded timeout — a wedged queue is a silence defect and strictly worse than overlap. Reuse the 45 s value currently at `ProfileChatTab.tsx:244`, moved into `voice.ts` and exported so the component and its tests read one constant.

Export `flushSpeechQueue(reason: string): void`.

### Section 2 — producers declare their class

| File | Anchor | Change |
|---|---|---|
| `ProfileChatTab.tsx` | `:984` greeting | pass `'interactive'` |
| `ProfileChatTab.tsx` | `:1915` BF-290 | pass `'interactive'` |
| `ProfileChatTab.tsx` | `:1732` send path | `'interactive'` when a call is live (reuse the existing call-live signal already read for `isOutputAudioEnabledNow`), else `'narration'` |
| `ProfileChatTab.tsx` | `:1309` drain | `'narration'` |
| `IntentSurface.tsx` | `:447`, `:475` | `'narration'` |

### Section 3 — remove the now-redundant component queue

With the arbiter serialising, the BF-764 drain in `ProfileChatTab.tsx` (`:1266`–`:1340`) is a second queue in front of the first. **Delete it and enqueue directly**, keeping the arrivals effect's claim/gate logic at `:1330`–`:1350` exactly as-is.

Keep the unmount cleanup at `:1259` in spirit: on unmount the component must drop **its own** queued narration, not the whole device queue (another surface may be speaking). Give `flushSpeechQueue` an optional `agentId` filter, or have the component track its ids — builder's choice, but it must not silence other surfaces.

The BF-764 tests must keep passing against the arbiter. If any assert on the component's internal queue rather than on spoken order, update them and record why inline — never delete them.

### Section 4 — barge-in

Call `flushSpeechQueue('barge-in')` wherever barge-in currently cancels speech (`wakeWord.ts` around `:187`, and the mic-arm path in `ProfileChatTab.tsx`). Verify against the BF-300 echo guard that this does not re-arm the mic mid-flush.

---

## 4. Tests

Vitest, under `ui/src/components/profile/__tests__/` and `ui/src/audio/__tests__/`.

### 4.1 The required end-to-end span

**The consumer that must accept this change is the BF-764 drain path in `ProfileChatTab.tsx`** — the strictest consumer, because it captures the synchronous return, correlates `'end'` on it, and carries both guards.

```
arrival burst admits two
  -> drain speaks ARRIVAL ONE, parks
  -> send path fires SEND PATH REPLY while ONE is in flight
  -> ASSERT: the reply has NOT reached the device
  -> fire ONE's 'end'
  -> ASSERT: SEND PATH REPLY reaches the device
  -> fire its 'end'
  -> ASSERT: ARRIVAL TWO reaches the device
```

> **This test must assert NON-OVERLAP, not order.**
> Today's cascade already produces the order `["ARRIVAL ONE.","SEND PATH REPLY.","ARRIVAL TWO."]` (Probe C) — with each utterance cancelling the previous. An acceptance test that checks only the final array **passes against the unfixed code**. Assert that each device call happens *after* the prior `'end'`, e.g. by snapshotting the call count immediately before firing each `'end'`.

Probes A and C in §1 are the pre-fix baseline; the fixed assertions above are their inverse. Reconstruct them from §1 rather than assuming a file exists — the probes were deleted.

### 4.2 Second required span — cross-component

A Ship's Computer utterance (`IntentSurface.tsx:475`, **no `agent_id`**) must **queue behind** a crew utterance from `ProfileChatTab` rather than cancel it. This is the test that proves the arbiter is at device level; a component-level queue fails it.

### 4.3 Unit coverage (`voice.ts`)

1. FIFO within `narration`; second entry dispatches only after the first `'end'`.
2. `interactive` pre-empts: queued narration is dropped, a `dropped` event fires per entry with the reason.
3. `interactive` behind `interactive` queues — never dropped.
4. A live/started utterance is **not** dropped by a later `interactive` (only queued-but-unstarted entries are).
5. GUARD 1 — an entry that will never emit `'end'` does not wedge the queue.
6. GUARD 2 — a lost `'end'` releases on the bounded timeout; assert both sides of the boundary.
7. `speakResponse` returns the id **synchronously** at enqueue, and a distinct id per call.
8. `undefined` is returned **only** when no engine exists.
9. No `'start'` / `'end'` is emitted for a queued-but-unstarted entry — **the microphone-gating invariant** (§2.4). Assert via a subscriber, not by reading internals.
10. `flushSpeechQueue()` empties pending without stopping consumers from receiving the in-flight `'end'`.
11. Barge-in: flush leaves the queue empty so nothing starts behind the Captain's voice.
12. Unmount flush drops only that surface's entries.

### 4.4 Mutation check (targeted, per repo policy)

Run the unmutated baseline **first** and abort if it is already red. Single-line anchors only (CRLF tree); an anchor that is not found is an **INERT** mutant, not a killed one — report it as such.

Mutate the **whole** pre-emption predicate, not one clause. `class === 'interactive'` and `entry.started === false` can be simultaneously decisive, so single-clause mutants may survive by masking rather than by a genuine test gap. A surviving mutant may also mean the *mutant* is wrong — check it actually reaches the behaviour before concluding a test is weak.

---

## 5. What this does NOT change

- **The BF-718 claim ledger.** Whether to speak stays with `claimSpeech` / `isSpeakableAgentMessage` / `isOutputAudioEnabledNow`. The arbiter never re-decides it.
- **The AD-921 reveal clock.** `speakRepliesSequentially` keeps owning meeting pacing (§2.6).
- **`defersToMeetingSequencer`** (`:1239`, `:1341`) stays.
- **BF-767 `utterance_id` semantics.** Ids stay per-`speakResponse`-call.
- **Any Python.** This change is entirely inside `ui/`.
- **`meetingVoice.ts:118` — deliberately out of scope.** `_speakAndWait` correlates on `agent_id` only, and a bare `'end'` with no `agent_id` matches **any** reply. `IntentSurface.tsx:475` emits exactly such a bare `'end'`, so a Ship's Computer reply can advance the meeting sequencer early. This is real, but it is **independently reachable and unchanged by the arbiter** (the bare `'end'` still fires when the queued utterance eventually plays). Per the burn-down filing policy it belongs in its own BF, not folded in here. **File it separately; do not fix it in this prompt.**

---

## 6. Notes for the builder

- **Gate with `cd ui; npx vitest run`.** This work is entirely in `ui/`, so it is **unaffected** by the broken Python tree.
- **The Python suite is currently unrunnable at `e25a1b1f`**: `browser/session.py` imports `RedirectEscalation`, which another session's uncommitted work removed (~423 tests break). You do **not** need to touch Python for this change. If you do end up needing a Python gate, run it in a linked worktree — `git worktree add`, `git apply` the staged patch, `PYTHONPATH=<wt>/src` to shadow the editable install — and note that three `test_phantom_api_precheck_*` tests fail in a linked worktree and pass in the main one; **count those three as passes.**
- **Do not touch** `README.md`, `docs/architecture/federation.md`, `docs/development/roadmap.md`, or any of `cognitive_agent.py`, `agentic_dispatch.py`, `continue_or_ask.py`, `repair_verification.py`, `fault_report.py`, `tools/browser/url_route_guard.py`. They carry another session's uncommitted work. **This design needs none of them.**
- **Reconcile the test count**: `before + new == after`. A `replace_string_in_file` whose `oldString` ends on a `def`/`it(`/`describe(` line can silently swallow an adjacent test and still leave the suite green.
- Run the adversarial diff review before committing, with a different model than the one that wrote the code.

---

## 7. Tracking

- `PROGRESS.md` — BF-858 entry, closed on merge.
- `docs/development/roadmap.md` Bug Tracker — **do not edit in this session** (foreign uncommitted work); the builder updates it once that work has landed.
- `DECISIONS.md` — AD-1291: the audio device is owned by a deterministic arbiter; producers declare a class, never a priority.

---

## 8. Acceptance criteria

1. Probe A's collision no longer occurs: a send-path reply issued while the arrival queue is mid-utterance does **not** reach the device until the in-flight utterance's `'end'`.
2. Probe C's cascade no longer occurs, asserted as **non-overlap**, not as final order (§4.1).
3. A Ship's Computer utterance from `IntentSurface` queues behind a crew utterance instead of cancelling it (§4.2).
4. No `'start'` / `'end'` is emitted for a queued-but-unstarted utterance; the PTT and barge-in gates never engage on silence (§2.4).
5. `speakResponse` still returns its id synchronously, and `undefined` still means only "no engine".
6. Both BF-764 guards hold at the arbiter: no-utterance entries and lost `'end'`s never wedge the queue.
7. Every drop emits an observable `dropped` event with a reason; no silent drops.
8. `flushSpeechQueue` is wired into barge-in, so a backlog cannot talk over the Captain.
9. All existing BF-764 / BF-767 / BF-718 / AD-921 tests pass; any test updated to assert spoken order rather than component internals records why inline.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-08-29, HEAD `e25a1b1f`)

```
rg -n "export function speakResponse|speechSynthesis\.cancel\(\)|_activeAudio\.pause|const myGen = |export function onSpeechEvent|let _activeAudio|let _speakGeneration" ui/src/audio/voice.ts
   60: export function onSpeechEvent(fn: SpeechListener): () => void {
  205: let _activeAudio: HTMLAudioElement | null = null;
  215: let _speakGeneration = 0;
  235: export function speakResponse(
  248:     speechSynthesis.cancel();
  251:     try { _activeAudio.pause(); } catch { /* ignore */ }
  258:   const myGen = ++_speakGeneration;

rg -n "speakResponse\(|speakMeetingReplies\(|const defersToMeetingSequencer|SPEECH_JOIN_TIMEOUT_MS = |const drainSpeechQueue" ui/src/components/profile/ProfileChatTab.tsx
  244: const SPEECH_JOIN_TIMEOUT_MS = 45000;
  984:         speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, requestAgentId);
 1239:   const defersToMeetingSequencer = meetingParticipantIds.length >= 2;
 1266:   const drainSpeechQueue = useCallback(async (): Promise<void> => {
 1309:           utteranceId = speakResponse(
 1582:             speakMeetingReplies(replies as PerAgentReply[], {
 1732:         speakResponse(
 1915:         ourUtteranceId = speakResponse(

rg -n "speakResponse\(" ui/src/components/IntentSurface.tsx
  447:             speakResponse(stripMarkdownForSpeech(replies[0].text), undefined, replies[0].agent_id);
  475:           speakResponse(stripMarkdownForSpeech(response));

rg -n "<IntentSurface" ui/src/App.tsx
  113:       <IntentSurface />

rg -n "speak: \(text|deps\.speak\(|e\.agent_id && e\.agent_id !== reply\.agent_id" ui/src/audio/meetingVoice.ts
   29:   speak: (text: string, profile: VoiceProfile | undefined, agentId: string) => void;
  118:       if (e.agent_id && e.agent_id !== reply.agent_id) return;
  125:       deps.speak(text, profile, reply.agent_id);

rg -n "onSpeechEvent\(" ui/src   (mic-gating consumers)
  wakeWord.ts:187            _bargeUnsubscribe = onSpeechEvent((e) => {   // _bargedIn
  ProfileChatTab.tsx:487     const unsub = onSpeechEvent((event) => {     // ttsActiveRef / PTT
```

**Absence verified**

```
CLAIM: defersToMeetingSequencer does not gate the greeting / send / BF-290 producers
RUN:   rg -n "defersToMeetingSequencer" ui/src/components/profile/ProfileChatTab.tsx
FOUND: 1239 (declaration), 1341 (single read, inside the arrivals effect), 1359 (dep array)
HOLDS: yes — the only read is at :1341; :984, :1732 and :1915 are unguarded.
```

**Probe evidence** (throwaway Vitest specs, run at `e25a1b1f`, deleted after):

```
PROBE premise OK: drain parked mid-utterance, spoken = [ 'ARRIVAL ONE.' ]
PROBE RESULT:     spoken order = ["ARRIVAL ONE.","SEND PATH REPLY."]
PROBE2a ids: 1 2  cancels after 1st: 1  after 2nd: 2
PROBE CASCADE:    spoken order = ["ARRIVAL ONE.","SEND PATH REPLY.","ARRIVAL TWO."]
```
