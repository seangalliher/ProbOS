# BF-930 (#1668): a spoken reply rides out a stall of one sentence's synthesis or storage, up to the audio already held

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27, after review round 1 and the BF-932 overlap decision (A1, section 16)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27, after review round 2 (A2, section 17: D8 hardened, claims corrected)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27, after the round-three brake (A3, section 18: split; D8 withdrawn, so A1's D8 parts and all of A2 are withdrawn; the R3-2 claim corrected). Where an earlier section and section 18 disagree, section 18 governs.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27, after the split's review (18.14: the overlap-length claim restated without a cap; text only).
**Status:** M1, M2, M4 built (`fcba563e`, `a44dd0ff`, `08a88fd0`); S3/M3 dropped; A1 built (`6a22d505`); A2 built (`1d9d5c48`); A3 (section 18) ready to build against `1d9d5c48`. **Owning issue:** #1668 (stays open: the live re-measurement is the Captain's). Commits and the PR say `Refs #1668.`, never a closing keyword.
**Base:** main `32997b18f3b12da4a58566b82b4a106193df56d5`; branch `fix/bf930-spoken-reply-stall-20261127` (worktree `D:\ProbOS-worktrees\speech-bf930`). **Number:** BF-930 is already allocated to #1668; this contract allocates no new AD or BF number.
**Line endings:** working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests (after A3):** Python 8 new in 1 new file; UI 11 new (9 in `voice.prefetch.bf918.test.tsx`: V1-V9, 2 in `voiceChunking.test.ts`: Q7-Q8), 5 changed in place against the base (P1, P2, P14 and the two `voice.pipelining.test.tsx` tests, each for lookahead 3 only); P19 is byte-identical to the base again; 0 removed against the base. A3 removes V10-V18 (they pinned D8), and returns the file's `afterEach` and `FakeAudio` to the base.
**Scope (files):** `ui/src/audio/voiceChunking.ts`, `ui/src/audio/voice.ts`, three UI test files; `src/probos/cognitive/dreaming.py`, `src/probos/routers/avatars.py`; one new Python test file; `PROGRESS.md`, `DECISIONS.md`, the regenerated ledger files. Nothing of BF-932 (#1670): `cognitive_agent.py`, `concurrency_manager.py`, `routers/agents.py`, `utils/step_timing.py`, `tests/test_bf932_reply_path_timing.py` are not touched. Nothing AD-738g owns: the backend gate (`voice.ts`:555, :567) and the `voice_name` resolution (`avatars.py`:250-262) are not touched.

## 1. Problem (premise table)

| Where | Evidence | Effect |
|---|---|---|
| `voice.ts`:261 `TTS_PREFETCH_LOOKAHEAD = 1`; `voiceChunking.ts`:99-115 (serial `ensure`, then `ensure(i+1..i+lookahead)` once item i is prepared) | sentence k+1 is requested only when sentence k starts to play | the only cushion at a boundary is the length of the sentence playing (2-5 s); a later sentence that takes longer is heard as a pause, bounded by `SPEECH_JOIN_TIMEOUT_MS` (`voice.ts`:25) |
| `avatars.py`:301 `await store.write(...)` before the route returns; :272-302 synthesis then store, then the route line :326-332 | live `probos.log.1`:64423 (2026-10-30 23:41:07): `synth_ms=164 store_ms=17618 total_ms=17782 audio_ms=3949` | one sentence arrived 17.8 s after its request, longer than any buffer of a few sentences |
| the same window, `probos.log.1`:64421-64422 | 23:40:49 then 23:41:07 from `probos.perception.consumer` (about 1 line/s normally), no line from any logger between them | the event loop itself was blocked; a store-lock convoy alone would not silence every logger |
| orchestrator's probes over `probos.log.1` (411 route lines) | `total_ms` 3-6 s: 22 of 23 windows at least 70% log-silent vs 16.4% of 4,000 matched random windows; 1.5-3 s: 7 of 11 vs 21.9%; dream lines within 20 s of 9 of 26 lines with `total_ms` >= 3 s vs 17.9% of matched windows | the large stalls are vessel-wide loop blocks; dreaming is a real contributor and a minority of the cause |
| `dreaming.py`:3184-3186 `record_activity`; callers `runtime.py`:5837, :6230 only (Absence Verified) | a spoken conversation (DM, meeting, TTS) calls neither | the idle clock runs during an interview: with the Captain's `config/system.yaml`:221-222 (`idle_threshold_seconds: 300.0`, `dream_interval_seconds: 600.0`) the monitor (`dreaming.py`:3333-3349) starts a full dream 5 minutes into a spoken conversation |
| `rg -i "loop_lag|loop lag|event.loop.(lag|block|stall)|slow_callback_duration|set_debug\(|_current_frames" src` (Absence Verified) | one docstring, `novelty_gate.py`:65 | no probe names the code that blocks the loop; the numbers that would choose a store fix do not exist (A1: BF-932's D2 sampler, #1670, supplies them; this contract no longer adds one) |
| attachments index (orchestrator, metadata only) | `.index.json` 217.4 KB, last write 2026-11-24; about 165-180 bytes per entry (`filesystem_store.py`:243-257, :361-369), so about 1.2-1.4 K entries against 11,952 files | the consult's "12 K stale entries, O(n^2) at boot" hazard is withdrawn; the live `index_entries=` field of `BF-930: attachment write slow` (`filesystem_store.py`:384-385) gives the exact count |
| live log since 2026-10-31 | no `BF-930:` line and no route line (the vessel last ran old code on 2026-11-24) | the slice-1 timing lines (`resident.py`:450, `filesystem_store.py`:384, :406) have never run live |

## 2. Overview

Two slices, both on by default, neither needing a Captain decision:

- **S1, client buffer (M1, repaired by A1).** The pipelined queue prepares up to three sentences ahead, and holds the first sentence until at least 3 s of audio, counted at the profile's playback rate, is ready (or all lookahead items are ready). A stall of one sentence no longer than the audio already held (about 10-14 s) is not heard; a longer one still pauses, for less time. A sentence the browser speaks in place of a failed one is spoken as on the base, and the next server sentence can overlap it (BF-918's registered R3, a known pre-existing limit; A3 withdrew D8, the follow-up redesigns it). Backend-independent (Piper today, Kokoro in AD-738g).
- **S2, speech holds off the idle full dream (M2).** The TTS route records each accepted request on the dream scheduler through a new bounded method, so while spoken replies come less than `idle_threshold_seconds` apart an idle full dream does not start; one stretch of speech can hold it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h). Past the cap speech stops resetting the idle clock, and the dream starts when the monitor's conditions hold (`idle_threshold_seconds` since the last activity, `dream_interval_seconds` since the last dream). The idle full dream logs its start and finish, so the Captain can see the dream state before recording.

Rejected, one line each:
- **S3, a loop-lag probe (was M3; dropped by A1):** BF-932's D2 loop-stall sampler (#1670, `utils/loop_stall.py`, `system.loop_stall_warn_seconds`) logs the same evidence; one sampler, not two.
- **S4, write-behind of spoken audio (the consult's slice 2):** left out of this contract (D1). The log-silent windows show the loop blocked, which moving the store write does not fix; there is no `behind=` evidence of a lock convoy yet; it is the riskiest change (new module, three routes, task lifecycle).
- A separate store or lock domain for `tts_audio`; audio inline in the response: rejected in the consult (they break `filesystem_store.py`:473-475's one-instance rule or AD-731, `avatars.py`:289-290).
- Making lookahead or the start buffer config fields: D2.
- `record_activity()` unbounded from the route: continuous machine-driven speech (crew meetings through `useMeetingVoice.ts`:158) could starve the full dream for ever.
- (A1, withdrawn by A3) A rate- or length-scaled browser wait. (A2, withdrawn by A3) Bounding the single-call path's browser fallback.
- (A3) Keeping D8 and guarding its late `start` (round 3's smallest fix): the wait emulates an end the browser engine has not reported, and every round found a new collision between the emulated event and a real one; the guard would leave a late utterance audible with the PTT gate open (section 18.1). The round-three brake chose split: the overlap is the base's registered R3, deferred to a follow-up with a design that owns the utterance's lifecycle.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Slices S1 and S2 in this order, one PR; trackers last (A1: S3 dropped, BF-932's D2 covers it). S4 is not in this contract | S1 hides stalls up to the buffered audio (about 3 sentences, 10-14 s); S2 removes the one contributor we can name (dreams mid-conversation; a dream was running in the 17.8 s window, `probos.log.1`:64413 per the consult). **S4 trigger:** after this ships, on a vessel running BF-932's sampler (BF-932 merged and `system.loop_stall_warn_seconds` > 0), a live window where a route line has `store_ms` >= 1000, its `BF-930: attachment write slow` line shows `behind=` > 0 or `lock_wait_ms` >= 500, and no `BF-932: event loop blocked` line falls within 5 s of it. Without the sampler "no loop-block line" is true for free and the trigger does not count. Then the consult's write-behind design (its section 2, slice 2) is drafted as its own slice |
| D2 | `TTS_PREFETCH_LOOKAHEAD = 3` and `TTS_START_BUFFER_MS = 3000` hold for Kokoro on CPU (0.5-1.5 s per sentence) and stay module constants in `voice.ts` | a sentence of 2-5 s audio synthesized in at most 1.5 s keeps the queue ahead (real-time factor <= 0.75), and three ahead accumulates 6-15 s of cushion; a short first sentence waits at most one more synthesis (<= 1.5 s). A config field would have to cross the wire (`/api/avatars/tts/status`) into the browser, widening a contract with no measured need; the live check's `bf918:sentence-gap` measure is the evidence that would reopen it |
| D3 | S2's bound: a "stretch" begins at the first spoken reply after the last full dream; while the stretch is younger than `SPEECH_DREAM_DEFER_CAP_SECONDS = 7200.0`, each reply resets the idle clock; once older, speech no longer writes the clock (A1: the dream then starts when all of the monitor's conditions hold, `idle_threshold_seconds` since the last activity of any source and `dream_interval_seconds` since the last dream; not necessarily one idle threshold after the cap); the reply after that dream begins a new stretch | by construction: past the cap, `record_speech_activity` never writes `_last_activity_time`, so nothing speech does can keep the monitor's idle condition (`dreaming.py`:3361-3364 at `08a88fd0`) false. Two hours covers a recording session; micro dreams (every 10 s, unconditional, :3292) are unaffected. A module constant, not config: it is a safety bound, and the operator's lever stays `idle_threshold_seconds` |
| D4 | S2's call sits in the route after validation and before synthesis; a runtime without a scheduler (`getattr(runtime, "dream_scheduler", None)`, the same style as `voice_synthesis` at :271) skips it | every accepted request is activity, including one whose synthesis stalls or degrades; the stand-in runtimes of the existing route tests have no scheduler |
| D5 | Superseded by A1 (S3 dropped) | - |
| D6 | Superseded by A1 (S3 dropped) | - |
| D7 | The S1 buffer counts a sentence of unknown duration (0 or missing) or a failed prepare (`null`) as a full 3000 ms | both then start exactly as today; only a known-short first sentence waits |
| D8 | **Withdrawn by A3 (section 18): the browser fallback behaves as on the base; the overlap is the known pre-existing limit R3, redesigned in the follow-up.** Record of what was built and withdrawn: (A1, hardened by A2) In the AD-1071 queue (`last` set), `_playPreparedSpeech` awaits each browser fallback (failed prepare, refused `play()`, a media `error` followed by the `play()` rejection, a throw in the play half). `_speakBrowserFallback(..., maxWaitMs)` is the one helper: with `maxWaitMs` it registers the utterance's single-settle `_fireBrowserEnd` as the module's `_settleBrowserSentence` and arms the bound. The wait ends exactly once, on the first of: `onend`, `onerror`, a stop (`stopSpeaking`), a newer dispatch (`_playNow`), the test seam, or `BROWSER_SENTENCE_MAX_WAIT_MS` = 20000, where it logs one `console.warn`. Every exit fires the utterance's one terminal 'end' (so the arbiter's GUARD 2 counts the bound as progress) and clears the timer. After a media `error` the play half also waits for `play()` to settle, because Chromium rejects it after the event. The single-call path and `speakResponse`'s callers pass no `maxWaitMs`: no timer, no settler, resolved at once, as on the base | the queue starts sentence N+1 only after `play` resolves (`voiceChunking.ts`:134-139); the base overlaps in the common case too (section 17.1). 20 s: past about 45 words at the default rate, inside `SPEECH_JOIN_TIMEOUT_MS` (45 s). A browser or voice can fail to report an end (round 2 found no ~15 s cut-off for the local Microsoft David voice: 25 s with only `start`); a sentence that really speaks longer than 20 s is overlapped after the bound, with one warning |
| D9 | (A1) `PreparedSpeech.playMs` = server `duration_ms` / `_playbackRate(profile?.rate)` (0.95 when unset, clamped to [0.25, 4.0]); the play half uses the same helper for `audio.playbackRate` | the buffer must count the time the sentence plays. Limit: with an `agent_id` the play half applies emotional modulation (`_resolveEffectiveProfile`), whose rate can differ from the profile's; the buffer uses the unmodulated rate |

## 4. Milestones and commits

Commit each milestone separately, explicit paths only. No subject carries an `AD-` or `BF-` token or the words close, fix or resolve.

| M | Pairs | Commit subject |
|---|---|---|
| M1 | 6.1-6.5 | `Spoken replies buffer three sentences ahead and hold a short first sentence until the next is ready` |
| M2 | 6.6-6.8 | `A spoken reply holds off the idle full dream for up to two hours, and the idle dream logs its start and finish` |
| M3 | removed by A1 (S3 dropped; its pairs 6.9-6.11 are gone) | - |
| M4 | 6.12-6.13, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change | `Trackers record the spoken-reply buffer, the speech dream guard and the loop-lag probe` (committed as `08a88fd0`; stands) |
| A1 | A1.1-A1.18 (section 16), then `gen_ad_ledger.py` as in M4 | `Spoken replies wait for a sentence the browser speaks, count the start buffer at playback speed, and state their limits` (committed as `6a22d505`) |
| A2 | A2.1-A2.17 (section 17), then `gen_ad_ledger.py` as in M4 | `A browser-spoken sentence in the reply queue ends on a stop, a new reply or its bound, and a media error's fallback is awaited` (committed as `1d9d5c48`; withdrawn by A3) |
| A3 | A3.1-A3.19 (section 18), then `gen_ad_ledger.py` as in M4 | `The reply queue speaks a failed sentence through the browser as before, and the bounded browser wait is withdrawn` |

Each body ends `Refs #1668.` and the attribution lines of the session.

## 5. Builder: may and may not

- **May:** apply the pairs in order (for A1: the A1 pairs against the tree at `08a88fd0`; for A2: the A2 pairs against `6a22d505`; for A3: the A3 pairs against `1d9d5c48`, after the orchestrator has replaced every `#<new>` in section 18 with the follow-up's number), create the new files the pairs name (A1 creates none), run `gen_ad_ledger.py`, `git diff --check`, `git diff --stat`.
- **May not:** run tests, commit, edit an unnamed file (never `config/system.yaml`), add `skip` or a retry, reword an anchor, or touch `voice.ts`:548-570 or `avatars.py`:250-262. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

6.1-6.8 and 6.12-6.13 were applied by M1, M2 and M4 and are kept as the record of what those commits did. Where A1 (section 16) changes their text (P3, P5, P6, P19's comment, the `record_speech_activity` docstring, the trackers), A1 governs; where A2 (section 17) changes A1's (the browser wait, V9, the lookahead comment, the trackers), A2 governs; A3 (section 18) withdraws the browser wait of A1 and A2 (restoring the base text of those hunks), keeps V9 as A2 wrote it, and governs the lookahead comment and the trackers. 6.9-6.11 (S3) are removed.

### 6.1 `ui/src/audio/voiceChunking.ts`

**P1.** SEARCH:
```ts
 *  Lookahead 0 is AD-1071's sequential queue. Returns the number of items played.
 *  Pure control flow: the Audio/fetch side-effects live in the injected callbacks. */
export async function runPrefetchQueue<P>(
  items: string[],
  prepare: (item: string, index: number) => Promise<P | null>,
  play: (prepared: P | null, item: string, index: number) => Promise<void>,
  shouldContinue: () => boolean,
  lookahead = 1,
  discard: (prepared: P | null) => void = () => {},
): Promise<number> {
```
REPLACE:
```ts
 *  Lookahead 0 is AD-1071's sequential queue. Returns the number of items played.
 *  BF-930 (#1668): `startWhen` holds the FIRST item. Before it plays, the queue keeps
 *  preparing items 1..lookahead until `startWhen(ready)` is true (`ready` is item 0 and
 *  every later item prepared so far, in order) or all of them are ready, so it starts
 *  after at most `lookahead` more preparations. `shouldContinue` is re-checked after
 *  each one; a stop during the wait plays nothing and discards every prepared item.
 *  The default (`() => true`) starts at once, as before.
 *  Pure control flow: the Audio/fetch side-effects live in the injected callbacks. */
export async function runPrefetchQueue<P>(
  items: string[],
  prepare: (item: string, index: number) => Promise<P | null>,
  play: (prepared: P | null, item: string, index: number) => Promise<void>,
  shouldContinue: () => boolean,
  lookahead = 1,
  discard: (prepared: P | null) => void = () => {},
  startWhen: (ready: Array<P | null>) => boolean = () => true,
): Promise<number> {
```

**P2.** SEARCH:
```ts
      for (let k = i + 1; k <= i + lookahead; k += 1) ensure(k);
      try {
        await play(prepared, items[i], i);
```
REPLACE:
```ts
      for (let k = i + 1; k <= i + lookahead; k += 1) ensure(k);
      if (i === 0) {
        // BF-930 (#1668): hold the first item until enough is ready to cover a stall.
        const ready: Array<P | null> = [prepared];
        let stopped = false;
        for (let k = 1; k <= lookahead && k < items.length && !startWhen(ready); k += 1) {
          ready.push(await pending[k]);
          if (!shouldContinue()) { stopped = true; break; }
        }
        // Items 1..k stay unconsumed, so the finally below discards them.
        if (stopped) { discard(prepared); break; }
      }
      try {
        await play(prepared, items[i], i);
```

### 6.2 `ui/src/audio/voice.ts`

**P3.** SEARCH:
```ts
/** BF-918 (#1626): sentences synthesized ahead of the one playing under AD-1071
 *  pipelining. One hides a sentence's synthesis behind the previous one's
 *  playback, and caps what a stopped reply can have spent at one sentence. */
const TTS_PREFETCH_LOOKAHEAD = 1;
```
REPLACE:
```ts
/** BF-918 (#1626): sentences synthesized ahead of the one playing under AD-1071
 *  pipelining. BF-930 (#1668): three (was one), so a sentence whose synthesis or
 *  storage stalls is covered by up to three sentences of audio already held; a
 *  stopped reply can have spent up to three syntheses (CPU only). */
const TTS_PREFETCH_LOOKAHEAD = 3;

/** BF-930 (#1668): audio the queue holds before the first sentence plays. A first
 *  sentence at least this long plays at once, as before; a shorter one waits for the
 *  next (at most TTS_PREFETCH_LOOKAHEAD more syntheses). */
const TTS_START_BUFFER_MS = 3000;

/** BF-930: `startWhen` of the AD-1071 queue. A sentence of unknown duration (0 or
 *  missing) or one whose preparation failed (`null`) counts as a full buffer, so it
 *  starts exactly as before. */
function _startBufferFilled(ready: Array<PreparedSpeech | null>): boolean {
  let held = 0;
  for (const prepared of ready) {
    held += prepared !== null && prepared.durationMs > 0 ? prepared.durationMs : TTS_START_BUFFER_MS;
  }
  return held >= TTS_START_BUFFER_MS;
}
```

**P4.** SEARCH:
```ts
            () => _activeUtteranceId === utterance_id,
            TTS_PREFETCH_LOOKAHEAD,
            _discardPreparedSpeech,
          );
```
REPLACE:
```ts
            () => _activeUtteranceId === utterance_id,
            TTS_PREFETCH_LOOKAHEAD,
            _discardPreparedSpeech,
            _startBufferFilled,
          );
```

**P5.** SEARCH:
```ts
interface PreparedSpeech {
  audio: HTMLAudioElement;
  visemes: LipSyncFrame[] | null;
  deferredVisemes: Promise<LipSyncFrame[]> | null;
}
```
REPLACE:
```ts
interface PreparedSpeech {
  audio: HTMLAudioElement;
  visemes: LipSyncFrame[] | null;
  deferredVisemes: Promise<LipSyncFrame[]> | null;
  /** BF-930: the server's `duration_ms`; 0 when absent or not a positive number. */
  durationMs: number;
}
```

**P6.** SEARCH:
```ts
      deferredVisemes: deferred ? _fetchDeferredVisemes(data.audio_attachment_id) : null,
    };
```
REPLACE:
```ts
      deferredVisemes: deferred ? _fetchDeferredVisemes(data.audio_attachment_id) : null,
      durationMs: typeof data.duration_ms === 'number' && Number.isFinite(data.duration_ms) && data.duration_ms > 0
        ? data.duration_ms
        : 0,
    };
```

### 6.3 `ui/src/audio/__tests__/voiceChunking.test.ts`

**P7.** SEARCH:
```ts
    expect(prepare).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });
});
```
REPLACE:
```ts
    expect(prepare).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it('Q7 BF-930: startWhen holds the first item, and the queue still starts after at most lookahead more items', async () => {
    const h = harness();
    let go = true;
    const done = runPrefetchQueue(['a', 'b', 'c', 'd'], h.prepare, h.play, () => go, 2, () => {}, () => false);
    await flush();
    h.preps[0]();
    await flush();
    expect(h.events).toEqual(['prep:a', 'prep:b']); // a is ready and waits
    h.preps[1]();
    await flush();
    expect(h.events).toContain('prep:c');
    expect(h.events).not.toContain('play:a');
    h.preps[2]();
    await flush();
    expect(h.events).toContain('play:a'); // lookahead 2 reached: it starts anyway
    expect(h.events).not.toContain('prep:d');
    go = false;
    h.ends[0]();
    expect(await done).toBe(1);
  });

  it('Q8 BF-930: a stop during the start wait plays nothing and discards every prepared item', async () => {
    const h = harness();
    let go = true;
    const discarded: Array<string | null> = [];
    const done = runPrefetchQueue(['a', 'b', 'c'], h.prepare, h.play, () => go, 2, (p) => { discarded.push(p); }, () => false);
    await flush();
    h.preps[0]();
    await flush();
    h.preps[1]();
    await flush(); // a and b are ready; c is being prepared
    go = false;
    h.preps[2]();
    expect(await done).toBe(0);
    await flush();
    expect(discarded).toEqual(['a', 'b', 'c']);
    expect(h.events).not.toContain('play:a');
  });
});
```

### 6.4 `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx`

**P8.** SEARCH:
```ts
async function _flush(): Promise<void> {
  for (let i = 0; i < 40; i++) await Promise.resolve();
}
```
REPLACE:
```ts
async function _flush(): Promise<void> {
  // BF-930: three sentences prepared in a row take more microtask hops (harness only).
  for (let i = 0; i < 120; i++) await Promise.resolve();
}
```

**P9.** SEARCH:
```ts
  framesFor?: (attachmentId: string) => unknown[];
}
```
REPLACE:
```ts
  framesFor?: (attachmentId: string) => unknown[];
  /** BF-930: `duration_ms` of the nth TTS answer (1-based nth at index nth-1); 0 when absent. */
  durations?: number[];
}
```

**P10.** SEARCH:
```ts
      nth += 1;
      const sha = String.fromCharCode(97 + nth).repeat(64);
      const response = {
        ok: true,
        json: async () => ({
          backend: 'piper',
          audio_attachment_id: sha,
          mime: 'audio/wav',
          visemes: plan.inlineVisemes ?? [],
          visemes_deferred: plan.deferVisemes === true,
          duration_ms: 0,
```
REPLACE:
```ts
      nth += 1;
      const sha = String.fromCharCode(97 + nth).repeat(64);
      const durationMs = plan.durations?.[nth - 1] ?? 0;
      const response = {
        ok: true,
        json: async () => ({
          backend: 'piper',
          audio_attachment_id: sha,
          mime: 'audio/wav',
          visemes: plan.inlineVisemes ?? [],
          visemes_deferred: plan.deferVisemes === true,
          duration_ms: durationMs,
```

**P11 (P1, changed in place).** SEARCH:
```ts
    voiceMod.speakResponse('One. Two. Three.');
    await _flush();
    expect(f.posted).toEqual(['One.', 'Two.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, false]);
    expect(f.bodies.every((b) => b.defer_visemes === true)).toBe(true);
```
REPLACE:
```ts
    voiceMod.speakResponse('One. Two. Three.');
    await _flush();
    // BF-930 (#1668): lookahead 3 (was 1): both later sentences are synthesized while One plays.
    expect(f.posted).toEqual(['One.', 'Two.', 'Three.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, false, false]);
    expect(f.bodies.every((b) => b.defer_visemes === true)).toBe(true);
```

**P12 (P2, changed in place).** SEARCH:
```ts
      // The prefetch premise: sentence two had been prepared while one played.
      expect(audiosWhileOnePlayed).toBe(2);
      expect(f.posted).toEqual(['One.', 'Two.']);
      expect(createdAudios[1].played).toBe(false);
      expect(createdAudios[1].discarded).toBe(true);
```
REPLACE:
```ts
      // The prefetch premise: sentences two and three had been prepared while one played
      // (BF-930 #1668: lookahead 3, was 1), and the stop discards both.
      expect(audiosWhileOnePlayed).toBe(3);
      expect(f.posted).toEqual(['One.', 'Two.', 'Three.']);
      expect(createdAudios[1].played).toBe(false);
      expect(createdAudios[1].discarded).toBe(true);
      expect(createdAudios[2].played).toBe(false);
      expect(createdAudios[2].discarded).toBe(true);
```

**P13 (P14, changed in place).** SEARCH:
```ts
      voiceMod.speakResponse('One. Two. Three.');
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.']);
```
REPLACE:
```ts
      voiceMod.speakResponse('One. Two. Three.');
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.', 'Three.']); // BF-930 (#1668): lookahead 3 (was 1)
```

**P14.** SEARCH (the end of P20 and of the file):
```ts
      expect(r.events.filter((e) => e.startsWith('end'))).toEqual(['end:One.']);
      expect(r.finals).toEqual([true]);
    } finally {
      r.off();
    }
  });
});
```
REPLACE:
```ts
      expect(r.events.filter((e) => e.startsWith('end'))).toEqual(['end:One.']);
      expect(r.finals).toEqual([true]);
    } finally {
      r.off();
    }
  });
});

describe('BF-930 (#1668): a buffer of sentences, and a short first sentence waits for the next', () => {
  const spoken = (): string[] => speakCalls.map((u) => (u as FakeUtterance).text);

  async function _recordAll() {
    const voiceMod = await import('../voice');
    const events: string[] = [];
    const off = voiceMod.onSpeechEvent((e) => { events.push(`${e.type}:${e.utterance?.text ?? ''}`); });
    return { events, off };
  }

  it('V1 a first sentence shorter than the start buffer waits until the next is ready', async () => {
    const f = _makeFetch({ pipelining: true, durations: [1500, 4000, 4000], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two. Three.');
    await _flush();
    expect(f.posted).toEqual(['One.', 'Two.']);
    expect(createdAudios.length).toBe(1);
    expect(createdAudios[0].played).toBe(false); // 1.5 s held, under the 3 s start buffer
    f.release();
    await _flush();
    expect(createdAudios[0].played).toBe(true);
    expect(f.posted).toEqual(['One.', 'Two.', 'Three.']);
  });

  it('V2 a first sentence as long as the start buffer plays at once (unchanged)', async () => {
    const f = _makeFetch({ pipelining: true, durations: [4000, 4000, 4000], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two. Three.');
    await _flush();
    expect(createdAudios[0].played).toBe(true);
    expect(f.posted).toEqual(['One.', 'Two.']);
  });

  it('V3 a first sentence of unknown duration plays at once (unchanged)', async () => {
    const f = _makeFetch({ pipelining: true, durations: [0, 0, 0], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two. Three.');
    await _flush();
    expect(createdAudios[0].played).toBe(true);
  });

  it('V4 the queue synthesizes three sentences ahead; a stall longer than the buffer pauses, then resumes in order', async () => {
    const f = _makeFetch({ pipelining: true, durations: [4000, 4000, 4000, 4000], holdTts: [3] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _recordAll();
    try {
      voiceMod.speakResponse('One. Two. Three. Four.');
      await _flush();
      expect(createdAudios[0].played).toBe(true);
      expect(f.posted).toEqual(['One.', 'Two.', 'Three.']); // Three requested while One plays; Four waits behind it
      createdAudios[0].end();
      await _flush();
      expect(createdAudios[1].played).toBe(true);
      createdAudios[1].end();
      await _flush();
      // Three is still synthesizing when Two ends: silence, with no browser voice and no final end.
      expect(createdAudios.length).toBe(2);
      expect(speakCalls.length).toBe(0);
      expect(r.events.filter((e) => e.startsWith('start'))).toEqual(['start:One.', 'start:Two.']);
      f.release();
      await _flush();
      expect(createdAudios[2].played).toBe(true);
      expect(f.posted).toEqual(['One.', 'Two.', 'Three.', 'Four.']);
    } finally {
      r.off();
    }
  });

  it('V5 a stop during the start wait plays nothing, discards what was prepared, and drops the reply', async () => {
    const f = _makeFetch({ pipelining: true, durations: [1500, 1500, 1500], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _recordAll();
    try {
      voiceMod.speakResponse('One. Two. Three.');
      await _flush();
      expect(createdAudios.length).toBe(1); // One is ready and waits for Two
      voiceMod.stopSpeaking();
      await _flush();
      f.release(); // Two answers after the stop
      await _flush();
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.', 'Next.']);
      expect(createdAudios.map((a) => a.played)).toEqual([false, false, true]);
      expect(createdAudios[0].discarded).toBe(true);
      expect(createdAudios[1].discarded).toBe(true);
      expect(r.events).toEqual(['dropped:One. Two. Three.', 'start:Next.']);
    } finally {
      r.off();
    }
  });

  it('V6 a first sentence whose synthesis failed is spoken by the browser without waiting (unchanged)', async () => {
    const f = _makeFetch({ pipelining: true, failTts: [1], durations: [1500, 1500], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two.');
    await _flush();
    expect(spoken()).toEqual(['One.']);
  });
});
```

### 6.5 `ui/src/audio/__tests__/voice.pipelining.test.tsx`

**P15.** SEARCH:
```ts
  for (let i = 0; i < 30; i++) await Promise.resolve();
```
REPLACE:
```ts
  for (let i = 0; i < 90; i++) await Promise.resolve(); // BF-930: three sentences prepared in a row
```

**P16.** SEARCH:
```ts
    // BF-918: first audio still needs only the FIRST sentence; the second is
    // synthesized while the first plays (it used to wait for the first to end).
    expect(posted).toEqual(['One.', 'Two.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, false]);

    // Finishing sentence[0] plays sentence[1] and prefetches sentence[2].
```
REPLACE:
```ts
    // BF-918: first audio still needs only the FIRST sentence. BF-930 (#1668):
    // lookahead 3 (was 1), so both later sentences are synthesized while the first plays.
    expect(posted).toEqual(['One.', 'Two.', 'Three.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, false, false]);

    // Finishing sentence[0] plays sentence[1]; nothing more is synthesized.
```

**P17.** SEARCH:
```ts
    // BF-918: sentence[1] is prefetched (and fails) while sentence[0] plays;
    // its browser fallback waits for its turn.
    expect(posted).toEqual(['Alpha.', 'Bravo.']);
```
REPLACE:
```ts
    // BF-918: sentence[1] is prefetched (and fails) while sentence[0] plays;
    // its browser fallback waits for its turn. BF-930 (#1668): lookahead 3 (was 1),
    // so sentence[2] is synthesized then too.
    expect(posted).toEqual(['Alpha.', 'Bravo.', 'Charlie.']);
```

### 6.6 `src/probos/cognitive/dreaming.py`

**P18.** SEARCH:
```python
def _full_dream_complete_payload(report: DreamReport) -> dict[str, Any]:
```
REPLACE:
```python
#: BF-930 (#1668): how long one stretch of spoken replies may hold off the idle full
#: dream. A stretch begins at the first spoken reply after the last full dream; past
#: this age speech no longer resets the idle clock (see record_speech_activity).
SPEECH_DREAM_DEFER_CAP_SECONDS = 7200.0


def _full_dream_complete_payload(report: DreamReport) -> dict[str, Any]:
```

**P19.** SEARCH:
```python
        self._last_activity_time: float = time.monotonic()
        self._last_dream_time: float = 0.0
```
REPLACE:
```python
        self._last_activity_time: float = time.monotonic()
        self._speech_since: float | None = None  # BF-930: start of the current spoken stretch
        self._last_dream_time: float = 0.0
```

**P20.** SEARCH:
```python
    def record_activity(self) -> None:
        """Record that user activity occurred (resets idle timer)."""
        self._last_activity_time = time.monotonic()
```
REPLACE:
```python
    def record_activity(self) -> None:
        """Record that user activity occurred (resets idle timer)."""
        self._last_activity_time = time.monotonic()

    def record_speech_activity(self, now: float | None = None) -> bool:
        """BF-930 (#1668): a spoken reply is activity for the idle full dream, within a bound.

        A stretch begins at the first spoken reply after the last full dream. While it is
        younger than ``SPEECH_DREAM_DEFER_CAP_SECONDS`` each reply resets the idle timer
        and this returns True. Past that age it returns False and leaves the timer alone,
        so the idle full dream starts ``idle_threshold_seconds`` later at the latest; the
        first reply after that dream begins a new stretch. ``now`` is a ``time.monotonic()``
        value (default: now).
        """
        at = time.monotonic() if now is None else now
        if self._speech_since is None or self._last_dream_time > self._speech_since:
            self._speech_since = at
        if at - self._speech_since >= SPEECH_DREAM_DEFER_CAP_SECONDS:
            return False
        self._last_activity_time = at
        return True
```

**P21.** SEARCH:
```python
                if (
                    idle_time >= self.idle_threshold_seconds
                    and time_since_last_dream >= self.dream_interval_seconds
                ):
                    self._is_dreaming = True
```
REPLACE:
```python
                if (
                    idle_time >= self.idle_threshold_seconds
                    and time_since_last_dream >= self.dream_interval_seconds
                ):
                    # BF-930 (#1668): the operator reads these two lines to see whether an idle dream runs.
                    logger.info("BF-930: idle full dream starting idle_s=%.0f", idle_time)
                    idle_dream_started_at = time.monotonic()
                    self._is_dreaming = True
```

**P22.** SEARCH:
```python
                        report = await self.engine.dream_cycle()
                        self._last_dream_report = report
                        self._last_dream_time = time.monotonic()
                        # AD-503: Emit dream complete event (monitor loop, full)
```
REPLACE:
```python
                        report = await self.engine.dream_cycle()
                        self._last_dream_report = report
                        self._last_dream_time = time.monotonic()
                        logger.info(
                            "BF-930: idle full dream finished duration_ms=%.0f",
                            (self._last_dream_time - idle_dream_started_at) * 1000,
                        )
                        # AD-503: Emit dream complete event (monitor loop, full)
```

### 6.7 `src/probos/routers/avatars.py`

**P23.** SEARCH:
```python
    defer_visemes = payload.get("defer_visemes") is True

    from probos.audio.tts import select_backend
```
REPLACE:
```python
    defer_visemes = payload.get("defer_visemes") is True

    # BF-930 (#1668): a spoken reply is activity for the idle full dream, so a dream does
    # not start in the middle of a spoken conversation. The scheduler bounds it
    # (SPEECH_DREAM_DEFER_CAP_SECONDS). A runtime without a scheduler skips it.
    dream_scheduler = getattr(runtime, "dream_scheduler", None)
    if dream_scheduler is not None:
        dream_scheduler.record_speech_activity()

    from probos.audio.tts import select_backend
```

### 6.8 `tests/test_bf930_speech_defers_idle_dream.py` (new file)

```python
"""BF-930 (#1668) M2: a spoken reply holds off the idle full dream, within a bound.

Real ``DreamScheduler`` and its monitor loop, the real TTS route and attachment store;
the dreaming engine and the TTS backend are stand-ins. The scheduler's own rule is
driven with an injected ``now``; the monitor-loop tests wait on an event (a liveness
bound only) and assert no duration.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import TTSResult
from probos.cognitive.dreaming import SPEECH_DREAM_DEFER_CAP_SECONDS, DreamScheduler
from probos.config import AttachmentsConfig, LipSyncConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.types import DreamReport

_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
_DREAMING = "probos.cognitive.dreaming"
_CAP = SPEECH_DREAM_DEFER_CAP_SECONDS


class _StubBackend:
    name = "piper"

    async def synthesize(self, text, emotion=None, voice_override=None):
        return TTSResult(audio_bytes=_WAV, mime="audio/wav")


def _scheduler() -> DreamScheduler:
    engine = MagicMock()
    engine.dream_cycle = AsyncMock(return_value=DreamReport())
    engine.proactive_procedure_scan = AsyncMock(return_value={})
    return DreamScheduler(
        engine, idle_threshold_seconds=3600.0, dream_interval_seconds=0.0, micro_dream_interval_seconds=0.0,
    )


@pytest.fixture
async def speech_client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda name, cfg, service=None: _StubBackend())
    scheduler = _scheduler()
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(backend="rhubarb"),
            tts=TTSConfig(backend="piper"),
        ),
        voice_synthesis=None,
        dream_scheduler=scheduler,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, rt, scheduler
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


async def _speak(client: AsyncClient) -> None:
    response = await client.post("/api/avatars/tts", json={"text": "Yes, Captain.", "defer_visemes": True})
    assert response.status_code == 200
    assert isinstance(response.json()["audio_attachment_id"], str)


async def _monitor_two_ticks(scheduler: DreamScheduler) -> None:
    """Run the real monitor loop until its second micro dream: its first full-dream check has run by then."""
    ticks = 0
    second = asyncio.Event()

    async def _micro():
        nonlocal ticks
        ticks += 1
        if ticks >= 2:
            second.set()
        return {"episodes_replayed": 0}

    scheduler.engine.micro_dream = _micro
    scheduler._task = asyncio.create_task(scheduler._monitor_loop())  # not start(): it would reset the idle clock
    try:
        await asyncio.wait_for(second.wait(), timeout=60.0)  # liveness only
    finally:
        await scheduler.stop()


# --- the route to the monitor loop (the seam the defect crossed) ---------------------


@pytest.mark.asyncio
async def test_a_spoken_reply_keeps_a_due_idle_full_dream_from_starting(speech_client, caplog) -> None:
    client, _rt, scheduler = speech_client
    scheduler._last_activity_time = time.monotonic() - 7200.0  # idle for two hours: a full dream is due
    caplog.set_level(logging.INFO, logger=_DREAMING)

    await _speak(client)
    await _monitor_two_ticks(scheduler)

    assert scheduler.engine.dream_cycle.await_count == 0
    assert not any("BF-930: idle full dream starting" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_control_without_speech_the_due_idle_full_dream_starts_and_logs_start_and_finish(speech_client, caplog) -> None:
    _client, _rt, scheduler = speech_client
    scheduler._last_activity_time = time.monotonic() - 7200.0
    caplog.set_level(logging.INFO, logger=_DREAMING)

    await _monitor_two_ticks(scheduler)

    assert scheduler.engine.dream_cycle.await_count >= 1
    messages = [r.getMessage() for r in caplog.records if r.name == _DREAMING]
    assert any(m.startswith("BF-930: idle full dream starting idle_s=") for m in messages)
    assert any(m.startswith("BF-930: idle full dream finished duration_ms=") for m in messages)


@pytest.mark.asyncio
async def test_the_route_leaves_the_idle_clock_alone_once_a_stretch_is_past_the_cap(speech_client) -> None:
    client, _rt, scheduler = speech_client
    now = time.monotonic()
    scheduler._speech_since = now - _CAP - 1.0  # a stretch older than the cap ...
    scheduler._last_dream_time = now - _CAP - 2.0  # ... with no full dream since it began
    scheduler._last_activity_time = now - 7200.0

    await _speak(client)

    assert scheduler._last_activity_time == now - 7200.0


@pytest.mark.asyncio
async def test_a_runtime_without_a_scheduler_still_speaks(speech_client) -> None:
    client, rt, _scheduler = speech_client
    rt.dream_scheduler = None
    await _speak(client)


# --- the scheduler's rule, with an injected clock -------------------------------------


def test_speech_resets_the_idle_timer_until_its_stretch_reaches_the_cap() -> None:
    scheduler = _scheduler()
    assert scheduler.record_speech_activity(now=1000.0) is True
    assert scheduler._last_activity_time == 1000.0
    last = 1000.0 + _CAP - 1.0
    assert scheduler.record_speech_activity(now=last) is True
    assert scheduler.record_speech_activity(now=1000.0 + _CAP) is False
    assert scheduler._last_activity_time == last  # unchanged: the full dream is due idle_threshold_seconds later


def test_a_full_dream_after_the_stretch_began_starts_a_new_stretch() -> None:
    scheduler = _scheduler()
    scheduler.record_speech_activity(now=1000.0)
    late = 1000.0 + _CAP + 5.0
    assert scheduler.record_speech_activity(now=late) is False
    scheduler._last_dream_time = late + 10.0  # as the monitor loop sets it when a full dream completes
    assert scheduler.record_speech_activity(now=late + 20.0) is True
    assert scheduler._last_activity_time == late + 20.0


def test_the_first_reply_after_start_begins_a_stretch() -> None:
    scheduler = _scheduler()
    assert scheduler.record_speech_activity(now=5.0) is True  # _last_dream_time is 0.0 at construction
    assert scheduler.record_speech_activity(now=5.0 + _CAP) is False


def test_typed_activity_is_not_bounded_by_the_speech_cap() -> None:
    scheduler = _scheduler()
    scheduler.record_speech_activity(now=0.0)  # 0.0: below any time.monotonic() value, whatever the uptime
    scheduler.record_speech_activity(now=_CAP)  # refused: past the cap
    before = scheduler._last_activity_time
    scheduler.record_activity()
    assert scheduler._last_activity_time > before
```

### 6.9-6.11 (removed by A1)

The S3 pairs (`src/probos/utils/loop_lag.py`, `__main__._serve` P24-P25, `tests/test_bf930_loop_lag_probe.py`) were removed with S3: BF-932's D2 sampler (#1670) covers it. The branch never carried them after the overlap decision; nothing of them is to be applied.

### 6.12 `PROGRESS.md`

**P26.** SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-930 (2026-11-27), #1668 -- a spoken reply no longer pauses mid-way when one sentence's synthesis or storage stalls.** The AD-1071 sentence queue now synthesizes up to three sentences ahead (was one) and holds a first sentence shorter than 3 s of audio until the next is ready (`ui/src/audio/voice.ts`, `voiceChunking.ts`: `runPrefetchQueue` gains `startWhen`), so a stalled sentence is covered by the audio already held; an unknown duration or a failed synthesis starts as before. The TTS route records each request on the dream scheduler (`DreamScheduler.record_speech_activity`), so an idle full dream does not start during a spoken conversation; one stretch of speech holds it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h), and the idle full dream logs `BF-930: idle full dream starting/finished`. The vessel's `_serve` runs a log-only loop-lag probe (`probos.utils.loop_lag`): a loop that does not answer a heartbeat within 1 s is logged as `BF-930: event loop blocked` with the loop thread's stack (code locations only), at most once per 30 s. Write-behind of spoken audio is not built: the 2026-10-30 stalls silenced every logger (a blocked loop), and it waits for `behind=` evidence. #1668 stays open for the Captain's live re-measurement. New `tests/test_bf930_speech_defers_idle_dream.py`, `tests/test_bf930_loop_lag_probe.py`; UI V1-V6, Q7-Q8; P1, P2, P14 and two pipelining tests updated in place for lookahead 3. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
```

### 6.13 `DECISIONS.md`

**P27.** SEARCH (the newest entry heading at build time; today the BF-1002 entry. If another entry has landed above it, anchor on that heading instead, as this label allows):
```markdown
### BF-1002 -- a full dream's dream_complete event reaches its listeners; one helper builds the payload for both emit sites (2026-11-27, #1820)
```
REPLACE:
```markdown
### BF-930 -- A spoken reply buffers three sentences, holds off the idle full dream, and a probe names what blocks the loop (2026-11-27, #1668)

- *Scope.* `ui/src/audio/voice.ts`, `ui/src/audio/voiceChunking.ts`, `cognitive/dreaming.py` (`record_speech_activity`, `SPEECH_DREAM_DEFER_CAP_SECONDS`, idle-dream start/finish lines), `routers/avatars.py`, `utils/loop_lag.py` (new), `__main__._serve`. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
- *D1.* Client buffer: lookahead 3 and a 3000 ms start buffer, module constants (a config field would cross the wire into the browser with no measured need). Unknown duration and a failed synthesis count as a full buffer.
- *D2.* Speech is activity for the idle full dream, bounded: a stretch begins at the first spoken reply after the last full dream, and past 2 h speech stops resetting the idle clock, so the dream starts `idle_threshold_seconds` later at the latest. Not `record_activity()` from the route: machine-driven speech could starve dreaming for ever.
- *D3.* The loop-lag probe is log-only, started only by the vessel's `_serve`, and its `stop()` never joins (it runs on the loop thread).
- *D4.* Write-behind of spoken audio is deferred until a live window shows a store stall with `behind=` > 0 or `lock_wait_ms` >= 500 and no loop-block report within 5 s.
- *Reversal.* Revert the commits; no persisted format changes.

### BF-1002 -- a full dream's dream_complete event reaches its listeners; one helper builds the payload for both emit sites (2026-11-27, #1820)
```

## 7. Consumers

| Contract | Consumer | After the change |
|---|---|---|
| `runPrefetchQueue` signature | `voice.ts`:588 (only production caller); `voiceChunking.test.ts` Q1-Q6 pass 5-6 args | the 7th arg defaults to `() => true`: Q1-Q6 unchanged |
| `TTS_PREFETCH_LOOKAHEAD` | the pipelined path only (`status.sentence_pipelining_enabled`, `voice.ts`:579); pipelined UI tests exist only in `voice.prefetch.bf918.test.tsx` and `voice.pipelining.test.tsx` (Absence Verified) | P1, P2, P14 and two pipelining tests changed in place; P3, P6, P8, P9, P15-P18, P20 hold (two-sentence replies, holds, or post-hoc assertions); P19 changed in place by A1 (it pinned the overlap) |
| `PreparedSpeech` | built only at `voice.ts`:712-719 (at `08a88fd0`); its fields read by `_startBufferFilled` (:275, the duration), `_playPreparedSpeech` (:761) and `_discardPreparedSpeech` (:845-846, `audio` only) | gains `durationMs` (M1), renamed `playMs` and divided by the playback rate (A1) |
| `_speakBrowserFallback`, `stopSpeaking`, `_playNow`, `_resetTtsStatusForTests`, `_playPreparedSpeech`'s fallback paths | (A3) every caller and the arbiter (GUARD 2, `_awaitEntry`) | byte-identical to the base after A3: A1's and A2's changes there (`Promise<void>`, `maxWaitMs`, the settler and its three calls, `browserDone`, `playSettled`, `mediaError`) are withdrawn |
| browser-fallback UI tests | `voice.prefetch.bf918` P11, P13 (single call), V6, P19; `voice.pipelining` honest-degrade; `voice.serverTts` :129, :159 (single call) | (A3) P19 byte-identical to the base again; honest-degrade back to its M1 text (the lookahead assertion only); V6 unchanged (it asserts the base behaviour); V10-V18 removed with D8 |
| `ProfileChatTab.bf918.test.tsx` M6/M7 (:533-680) | pipelined two-sentence replies with no `duration_ms` | unknown duration: start at once; lookahead irrelevant for two sentences |
| TTS route | `test_bf918_tts_latency.py`, `test_bf930_voice_path_timing.py`, `test_ad738_piper_tts.py`, `test_ad738e_1_per_emotion_prosody.py`, `test_bf291_piper_voice_catalog.py`, `test_ad721b1_rhubarb_backend.py`, `test_ad721e_animation_manifest.py`, `test_ad1071_tts_pipelining.py`, `test_bf918_tts_retention.py`, `test_bf918_attachment_io.py` | their stand-in runtimes have no `dream_scheduler` (SimpleNamespace) or a MagicMock one: skipped or a no-op call |
| `DreamScheduler` | `runtime.py`:3286 (holds it), `test_dreaming.py` (:420, :448, :489-504, :619-627 set or read `_last_activity_time`), `test_bf1002_full_dream_complete_event.py` | one new field, one new method, two INFO lines; `record_activity` unchanged |
| live log readers | the Captain's live check (section 12) | two new line kinds (`BF-930: idle full dream starting/finished`); loop-block lines are BF-932's |
| HXI devtools console | the operator | (A3) no new line: the `[voice] BF-930: browser speech gave no end or error ...` warning went with D8 |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts
- Each SEARCH of section 6 counted at its turn: 1 each; the new file did not exist (done for M1-M2). For A1: each SEARCH of 16.2 counted at its turn on `08a88fd0`: 1 each.
- A/B on main (the new tests and the changed UI tests on the base without the source pairs):
  - UI: V1 (played before release), V4 (`posted` has two), V5 (a `start:One.` event), Q7 (first `toEqual`), and the changed P1, P2, P14 and two pipelining tests fail on assertions; Q8 fails by vitest's test timeout (on main `a` plays and its `play` never ends). V2, V3, V6 pass on both trees (preservation).
  - Python: `test_a_spoken_reply_keeps_a_due_idle_full_dream_from_starting` fails on main at `await_count == 0` (the route does not touch the scheduler) once the import of `SPEECH_DREAM_DEFER_CAP_SECONDS` is satisfied; record the rest of that file as new-API cases (they fail on import on main), not as A/B evidence. The control test passes on both trees apart from its log-line asserts.
- A1 A/B (the A1 test pairs on `08a88fd0` without the A1 source pairs A1.1-A1.11): V7 (`played` false expected, plays at once), V8 (expected to play at once, waits), V10 (`spoken()` is `['One.', 'Two.']`: Two plays while still blocked), V11 and V12 (Three already played), changed P19 and the changed honest-degrade test (`createdAudios[1].played` is true before the browser's end) fail on assertions. V9 passes on both trees (it guards the clamp; R2 kills it). A1.12-A1.14 count once each on `08a88fd0`.
- A2 A/B (the A2 test pairs A2.12-A2.15 on `6a22d505` without the A2 source pairs A2.1-A2.11): V13 (`createdAudios[1].played` true right after the media `error`), V14 (`f.posted` contains `Next.` at 65 s), V15 (`end:Two.` missing after the stop), V16 (`end:One.` missing at 45 s), V17 and V18 (one BF-930 warning at 20 s) fail on assertions. The rewritten V9 passes on `6a22d505` and fails on the base `32997b18` (raw 6400 ms starts at once): the whole-repair reversion the round-2 reviewer ran. V18 passes on the base (preservation). Each A2 SEARCH counts once at its turn on `6a22d505`.
- (A3) The A1 and A2 A/B bullets above are history: their D8 tests are removed. The A3 A/B and SEARCH counts are in section 18.6.

### 8.2 Focused checks on the candidate
```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf930_speech_defers_idle_dream.py tests/test_dreaming.py tests/test_bf1002_full_dream_complete_event.py tests/test_bf918_tts_latency.py tests/test_bf930_voice_path_timing.py tests/test_ad738_piper_tts.py tests/test_ad738e_1_per_emotion_prosody.py tests/test_bf291_piper_voice_catalog.py tests/test_ad721b1_rhubarb_backend.py tests/test_ad721e_animation_manifest.py tests/test_ad1071_tts_pipelining.py tests/test_bf918_tts_retention.py tests/test_bf918_attachment_io.py -n 0 -q
rg -l -g 'test_*.py' -e 'rglob\("\*\.py"\)' -e 'os\.walk\(' -e 'cognitive\.dreaming' -e 'DreamScheduler' tests
d:/ProbOS/.venv/Scripts/pytest.exe <each file the rg command lists> -n 8 -q
cd ui; npx vitest run src/audio src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx src/__tests__/CrewVRM.mouthClock.bf931.test.tsx
cd ui; npm run build
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label bf-930-speech
```
The broad gate does not run vitest; the vitest line and `npm run build` (tsc) are the UI evidence. Retriage a parallel failure at `-n 0`.

### 8.3 Mutation rows (one at a time, file restored byte for byte; each locator is a whole stripped line of the candidate and occurs once)

| ID | File: line (stripped) | Becomes | Killed by |
|---|---|---|---|
| U1 | voice.ts: `const TTS_PREFETCH_LOOKAHEAD = 3;` | `= 1;` | V4, P1, P2, P14, pipelining |
| U2 | voiceChunking.ts: `for (let k = 1; k <= lookahead && k < items.length && !startWhen(ready); k += 1) {` | `for (let k = 1; false; k += 1) {` | V1, V5, Q7, Q8 |
| U3 | voiceChunking.ts: `if (!shouldContinue()) { stopped = true; break; }` | (line deleted) | V5, Q8 |
| U4 | voice.ts: `held += prepared !== null && prepared.playMs > 0 ? prepared.playMs : TTS_START_BUFFER_MS;` (A1 locator) | `held += prepared !== null ? prepared.playMs : TTS_START_BUFFER_MS;` | V3 |
| U5 | the same line | `held += prepared !== null && prepared.playMs > 0 ? prepared.playMs : 0;` | V3, V6 |
| U6 | voice.ts: `? data.duration_ms / _playbackRate(profile?.rate)` (A1 locator) | `? 0` | V1 |
| U7 | voice.ts: `_startBufferFilled,` | (line deleted) | V1, V5 |
| D1 | avatars.py: `dream_scheduler.record_speech_activity()` | `pass` | spoken-reply chain test |
| D2 | avatars.py: same line | `dream_scheduler.record_activity()` | route cap test |
| D3 | dreaming.py: `if at - self._speech_since >= SPEECH_DREAM_DEFER_CAP_SECONDS:` | `if False:` | cap unit test, first-reply test, route cap test |
| D4 | dreaming.py: `if self._speech_since is None or self._last_dream_time > self._speech_since:` | `if self._speech_since is None:` | new-stretch test |
| D5 | dreaming.py: `logger.info("BF-930: idle full dream starting idle_s=%.0f", idle_time)` | (line deleted) | control test |
| R1 | voice.ts: `? data.duration_ms / _playbackRate(profile?.rate)` | `? data.duration_ms` | V7, V8, V9 (A2) |
| R2 | voice.ts: `return Math.max(0.25, Math.min(4.0, rate ?? 0.95));` | `return rate ?? 0.95;` | V9 |
| B1-B5, C1-C11 | **Retired by A3** (their lines and killing tests went with D8; the rows below are the record) | - | - |
| B1 | (A2 locator) voice.ts: `await _speakBrowserFallback(text, profile, agent_id, utterance_id, last, browserWaitMs);` | `_speakBrowserFallback(text, profile, agent_id, utterance_id, last, browserWaitMs);` | P19, V11, V12, pipelining honest-degrade |
| B2 | (A2 locator) voice.ts: `if (browserDone !== null) await browserDone;` | (line deleted) | V10, V13 |
| B3 | (A2 locator) voice.ts: `}, maxWaitMs);` | `}, maxWaitMs * 1000);` | V12, V14 |
| B4 | retired by A2 (`_awaitBrowserSentence` is gone; C8 covers the clear) | - | - |
| B5 | voice.ts: `_resolveSpoken();` | (line deleted) | P19, V10, V11, V13, pipelining honest-degrade |
| C1 | (A2) voice.ts: `_endBrowserSentenceWait(); // BF-930 A2: a stop` | (line deleted) | V15 |
| C2 | (A2) voice.ts: `_endBrowserSentenceWait(); // BF-930 A2: a newer dispatch` | (line deleted) | V16 |
| C3 | (A2) voice.ts: `_endBrowserSentenceWait(); // BF-930 A2: a browser sentence a test left waiting, with its bound` | (line deleted) | V17 |
| C4 | (A2) voice.ts: `if (mediaError) await playSettled;` | (line deleted) | V13 |
| C5 | (A2) voice.ts: `audio.addEventListener('error', () => { mediaError = true; _finish(true); });` | `audio.addEventListener('error', () => _finish(true));` | V13 |
| C6 | (A2) voice.ts: `playSettled = audio.play().then(undefined, () => {` | `audio.play().then(undefined, () => {` | V13 |
| C7 | (A2) voice.ts: `_fireBrowserEnd();` | `_resolveSpoken();` | V14 |
| C8 | (A2) voice.ts: `if (bound !== undefined) clearTimeout(bound);` | (line deleted) | V15, V16, V17 |
| C9 | (A2) voice.ts: `_settleBrowserSentence = _fireBrowserEnd;` | (line deleted) | V15, V16, V17 |
| C10 | (A2) voice.ts: `const browserWaitMs = last === undefined ? undefined : BROWSER_SENTENCE_MAX_WAIT_MS;` | `const browserWaitMs = BROWSER_SENTENCE_MAX_WAIT_MS;` | V18 |
| C11 | (A2) voice.ts: `if (maxWaitMs !== undefined) {` | `if (false) {` | V12, V14, V15 |

Equivalent, not a row (A2): `return maxWaitMs === undefined ? Promise.resolve() : spoken;` to `return spoken;` makes only the single-call path's IIFE (`voice.ts`:603-652) finish later; nothing consumes its completion.

(A3) The live rows are U1-U7, D1-D5, R1 and R2, with the locators above unchanged on the A3 head (section 18.7); A3 adds no row (it adds no code). L1-L8 (the probe) went with S3. (A2, history) Run R1, R2, B1-B3, B5 and C1-C11 on the A2 head; the other rows stand unless their files' code lines differ from `6a22d505` (A2 changes only comments in the region of U1). The orchestrator's campaign of record for U1-U7 and D1-D5 ran on the pre-drop candidate; rerun U4, U5 and U6 (their locators moved) and the new R and B rows on the A1 head. D1-D5 stand unless `dreaming.py` or `avatars.py` code lines differ (A1 changes only a docstring and a comment there).

### 8.4 The gate
`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-930-speech --receipt logs/gates/bf-930-speech.receipt.json` once on the committed head, after merging the base. The gate lock is shared with the main orchestrator: queue behind its gate, never run two at once.

## 9. Diff Reviewer: properties to verify

(A3: properties 6, 12 and the browser-wait part of 13 are withdrawn; the one review a split allows uses section 18.8.) The change claims that a spoken reply's later sentences are synthesized up to three ahead and a first sentence that plays for less than 3 s waits for the next, that a sentence the browser speaks in place of a server one behaves as on the base, and that a spoken request keeps an idle full dream from starting for at most two hours of continuous speech. Consumers that must accept it: the HXI voice path (`speakResponse` through `runPrefetchQueue`), the dream monitor loop, and the operator reading `probos.log` and the devtools console.
1. With the default `startWhen`, `runPrefetchQueue` behaves byte-for-byte as before (Q1-Q6 unchanged); with `startWhen`, the first item starts after at most `lookahead` more preparations, and a stop during the wait plays nothing and discards each prepared item exactly once.
2. A sentence whose duration is unknown, or whose preparation failed, never delays the first audio.
3. `voice.ts`:548-570 (the backend gate) and `avatars.py`:250-262 (`voice_name`) are byte-identical to the base.
4. `record_speech_activity` cannot write `_last_activity_time` once its stretch is at or past the cap, so speech alone cannot keep the monitor's full-dream predicate false; a full dream completed after the stretch began starts a new stretch; `record_activity` is unchanged.
5. The route records activity once per accepted request, after validation and before synthesis, and a runtime without a scheduler is unaffected.
6. (Withdrawn by A3; replaced by 18.8 P1.) (A1, A2) In the AD-1071 queue, a sentence the browser speaks in place of a server one (failed preparation, refused `play()`, a media `error` then the `play()` rejection, or a throw in the play half) resolves its `play` only when that utterance's wait ends. The wait ends exactly once, on the first of `onend`, `onerror`, `stopSpeaking`, a newer `_playNow`, `_resetTtsStatusForTests`, or `BROWSER_SENTENCE_MAX_WAIT_MS` (20 s, one `console.warn`). Each exit fires the one terminal 'end' (`_fireBrowserEnd`), clears the timer and resolves; a later engine callback is a no-op. The bound's 'end' re-arms the arbiter's GUARD 2. After a stop or a newer dispatch the 'end' is final and the queue plays nothing more. On the single-call path no wait, timer or settler exists (as on the base).
7. (A1) The start buffer counts each prepared sentence's server duration divided by `_playbackRate(profile?.rate)`, the helper the play half uses for `audio.playbackRate`; an unknown duration or a failed prepare still counts as a full 3000 ms. The calls of `_speakBrowserFallback` in `_playNow` (`voice.ts`:595, :599, :611 at `6a22d505`) are byte-identical.
8. Each changed UI test keeps every assertion it had, changed only where lookahead 3 (M1) changes the value, with the reason inline; nothing that existed on the base is deleted or skipped (A3 removes only V10-V18, which A1 and A2 added to pin D8).
9. No file of BF-932 changes; ASCII and LF in the new text; no file outside the scope line changes; `config/system.yaml` is untouched; no `loop_lag` or `__main__.py` change is on the branch.
10. Each absolute word of the new text (each, every, no, only, never, none), including A1's code comments, tracker text and issue text, holds against sections 1 and 7 and the Absence Verified list.
11. (A1) No claim says a reply never pauses: the PROGRESS, DECISIONS, issue and `voice.ts` text bound the coverage by the audio held, and the dream text names both monitor conditions.
12. (Withdrawn by A3: no browser-sentence timer exists.)
13. (A2, corrected by A3) The claims hold: a stop discards up to four unplayed preparations while the first sentence waits for the start buffer and up to three unplayed ones ahead while a sentence plays (no claim about total synthesis spend); no text states a general ~15 s Chromium cut-off; the route records each **accepted** request.

## 10. Verified Against Codebase (2026-11-27, tree `32997b18`)

- `voiceChunking.ts`: doc :73-89, `runPrefetchQueue` :90-130 (`ensure` :99-105, the loop :109-122, `ensure(i+1..)` :115, `finally` discard :123-128).
- `voice.ts`: `SPEECH_JOIN_TIMEOUT_MS` :25; `TTS_PREFETCH_LOOKAHEAD` :258-261; backend gate :555, :567; pipelined path :579-603 (call :588-595); `PreparedSpeech` :618-622; `_prepareServerSpeech` :648-701 (return object :692-696); `_playPreparedSpeech` :725; `_discardPreparedSpeech` :819.
- `avatars.py`: `_synthesize_tts_impl` :220; `voice_name` :250-262; `defer_visemes` :268; `select_backend` import :270; `voice_synthesis` getattr :271; store write :301; route line :326-332; response `duration_ms` :340.
- `dreaming.py`: `import time` :12; `logger` :62; `_full_dream_complete_payload` :3129; `class DreamScheduler` :3146; `__init__` :3149-3174 (`_last_activity_time` :3161, `_last_dream_time` :3162); `record_activity` :3184-3186; `start` :3188-3194 (resets the clock :3193); `stop` :3196-3205; `force_dream` :3248; `_monitor_loop` :3280 (sleep :3284, micro :3292, scan :3319-3330, full :3333-3369, `dream_cycle` :3349, `_last_dream_time` :3351, cancel :3370-3371).
- `runtime.py`: `dream_scheduler` declared :1162, set :3286; `record_activity` calls :5837, :6230.
- `__main__.py`: `_serve` :732; heartbeat :918-938 (task :938); `try` :940; `finally` :958 (heartbeat cancel :959-960); `runtime.stop(), timeout=10` :1007; `os._exit(0)` :1027.
- `filesystem_store.py`: write-slow line :384-385 (`behind=`, `index_entries=`); find-slow :406. `resident.py`:450 piper-slow line.
- Tests: `voice.prefetch.bf918.test.tsx` `_flush` :91-93, `Plan` :95-105, `_makeFetch` :107-153 (`duration_ms: 0` :133), P1 :167-189, P2 :191-219, P14 :547-578, P20 :714-729 (end of file :730); `voice.pipelining.test.tsx` `_flush` :74-77, :143-152, :207-209; `voiceChunking.test.ts` `harness` :93-108, Q6 :196-203 (end of file :204); `test_bf918_tts_latency.py` `_WAV` :42, `_StubBackend` :100-104, `voice_client` :538-557, `_stub_rhubarb` :560-569; `test_ad1341_s1_reset_and_erase.py` vessel script :102-158, env :322-325.
- Live: `probos.log.1`:64421 (23:40:49), :64422 (23:41:07), :64423 (route line, `store_ms=17618 total_ms=17782 audio_ms=3949`). `D:\ProbOS\config\system.yaml`:221-222 (300.0, 600.0).
- (A1, tree `08a88fd0`) `voice.ts`: `SPEECH_JOIN_TIMEOUT_MS = 45000` :25; `VoiceProfile.rate` (0.1-10.0) :34; listener `console.warn('[voice] ...')` :100; `speakResponse(text, profile?, agent_id?, ...)` :370-377; lookahead comment :258-262; `_startBufferFilled` :269-278; fallback calls :569, :573, :585; queue call :605-613 (`_prepareServerSpeech(sentence, profile, emotion)` :607); `PreparedSpeech` :636-642; `_synthesizeAndPlay` :652-663 (awaited at :625); `_prepareServerSpeech(text, profile, emotion)` :668-724 (`durationMs` :716-718); `_playPreparedSpeech` :748-839 (null path :756-760, `playbackRate` :769, reject path :823-833, catch :835-838); `_resolveEffectiveProfile` :852-878 (modulated rate :864-872); `_speakBrowserFallback` :881-944 (no-engine return :914, `_fireBrowserEnd` :934-941, `speak` :943); `stopSpeaking` :960 (`cancel()` :966-968). `voiceChunking.ts`: play then `played += 1` :134-139, loop top re-check :117, `finally` discard :141-146. `dreaming.py`: `record_speech_activity` docstring :3196-3204; monitor conditions :3358-3364. `avatars.py`: comment :270-272. Tests: `voice.prefetch.bf918.test.tsx` `vi` import :5, `FakeUtterance.onend/onerror` :17-18, `playMode` :30, `speechSynthesis.cancel: vi.fn()` :81, P16 fake timers :619, P19 :695-720, V6 :837-844 (end of file :845); `voice.pipelining.test.tsx` `FakeAudio.played` :32, honest-degrade :177-219. `PROGRESS.md`:3; `DECISIONS.md`:13-20. BF-932 contract (`D:\ProbOS-worktrees\b932\prompts\bf-932-reply-never-waits.md`): blocked line :811, resumed line :820, innermost first :692, `suppressed=N` :665, selector frames mean a paused process :1771, :1792.

- (A2, tree `6a22d505`) `voice.ts`: `SPEECH_JOIN_TIMEOUT_MS` export :25; `_resetTtsStatusForTests` :229-238 (`_activeUtteranceId = null` :234, `_endSentenceQueueWait = null` :237); lookahead comment :258-263; `BROWSER_SENTENCE_MAX_WAIT_MS` comment and const :288-292; `_awaitBrowserSentence` :294-304; `_endSentenceQueueWait` :316; `_awaitEntry` :480-529 (non-final 'end' re-arms GUARD 2 :514-516, GUARD 2 :527); `_playNow` :561 (`speechSynthesis.cancel()` :574, `_activeUtteranceId = utterance_id` :586, `_sentenceEndedAt = null` :589, unbounded fallbacks :595, :599, :611, queue call :631-639 with `index === last` :634); `_synthesizeAndPlay` :680-691 (`_playPreparedSpeech` without `last` :689); `_playPreparedSpeech` :776-873 (null path :784-790, `browserDone` :794, `error` listener :823, `pause` :831, `audio.play().then` :856, reject fallback :864, catch :868-871, wait :872); `_speakBrowserFallback` :915-984 (signature :920-921, `_fireBrowserEnd` :973-978, `speak` :982, `return spoken` :983); `stopSpeaking` :1000-1025 (`cancel()` :1007). Tests: `voice.prefetch.bf918.test.tsx` `FakeAudio` :32-69 (`_rejectPlay` :40, `pause` :41-46, `play` hold :54, `load` :57), `_flush` :91-94, `_voice` :161-165, `afterEach` :168, P11 :446, P13 :500-537 (only `'hold'` user, :516), V6 :840-847, V9 :873-881, V12 :924-946 (end of file :947). `voiceChunking.ts` start hold :123-133. `speechQueueStore.ts` `resetSpeechArbiterForTests` :83-94 (global `beforeEach`, `ui/src/test/setup.ts`:26-30). `PROGRESS.md`:3; `DECISIONS.md`:20 (D5). Base `32997b18`: `voiceChunking.ts`:111-117 (`ensure(i)`, `await pending[i]`, `ensure(k)` for `k <= i + lookahead`, `await play`); `voice.ts`:261 (`TTS_PREFETCH_LOOKAHEAD = 1`), :733-737 (null path: `_speakBrowserFallback` then `return`), :808 and :814 (unawaited fallbacks).

- (A3, tree `1d9d5c48`): see section 18.10.

### Absence Verified (2026-11-27)

- CLAIM: only `process_natural_language` and `decompose_only` reset the dream idle clock. RUN: Grep `record_activity|_last_activity_time` over `src` and `tests`. FOUND in `src`: `runtime.py`:5837, :6230 (dream scheduler), :4522, :4744 (emergent detector, a different clock); `dreaming.py`:3161, :3184-3193, :3333. HOLDS.
- CLAIM: no loop-lag monitor exists. RUN: Grep `-i "loop_lag|loop lag|event.loop.(lag|block|stall)|slow_callback_duration|set_debug\(|_current_frames"` over `src`. FOUND: `novelty_gate.py`:65 (a docstring). HOLDS at `32997b18`; A1: on `08a88fd0` Grep `loop_lag|LoopLagProbe` over `src` finds nothing (S3 is off the branch); BF-932 D2 adds the sampler.
- (A1) CLAIM: the result of `_speakBrowserFallback` is used nowhere today. RUN: Grep `_speakBrowserFallback` over `ui/src/audio/voice.ts`. FOUND: definition :881 and statement calls :569, :573, :585, :758, :831, :837. HOLDS.
- (A1) CLAIM: no UI test asserts `playbackRate`. RUN: Grep `playbackRate` over `ui/src/**/__tests__/**`. FOUND: field declarations only (`voice.balancedEnd`:48, `voice.perEmotion`:22, `voice.pipelining`:29, `voice.prefetch.bf918`:35, `voice.serverTts`:26, `CrewVRM.mouthClock.bf931`:68, `ProfileChatTab.bf918`:94). HOLDS.
- (A1) CLAIM: nothing outside `voice.ts` reads `PreparedSpeech.durationMs`. RUN: Grep `durationMs` over `ui/src/audio`. FOUND: `voice.ts`:275, :641, :716; the rest are `lipSyncTrack.ts`'s own segment type and its tests. HOLDS.
- (A1) CLAIM: the UI lint has no floating-promise rule a discarded `Promise<void>` would trip. RUN: Grep `no-floating-promises|no-misused-promises` over `ui` (excluding `node_modules`). FOUND: nothing. HOLDS.
- (A1) CLAIM: no other test of the pipelined path fails a TTS answer or refuses `play()`. RUN: Grep `failTts|playMode = 'blocked'|ok: false` over `ui/src/audio/__tests__` and `ProfileChatTab.bf918.test.tsx`. FOUND: `voice.prefetch.bf918` :447 (P11, single call), :507 (P13, single call), :696 (P19), :838 (V6); `voice.pipelining`:192 (honest-degrade); `ProfileChatTab.bf918`:310 (a thread fetch, not TTS). HOLDS.
- (A2) CLAIM: only `_playNow` and `stopSpeaking` cancel the browser engine. RUN: Grep `speechSynthesis\.cancel\(` over `ui/src`. FOUND: `voice.ts`:574, :1007; comments in `meetingVoice.ts`:72, `ProfileChatTab.bf767.test.tsx`:4, `ProfileChatTab.bf764.test.tsx`:425. HOLDS.
- (A2) CLAIM: only `voice.prefetch.bf918`'s `'hold'` mode makes a fake `play()` that stays pending, and no UI test emits a media `error`. RUN: Grep `play\(\)\s*[:{]|playMode|emit\('error'\)|_dispatch\('error'\)` and `^\s*(async\s+)?play\b|play = |play:` over `ui/src/**/__tests__/**`. FOUND: every other audio fake's `play` resolves (`voice.pipelining`:35, `voice.perEmotion`:26, `voice.balancedEnd`:54, `voice.serverTts`:31, `CrewVRM.mouthClock.bf931`:73, `ProfileChatTab.bf918`:102); `'hold'` is used only by P13 (:516); no `emit('error')`. HOLDS: `if (mediaError) await playSettled` cannot hang an existing test.
- (A2) CLAIM: `_playPreparedSpeech` gets `last` only from the queue. RUN: Grep `_playPreparedSpeech\(` over `ui/src/audio/voice.ts`. FOUND: definition :776, queue :634 (`index === last`), single call :689 (no `last`). HOLDS.
- CLAIM: pipelined UI tests exist only in two files. RUN: Grep `sentence_pipelining_enabled: true|pipelining: true|_makeFetch\(true` over `ui/src` (count); Grep `sentence_pipelining_enabled` over the three other files that mention it. FOUND: `voice.prefetch.bf918` 12, `voice.pipelining` 4; `CrewVRM.mouthClock.bf931`:92 and `ProfileChatTab.bf918`:176 answer `false`; `voice.balancedEnd`:110 and `ProfileChatTab.bf918`:544 pass a variable whose multi-sentence uses are pipelining-off (`voice.balancedEnd`:284) or two-sentence replies (`ProfileChatTab.bf918`:536). HOLDS.
- CLAIM: no test reads the lookahead constant or scans `voice.ts`/`voiceChunking.ts` as text. RUN: Grep `(voice|voiceChunking)(\.ts)?\?raw|TTS_PREFETCH_LOOKAHEAD|TTS_START_BUFFER` over `ui`. FOUND: `voice.ts`:261, :593 only. HOLDS.
- CLAIM: every UI TTS answer of a pipelined test has `duration_ms` 0 or none. RUN: Grep `duration_ms` over `ui/src/**/__tests__/**`. FOUND: 0 in the pipelined files; `voice.serverTts`:190 (1000) and :222 (100) are on the single-call path (no `sentence_pipelining_enabled` in that file). HOLDS.
- CLAIM: `PreparedSpeech` is built in one place. RUN: Grep `deferredVisemes:|PreparedSpeech` over `ui/src`. FOUND: the object at `voice.ts`:692-696 only. HOLDS.
- CLAIM: no test scans `avatars.py` as text. RUN: Grep `avatars\.py|getsource\(.*avatars` over `tests`. FOUND: a comment, `test_bf918_attachment_io.py`:134. HOLDS.
- CLAIM: the `_serve` source scans do not pin the edited lines. RUN: Grep `_heartbeat_loop|serve-heartbeat|__main__\._serve|main_mod\._serve|_serve\(` over `tests`, read `test_ad708e_mdns_discovery.py`:154-161 and `test_bf207_shutdown_episodic_integrity.py`:306-314. FOUND: they assert `build_advertiser(`, `.stop()`, `runtime.stop(), timeout=10`, `adapter.stop(), timeout=5`. HOLDS.
- CLAIM: no thread-leak check counts daemon threads. RUN: Grep `threading\.(enumerate|Thread)|daemon` over `tests/fixtures/runtime_lifecycle.py`. FOUND: `nondaemon_threads_since` :144-154 counts non-daemon threads only. HOLDS.

## 11. What this does NOT change

- The attachment store, its lock and index, the GET route, the lipsync route; write-behind (D1's trigger).
- The backend gate (`voice.ts`:555, :567) and `voice_name` resolution (AD-738g's).
- Dreams started outside the idle monitor: the Counselor's forced dream (`counselor.py`:2738), `/dream now` (`commands_memory.py`:93), the surgeon agent (`surgeon.py`:82), the dreaming organ, shutdown consolidation. A dream already running when an interview starts runs to its end.
- What a typed DM conversation does to the idle clock (it still does not reset it; considered, deferred).
- Dream step 7g's pairwise Jaccard (`dreaming.py`:1079-1088): BF-932's to change; its sampler's stacks decide.
- Any config field or default; `config/system.yaml`.
- (A1) `__main__._serve` and any loop monitor (BF-932's). The single-call path's code (`_synthesizeAndPlay`) and the `speakResponse` fallback calls. The arbiter, `SPEECH_JOIN_TIMEOUT_MS` and `runPrefetchQueue`.
- (A3) The browser fallback, everywhere: `_speakBrowserFallback`, `_playPreparedSpeech`'s fallback paths, `stopSpeaking`, `_playNow` (apart from the S1 `_startBufferFilled` argument) and `_resetTtsStatusForTests` are the base's. The overlap of a browser-spoken sentence (BF-918's R3) is a known pre-existing limit, redesigned in the follow-up (section 18.11).
- (A2) The single-call path's browser fallback: no wait, timer or settler (A1's bounded wait there is withdrawn). The arbiter's code (`_awaitEntry`), `flushSpeechQueue`, `speechQueueStore.ts` and `ui/src/test/setup.ts`. The server-path 'end' an `error` fires (BF-655), and the last-sentence ordering in section 17.6.

## 12. Issue text (#1668, on merge) and the Captain's live check

Wave comment:

```text
BF-930 shipped in PR #<PR> (contract prompts/bf-930-spoken-reply-pause-fix.md). Refs #1668; the issue stays open for the live re-measurement.
- Client buffer: the sentence queue synthesizes up to three sentences ahead (was one) and holds a first sentence that plays for less than 3 s (counted at the voice's rate) until the next is ready. A stall of one sentence no longer than the audio held (about 10-14 s) is not heard; a longer one, like the 17.8 s of 2026-10-30, still pauses, for less time. Unknown durations and failed syntheses start as before. Known limit, unchanged from before (BF-918's registered R3): a sentence the browser speaks in place of a failed one can be overlapped by the next server sentence; a bounded wait for it was built and withdrawn before merge (a late browser start locked push-to-talk after the reply ended), and its redesign is #1869.
- Dream guard: each accepted TTS request counts as activity for the idle full dream, so while replies come less than idle_threshold_seconds apart an idle dream does not start; one stretch of speech holds it off for at most 2 h, after which the dream starts once the monitor's idle and interval conditions hold. The idle dream now logs "BF-930: idle full dream starting/finished".
- Loop blocks: the loop-lag probe was dropped from this change; BF-932's loop-stall sampler (#1670) logs "BF-932: event loop blocked ... loop thread at: ..." instead.
- Not built: write-behind of spoken audio. The 2026-10-30 stalls silenced every logger (a blocked loop). It is drafted only if, on a vessel running BF-932's sampler, a live window shows a store stall with behind>0 or lock_wait_ms>=500 and no "BF-932: event loop blocked" line within 5 s.
- Corrected premise: the attachments index is about 1.2-1.4 K entries (217 KB), not 12 K; no boot-time reaper hazard.
```

The Captain's actions after the merge: update `D:\ProbOS` to main; `cd ui; npm run build`; restart the vessel; hard-reload the HXI (Ctrl+Shift+R). Before recording, let the vessel run a few minutes and check line 1.

Live check (PowerShell; `$L = "$env:LOCALAPPDATA\ProbOS\data\logs\probos.log"`):
1. `Select-String $L -Pattern 'BF-930: idle full dream (starting|finished)' | Select -Last 4` -- the last line should be `finished` (or none) before you start; `starting` with no `finished` after it means a dream is running: wait for `finished`.
2. `Select-String $L -Pattern 'BF-918: tts route' | Select -Last 30` -- `total_ms` per sentence.
3. `Select-String $L -Pattern 'BF-932: event loop (blocked|resumed)' | Select -Last 20` -- BF-932's sampler. The frames after `loop thread at:` name the blocker, innermost first; a first frame in `selectors.py` or `windows_events.py` means the process was paused, not blocked by code. The WARNING's ms is the stall's age when it was detected; the `resumed` line carries the whole gap. A stall the sampler suppressed writes no line: check the `suppressed=N` on the next WARNING. Paste them to #1668. If BF-930 reaches the Captain before BF-932 is merged, this line prints nothing; that is not a failure.
4. `Select-String $L -Pattern 'BF-930: (piper request slow|attachment write slow)' | Select -Last 10` -- where a slow sentence's time went (`resume_lag_ms`, `behind=`, `index_entries=`).
5. In the HXI devtools console: `performance.getEntriesByName('bf918:sentence-gap').map(m=>Math.round(m.duration))`.

**Pass:** over at least 20 spoken sentences with the camera on, no pause is heard in the middle of a reply where no route line in that reply has `total_ms` above about 10 s, every such sentence gap is under about 300 ms, and no `idle full dream starting` line falls between the interview's first and last route lines. A pause behind a route line with `total_ms` above the audio held is the stated limit, not a failure; post it with its loop-block lines. Loop-block lines are evidence for the next slice, not a failure. **Operator note:** S2 covers only the idle dream; a dream already running, or one the Counselor forces, is not held off. For more margin the Captain may raise `dreaming.idle_threshold_seconds` in his own `config/system.yaml` (today 300.0) to, say, 1800.0 for the session; it is his file and no build step touches it.

PR title: `Spoken replies hold three sentences ahead and hold off the idle dream`.

## 13. Prior art and blind spots

- Internal: BF-918 (#1626; the queue, deferred visemes, the route line), BF-930 slice 1 (the timing lines), AD-1071 (sentence pipelining), AD-731 (audio by sha only), BF-1002 (the full-dream emit sites this file now sits beside), the consult of 2026-11-27 (its slice 1 kept, slice 2 deferred, its boot hazard withdrawn).
- External (date used 2026-11-27; one search; `docs/research/reference-projects.md` not examined: no row is about loop monitoring or audio buffering):
  - Watchdog thread plus heartbeat plus `sys._current_frames` ([thehesiod gist](https://gist.github.com/thehesiod/0d2beed27c800e4f7286be6c3cd17a09), [imayhaveborkedit gist](https://gist.github.com/imayhaveborkedit/97ccc3fd654873b7b0c1540c94b5a069), [Hassette blocking detection](https://hassette.readthedocs.io/en/stable/pages/core-concepts/blocking-io-detection/)): adopted; it names the line, where a latency probe alone ([Mergify](https://mergify.com/blog/detecting-blocking-tasks-in-asyncio-by-measuring-event-loop-latency)) only reports the stall.
  - [pyleak](https://tessl.io/registry/tessl/pypi-pyleak/files/docs/blocking-detection.md), [aiodebug](https://pypi.python.org/project/aiodebug/), [LoopSentry](https://github.com/amzker/loopsentry), [blocksnoop](https://pypi.org/project/blocksnoop/0.1.0/): rejected as dependencies for about 100 lines of stdlib code; blocksnoop's eBPF does not run on the Captain's Windows host.
  - `faulthandler.dump_traceback_later`: rejected; it dumps every thread to a stream with no rate limit or lag value.
  - The client buffer is a playout (jitter) buffer of whole sentences; no search needed.
  - (A1) The loop-probe references above informed S3, which A1 dropped; they now bear on BF-932's sampler, not on this change.
  - (A1, one search, 2026-11-27) Reports that Chromium cuts off an utterance at about 15 s and fires neither `end` nor `error` ([PhET utterance-queue #60](https://github.com/phetsims/utterance-queue/issues/60), [Stack Overflow 21947730](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/21947730/chrome-speech-synthesis-with-longer-texts)); the common advice is sentence-sized utterances plus a timeout fallback, which D8 adopted (withdrawn by A3: a timeout that emulates the end collides with the engine's late events; section 18.1). (A2) The cut-off is not general: review round 2 measured the local Microsoft David voice in Chromium still speaking at 25,156 ms with only `start` reported; the text now says a browser or voice can fail to report an end. The pause/resume keep-alive: rejected (it reportedly breaks on Android Chrome, same PhET thread).
  - (A2, no search) The media-failure order (the `error` event, then the pending `play()` rejected with `NotSupportedError`) is the reviewer's Chromium measurement (round 2, finding 1); the HTML standard's "dedicated media source failure steps" describe the same order (not fetched for this amendment).
- Blind spots:
  - Barge-in now discards up to three unplayed preparations ahead instead of one (four while the first sentence waits for the start buffer), each with its stored WAV and any viseme request it started (Kokoro costs more per sentence). (A3 wording: a count of unplayed preparations, not of total synthesis spend.)
  - (A3) The A2 and A1 bullets on the 20 s bound and the collected utterance below are history: D8 is withdrawn. Lookahead 3 can lengthen the base's R3 overlap, most when several sentences in a row fail (18.9 R-b, corrected in 18.14; no numerical cap).
  - (A2) At the bound the browser sentence's 'end' fires while a voice that lost its end report may still be speaking: the PTT gate re-arms and the next server sentence overlaps it, and on a reply's last sentence the arbiter may dispatch the next reply, whose `cancel()` cuts it. Bounded to sentences that speak past 20 s or lose their end; logged.
  - The orchestrator's "boot dream" was not located in `src`; if one exists it is a dream outside the idle monitor and is not held off (section 11).
  - (A1) A browser-spoken sentence longer than 20 s (a very long sentence, or a rate well below 0.95) is overlapped by the next server sentence after the bound, with one warning: the base's behaviour, now bounded and visible.
  - (A1) A `SpeechSynthesisUtterance` that is garbage-collected before it ends can lose its `onend` (reported for Chrome); the 20 s bound covers it. Holding a module reference to the speaking utterance: considered, deferred.
  - (A1) The buffer uses the profile's rate; emotional modulation at play time (with an `agent_id`) can change it (D9). The buffer can then be off by the modulation factor; the first sentence still starts within `lookahead` preparations.

## 14. Acceptance criteria

1. (A3) The A/B of 18.6 holds; U1-U7, D1-D5, R1 and R2 are killed as 8.3 and 18.7 say; B1-B5 and C1-C11 are retired.
2. The focused checks of 8.2 pass, the `rg` list and the vitest and build lines included; the pre-existing tests in those files pass unchanged apart from the five changed in place (A3); the absence checks of 18.5 find nothing.
3. `git diff --check` is clean, the new text is ASCII, and no file outside the scope line changes; no BF-932 file and no `config/system.yaml` change.
4. The Diff Reviewer approves against section 9.
5. One receipted broad gate on the committed head is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1 (2026-11-27, after review round 1 and the BF-932 overlap decision) -- D8 parts withdrawn by A3

> **Audit trail, not instructions (A3, section 18).** A1-c (D8, the awaited browser fallback: every A1 pair touching `_playPreparedSpeech`'s fallback paths or `_speakBrowserFallback`, and the tests V10-V12, the changed P19 and the changed honest-degrade test) is withdrawn by A3. A1-a, A1-b, A1-d (D9), A1-e and A1-f stand as built, as A2 and A3 amended them. Do not apply any pair of this section again.

### 16.1 What changes, why, and what it replaces

| # | What | Why | Replaces |
|---|---|---|---|
| A1-a | S3 (loop-lag probe) dropped; 6.9-6.11, M3, D5, D6, L1-L8, properties 6-7 (old) removed | BF-932's D2 sampler covers it (overlap consult, session `ad6d6107`); the M3 review findings are moot | sections 2, 3 (D1, D5, D6), 4, 6.9-6.11, 8.3, 9 |
| A1-b | Live check line 3 and the S4 trigger read BF-932's lines; the trigger counts only on a vessel running the sampler | without the sampler "no loop-block line within 5 s" holds for free | D1, section 12 |
| A1-c | Repair 1: the play half awaits a browser fallback (D8, bound 20 s) | review P2: Three started at 1207 ms before browser Two ended at 1409 ms (`voice.ts`:756-760 resolved at once) | 6.2 behaviour of `_playPreparedSpeech`; P19's "Three plays meanwhile" |
| A1-d | Repair 2: the start buffer counts playing time (D9) | review P2: a 4 s WAV at rate 2 ended in 2.3 s while the raw 4000 ms cleared the 3000 ms gate | P3 (`_startBufferFilled`), P5, P6 |
| A1-e | Claims: "(CPU only)" removed; coverage bounded by the audio held; the dream text names both monitor conditions; the route comment bounded | review P3 x2 and property 10 | P3's comment, the 6.6 docstring, the avatars comment, 6.12, 6.13, section 12 |
| A1-f | Trackers: PROGRESS and DECISIONS rewritten for the shipped scope, with a DECISIONS clause for the S3 drop | they still describe the probe | 6.12, 6.13 |

### 16.2 The pairs (against `08a88fd0`; CRLF working copies, LF blocks; each SEARCH occurs once at its turn)

These pairs were applied in `6a22d505` and stay as the record. A2 (section 17) supersedes: A1.1's comment (A2.1), A1.2's `BROWSER_SENTENCE_MAX_WAIT_MS` comment and `_awaitBrowserSentence` (A2.3), A1.5's null path and declarations (A2.5), A1.7 and A1.8's fallback calls and wait (A2.8), A1.9's comment (A2.9), A1.11's body (A2.10), A1.13's V9 (A2.14), A1.17 and A1.18 (A2.16, A2.17). The A1 sentence under A1.11 ("`_synthesizeAndPlay` ... now resolves after the browser's end") no longer holds: under A2 it resolves at once, as on the base.

#### `ui/src/audio/voice.ts`

**A1.1.** SEARCH:
```ts
 *  pipelining. BF-930 (#1668): three (was one), so a sentence whose synthesis or
 *  storage stalls is covered by up to three sentences of audio already held; a
 *  stopped reply can have spent up to three syntheses (CPU only). */
const TTS_PREFETCH_LOOKAHEAD = 3;
```
REPLACE:
```ts
 *  pipelining. BF-930 (#1668): three (was one), so a stall of one sentence's synthesis
 *  or storage no longer than the audio already held (up to three sentences, about
 *  10-14 s) is not heard; a longer stall still pauses. A stopped reply can have spent
 *  up to three syntheses, their stored WAVs and any viseme requests they started. */
const TTS_PREFETCH_LOOKAHEAD = 3;
```

**A1.2.** SEARCH:
```ts
/** BF-930: `startWhen` of the AD-1071 queue. A sentence of unknown duration (0 or
 *  missing) or one whose preparation failed (`null`) counts as a full buffer, so it
 *  starts exactly as before. */
function _startBufferFilled(ready: Array<PreparedSpeech | null>): boolean {
  let held = 0;
  for (const prepared of ready) {
    held += prepared !== null && prepared.durationMs > 0 ? prepared.durationMs : TTS_START_BUFFER_MS;
  }
  return held >= TTS_START_BUFFER_MS;
}
```
REPLACE:
```ts
/** BF-930: `startWhen` of the AD-1071 queue. It counts how long each ready sentence
 *  plays (`playMs`, at the profile's rate). A sentence of unknown duration (0 or
 *  missing) or one whose preparation failed (`null`) counts as a full buffer, so it
 *  starts exactly as before. */
function _startBufferFilled(ready: Array<PreparedSpeech | null>): boolean {
  let held = 0;
  for (const prepared of ready) {
    held += prepared !== null && prepared.playMs > 0 ? prepared.playMs : TTS_START_BUFFER_MS;
  }
  return held >= TTS_START_BUFFER_MS;
}

/** BF-930 A1: the <audio> playbackRate for a profile rate: 0.95 when unset, clamped to
 *  [0.25, 4.0]. The play half sets it; the start buffer divides durations by it. */
function _playbackRate(rate: number | undefined): number {
  return Math.max(0.25, Math.min(4.0, rate ?? 0.95));
}

/** BF-930 A1: the longest the play half waits for a sentence the browser speaks in place
 *  of a server one. Chromium cuts an utterance off at about 15 s with no end or error
 *  event, and onend can be lost in a backgrounded tab; 20 s is past that cut-off and
 *  past about 45 words at the default rate, and inside SPEECH_JOIN_TIMEOUT_MS (45 s). */
export const BROWSER_SENTENCE_MAX_WAIT_MS = 20000;

/** BF-930 A1: resolve when `spoken` does (the utterance's onend or onerror) or after
 *  BROWSER_SENTENCE_MAX_WAIT_MS with one warning, whichever is first. Never rejects. */
function _awaitBrowserSentence(spoken: Promise<void>): Promise<void> {
  return new Promise<void>((resolve) => {
    const bound = setTimeout(() => {
      console.warn(`[voice] BF-930: browser speech gave no end or error within ${BROWSER_SENTENCE_MAX_WAIT_MS} ms; the reply goes on`);
      resolve();
    }, BROWSER_SENTENCE_MAX_WAIT_MS);
    void spoken.then(() => { clearTimeout(bound); resolve(); });
  });
}
```

**A1.3.** SEARCH:
```ts
  /** BF-930: the server's `duration_ms`; 0 when absent or not a positive number. */
  durationMs: number;
}
```
REPLACE:
```ts
  /** BF-930 A1: how long it plays: the server's `duration_ms` divided by the profile's
   *  playback rate (`_playbackRate`); 0 when the duration is absent or not a positive
   *  number. Emotional modulation at play time can change the rate (a stated limit). */
  playMs: number;
}
```

**A1.4.** SEARCH:
```ts
      durationMs: typeof data.duration_ms === 'number' && Number.isFinite(data.duration_ms) && data.duration_ms > 0
        ? data.duration_ms
        : 0,
```
REPLACE:
```ts
      playMs: typeof data.duration_ms === 'number' && Number.isFinite(data.duration_ms) && data.duration_ms > 0
        ? data.duration_ms / _playbackRate(profile?.rate)
        : 0,
```

**A1.5.** SEARCH:
```ts
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
    return;
  }
  const { audio, visemes, deferredVisemes } = prepared;
  try {
```
REPLACE:
```ts
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    // BF-930 A1 (#1668): resolve once the browser has spoken it (bounded), so the AD-1071
    // queue does not start the next sentence over it.
    await _awaitBrowserSentence(_speakBrowserFallback(text, profile, agent_id, utterance_id, last));
    return;
  }
  const { audio, visemes, deferredVisemes } = prepared;
  // BF-930 A1: a browser fallback started below (play() refused, or a throw) is awaited
  // once the server half has settled, as the null path's is.
  let browserDone = null as Promise<void> | null;
  try {
```

**A1.6.** SEARCH:
```ts
    audio.playbackRate = Math.max(0.25, Math.min(4.0, effective.rate ?? 0.95));
```
REPLACE:
```ts
    audio.playbackRate = _playbackRate(effective.rate);
```

**A1.7.** SEARCH:
```ts
        if (_activeAudio === audio) _activeAudio = null;
        _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
        _finish(false);
```
REPLACE:
```ts
        if (_activeAudio === audio) _activeAudio = null;
        browserDone = _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
        _finish(false);
```

**A1.8.** SEARCH:
```ts
  } catch {
    _invalidateTtsStatus();
    _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
  }
}
```
REPLACE:
```ts
  } catch {
    _invalidateTtsStatus();
    browserDone = _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
  }
  if (browserDone !== null) await _awaitBrowserSentence(browserDone);
}
```

**A1.9.** SEARCH:
```ts
  utterance_id?: number,
  last?: boolean,
): void {
  if (!('speechSynthesis' in window)) {
```
REPLACE:
```ts
  utterance_id?: number,
  last?: boolean,
): Promise<void> {
  // BF-930 A1 (#1668): resolves once this utterance's terminal 'end' has fired (onend or
  // onerror; at once when there is no engine). Callers that do not wait ignore it.
  if (!('speechSynthesis' in window)) {
```

**A1.10.** SEARCH:
```ts
      ..._finalField(last, utterance_id),
    });
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
```
REPLACE:
```ts
      ..._finalField(last, utterance_id),
    });
    return Promise.resolve();
  }
  const utterance = new SpeechSynthesisUtterance(text);
```

**A1.11.** SEARCH:
```ts
  let _ended = false;
  const _fireBrowserEnd = () => {
    if (_ended) return;
    _ended = true;
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id, ..._finalField(last, utterance_id) });
  };
  utterance.onend = _fireBrowserEnd;
  utterance.onerror = _fireBrowserEnd;
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.
  speechSynthesis.speak(utterance);
}
```
REPLACE:
```ts
  let _ended = false;
  let _resolveSpoken: () => void = () => {};
  const spoken = new Promise<void>((resolve) => { _resolveSpoken = () => resolve(); });
  const _fireBrowserEnd = () => {
    if (_ended) return;
    _ended = true;
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id, ..._finalField(last, utterance_id) });
    _resolveSpoken();
  };
  utterance.onend = _fireBrowserEnd;
  utterance.onerror = _fireBrowserEnd;
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.
  speechSynthesis.speak(utterance);
  return spoken;
}
```

The single-call path needs no change: `_synthesizeAndPlay` (`voice.ts`:652-663) now resolves after the browser's end instead of at once, and only its own IIFE awaits it (:625). `_fire` catches each listener's error (:100), so `_resolveSpoken()` is reached.

#### `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx`

**A1.12** (P19, changed in place). SEARCH:
```ts
      // Two failed: the browser speaks it, and Three plays meanwhile (R3, unchanged).
      expect(spoken()).toEqual(['Two.']);
      expect(createdAudios[1].played).toBe(true);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();
      expect(f.posted).not.toContain('Next.');
```
REPLACE:
```ts
      // Two failed: the browser speaks it. BF-930 A1 (#1668, review round 1): Three now
      // waits for the browser's end; it used to play meanwhile (R3), which with lookahead 3
      // overlapped Two. The played-true assertion moves after Two's end.
      expect(spoken()).toEqual(['Two.']);
      expect(createdAudios[1].played).toBe(false);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();
      expect(createdAudios[1].played).toBe(true);
      expect(f.posted).not.toContain('Next.');
```

**A1.13** (V7-V12, new). SEARCH:
```ts
    const f = _makeFetch({ pipelining: true, failTts: [1], durations: [1500, 1500], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two.');
    await _flush();
    expect(spoken()).toEqual(['One.']);
  });
});
```
REPLACE:
```ts
    const f = _makeFetch({ pipelining: true, failTts: [1], durations: [1500, 1500], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two.');
    await _flush();
    expect(spoken()).toEqual(['One.']);
  });

  it('V7 A1: the start buffer counts playing time; at rate 2 a 4 s sentence holds 2 s and waits', async () => {
    const f = _makeFetch({ pipelining: true, durations: [4000, 4000, 4000], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two. Three.', { rate: 2 });
    await _flush();
    expect(createdAudios.length).toBe(1);
    expect(createdAudios[0].played).toBe(false); // 4000 ms / 2 = 2000 ms, under the 3 s start buffer
    f.release();
    await _flush();
    expect(createdAudios[0].played).toBe(true);
    expect(createdAudios[0].playbackRate).toBe(2);
  });

  it('V8 A1: at rate 0.5 a 2 s sentence plays for 4 s and starts at once', async () => {
    const f = _makeFetch({ pipelining: true, durations: [2000, 2000], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two.', { rate: 0.5 });
    await _flush();
    expect(createdAudios[0].played).toBe(true);
    expect(createdAudios[0].playbackRate).toBe(0.5);
  });

  it('V9 A1: the rate is clamped to 4 as at play time, so 13 s at rate 10 holds 3.25 s and starts at once', async () => {
    const f = _makeFetch({ pipelining: true, durations: [13000, 4000], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two.', { rate: 10 });
    await _flush();
    expect(createdAudios[0].played).toBe(true);
    expect(createdAudios[0].playbackRate).toBe(4);
  });

  it('V10 A1: a sentence whose play() is refused is spoken by the browser, and the next waits for its end', async () => {
    playMode = 'blocked';
    const f = _makeFetch({ pipelining: true, durations: [4000, 4000] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two.');
    await _flush();
    expect(spoken()).toEqual(['One.']); // its play() was refused: the browser speaks it
    playMode = 'resolve';
    expect(createdAudios[1].played).toBe(false);
    (speakCalls[0] as FakeUtterance).onend?.();
    await _flush();
    expect(createdAudios[1].played).toBe(true);
  });

  it('V11 A1: a stop while the browser speaks a failed sentence ends the wait, and nothing after it plays', async () => {
    const f = _makeFetch({ pipelining: true, failTts: [2], durations: [4000, 4000, 4000] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _recordAll();
    try {
      voiceMod.speakResponse('One. Two. Three.');
      await _flush();
      createdAudios[0].end();
      await _flush();
      expect(spoken()).toEqual(['Two.']);
      expect(createdAudios[1].played).toBe(false); // Three waits for Two
      const cancel = (globalThis as any).speechSynthesis.cancel;
      const cancels = cancel.mock.calls.length;
      voiceMod.stopSpeaking();
      expect(cancel.mock.calls.length).toBeGreaterThan(cancels);
      (speakCalls[0] as FakeUtterance).onerror?.(); // what cancel() makes a real engine fire
      await _flush();
      expect(createdAudios[1].played).toBe(false);
      expect(createdAudios[1].discarded).toBe(true);
      expect(r.events.filter((e) => e.startsWith('start'))).toEqual(['start:One.']);
    } finally {
      r.off();
    }
  });

  it('V12 A1: a browser sentence that never reports its end holds the next for at most BROWSER_SENTENCE_MAX_WAIT_MS, with one warning', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const f = _makeFetch({ pipelining: true, failTts: [2], durations: [4000, 4000, 4000] });
      (globalThis as any).fetch = f.fetchMock;
      const voiceMod = await _voice();
      voiceMod.speakResponse('One. Two. Three.');
      await _flush();
      createdAudios[0].end();
      await _flush();
      expect(spoken()).toEqual(['Two.']); // its onend and onerror never fire
      vi.advanceTimersByTime(voiceMod.BROWSER_SENTENCE_MAX_WAIT_MS - 1);
      await _flush();
      expect(createdAudios[1].played).toBe(false);
      vi.advanceTimersByTime(1);
      await _flush();
      expect(createdAudios[1].played).toBe(true);
      expect(warn.mock.calls.filter((c) => String(c[0]).includes('BF-930')).length).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
```

#### `ui/src/audio/__tests__/voice.pipelining.test.tsx`

**A1.14** (honest-degrade, changed in place). SEARCH:
```ts
    // Sentence[1] fell back to the browser in its turn and resolved at once,
    // so the queue already moved on to sentence[2] without a new 'ended'.
    expect(speakCalls.length).toBe(1);
    expect(posted).toEqual(['Alpha.', 'Bravo.', 'Charlie.']);
  });
```
REPLACE:
```ts
    // Sentence[1] fell back to the browser in its turn. BF-930 A1 (#1668): the queue now
    // waits for that utterance's end before sentence[2] plays; it used to resolve at once
    // and play sentence[2] over it.
    expect(speakCalls.length).toBe(1);
    expect(posted).toEqual(['Alpha.', 'Bravo.', 'Charlie.']);
    expect(createdAudios[1].played).toBe(false);
    (speakCalls[0] as { onend: (() => void) | null }).onend?.();
    await _flush();
    expect(createdAudios[1].played).toBe(true);
  });
```

#### `src/probos/cognitive/dreaming.py`

**A1.15.** SEARCH:
```python
        and this returns True. Past that age it returns False and leaves the timer alone,
        so the idle full dream starts ``idle_threshold_seconds`` later at the latest; the
        first reply after that dream begins a new stretch. ``now`` is a ``time.monotonic()``
        value (default: now).
```
REPLACE:
```python
        and this returns True. Past that age it returns False and leaves the timer alone,
        so speech no longer keeps the monitor's idle condition false; the full dream starts
        when all of the monitor's conditions hold (``idle_threshold_seconds`` since the last
        activity of any source, ``dream_interval_seconds`` since the last dream). The first
        reply after that dream begins a new stretch. ``now`` is a ``time.monotonic()``
        value (default: now).
```

#### `src/probos/routers/avatars.py`

**A1.16.** SEARCH:
```python
    # BF-930 (#1668): a spoken reply is activity for the idle full dream, so a dream does
    # not start in the middle of a spoken conversation. The scheduler bounds it
    # (SPEECH_DREAM_DEFER_CAP_SECONDS). A runtime without a scheduler skips it.
```
REPLACE:
```python
    # BF-930 (#1668): a spoken reply is activity for the idle full dream, so the idle dream
    # does not start between replies that come less than idle_threshold_seconds apart. The
    # scheduler bounds it (SPEECH_DREAM_DEFER_CAP_SECONDS). A runtime without a scheduler
    # skips it.
```

#### `PROGRESS.md`

**A1.17.** SEARCH (line 3, whole):
```markdown
**BF-930 (2026-11-27), #1668 -- a spoken reply no longer pauses mid-way when one sentence's synthesis or storage stalls.** The AD-1071 sentence queue now synthesizes up to three sentences ahead (was one) and holds a first sentence shorter than 3 s of audio until the next is ready (`ui/src/audio/voice.ts`, `voiceChunking.ts`: `runPrefetchQueue` gains `startWhen`), so a stalled sentence is covered by the audio already held; an unknown duration or a failed synthesis starts as before. The TTS route records each request on the dream scheduler (`DreamScheduler.record_speech_activity`), so an idle full dream does not start during a spoken conversation; one stretch of speech holds it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h), and the idle full dream logs `BF-930: idle full dream starting/finished`. The vessel's `_serve` runs a log-only loop-lag probe (`probos.utils.loop_lag`): a loop that does not answer a heartbeat within 1 s is logged as `BF-930: event loop blocked` with the loop thread's stack (code locations only), at most once per 30 s. Write-behind of spoken audio is not built: the 2026-10-30 stalls silenced every logger (a blocked loop), and it waits for `behind=` evidence. #1668 stays open for the Captain's live re-measurement. New `tests/test_bf930_speech_defers_idle_dream.py`, `tests/test_bf930_loop_lag_probe.py`; UI V1-V6, Q7-Q8; P1, P2, P14 and two pipelining tests updated in place for lookahead 3. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
```
REPLACE:
```markdown
**BF-930 (2026-11-27), #1668 -- a spoken reply rides out a stall of one sentence's synthesis or storage, up to the audio already held.** The AD-1071 sentence queue now synthesizes up to three sentences ahead (was one) and holds a first sentence that plays for less than 3 s until the next is ready (`ui/src/audio/voice.ts`, `voiceChunking.ts`: `runPrefetchQueue` gains `startWhen`); the buffer counts each sentence's playing time at the profile's rate. A stall no longer than the audio held (about 10-14 s) is not heard; a longer one, like the 17.8 s of 2026-10-30, still pauses, for less time. An unknown duration or a failed synthesis starts as before. A sentence the browser speaks in place of a failed one now ends before the next sentence starts; a browser that never reports that end is waited on for at most 20 s (`BROWSER_SENTENCE_MAX_WAIT_MS`). The TTS route records each request on the dream scheduler (`DreamScheduler.record_speech_activity`), so while replies come less than `idle_threshold_seconds` apart an idle full dream does not start; one stretch of speech holds it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h), after which the dream starts once the monitor's idle and interval conditions hold. The idle full dream logs `BF-930: idle full dream starting/finished`. The contract's loop-lag probe was dropped: BF-932's loop-stall sampler (#1670) logs loop blocks. Write-behind of spoken audio is not built: the 2026-10-30 stalls silenced every logger (a blocked loop), and it waits for `behind=` evidence. #1668 stays open for the Captain's live re-measurement. New `tests/test_bf930_speech_defers_idle_dream.py` (8 tests); UI V1-V12, Q7-Q8; P1, P2, P14, P19 and two pipelining tests updated in place. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
```

#### `DECISIONS.md`

**A1.18.** SEARCH:
```markdown
### BF-930 -- A spoken reply buffers three sentences, holds off the idle full dream, and a probe names what blocks the loop (2026-11-27, #1668)

- *Scope.* `ui/src/audio/voice.ts`, `ui/src/audio/voiceChunking.ts`, `cognitive/dreaming.py` (`record_speech_activity`, `SPEECH_DREAM_DEFER_CAP_SECONDS`, idle-dream start/finish lines), `routers/avatars.py`, `utils/loop_lag.py` (new), `__main__._serve`. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
- *D1.* Client buffer: lookahead 3 and a 3000 ms start buffer, module constants (a config field would cross the wire into the browser with no measured need). Unknown duration and a failed synthesis count as a full buffer.
- *D2.* Speech is activity for the idle full dream, bounded: a stretch begins at the first spoken reply after the last full dream, and past 2 h speech stops resetting the idle clock, so the dream starts `idle_threshold_seconds` later at the latest. Not `record_activity()` from the route: machine-driven speech could starve dreaming for ever.
- *D3.* The loop-lag probe is log-only, started only by the vessel's `_serve`, and its `stop()` never joins (it runs on the loop thread).
- *D4.* Write-behind of spoken audio is deferred until a live window shows a store stall with `behind=` > 0 or `lock_wait_ms` >= 500 and no loop-block report within 5 s.
```
REPLACE:
```markdown
### BF-930 -- A spoken reply buffers three sentences and holds off the idle full dream (2026-11-27, #1668)

- *Scope.* `ui/src/audio/voice.ts`, `ui/src/audio/voiceChunking.ts`, `cognitive/dreaming.py` (`record_speech_activity`, `SPEECH_DREAM_DEFER_CAP_SECONDS`, idle-dream start/finish lines), `routers/avatars.py`. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
- *D1.* Client buffer: lookahead 3 and a 3000 ms start buffer, module constants (a config field would cross the wire into the browser with no measured need). The buffer counts the time each sentence plays (server duration divided by the clamped profile rate). Unknown duration and a failed synthesis count as a full buffer. It covers a stall up to the audio held (about 10-14 s); a longer one still pauses.
- *D2.* Speech is activity for the idle full dream, bounded: a stretch begins at the first spoken reply after the last full dream, and past 2 h speech stops resetting the idle clock; the dream then starts when the monitor's conditions hold (`idle_threshold_seconds` since the last activity of any source, `dream_interval_seconds` since the last dream). Not `record_activity()` from the route: machine-driven speech could starve dreaming for ever.
- *D3.* The contract's loop-lag probe (S3) was dropped before merge: BF-932's loop-stall sampler (#1670) logs the same evidence, and one sampler is kept, not two.
- *D4.* Write-behind of spoken audio is deferred until a live window on a vessel running BF-932's sampler shows a store stall with `behind=` > 0 or `lock_wait_ms` >= 500 and no `BF-932: event loop blocked` line within 5 s.
- *D5.* A sentence the browser speaks in place of a server one is awaited before the next sentence plays, for at most 20 s (`BROWSER_SENTENCE_MAX_WAIT_MS`, past Chromium's ~15 s utterance cut-off, which fires no end event); at the bound the reply goes on and the console logs one warning.
```

### 16.3 After the pairs

1. `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` if they change.
2. `git diff --check`; `git diff --stat` shows only `voice.ts`, the two UI test files, `dreaming.py`, `avatars.py`, `PROGRESS.md`, `DECISIONS.md` and the ledger files.
3. The orchestrator commits with the A1 subject of section 4 (no `AD-`/`BF-` token, none of close, fix, resolve), body ending `Refs #1668.`, then runs 8.1 (A1 A/B), 8.2, the 8.3 rows named there, and the gate (8.4).

## 17. Amendment A2 (2026-11-27, after review round 2) -- withdrawn by A3

> **Audit trail, not instructions (A3, section 18).** All of A2's code and tests are withdrawn by A3 except V9 as A2 rewrote it (kept) and A2-f's claim corrections ("each accepted request", no general ~15 s cut-off; kept; the four/three wording is corrected again by A3). 17.1's convergence argument is superseded by the round-three brake's split decision (18.1). Do not apply any pair of this section again.

### 17.1 Is the overlap a regression? No: the base overlaps in the common case

On the base `32997b18` (lookahead 1), `runPrefetchQueue` consumes item i (`voiceChunking.ts`:112), calls `ensure(i+1)` (:115) and only then `play(i)` (:117). `ensure(i+1)` chains on `pending[i]`, which has just resolved, so sentence i+1's synthesis starts at once. When item i failed, the play half speaks it through the browser and returns at once (`voice.ts`:733-737; the refused and throw paths :808, :814 likewise). The loop then awaits `pending[i+1]` and plays it as soon as its synthesis lands. With a 0.2-1.5 s synthesis against a 3-5 s browser sentence, the server sentence starts 0.2-1.5 s into the browser one: an overlap of about the browser sentence's length minus one synthesis. The base keeps the order only when the next synthesis takes longer than the browser sentence. Round 1's "the base preserves that order" fits a stand-in whose browser sentence was shorter than one synthesis (its repair measurement had the browser sentence ending at 1409 ms); I read the code and did not run the stand-in. Lookahead 3 lengthens the overlap by at most one synthesis (the next sentence is usually ready). [Corrected by 18.14: false with consecutive failed sentences; the split's review measured 2.9 s against 1.7 s with two in a row. No cap holds.] Round 2 already classed its finding 1 "regression: no" for the same reason.

The overlap is still ordinary reach (any failed synthesis, refused `play()` or media error during a reply), and convergence fixes every ordinary-reach finding whether or not it is a regression. Removing D8 therefore does not converge: it would bring back round 1's finding and leave round 2's finding 1. A2 keeps D8 and closes every gap round 2 found in it.

### 17.2 What changes, why, and what it replaces

| # | What | Why (round 2) | Replaces |
|---|---|---|---|
| A2-a | After a media `error`, the play half waits for `play()` to settle (`mediaError`, `playSettled`), so the fallback that the rejection starts is awaited | finding 1 (P2, ordinary): Three started at 776 ms, browser Two ended at 5090 ms | A1.5, A1.8 |
| A2-b | `_speakBrowserFallback(..., maxWaitMs)` is the one helper: it registers `_fireBrowserEnd` as `_settleBrowserSentence` and arms the bound; the bound calls `_fireBrowserEnd` (the 'end' fires, so GUARD 2 re-arms) | finding 2 (P2, injected, regression): two bounded sentences exhausted the 45 s | A1.2 (`_awaitBrowserSentence`), A1.11 |
| A2-c | `stopSpeaking`, `_playNow` and `_resetTtsStatusForTests` call `_endBrowserSentenceWait()` | finding 3 (P3, injected, regression): stop left `liveBounds=1` | A1's "a stop fires `onerror`" assumption |
| A2-d | The single-call path holds no wait (`browserWaitMs` is `undefined` when `last` is) | a whole browser reply can run past 20 s, and a bound 'end' would let the arbiter cut it; its two tests (`voice.serverTts`:129, :159) also leaked timers | A1's single-call wait |
| A2-e | `voice.prefetch.bf918`'s `afterEach` ends any wait; `FakeAudio.rejectPlay()`; V13-V18 new; V9 rewritten so it fails on the base | finding 4 (P3, ordinary, regression); "V9 survives" | A1.13's V9 |
| A2-f | Claims: four syntheses at the start hold; no general ~15 s cut-off; "each accepted request" | the three remaining claims | A1.1, A1.2 comments, A1.17, A1.18, section 12 |

### 17.3 Every state and ordering the wait covers

Where the play half is when the fallback starts (queue only; the single-call path has none of this):

| # | Ordering | Result under A2 | Test |
|---|---|---|---|
| O1 | `prepared === null` (synthesis or storage failed) | fallback awaited | P19, V6, V11, V12, V14-V17 |
| O2 | `play()` rejects first (autoplay refused; or the element failed while loading at prepare time, before the listeners: `play()` then rejects with no new `error`) | rejection handler starts the fallback; awaited | V10 |
| O3 | `play` then media `error` then the `play()` rejection (Chromium's order) | `error` settles the server half, the half waits for `playSettled`, the rejection starts the fallback, awaited | V13 |
| O4 | media `error` after `play()` resolved (mid-stream) | no fallback, as on the base; `playSettled` already settled, no wait | - (unchanged) |
| O5 | `pause` (stop or newer dispatch) while `play()` is pending, then the AbortError rejection | `_finish(true)`; the handler sees the device taken and speaks nothing; `mediaError` false, no wait | P13 |
| O6 | a throw in the play half's setup | catch starts the fallback; awaited | (unchanged A1 path) |

How a wait (W: a queued browser sentence speaking, `_settleBrowserSentence` set, bound armed) ends; each runs `_fireBrowserEnd` once (`_ended` guard), clears the bound, fires one 'end' and resolves; any later callback is a no-op:

| # | Exit | 'end' `final` | Test |
|---|---|---|---|
| E1 | `onend` | false (true on the last sentence) | P19, V10, V13 |
| E2 | `onerror` (including the one `cancel()` makes an engine fire) | as E1, or true after a stop | V11 |
| E3 | the bound (20 s), one warning | as E1; GUARD 2 re-arms (or the entry ends on the last sentence) | V12, V14 |
| E4 | `stopSpeaking` (after `cancel()`, `_activeUtteranceId` already null) | true; the queue discards the rest | V15 |
| E5 | `_playNow` of a newer entry (reachable when GUARD 2 fired first, e.g. a first synthesis stalled past 25 s) | true (called after the device changed hands) | V16 |
| E6 | `_resetTtsStatusForTests` (test seam; the file's `afterEach`) | true | V17 |

No-engine (`speechSynthesis` absent): one 'end' and an already-resolved promise, no timer (unchanged). At most one wait is live: the queue plays one sentence at a time, and every new dispatch ends any wait before it plays. `_settleBrowserSentence` can keep an ended utterance's `_fireBrowserEnd` until the next exit; calling it is a no-op.

### 17.4 The pairs (against `6a22d505`; CRLF working copies, LF blocks; each SEARCH occurs once at its turn)

#### `ui/src/audio/voice.ts`

**A2.1** (claim: four syntheses). SEARCH:
```ts
 *  pipelining. BF-930 (#1668): three (was one), so a stall of one sentence's synthesis
 *  or storage no longer than the audio already held (up to three sentences, about
 *  10-14 s) is not heard; a longer stall still pauses. A stopped reply can have spent
 *  up to three syntheses, their stored WAVs and any viseme requests they started. */
const TTS_PREFETCH_LOOKAHEAD = 3;
```
REPLACE:
```ts
 *  pipelining. BF-930 (#1668): three (was one), so a stall of one sentence's synthesis
 *  or storage no longer than the audio already held (up to three sentences, about
 *  10-14 s) is not heard; a longer stall still pauses. A reply stopped while its first
 *  sentence waits for the start buffer can have spent four syntheses (that sentence and
 *  three ahead), and three once a sentence plays, with their stored WAVs and any viseme
 *  requests they started. */
const TTS_PREFETCH_LOOKAHEAD = 3;
```

**A2.2** (test seam). SEARCH:
```ts
  _dispatchStartedAt = null;
  _sentenceEndedAt = null;
  _endSentenceQueueWait = null;
}
```
REPLACE:
```ts
  _dispatchStartedAt = null;
  _sentenceEndedAt = null;
  _endSentenceQueueWait = null;
  _endBrowserSentenceWait(); // BF-930 A2: a browser sentence a test left waiting, with its bound
}
```

**A2.3** (claim: no general cut-off; the settler replaces `_awaitBrowserSentence`). SEARCH:
```ts
/** BF-930 A1: the longest the play half waits for a sentence the browser speaks in place
 *  of a server one. Chromium cuts an utterance off at about 15 s with no end or error
 *  event, and onend can be lost in a backgrounded tab; 20 s is past that cut-off and
 *  past about 45 words at the default rate, and inside SPEECH_JOIN_TIMEOUT_MS (45 s). */
export const BROWSER_SENTENCE_MAX_WAIT_MS = 20000;

/** BF-930 A1: resolve when `spoken` does (the utterance's onend or onerror) or after
 *  BROWSER_SENTENCE_MAX_WAIT_MS with one warning, whichever is first. Never rejects. */
function _awaitBrowserSentence(spoken: Promise<void>): Promise<void> {
  return new Promise<void>((resolve) => {
    const bound = setTimeout(() => {
      console.warn(`[voice] BF-930: browser speech gave no end or error within ${BROWSER_SENTENCE_MAX_WAIT_MS} ms; the reply goes on`);
      resolve();
    }, BROWSER_SENTENCE_MAX_WAIT_MS);
    void spoken.then(() => { clearTimeout(bound); resolve(); });
  });
}
```
REPLACE:
```ts
/** BF-930 A1/A2: the longest the AD-1071 play half waits for a sentence the browser
 *  speaks in place of a server one. A browser or voice can fail to report an
 *  utterance's end (onend can be lost in a backgrounded tab, or when the utterance
 *  object is collected); 20 s is past about 45 words at the default rate and inside
 *  SPEECH_JOIN_TIMEOUT_MS (45 s). A browser sentence that really speaks for longer is
 *  overlapped by the next sentence after the bound. */
export const BROWSER_SENTENCE_MAX_WAIT_MS = 20000;

/** BF-930 A2 (#1668): the `_fireBrowserEnd` of the browser sentence the AD-1071 play
 *  half waits on (a no-op once that sentence has ended), or null. Calling it fires the
 *  utterance's one terminal 'end' unless onend or onerror already did, clears its bound
 *  and resolves the wait. The queue plays one sentence at a time and every new dispatch
 *  ends any wait first, so at most one wait is live. */
let _settleBrowserSentence: (() => void) | null = null;

/** BF-930 A2: a stop (`stopSpeaking`) and a newer dispatch (`_playNow`) end the current
 *  browser-sentence wait here, after `speechSynthesis.cancel()`, which fires no event for
 *  an utterance whose engine has already gone quiet or lost its end. The test seam
 *  (`_resetTtsStatusForTests`) calls it too. */
function _endBrowserSentenceWait(): void {
  const settle = _settleBrowserSentence;
  _settleBrowserSentence = null;
  if (settle !== null) settle();
}
```

**A2.4** (a newer dispatch). SEARCH:
```ts
  _activeUtteranceId = utterance_id;
  // BF-918: first audio is measured from here, where the device becomes this utterance's.
  _dispatchStartedAt = { id: utterance_id, at: _voiceNow() };
  _sentenceEndedAt = null;
```
REPLACE:
```ts
  _activeUtteranceId = utterance_id;
  // BF-918: first audio is measured from here, where the device becomes this utterance's.
  _dispatchStartedAt = { id: utterance_id, at: _voiceNow() };
  _sentenceEndedAt = null;
  // BF-930 A2 (#1668): an earlier reply's queue may still wait on a browser sentence that
  // cancel() above ended without an event. Ended after the device changed hands, so its
  // 'end' is final and that queue plays nothing more.
  _endBrowserSentenceWait(); // BF-930 A2: a newer dispatch
```

**A2.5** (the queue-only wait; the media-error state). SEARCH:
```ts
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    // BF-930 A1 (#1668): resolve once the browser has spoken it (bounded), so the AD-1071
    // queue does not start the next sentence over it.
    await _awaitBrowserSentence(_speakBrowserFallback(text, profile, agent_id, utterance_id, last));
    return;
  }
  const { audio, visemes, deferredVisemes } = prepared;
  // BF-930 A1: a browser fallback started below (play() refused, or a throw) is awaited
  // once the server half has settled, as the null path's is.
  let browserDone = null as Promise<void> | null;
  try {
```
REPLACE:
```ts
  // BF-930 A2 (#1668): only the AD-1071 queue (which sets `last`) waits for a sentence the
  // browser speaks in its place; the single-call path resolves at once, as before.
  const browserWaitMs = last === undefined ? undefined : BROWSER_SENTENCE_MAX_WAIT_MS;
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    // BF-930 A1/A2: in the queue, resolve once the browser has spoken it (bounded), so the
    // queue does not start the next sentence over it.
    await _speakBrowserFallback(text, profile, agent_id, utterance_id, last, browserWaitMs);
    return;
  }
  const { audio, visemes, deferredVisemes } = prepared;
  // BF-930 A1/A2: a browser fallback started below (play() refused, a media error, or a
  // throw) is awaited once the server half and play() have both settled.
  let browserDone = null as Promise<void> | null;
  // BF-930 A2: Chromium fires a media 'error' (which settles the server half) BEFORE it
  // rejects a pending play(), and that rejection starts the fallback. After an 'error'
  // the half therefore waits for play() to settle (`playSettled`).
  let playSettled: Promise<void> = Promise.resolve();
  let mediaError = false as boolean;
  try {
```

**A2.6.** SEARCH:
```ts
      audio.addEventListener('error', () => _finish(true));
      // BF-655 (refines AD-1071): a newer speakResponse, or a barge-in (BF-918),
```
REPLACE:
```ts
      // BF-930 A2: a media error. If play() is still pending, Chromium rejects it next.
      audio.addEventListener('error', () => { mediaError = true; _finish(true); });
      // BF-655 (refines AD-1071): a newer speakResponse, or a barge-in (BF-918),
```

**A2.7.** SEARCH:
```ts
      audio.play().then(undefined, () => {
        // BF-918 (review round 1): pausing a play() that has not started playback
```
REPLACE:
```ts
      playSettled = audio.play().then(undefined, () => {
        // BF-918 (review round 1): pausing a play() that has not started playback
```

**A2.8.** SEARCH:
```ts
        browserDone = _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
        _finish(false);
      });
    });
  } catch {
    _invalidateTtsStatus();
    browserDone = _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
  }
  if (browserDone !== null) await _awaitBrowserSentence(browserDone);
}
```
REPLACE:
```ts
        browserDone = _speakBrowserFallback(text, profile, agent_id, utterance_id, last, browserWaitMs);
        _finish(false);
      });
    });
    // BF-930 A2: after a media 'error' the server half settled before play() rejected;
    // wait for that rejection, which starts the fallback awaited below.
    if (mediaError) await playSettled;
  } catch {
    _invalidateTtsStatus();
    browserDone = _speakBrowserFallback(text, profile, agent_id, utterance_id, last, browserWaitMs); // a throw
  }
  if (browserDone !== null) await browserDone;
}
```

**A2.9.** SEARCH:
```ts
  utterance_id?: number,
  last?: boolean,
): Promise<void> {
  // BF-930 A1 (#1668): resolves once this utterance's terminal 'end' has fired (onend or
  // onerror; at once when there is no engine). Callers that do not wait ignore it.
  if (!('speechSynthesis' in window)) {
```
REPLACE:
```ts
  utterance_id?: number,
  last?: boolean,
  maxWaitMs?: number,
): Promise<void> {
  // BF-930 A1/A2 (#1668): with `maxWaitMs` (the AD-1071 play half) it resolves once this
  // utterance's one terminal 'end' has fired: onend, onerror, the bound, a stop or a newer
  // dispatch. Without it, and when there is no engine, it resolves at once, as before.
  if (!('speechSynthesis' in window)) {
```

**A2.10.** SEARCH:
```ts
  let _ended = false;
  let _resolveSpoken: () => void = () => {};
  const spoken = new Promise<void>((resolve) => { _resolveSpoken = () => resolve(); });
  const _fireBrowserEnd = () => {
    if (_ended) return;
    _ended = true;
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id, ..._finalField(last, utterance_id) });
    _resolveSpoken();
  };
  utterance.onend = _fireBrowserEnd;
  utterance.onerror = _fireBrowserEnd;
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.
  speechSynthesis.speak(utterance);
  return spoken;
}
```
REPLACE:
```ts
  let _ended = false;
  let _resolveSpoken: () => void = () => {};
  const spoken = new Promise<void>((resolve) => { _resolveSpoken = () => resolve(); });
  let bound: ReturnType<typeof setTimeout> | undefined;
  const _fireBrowserEnd = () => {
    if (_ended) return;
    _ended = true;
    if (bound !== undefined) clearTimeout(bound);
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id, ..._finalField(last, utterance_id) });
    _resolveSpoken();
  };
  utterance.onend = _fireBrowserEnd;
  utterance.onerror = _fireBrowserEnd;
  if (maxWaitMs !== undefined) {
    // BF-930 A2 (#1668): a lost onend/onerror must not hold the reply. A stop or a newer
    // dispatch ends the wait through `_settleBrowserSentence`; at the bound this
    // utterance's 'end' fires here, which the arbiter counts as progress (GUARD 2).
    _settleBrowserSentence = _fireBrowserEnd;
    bound = setTimeout(() => {
      console.warn(`[voice] BF-930: browser speech gave no end or error within ${maxWaitMs} ms; the reply goes on`);
      _fireBrowserEnd();
    }, maxWaitMs);
  }
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.
  speechSynthesis.speak(utterance);
  return maxWaitMs === undefined ? Promise.resolve() : spoken;
}
```

**A2.11** (a stop). SEARCH:
```ts
  _activeUtteranceId = null;
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
  // BF-918 (#1626): the server path too. Its <audio> used to play on after a
```
REPLACE:
```ts
  _activeUtteranceId = null;
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
  // BF-930 A2 (#1668): cancel() fires no event for an utterance whose engine has already
  // gone quiet or lost its end; end the browser sentence the AD-1071 play half waits on.
  _endBrowserSentenceWait(); // BF-930 A2: a stop
  // BF-918 (#1626): the server path too. Its <audio> used to play on after a
```

#### `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx`

**A2.12** (harness: Chromium's media failure). SEARCH:
```ts
  removeAttribute = vi.fn(() => { this.discarded = true; });
  load = vi.fn();
  constructor(src: string) {
```
REPLACE:
```ts
  removeAttribute = vi.fn(() => { this.discarded = true; });
  load = vi.fn();
  /** BF-930 A2: the second half of Chromium's media failure. After 'error' (sent with
   *  `emit('error')`), a pending play() rejects with NotSupportedError. */
  rejectPlay(): void {
    const reject = this._rejectPlay;
    this._rejectPlay = null;
    if (reject !== null) reject(new DOMException('The element has no supported sources.', 'NotSupportedError'));
  }
  constructor(src: string) {
```

**A2.13** (teardown, finding 4). SEARCH:
```ts
beforeEach(() => { _installGlobals(); playMode = 'resolve'; });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); cleanup(); });
```
REPLACE:
```ts
beforeEach(() => { _installGlobals(); playMode = 'resolve'; });
afterEach(async () => {
  vi.restoreAllMocks(); vi.unstubAllGlobals(); cleanup();
  // BF-930 A2 (review round 2): end any browser sentence a test left the AD-1071 play
  // half waiting on (V6 does), so its 20 s bound does not outlive the test.
  (await import('../voice'))._resetTtsStatusForTests();
  await _flush();
});
```

**A2.14** (V9, changed in place). SEARCH:
```ts
  it('V9 A1: the rate is clamped to 4 as at play time, so 13 s at rate 10 holds 3.25 s and starts at once', async () => {
    const f = _makeFetch({ pipelining: true, durations: [13000, 4000], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two.', { rate: 10 });
    await _flush();
    expect(createdAudios[0].played).toBe(true);
    expect(createdAudios[0].playbackRate).toBe(4);
  });
```
REPLACE:
```ts
  it('V9 A1: the rate is clamped to 4 as at play time, so at rate 10 a 6.4 s sentence holds 1.6 s, and two hold 3.2 s', async () => {
    // BF-930 A2 (review round 2): the old body (13 s at rate 10) also started at once with
    // no division at all, so it could not tell the repair from the base. Here raw 6400 ms
    // would start at once; unclamped (/10) 640 ms a sentence would still wait after Two;
    // clamped (/4) 1600 ms waits for Two and then starts. Both old assertions are kept.
    const f = _makeFetch({ pipelining: true, durations: [6400, 6400, 6400, 6400], holdTts: [2, 3] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two. Three. Four.', { rate: 10 });
    await _flush();
    expect(createdAudios[0].played).toBe(false);
    f.release(); // Two answers: 3200 ms held
    await _flush();
    expect(createdAudios[0].played).toBe(true);
    expect(createdAudios[0].playbackRate).toBe(4);
  });
```

**A2.15** (V13-V18, new). SEARCH:
```ts
      expect(warn.mock.calls.filter((c) => String(c[0]).includes('BF-930')).length).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
```
REPLACE:
```ts
      expect(warn.mock.calls.filter((c) => String(c[0]).includes('BF-930')).length).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('V13 A2: a media error and then the play() rejection (Chromium order) are spoken by the browser, and the next waits for its end', async () => {
    playMode = 'hold';
    const f = _makeFetch({ pipelining: true, durations: [4000, 4000] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    voiceMod.speakResponse('One. Two.');
    await _flush();
    expect(createdAudios[0].played).toBe(true); // play() is pending: its WAV still loads
    playMode = 'resolve';
    createdAudios[0].emit('error'); // the server half settles here ...
    await _flush();
    expect(createdAudios[1].played).toBe(false); // ... and the queue waits for play() to settle
    createdAudios[0].rejectPlay(); // ... which Chromium rejects after the 'error'
    await _flush();
    expect(spoken()).toEqual(['One.']);
    expect(createdAudios[1].played).toBe(false); // Two waits for the browser's One
    (speakCalls[0] as FakeUtterance).onend?.();
    await _flush();
    expect(createdAudios[1].played).toBe(true);
  });

  it('V14 A2: browser sentences that hit the bound one after another keep the reply: each bound fires its end, which re-arms the arbiter', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const f = _makeFetch({ pipelining: true, failTts: [2, 3], durations: [4000, 4000, 4000, 4000] });
      (globalThis as any).fetch = f.fetchMock;
      const voiceMod = await _voice();
      const r = await _recordAll();
      try {
        voiceMod.speakResponse('One. Two. Three. Four.');
        voiceMod.speakResponse('Next.');
        await _flush();
        createdAudios[0].end();
        await _flush();
        expect(spoken()).toEqual(['Two.']); // its end never comes
        vi.advanceTimersByTime(voiceMod.BROWSER_SENTENCE_MAX_WAIT_MS);
        await _flush();
        expect(spoken()).toEqual(['Two.', 'Three.']); // nor does Three's
        vi.advanceTimersByTime(voiceMod.BROWSER_SENTENCE_MAX_WAIT_MS);
        await _flush();
        expect(createdAudios[1].played).toBe(true); // Four, at 40 s
        // 65 s: past the 45 s after which the arbiter used to hand the device to Next.
        vi.advanceTimersByTime(voiceMod.SPEECH_JOIN_TIMEOUT_MS - voiceMod.BROWSER_SENTENCE_MAX_WAIT_MS);
        await _flush();
        expect(f.posted).not.toContain('Next.');
        expect(createdAudios[1].pause).not.toHaveBeenCalled();
        createdAudios[1].end();
        await _flush();
        expect(f.posted).toContain('Next.');
        expect(r.events.filter((e) => e === 'end:Two.' || e === 'end:Three.')).toEqual(['end:Two.', 'end:Three.']);
        expect(warn.mock.calls.filter((c) => String(c[0]).includes('BF-930')).length).toBe(2);
      } finally {
        r.off();
      }
    } finally {
      vi.useRealTimers();
    }
  });

  it('V15 A2: a stop ends the wait for a browser sentence whose end never comes, and its bound with it', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const f = _makeFetch({ pipelining: true, failTts: [2], durations: [4000, 4000, 4000] });
      (globalThis as any).fetch = f.fetchMock;
      const voiceMod = await _voice();
      const r = await _recordAll();
      try {
        voiceMod.speakResponse('One. Two. Three.');
        await _flush();
        createdAudios[0].end();
        await _flush();
        expect(spoken()).toEqual(['Two.']);
        voiceMod.stopSpeaking(); // the engine had already gone quiet: cancel() fires no onerror
        await _flush();
        expect(r.events.filter((e) => e === 'end:Two.')).toEqual(['end:Two.']);
        expect(createdAudios[1].played).toBe(false);
        expect(createdAudios[1].discarded).toBe(true);
        vi.advanceTimersByTime(voiceMod.BROWSER_SENTENCE_MAX_WAIT_MS);
        await _flush();
        expect(warn.mock.calls.filter((c) => String(c[0]).includes('BF-930')).length).toBe(0);
        expect(r.events.filter((e) => e === 'end:Two.')).toEqual(['end:Two.']);
      } finally {
        r.off();
      }
    } finally {
      vi.useRealTimers();
    }
  });

  it('V16 A2: a newer dispatch ends the wait for a browser sentence whose end never comes', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const f = _makeFetch({ pipelining: true, failTts: [1], holdTts: [1], durations: [4000, 4000] });
      (globalThis as any).fetch = f.fetchMock;
      const voiceMod = await _voice();
      const r = await _recordAll();
      try {
        voiceMod.speakResponse('One. Two.');
        voiceMod.speakResponse('Next.');
        await _flush();
        vi.advanceTimersByTime(30000); // One's synthesis stalls for 30 s ...
        f.release(); // ... and then fails: the browser speaks it, and its end never comes
        await _flush();
        expect(spoken()).toEqual(['One.']);
        // At 45 s the arbiter's GUARD 2 gives the device to Next, whose dispatch ends the wait.
        vi.advanceTimersByTime(voiceMod.SPEECH_JOIN_TIMEOUT_MS - 30000);
        await _flush();
        expect(f.posted).toContain('Next.');
        expect(r.events.filter((e) => e === 'end:One.')).toEqual(['end:One.']);
        expect(createdAudios[0].played).toBe(false); // Two never plays
        vi.advanceTimersByTime(voiceMod.BROWSER_SENTENCE_MAX_WAIT_MS);
        await _flush();
        expect(warn.mock.calls.filter((c) => String(c[0]).includes('BF-930')).length).toBe(0);
      } finally {
        r.off();
      }
    } finally {
      vi.useRealTimers();
    }
  });

  it('V17 A2: the test seam ends a browser sentence a test left waiting, so its bound does not outlive the test', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const f = _makeFetch({ pipelining: true, failTts: [1], durations: [4000, 4000] });
      (globalThis as any).fetch = f.fetchMock;
      const voiceMod = await _voice();
      voiceMod.speakResponse('One. Two.');
      await _flush();
      expect(spoken()).toEqual(['One.']); // as in V6, its end never comes
      voiceMod._resetTtsStatusForTests();
      await _flush();
      vi.advanceTimersByTime(voiceMod.BROWSER_SENTENCE_MAX_WAIT_MS);
      await _flush();
      expect(warn.mock.calls.filter((c) => String(c[0]).includes('BF-930')).length).toBe(0);
      expect(createdAudios[0].played).toBe(false); // the ended queue plays nothing more
    } finally {
      vi.useRealTimers();
    }
  });

  it('V18 A2: on the single-call path a browser reply is not bounded: nothing ends it early or starts the next over it', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const f = _makeFetch({ pipelining: false, failTts: [1] });
      (globalThis as any).fetch = f.fetchMock;
      const voiceMod = await _voice();
      const r = await _recordAll();
      try {
        voiceMod.speakResponse('A long reply. Its synthesis failed.');
        voiceMod.speakResponse('Next.');
        await _flush();
        expect(spoken()).toEqual(['A long reply. Its synthesis failed.']);
        vi.advanceTimersByTime(voiceMod.BROWSER_SENTENCE_MAX_WAIT_MS);
        await _flush();
        expect(f.posted).not.toContain('Next.');
        expect(r.events.filter((e) => e.startsWith('end'))).toEqual([]);
        expect(warn.mock.calls.filter((c) => String(c[0]).includes('BF-930')).length).toBe(0);
        (speakCalls[0] as FakeUtterance).onend?.();
        await _flush();
        expect(f.posted).toContain('Next.');
      } finally {
        r.off();
      }
    } finally {
      vi.useRealTimers();
    }
  });
});
```

#### `ui/src/audio/__tests__/voice.pipelining.test.tsx`

No A2 pair. Its only pipelined fallback (honest-degrade, :177-224) fires the utterance's `onend` (A1.14), which ends the wait and clears the bound under A2 as under A1; its other browser call (:226, browser backend) goes through `_playNow` and creates no wait.

#### `PROGRESS.md`

**A2.16** (claims: accepted requests; the wait's exits; test range). SEARCH (line 3, whole):
```markdown
**BF-930 (2026-11-27), #1668 -- a spoken reply rides out a stall of one sentence's synthesis or storage, up to the audio already held.** The AD-1071 sentence queue now synthesizes up to three sentences ahead (was one) and holds a first sentence that plays for less than 3 s until the next is ready (`ui/src/audio/voice.ts`, `voiceChunking.ts`: `runPrefetchQueue` gains `startWhen`); the buffer counts each sentence's playing time at the profile's rate. A stall no longer than the audio held (about 10-14 s) is not heard; a longer one, like the 17.8 s of 2026-10-30, still pauses, for less time. An unknown duration or a failed synthesis starts as before. A sentence the browser speaks in place of a failed one now ends before the next sentence starts; a browser that never reports that end is waited on for at most 20 s (`BROWSER_SENTENCE_MAX_WAIT_MS`). The TTS route records each request on the dream scheduler (`DreamScheduler.record_speech_activity`), so while replies come less than `idle_threshold_seconds` apart an idle full dream does not start; one stretch of speech holds it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h), after which the dream starts once the monitor's idle and interval conditions hold. The idle full dream logs `BF-930: idle full dream starting/finished`. The contract's loop-lag probe was dropped: BF-932's loop-stall sampler (#1670) logs loop blocks. Write-behind of spoken audio is not built: the 2026-10-30 stalls silenced every logger (a blocked loop), and it waits for `behind=` evidence. #1668 stays open for the Captain's live re-measurement. New `tests/test_bf930_speech_defers_idle_dream.py` (8 tests); UI V1-V12, Q7-Q8; P1, P2, P14, P19 and two pipelining tests updated in place. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
```
REPLACE:
```markdown
**BF-930 (2026-11-27), #1668 -- a spoken reply rides out a stall of one sentence's synthesis or storage, up to the audio already held.** The AD-1071 sentence queue now synthesizes up to three sentences ahead (was one) and holds a first sentence that plays for less than 3 s until the next is ready (`ui/src/audio/voice.ts`, `voiceChunking.ts`: `runPrefetchQueue` gains `startWhen`); the buffer counts each sentence's playing time at the profile's rate. A stall no longer than the audio held (about 10-14 s) is not heard; a longer one, like the 17.8 s of 2026-10-30, still pauses, for less time. An unknown duration or a failed synthesis starts as before. In the queue, a sentence the browser speaks in place of a failed one (failed synthesis, refused playback or a media error) now ends before the next sentence starts; its end, a stop, a newer reply, or 20 s with no end report (`BROWSER_SENTENCE_MAX_WAIT_MS`, one console warning) ends that wait. The TTS route records each accepted request on the dream scheduler (`DreamScheduler.record_speech_activity`), so while replies come less than `idle_threshold_seconds` apart an idle full dream does not start; one stretch of speech holds it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h), after which the dream starts once the monitor's idle and interval conditions hold. The idle full dream logs `BF-930: idle full dream starting/finished`. The contract's loop-lag probe was dropped: BF-932's loop-stall sampler (#1670) logs loop blocks. Write-behind of spoken audio is not built: the 2026-10-30 stalls silenced every logger (a blocked loop), and it waits for `behind=` evidence. #1668 stays open for the Captain's live re-measurement. New `tests/test_bf930_speech_defers_idle_dream.py` (8 tests); UI V1-V18, Q7-Q8; P1, P2, P14, P19 and two pipelining tests updated in place. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
```

#### `DECISIONS.md`

**A2.17** (claim: no general cut-off; the hardened wait). SEARCH (line 20, whole):
```markdown
- *D5.* A sentence the browser speaks in place of a server one is awaited before the next sentence plays, for at most 20 s (`BROWSER_SENTENCE_MAX_WAIT_MS`, past Chromium's ~15 s utterance cut-off, which fires no end event); at the bound the reply goes on and the console logs one warning.
```
REPLACE:
```markdown
- *D5.* In the sentence queue, a sentence the browser speaks in place of a server one (failed synthesis, refused playback, a media error, or a throw) is awaited before the next sentence plays. The wait ends once, on the utterance's end or error event, a stop, a newer dispatch, or 20 s (`BROWSER_SENTENCE_MAX_WAIT_MS`); every exit fires the utterance's one terminal 'end', so the arbiter counts a bounded sentence as progress, and the bound logs one console warning. A browser or voice can fail to report an end; a browser sentence that really speaks for longer than 20 s is overlapped after the bound. The single-call path does not wait, as before.
```

### 17.5 Counts, rows, commit

- UI tests: 6 new (V13-V18), 1 changed in place (V9, reason inline), 0 removed; `FakeAudio` gains `rejectPlay()`, the file's `afterEach` becomes async. Branch totals in the header.
- Mutation rows: 8.3 (B1-B3 relocated, B4 retired, B5 kept, C1-C11 new, R1 now also killed by V9). The campaign of record reruns R1, R2, B1-B3, B5 and C1-C11 on the A2 head.
- A/B: 8.1 (A2 bullet).
- Commit subject: `A browser-spoken sentence in the reply queue ends on a stop, a new reply or its bound, and a media error's fallback is awaited`; body ends `Refs #1668.`

### 17.6 What a round 3 will still see (known; not in this family or stated limits)

- **Pre-existing, unchanged:** a reply's **last** sentence whose media fails (O3) while another entry is queued. The `error` fires that sentence's final 'end' first, the arbiter hands the device to the next entry, and the `play()` rejection then finds the device taken and speaks nothing, so the sentence is skipped. The base does the same; fixing it means deferring a server 'end' until `play()` settles, which changes the BF-655 start/end contract. Out of scope; a follow-up item if the reviewer raises it.
- **Stated limit:** a queued browser sentence that really speaks past 20 s, or loses its end report, gets its 'end' at the bound. The PTT gate re-arms, the next sentence overlaps it, and on a last sentence the next reply's `cancel()` may cut it. One warning each (sections 3 D8, 13).
- **Equivalent mutant:** `return spoken;` for the unbounded return (8.3 note).
- `_settleBrowserSentence` can hold an ended utterance's closure until the next exit (a guarded no-op, 17.3).

### 17.7 After the pairs

1. `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` if they change.
2. `git diff --check`; `git diff --stat` shows only `voice.ts`, `voice.prefetch.bf918.test.tsx`, `PROGRESS.md`, `DECISIONS.md`, the contract and the ledger files.
3. The orchestrator commits with the A2 subject, then runs 8.1 (A2 A/B), 8.2 (the vitest line and `npm run build` cover the A2 change), the 8.3 rows named in 17.5, and the gate (8.4).

## 18. Amendment A3 (2026-11-27, round-three brake: split; D8 withdrawn)

### 18.1 Decision and why

Round 3 (`6a22d505..1d9d5c48`) returned NOT READY with R3-1 (P2, ordinary, regression), R3-2 (P3, claim) and R3-3 (P4, size). The round-three brake decision (Architect, 2026-11-27, recorded on #1668) is **split**: land S1, D9, S2 and the claim fixes; withdraw D8 completely; the browser-fallback overlap returns to what it is on the base, BF-918's registered residual R3, and its redesign is filed as follow-up #1869 under the filing policy (not kept as a slice of #1668).

The design is what keeps producing findings. D8 makes the play half emulate the browser engine's end, but the engine is a shared global queue (`speechSynthesis`) whose events D8 does not own, and the 20 s bound counts from `speak()` (`voice.ts`:1016-1019 at `1d9d5c48`), not from `onstart`, so time spent behind an earlier utterance in the engine's queue counts against it. Each round found a new place where an emulated event met a real one: round 2 found the media `error`/`play()` order, the arbiter deadline, stop and teardown; round 3 found a late `start` (R3-1: real Chromium 148, Three's bounded 'end' at 41.3 s, its native `start` at 50.1 s, the PTT gate still locked at 54.7 s). Guarding `onstart` with `_ended` would leave that utterance audible with no 'start' and no 'end', with the PTT gate and wake word open while the agent speaks (18.13 a).

Disposition of every finding:

| Round | Finding | Disposition after A3 |
|---|---|---|
| 1 | M1-a (P2, ordinary; "regression: yes", refuted: base P19 says "R3, unchanged", 17.1) | deferred to #1869: pre-existing, registered, not a regression, does not break the next run |
| 1 | M1-b (P2, playback rate) | fixed by D9; kept |
| 1 | M1 claims P3, M2 P3 | fixed; kept |
| 1 | M3 (loop-lag probe) | moot (S3 dropped; BF-932 D2) |
| 2 | F1 (P2), F2 (P2), F3 (P3), F4 (P3) | removed with D8 (their code no longer exists) |
| 2 | claims x3 ("each accepted request", no general ~15 s cut-off, four/three) | kept; the four/three wording corrected again (R3-2) |
| 3 | R3-1 (P2, regression) | removed with D8 |
| 3 | R3-2 (P3, claim) | fixed here (A3.2, section 9 property 13, section 13) |
| 3 | R3-3 (P4, size) | moot: the allocation goes with D8 |

Every regression a repair introduced (F2, F3, F4, R3-1, R3-3) is removed together with its code, not deferred. The only deferred finding, M1-a, is base behaviour.

### 18.2 What changes and what stays

| Part | After A3 |
|---|---|
| S1 (`TTS_PREFETCH_LOOKAHEAD = 3`, `TTS_START_BUFFER_MS`, `_startBufferFilled`, the `startWhen` argument, `voiceChunking.ts`) | unchanged from `1d9d5c48` apart from the lookahead comment (R3-2) |
| D9 (`_playbackRate`, `PreparedSpeech.playMs`, the `_prepareServerSpeech` return object, `audio.playbackRate = _playbackRate(...)`) | unchanged |
| S2 (`dreaming.py`, `avatars.py`, the Python test file) | unchanged |
| D8 (`BROWSER_SENTENCE_MAX_WAIT_MS`, `_settleBrowserSentence`, `_endBrowserSentenceWait` and its three calls, `browserWaitMs`, `browserDone`, `playSettled`, `mediaError`, `_speakBrowserFallback`'s `Promise<void>`/`maxWaitMs`/`spoken`/`bound`) | removed; those hunks are the base's text again |
| Tests | V10-V18 removed (18.6); P19 and the `afterEach` and `FakeAudio` of `voice.prefetch.bf918` byte-identical to the base; `voice.pipelining.test.tsx` byte-identical to `08a88fd0` (M1); V1-V9 kept, V9 as A2 wrote it |
| Trackers | PROGRESS and DECISIONS: D8 text replaced by the known limit with a pointer to #1869; "each accepted request" kept |

`afterEach`: back to the base. Its async reset (A2.13) existed only to end a browser-sentence wait and its 20 s timer; no such timer exists after A3, and V1-V6 passed under the base `afterEach` at `08a88fd0` (campaign 1). `FakeAudio.rejectPlay()` (A2.12): removed; only V13 used it (18.10). The base's `_rejectPlay` field stays (P13's `'hold'` mode uses it).

**Orchestrator, before the Builder starts:** file the follow-up (18.11), then replace every `#<new>` in this section (A3.18, A3.19) and in section 12 with its number. A Builder that finds `#<new>` in a REPLACE stops.

### 18.3 The pairs (against `1d9d5c48`; CRLF working copies, LF blocks; each SEARCH occurs once at its turn)

#### `ui/src/audio/voice.ts`

**A3.1** (test seam: base). SEARCH:
```ts
  _endSentenceQueueWait = null;
  _endBrowserSentenceWait(); // BF-930 A2: a browser sentence a test left waiting, with its bound
}
```
REPLACE:
```ts
  _endSentenceQueueWait = null;
}
```

**A3.2** (R3-2: the lookahead comment counts unplayed preparations). SEARCH:
```ts
 *  pipelining. BF-930 (#1668): three (was one), so a stall of one sentence's synthesis
 *  or storage no longer than the audio already held (up to three sentences, about
 *  10-14 s) is not heard; a longer stall still pauses. A reply stopped while its first
 *  sentence waits for the start buffer can have spent four syntheses (that sentence and
 *  three ahead), and three once a sentence plays, with their stored WAVs and any viseme
 *  requests they started. */
const TTS_PREFETCH_LOOKAHEAD = 3;
```
REPLACE:
```ts
 *  pipelining. BF-930 (#1668): three (was one), so a stall of one sentence's synthesis
 *  or storage no longer than the audio already held (up to three sentences, about
 *  10-14 s) is not heard; a longer stall still pauses. A stop discards what was
 *  prepared and not played: up to four sentences while the first waits for the start
 *  buffer (that sentence and three ahead), and up to three ahead while a sentence
 *  plays, each with its stored WAV and any viseme request it started. */
const TTS_PREFETCH_LOOKAHEAD = 3;
```

**A3.3** (the bound, the settler and its helper: removed). SEARCH:
```ts
/** BF-930 A1/A2: the longest the AD-1071 play half waits for a sentence the browser
 *  speaks in place of a server one. A browser or voice can fail to report an
 *  utterance's end (onend can be lost in a backgrounded tab, or when the utterance
 *  object is collected); 20 s is past about 45 words at the default rate and inside
 *  SPEECH_JOIN_TIMEOUT_MS (45 s). A browser sentence that really speaks for longer is
 *  overlapped by the next sentence after the bound. */
export const BROWSER_SENTENCE_MAX_WAIT_MS = 20000;

/** BF-930 A2 (#1668): the `_fireBrowserEnd` of the browser sentence the AD-1071 play
 *  half waits on (a no-op once that sentence has ended), or null. Calling it fires the
 *  utterance's one terminal 'end' unless onend or onerror already did, clears its bound
 *  and resolves the wait. The queue plays one sentence at a time and every new dispatch
 *  ends any wait first, so at most one wait is live. */
let _settleBrowserSentence: (() => void) | null = null;

/** BF-930 A2: a stop (`stopSpeaking`) and a newer dispatch (`_playNow`) end the current
 *  browser-sentence wait here, after `speechSynthesis.cancel()`, which fires no event for
 *  an utterance whose engine has already gone quiet or lost its end. The test seam
 *  (`_resetTtsStatusForTests`) calls it too. */
function _endBrowserSentenceWait(): void {
  const settle = _settleBrowserSentence;
  _settleBrowserSentence = null;
  if (settle !== null) settle();
}

/** BF-918 (review round 1, D7a): the `dropped` reason of a dispatched utterance that
```
REPLACE:
```ts
/** BF-918 (review round 1, D7a): the `dropped` reason of a dispatched utterance that
```

**A3.4** (`_playNow`: base). SEARCH:
```ts
  _sentenceEndedAt = null;
  // BF-930 A2 (#1668): an earlier reply's queue may still wait on a browser sentence that
  // cancel() above ended without an event. Ended after the device changed hands, so its
  // 'end' is final and that queue plays nothing more.
  _endBrowserSentenceWait(); // BF-930 A2: a newer dispatch
```
REPLACE:
```ts
  _sentenceEndedAt = null;
```

**A3.5** (`_playPreparedSpeech` head and null path: base). SEARCH:
```ts
  // BF-930 A2 (#1668): only the AD-1071 queue (which sets `last`) waits for a sentence the
  // browser speaks in its place; the single-call path resolves at once, as before.
  const browserWaitMs = last === undefined ? undefined : BROWSER_SENTENCE_MAX_WAIT_MS;
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    // BF-930 A1/A2: in the queue, resolve once the browser has spoken it (bounded), so the
    // queue does not start the next sentence over it.
    await _speakBrowserFallback(text, profile, agent_id, utterance_id, last, browserWaitMs);
    return;
  }
  const { audio, visemes, deferredVisemes } = prepared;
  // BF-930 A1/A2: a browser fallback started below (play() refused, a media error, or a
  // throw) is awaited once the server half and play() have both settled.
  let browserDone = null as Promise<void> | null;
  // BF-930 A2: Chromium fires a media 'error' (which settles the server half) BEFORE it
  // rejects a pending play(), and that rejection starts the fallback. After an 'error'
  // the half therefore waits for play() to settle (`playSettled`).
  let playSettled: Promise<void> = Promise.resolve();
  let mediaError = false as boolean;
  try {
```
REPLACE:
```ts
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
    return;
  }
  const { audio, visemes, deferredVisemes } = prepared;
  try {
```

**A3.6** (media `error` listener: base). SEARCH:
```ts
      // BF-930 A2: a media error. If play() is still pending, Chromium rejects it next.
      audio.addEventListener('error', () => { mediaError = true; _finish(true); });
```
REPLACE:
```ts
      audio.addEventListener('error', () => _finish(true));
```

**A3.7** (`play()`: base). SEARCH:
```ts
      playSettled = audio.play().then(undefined, () => {
```
REPLACE:
```ts
      audio.play().then(undefined, () => {
```

**A3.8** (refused and throw fallbacks, the final wait: base). SEARCH:
```ts
        browserDone = _speakBrowserFallback(text, profile, agent_id, utterance_id, last, browserWaitMs);
        _finish(false);
      });
    });
    // BF-930 A2: after a media 'error' the server half settled before play() rejected;
    // wait for that rejection, which starts the fallback awaited below.
    if (mediaError) await playSettled;
  } catch {
    _invalidateTtsStatus();
    browserDone = _speakBrowserFallback(text, profile, agent_id, utterance_id, last, browserWaitMs); // a throw
  }
  if (browserDone !== null) await browserDone;
}
```
REPLACE:
```ts
        _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
        _finish(false);
      });
    });
  } catch {
    _invalidateTtsStatus();
    _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
  }
}
```

**A3.9** (`_speakBrowserFallback` signature: base). SEARCH:
```ts
  last?: boolean,
  maxWaitMs?: number,
): Promise<void> {
  // BF-930 A1/A2 (#1668): with `maxWaitMs` (the AD-1071 play half) it resolves once this
  // utterance's one terminal 'end' has fired: onend, onerror, the bound, a stop or a newer
  // dispatch. Without it, and when there is no engine, it resolves at once, as before.
  if (!('speechSynthesis' in window)) {
```
REPLACE:
```ts
  last?: boolean,
): void {
  if (!('speechSynthesis' in window)) {
```

**A3.10** (no-engine return: base). SEARCH:
```ts
      ..._finalField(last, utterance_id),
    });
    return Promise.resolve();
  }
```
REPLACE:
```ts
      ..._finalField(last, utterance_id),
    });
    return;
  }
```

**A3.11** (body: base). SEARCH:
```ts
  let _ended = false;
  let _resolveSpoken: () => void = () => {};
  const spoken = new Promise<void>((resolve) => { _resolveSpoken = () => resolve(); });
  let bound: ReturnType<typeof setTimeout> | undefined;
  const _fireBrowserEnd = () => {
    if (_ended) return;
    _ended = true;
    if (bound !== undefined) clearTimeout(bound);
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id, ..._finalField(last, utterance_id) });
    _resolveSpoken();
  };
  utterance.onend = _fireBrowserEnd;
  utterance.onerror = _fireBrowserEnd;
  if (maxWaitMs !== undefined) {
    // BF-930 A2 (#1668): a lost onend/onerror must not hold the reply. A stop or a newer
    // dispatch ends the wait through `_settleBrowserSentence`; at the bound this
    // utterance's 'end' fires here, which the arbiter counts as progress (GUARD 2).
    _settleBrowserSentence = _fireBrowserEnd;
    bound = setTimeout(() => {
      console.warn(`[voice] BF-930: browser speech gave no end or error within ${maxWaitMs} ms; the reply goes on`);
      _fireBrowserEnd();
    }, maxWaitMs);
  }
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.
  speechSynthesis.speak(utterance);
  return maxWaitMs === undefined ? Promise.resolve() : spoken;
}
```
REPLACE:
```ts
  let _ended = false;
  const _fireBrowserEnd = () => {
    if (_ended) return;
    _ended = true;
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id, ..._finalField(last, utterance_id) });
  };
  utterance.onend = _fireBrowserEnd;
  utterance.onerror = _fireBrowserEnd;
  // 'boundary' reserved for AD-721b phoneme work; not wired in v1.
  speechSynthesis.speak(utterance);
}
```

**A3.12** (`stopSpeaking`: base). SEARCH:
```ts
    speechSynthesis.cancel();
  }
  // BF-930 A2 (#1668): cancel() fires no event for an utterance whose engine has already
  // gone quiet or lost its end; end the browser sentence the AD-1071 play half waits on.
  _endBrowserSentenceWait(); // BF-930 A2: a stop
```
REPLACE:
```ts
    speechSynthesis.cancel();
  }
```

#### `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx`

**A3.13** (`FakeAudio.rejectPlay()`: removed; only V13 used it). SEARCH:
```ts
  load = vi.fn();
  /** BF-930 A2: the second half of Chromium's media failure. After 'error' (sent with
   *  `emit('error')`), a pending play() rejects with NotSupportedError. */
  rejectPlay(): void {
    const reject = this._rejectPlay;
    this._rejectPlay = null;
    if (reject !== null) reject(new DOMException('The element has no supported sources.', 'NotSupportedError'));
  }
  constructor(src: string) {
```
REPLACE:
```ts
  load = vi.fn();
  constructor(src: string) {
```

**A3.14** (`afterEach`: base). SEARCH:
```ts
afterEach(async () => {
  vi.restoreAllMocks(); vi.unstubAllGlobals(); cleanup();
  // BF-930 A2 (review round 2): end any browser sentence a test left the AD-1071 play
  // half waiting on (V6 does), so its 20 s bound does not outlive the test.
  (await import('../voice'))._resetTtsStatusForTests();
  await _flush();
});
```
REPLACE:
```ts
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); cleanup(); });
```

**A3.15** (P19: the base text; it pins R3, which is the base behaviour again). SEARCH:
```ts
      // Two failed: the browser speaks it. BF-930 A1 (#1668, review round 1): Three now
      // waits for the browser's end; it used to play meanwhile (R3), which with lookahead 3
      // overlapped Two. The played-true assertion moves after Two's end.
      expect(spoken()).toEqual(['Two.']);
      expect(createdAudios[1].played).toBe(false);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();
      expect(createdAudios[1].played).toBe(true);
      expect(f.posted).not.toContain('Next.');
```
REPLACE:
```ts
      // Two failed: the browser speaks it, and Three plays meanwhile (R3, unchanged).
      expect(spoken()).toEqual(['Two.']);
      expect(createdAudios[1].played).toBe(true);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();
      expect(f.posted).not.toContain('Next.');
```

**A3.16** (V10-V18: removed with D8). This is an anchored range deletion, not a SEARCH block (239 lines). Delete from the blank line directly above `  it('V10 A1: a sentence whose play() is refused is spoken by the browser, and the next waits for its end', async () => {` (it is line 902 at `1d9d5c48`; after A3.13-A3.15 it is line 886) through the line `  });` directly above the file's last line `});`, inclusive. Both anchors occur once: the V10 title line, and the file's last line. After the deletion the file ends with V9's last three lines and the describe's close:
```ts
    expect(createdAudios[0].playbackRate).toBe(4);
  });
});
```
Check: before A3.13-A3.16 the file has 1141 lines; after them, 1141 - 7 - 6 - 3 - 239 = 886 lines (A3.13 removes 7, A3.14 removes 6, A3.15 removes 3, A3.16 removes 239) (`wc -l`, which counts CRLF lines the same).

#### `ui/src/audio/__tests__/voice.pipelining.test.tsx`

**A3.17** (the honest-degrade test: its M1 text; the file then equals `08a88fd0`). SEARCH:
```ts
    // Sentence[1] fell back to the browser in its turn. BF-930 A1 (#1668): the queue now
    // waits for that utterance's end before sentence[2] plays; it used to resolve at once
    // and play sentence[2] over it.
    expect(speakCalls.length).toBe(1);
    expect(posted).toEqual(['Alpha.', 'Bravo.', 'Charlie.']);
    expect(createdAudios[1].played).toBe(false);
    (speakCalls[0] as { onend: (() => void) | null }).onend?.();
    await _flush();
    expect(createdAudios[1].played).toBe(true);
  });
```
REPLACE:
```ts
    // Sentence[1] fell back to the browser in its turn and resolved at once,
    // so the queue already moved on to sentence[2] without a new 'ended'.
    expect(speakCalls.length).toBe(1);
    expect(posted).toEqual(['Alpha.', 'Bravo.', 'Charlie.']);
  });
```

#### `PROGRESS.md`

**A3.18** (line 3, the whole line). SEARCH:
```text
**BF-930 (2026-11-27), #1668 -- a spoken reply rides out a stall of one sentence's synthesis or storage, up to the audio already held.** The AD-1071 sentence queue now synthesizes up to three sentences ahead (was one) and holds a first sentence that plays for less than 3 s until the next is ready (`ui/src/audio/voice.ts`, `voiceChunking.ts`: `runPrefetchQueue` gains `startWhen`); the buffer counts each sentence's playing time at the profile's rate. A stall no longer than the audio held (about 10-14 s) is not heard; a longer one, like the 17.8 s of 2026-10-30, still pauses, for less time. An unknown duration or a failed synthesis starts as before. In the queue, a sentence the browser speaks in place of a failed one (failed synthesis, refused playback or a media error) now ends before the next sentence starts; its end, a stop, a newer reply, or 20 s with no end report (`BROWSER_SENTENCE_MAX_WAIT_MS`, one console warning) ends that wait. The TTS route records each accepted request on the dream scheduler (`DreamScheduler.record_speech_activity`), so while replies come less than `idle_threshold_seconds` apart an idle full dream does not start; one stretch of speech holds it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h), after which the dream starts once the monitor's idle and interval conditions hold. The idle full dream logs `BF-930: idle full dream starting/finished`. The contract's loop-lag probe was dropped: BF-932's loop-stall sampler (#1670) logs loop blocks. Write-behind of spoken audio is not built: the 2026-10-30 stalls silenced every logger (a blocked loop), and it waits for `behind=` evidence. #1668 stays open for the Captain's live re-measurement. New `tests/test_bf930_speech_defers_idle_dream.py` (8 tests); UI V1-V18, Q7-Q8; P1, P2, P14, P19 and two pipelining tests updated in place. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
```
REPLACE:
```text
**BF-930 (2026-11-27), #1668 -- a spoken reply rides out a stall of one sentence's synthesis or storage, up to the audio already held.** The AD-1071 sentence queue now synthesizes up to three sentences ahead (was one) and holds a first sentence that plays for less than 3 s until the next is ready (`ui/src/audio/voice.ts`, `voiceChunking.ts`: `runPrefetchQueue` gains `startWhen`); the buffer counts each sentence's playing time at the profile's rate. A stall no longer than the audio held (about 10-14 s) is not heard; a longer one, like the 17.8 s of 2026-10-30, still pauses, for less time. An unknown duration or a failed synthesis starts as before. Known limit, unchanged from before (BF-918's registered R3): a sentence the browser speaks in place of a failed one (failed synthesis, refused playback or a media error) can be overlapped by the next server sentence; a bounded wait for it was built and withdrawn before merge, and its redesign is #1869. The TTS route records each accepted request on the dream scheduler (`DreamScheduler.record_speech_activity`), so while replies come less than `idle_threshold_seconds` apart an idle full dream does not start; one stretch of speech holds it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h), after which the dream starts once the monitor's idle and interval conditions hold. The idle full dream logs `BF-930: idle full dream starting/finished`. The contract's loop-lag probe was dropped: BF-932's loop-stall sampler (#1670) logs loop blocks. Write-behind of spoken audio is not built: the 2026-10-30 stalls silenced every logger (a blocked loop), and it waits for `behind=` evidence. #1668 stays open for the Captain's live re-measurement. New `tests/test_bf930_speech_defers_idle_dream.py` (8 tests); UI V1-V9, Q7-Q8; P1, P2, P14 and two pipelining tests updated in place. Contract `prompts/bf-930-spoken-reply-pause-fix.md`.
```

#### `DECISIONS.md`

**A3.19** (D5, the whole line). SEARCH:
```text
- *D5.* In the sentence queue, a sentence the browser speaks in place of a server one (failed synthesis, refused playback, a media error, or a throw) is awaited before the next sentence plays. The wait ends once, on the utterance's end or error event, a stop, a newer dispatch, or 20 s (`BROWSER_SENTENCE_MAX_WAIT_MS`); every exit fires the utterance's one terminal 'end', so the arbiter counts a bounded sentence as progress, and the bound logs one console warning. A browser or voice can fail to report an end; a browser sentence that really speaks for longer than 20 s is overlapped after the bound. The single-call path does not wait, as before.
```
REPLACE:
```text
- *D5.* Known limit, not changed here: in the sentence queue a sentence the browser speaks in place of a server one (failed synthesis, refused playback, a media error, or a throw) is not awaited, so the next server sentence can start over it. This is BF-918's registered residual R3, the base behaviour; lookahead 3 can lengthen the overlap by about one synthesis at most. A bounded wait for that sentence was built and withdrawn before merge: it emulated an end the browser engine had not reported, and a late browser `start` then locked push-to-talk after the reply ended (review round 3). The redesign, a wait that owns the utterance's lifecycle, is #1869.
```

### 18.4 After the pairs

1. `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` if they change.
2. `git diff --check`; `git diff --stat` against `1d9d5c48` shows only `voice.ts`, the two UI test files, `PROGRESS.md`, `DECISIONS.md`, the contract (if not committed first) and the ledger files.
3. The orchestrator commits with the A3 subject (18.12), body ending `Refs #1668.`, then runs 18.5, 18.6, 8.2 (the vitest line and `npm run build` cover A3), the rows of 18.7 named there, the one review (18.8), and the gate (8.4).

### 18.5 Absence checks (run on the A3 head; each must print nothing)

```text
rg -n "BROWSER_SENTENCE_MAX_WAIT_MS|_settleBrowserSentence|_endBrowserSentenceWait|browserWaitMs|browserDone|playSettled|mediaError|maxWaitMs|_resolveSpoken|\brejectPlay" ui/src
rg -n "BROWSER_SENTENCE_MAX_WAIT_MS|20 s with no end report|is awaited before the next sentence plays" PROGRESS.md DECISIONS.md
rg -n "V1[0-8] A[12]:" ui/src
git diff 08a88fd0 HEAD -- ui/src/audio/__tests__/voice.pipelining.test.tsx
```
On `1d9d5c48` the first command finds 42 hits (`voice.ts` 31, `voice.prefetch.bf918.test.tsx` 11; 18.10), all in the hunks A3 removes. `\brejectPlay` does not match the base's `_rejectPlay` field.

Presence checks (each prints exactly one line): `rg -n "const TTS_PREFETCH_LOOKAHEAD = 3;" ui/src/audio/voice.ts`; `rg -n "each accepted request" PROGRESS.md`; `rg -n "R3, unchanged" ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx`.

### 18.6 Counts and A/B

- **Vitest:** 31 files / 359 tests on `1d9d5c48`; **31 files / 350 tests** after A3.
- **Removed (9), each pinned D8 only:** V10 (refused `play()` waits for the browser's end), V11 (stop during a browser wait), V12 (the 20 s bound and its warning), V13 (media `error` then `play()` rejection), V14 (consecutive bounds re-arm the arbiter), V15 (stop ends a wait with a lost end), V16 (newer dispatch ends the wait), V17 (test seam ends the wait), V18 (single-call path unbounded). V18 passed on the base too; its subject, the bound, no longer exists, and the single-call fallback's base behaviour stays pinned by P11, P13 and `voice.serverTts` :129, :159.
- **Changed in place by A3:** P19 (back to the base text), the honest-degrade test (back to its M1 text), the `afterEach` and `FakeAudio` (back to the base). Against the base, the branch's changed-in-place tests are P1, P2, P14 and the two pipelining tests (lookahead 3 only).
- **Python:** unchanged, 230 tests in the 8.2 file list; A3 touches no Python file.
- **`git diff --stat 32997b18 <A3 head>`, expected (record the actual):** `voice.ts` +39/-4; `voice.prefetch.bf918.test.tsx` +165/-7; `voice.pipelining.test.tsx` +9/-8 (equal to `08a88fd0`); `voiceChunking.ts` +18, `voiceChunking.test.ts` +39, `dreaming.py` +34, `avatars.py` +8, `test_bf930_speech_defers_idle_dream.py` +186 (all unchanged); `PROGRESS.md`, `DECISIONS.md`, the ledger files and the contract also differ. A count that differs by a line or two in a test file is a counting difference, not a failure; a hunk outside 18.8 P1-P3 is a failure.
- **SEARCH counts:** A3.1-A3.15 and A3.17-A3.19 each count once at their turn on `1d9d5c48`; A3.16's two anchors each occur once.
- **A/B on the base `32997b18`** (the A3 head's test files on the base's source): fail on assertions: V1, V4, V5, V7 (plays at once), V9 (raw 6400 ms starts at once), Q7, P1, P2, P14 and the first pipelining test, and the second pipelining test (its `posted` has two); Q8 fails by vitest's timeout. Pass on both trees: V2, V3, V6, V8 (with no start buffer it plays at once, as V8 expects), P19, and every other pre-existing test. The base half of A1's and A2's A/Bs is moot (their D8 tests are gone).

### 18.7 Mutation rows

- **Retired (16):** B1, B2, B3, B5 (B4 was already retired) and C1-C11: their lines are removed and their killing tests went with D8.
- **Live:** U1-U7, D1-D5, R1, R2, with the locators of 8.3. On the A3 head, R1's stripped line is `? data.duration_ms / _playbackRate(profile?.rate)` and R2's is `return Math.max(0.25, Math.min(4.0, rate ?? 0.95));`, both unchanged and each occurring once in `voice.ts`. U4's and U5's line `held += prepared !== null && prepared.playMs > 0 ? prepared.playMs : TTS_START_BUFFER_MS;`, U6's (as R1's), U1's `const TTS_PREFETCH_LOOKAHEAD = 3;` and U7's `_startBufferFilled,` are unchanged and occur once.
- **Killers after A3:** U1 by V4, P1, P2, P14, pipelining; U5 by V3, V6; R1 by V7, V8, V9; R2 by V9; the others as 8.3 says (none of their killers is among V10-V18).
- **New rows:** none (A3 adds no code; every line it writes is the base's or a comment).
- **Campaign of record:** A3 changes no code line of `voiceChunking.ts`, `dreaming.py` or `avatars.py`, and in `voice.ts` only removes lines outside every live locator, so the earlier campaigns stand for U2, U3, D1-D5. Rerun U1, U4-U7, R1 and R2 on the A3 head, because their killing test file lost tests and its `afterEach` changed.

### 18.8 Diff Reviewer brief (the one round the split allows)

The change claims that it removes the browser-sentence wait (D8) completely, so every browser-fallback path behaves as on the base, and keeps S1, D9 and S2 exactly as reviewed in rounds 2 and 3. Consumers that must accept it: the HXI voice path (`speakResponse`, the AD-1071 queue, the arbiter's GUARD 2, `stopSpeaking`), the PTT gate and wake word (speech events), and the reader of `PROGRESS.md` and `DECISIONS.md`. Delta: `git diff 1d9d5c48 <A3 head>`; whole candidate: `git diff 32997b18 <A3 head>`.

1. **P1 `voice.ts` is the base plus S1 and D9 only.** `git diff 32997b18 <A3 head> -- ui/src/audio/voice.ts` has exactly these hunks: the lookahead comment, `TTS_PREFETCH_LOOKAHEAD = 3`, `TTS_START_BUFFER_MS`, `_startBufferFilled`, `_playbackRate`; the `_startBufferFilled,` argument; `PreparedSpeech.playMs`; the `playMs` field of `_prepareServerSpeech`'s return; `audio.playbackRate = _playbackRate(effective.rate);`. Nothing in `_resetTtsStatusForTests`, `_playNow` (beyond the argument), `_playPreparedSpeech` (beyond the rate line), `_speakBrowserFallback` or `stopSpeaking`.
2. **P2 the converged parts are byte-identical to `1d9d5c48`.** `git diff 1d9d5c48 <A3 head> -- ui/src/audio/voiceChunking.ts ui/src/audio/__tests__/voiceChunking.test.ts src tests` prints nothing; in `git diff 1d9d5c48 <A3 head> -- ui/src/audio/voice.ts` every added line is a base line or the lookahead comment.
3. **P3 tests.** `git diff 08a88fd0 <A3 head> -- ui/src/audio/__tests__/voice.pipelining.test.tsx` prints nothing. `git diff 32997b18 <A3 head> -- ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx` touches only `_flush`, `Plan.durations`, the `duration_ms` answer, P1, P2, P14 and the BF-930 describe (V1-V9); `FakeAudio`, the `afterEach` and P19 are not in it. V9's body equals `1d9d5c48`'s.
4. **P4 no D8 leftovers:** the absence checks of 18.5 print nothing.
5. **P5 claims.** The lookahead comment, PROGRESS line 3, DECISIONS D5 and section 12's issue text are true against the code: four/three count unplayed preparations, the overlap is stated as the base's R3 with a pointer to the follow-up, "each accepted request" holds against `avatars.py`, and no text claims the queue waits for a browser-spoken sentence.

Not in scope for this round: S1, D9 and S2 behaviour (clean in rounds 2 and 3, byte-identical by P2), and the overlap itself (deferred by the brake decision, 18.1; see Readings).

### 18.9 Readings for the reviewer's Assumptions check

- **R-a** The overlap of a browser-spoken sentence by the next server sentence is the base's behaviour: base P19 says "Three plays meanwhile (R3, unchanged)", BF-918's contract registers it as R3, and round 3 confirmed it separately. Deferring it is the brake's split decision, not an oversight.
- **R-b** (corrected after the split's review, 18.14) Lookahead 3 can lengthen that overlap, most when several sentences in a row fail: the base requests the sentence after a failed one only once the failed preparation has returned, while lookahead 3 has it ready. One measurement (review of `b184d448`, Chromium 148, two consecutive failed preparations of about 0.6 s each): 2.9 s of overlap against 1.7 s on the base. No numerical cap is claimed.
- **R-c** A reply's last sentence whose media fails while another entry is queued is skipped (17.6). That is base behaviour, unchanged here, and listed in the follow-up.
- **R-d** The single-call path's browser fallback is the base's (unbounded, resolves at once).
- **R-e** R3-3 (the wasted promise) is moot: `_speakBrowserFallback` returns `void` again and allocates no promise.

### 18.10 Verified Against Codebase (2026-11-27, tree `1d9d5c48`)

- `voice.ts` (1139 lines): `_resetTtsStatusForTests` tail :236-239 (`_endBrowserSentenceWait()` :238); lookahead comment and const :259-266; `_startBufferFilled` :277-283 (`held +=` :280); `_playbackRate` :285-289 (`return Math.max(...)` :288); `BROWSER_SENTENCE_MAX_WAIT_MS` to `_endBrowserSentenceWait` :291-314; `_playNow` `_sentenceEndedAt = null` :599 and the A2 call :600-603; `playMs` :759; `_playPreparedSpeech` :790-899 (`browserWaitMs` :800, null path :801-807, D8 declarations :809-816, `error` listener :845-846, `playSettled = audio.play()` :879, refused fallback :887, `if (mediaError)` :891-893, catch :894-897, `await browserDone` :898); `_speakBrowserFallback` :941-1024 (signature :946-948, comment :949-951, no-engine `return Promise.resolve()` :978, `onstart` :991, `_ended` :998, `spoken` :1000, bound block :1011-1020, return :1023); `stopSpeaking` :1040 (`cancel()` :1047, A2 call :1049-1051).
- `voice.prefetch.bf918.test.tsx` (1141 lines): `rejectPlay` :58-64; `_voice` :168-172; `afterEach` :175-181; P19 :708-735 (A1 lines :719-726); V9 ends :901; V10 :903; V18 ends :1140; describe close :1141.
- `voice.pipelining.test.tsx`: honest-degrade A1 lines :215-223; `git diff 32997b18 08a88fd0` of this file shows only the `_flush` and the two lookahead hunks.
- `git diff 32997b18 1d9d5c48 -- ui/src/audio/voice.ts`: the base text each A3 REPLACE restores (null path, `audio.play().then`, both unawaited fallbacks, `error` listener, `): void {`, `return;`, the base `_fireBrowserEnd`).
- `PROGRESS.md`:3 and `DECISIONS.md`:13-21 (D5 :20) as quoted in A3.18 and A3.19.

#### Absence Verified (2026-11-27)

- CLAIM: the D8 names occur only in `voice.ts` and `voice.prefetch.bf918.test.tsx`. RUN: Grep `BROWSER_SENTENCE_MAX_WAIT_MS|_settleBrowserSentence|_endBrowserSentenceWait|browserWaitMs|browserDone|playSettled|mediaError|maxWaitMs|_resolveSpoken|\brejectPlay` over `ui/src` (count). FOUND: `voice.ts` 31, `voice.prefetch.bf918.test.tsx` 11 (V12, V13, V14 x2, V15-V18, and `rejectPlay`'s definition and V13's call). HOLDS.
- CLAIM: no kept test uses `rejectPlay` or `BROWSER_SENTENCE_MAX_WAIT_MS`. RUN: the same Grep, read against `git diff 32997b18 1d9d5c48` of the test file. FOUND: every hit lies in V12-V18 or the `rejectPlay` definition. HOLDS.

### 18.11 Text to file

**Follow-up issue checklist item** (the wave's consolidated follow-up, or its own issue under the filing policy; this is #1869):

```text
- [ ] Browser-fallback overlap (BF-918 R3), redesign. When a sentence's synthesis or playback fails, the browser speaks it and the next server sentence can start over it (base behaviour; BF-930 left it as is). BF-930's attempt (D8: await the browser utterance, bounded at 20 s from speak(), emulating its 'end') was withdrawn at the round-three brake (#1668, contract prompts/bf-930-spoken-reply-pause-fix.md sections 16-18). The design must own the utterance's lifecycle rather than emulate an end the engine has not reported: start the bound at onstart, with a separate short bound for starting; at the bound, call speechSynthesis.cancel() so the end is real and no late event can follow (trade-off: a sentence that speaks past the bound is cut off). Test with a fake engine that models the queue (late start, late end, cancel). Cases that must pass, from D8's measured failures: (1) R3-1: an utterance whose start comes after its bounded end must not re-lock PTT (real Chromium 148: bounded end 41.3 s, native start 50.1 s, gate still locked at 54.7 s); (2) that utterance must not play out loud with no start/end, leaving PTT and wake word open while the agent speaks; (3) utterances queued behind an over-long one must not pile up and play after the reply's final end; (4) round 2's cases: a media 'error' before the play() rejection, consecutive bounds against the arbiter's 45 s, a stop or a newer dispatch when the end is lost, a test-seam teardown.
- [ ] Last-sentence media failure while another entry is queued (base behaviour, BF-930 contract 17.6): the 'error' fires the final 'end', the arbiter hands over, and the play() rejection then speaks nothing, so the sentence is skipped. Fixing it means deferring a server 'end' until play() settles, which changes the BF-655 start/end contract.
```

The wave's consolidated follow-up must hold, for BF-930: the R3 redesign above (with D8's measured failures and corners (2) and (3)), and the last-sentence limit. The round-3 size finding R3-3 (an abandoned promise in `_speakBrowserFallback`) is moot, because D8 is gone; record it as moot, not as an item.

**#1668 decision comment:**

```text
Round-three brake, 2026-11-27: split (Architect). D8, the browser-fallback wait added in A1/A2, is withdrawn. Its findings F1-F4, R3-1 and R3-3 are removed together with the code, not deferred. M1-a is the pre-existing BF-918 R3 overlap (base P19 says "R3, unchanged"), not a regression; it is filed as follow-up #1869 with a design where the play half owns the utterance's lifecycle. S1, D9, S2 and the claim fixes, including R3-2, land after one review of the reduced candidate (contract section 18, A3). Reason: D8 pretended to report end events for an engine it does not own, and every round found a new collision. Build and review so far: about 208 min, of which 96 were review. Any finding from that one review round needs a new decision.
```

### 18.12 Commit subjects

- Contract (this amendment, committed before the Builder starts): `Contract amendment withdraws the browser-sentence wait after the round-three brake`
- Repair (A3.1-A3.19 and the ledger files): `The reply queue speaks a failed sentence through the browser as before, and the bounded browser wait is withdrawn`

Neither carries an `AD-` or `BF-` token or the words close, fix or resolve. Bodies end `Refs #1668.` and the session's attribution lines.

### 18.13 What the one review will still see (known)

- **a. The overlap**, as base behaviour (R-a). A reviewer who classes it as ordinary reach is answered by the brake decision (18.1); it is filed, with D8's measured failures, as #1869.
- **b. The last-sentence skip** (R-c), base behaviour, filed.
- **c. History in the contract:** sections 16 and 17 and several rows of 3, 8.1, 8.3 and 13 still describe D8, each marked withdrawn or history. They are the audit trail, not the shipped text.
- **d. Possibly `voice.ts`'s `_playPreparedSpeech` docstring** ("`null` ... speaks it through the browser instead, as before"): it is the base's text and true again.
- Nothing new in S1, D9 or S2: P2 makes them byte-identical to the tree rounds 2 and 3 found clean.

### 18.14 After the split's review (head `b184d448`): one claim corrected, text only

The split's one review verified 18.8 P1-P4 and R-a, R-c, R-d, R-e, and found one P3 (ordinary, a false claim): R-b's "by at most about one synthesis" fails when consecutive sentences fail. Measured natively (Chromium 148, the real `voice.ts` and `voiceChunking.ts` of each revision, two consecutive failed preparations of 601-612 ms each): on the base the first browser sentence overlapped the following server audio for 1719 ms; on `b184d448` for 2905 ms, 1186 ms more, because lookahead 3 had already prepared both failed sentences and the following server sentence. (The short property check of the repair, same engine, base against `b184d448`: one failed preparation gave 509 ms more overlap, two gave 1202 ms more; the effect is smaller with one failure, not absent. The first measurement's "next server sentence started 1221 ms after the first browser sentence ended" was a mislabelled timing reference and is withdrawn.)

**Decision (Architect, 2026-11-27): restate the claim with no numerical cap, keeping the one measurement; the split's scope does not change.** Lookahead 3 stays: the overlap is the base's registered R3, the longer overlap arises only on the failure path (one or more failed sentences followed by a server one, most with several in a row: +509 ms for one failure and +1202 ms for two in the check's measurement), lookahead 3 is what covers the stall #1668 is about, and the overlap's redesign is #1869, whose S-R3 item gains this measurement as a case. No test is added: the effect needs a real engine's timing (the fake engine does not speak), and the claim no longer states a number for a test to pin.

**Re-review:** one short property check of the delta by the Diff Reviewer (text only: no code or test line changes), with two properties: (1) `git diff b184d448 <head>` touches only `DECISIONS.md` line 20 and this contract; (2) each new sentence holds against the measurement above and states no cap. If that check finds the restated sentence false, delete the overlap-length clause outright (option a: "lookahead 3 can lengthen the overlap") without another round.

**A3.20** `DECISIONS.md` (D5, the whole line; against `b184d448`). SEARCH:
```text
- *D5.* Known limit, not changed here: in the sentence queue a sentence the browser speaks in place of a server one (failed synthesis, refused playback, a media error, or a throw) is not awaited, so the next server sentence can start over it. This is BF-918's registered residual R3, the base behaviour; lookahead 3 can lengthen the overlap by about one synthesis at most. A bounded wait for that sentence was built and withdrawn before merge: it emulated an end the browser engine had not reported, and a late browser `start` then locked push-to-talk after the reply ended (review round 3). The redesign, a wait that owns the utterance's lifecycle, is #1869.
```
REPLACE:
```text
- *D5.* Known limit, not changed here: in the sentence queue a sentence the browser speaks in place of a server one (failed synthesis, refused playback, a media error, or a throw) is not awaited, so the next server sentence can start over it. This is BF-918's registered residual R3, the base behaviour. Lookahead 3 can lengthen the overlap, most when several sentences in a row fail, because the sentence after them is already prepared; in one measurement with two consecutive failures (Chromium 148) the overlap was 2.9 s against 1.7 s on the base. A bounded wait for that sentence was built and withdrawn before merge: it emulated an end the browser engine had not reported, and a late browser `start` then locked push-to-talk after the reply ended (review round 3). The redesign, a wait that owns the utterance's lifecycle, is #1869.
```

The pair A3.19 above is the record of what `b184d448` applied; A3.20 supersedes its overlap sentence. `PROGRESS.md` line 3 and section 12's issue text do not state the cap (they say "can be overlapped"), so they are unchanged. In this contract the cap is corrected in place in 17.1 (bracketed note), section 13 (the A3 bullet) and 18.9 R-b.

**#1869 S-R3, replacement sentence (the orchestrator edits the issue):** "Lookahead 3 (BF-930) can lengthen this overlap, most when several sentences in a row fail, because the sentence after them is already prepared: one measurement (Chromium 148, two consecutive failed preparations of about 0.6 s each) gave 2.9 s of overlap against 1.7 s on the base. The redesign must cover that case: one or more consecutive browser-fallback sentences followed by a server sentence (a second measurement on the same engine: +509 ms of overlap for one failure, +1202 ms for two)."

**Commit subject:** `The decision record states the browser-fallback overlap without a numerical cap` (body ends `Refs #1668.`).
