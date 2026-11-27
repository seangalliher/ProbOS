# BF-930 (#1668): a spoken reply no longer pauses mid-way when one sentence's synthesis or storage stalls

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27
**Status:** ready to build. **Owning issue:** #1668 (stays open: the live re-measurement is the Captain's). Commits and the PR say `Refs #1668.`, never a closing keyword.
**Base:** main `32997b18f3b12da4a58566b82b4a106193df56d5`; branch `fix/bf930-spoken-reply-stall-20261127` (worktree `D:\ProbOS-worktrees\speech-bf930`). **Number:** BF-930 is already allocated to #1668; this contract allocates no new AD or BF number.
**Line endings:** working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** Python 18 new in 2 new files; UI 8 new (6 in `voice.prefetch.bf918.test.tsx`, 2 in `voiceChunking.test.ts`), 5 changed in place (P1, P2, P14, and two in `voice.pipelining.test.tsx`), 0 removed.
**Scope (files):** `ui/src/audio/voiceChunking.ts`, `ui/src/audio/voice.ts`, three UI test files; `src/probos/cognitive/dreaming.py`, `src/probos/routers/avatars.py`, `src/probos/utils/loop_lag.py` (new), `src/probos/__main__.py`; two new Python test files; `PROGRESS.md`, `DECISIONS.md`, the regenerated ledger files. Nothing of BF-932 (#1670): `cognitive_agent.py`, `concurrency_manager.py`, `routers/agents.py`, `utils/step_timing.py`, `tests/test_bf932_reply_path_timing.py` are not touched. Nothing AD-738g owns: the backend gate (`voice.ts`:555, :567) and the `voice_name` resolution (`avatars.py`:250-262) are not touched.

## 1. Problem (premise table)

| Where | Evidence | Effect |
|---|---|---|
| `voice.ts`:261 `TTS_PREFETCH_LOOKAHEAD = 1`; `voiceChunking.ts`:99-115 (serial `ensure`, then `ensure(i+1..i+lookahead)` once item i is prepared) | sentence k+1 is requested only when sentence k starts to play | the only cushion at a boundary is the length of the sentence playing (2-5 s); a later sentence that takes longer is heard as a pause, bounded by `SPEECH_JOIN_TIMEOUT_MS` (`voice.ts`:25) |
| `avatars.py`:301 `await store.write(...)` before the route returns; :272-302 synthesis then store, then the route line :326-332 | live `probos.log.1`:64423 (2026-10-30 23:41:07): `synth_ms=164 store_ms=17618 total_ms=17782 audio_ms=3949` | one sentence arrived 17.8 s after its request, longer than any buffer of a few sentences |
| the same window, `probos.log.1`:64421-64422 | 23:40:49 then 23:41:07 from `probos.perception.consumer` (about 1 line/s normally), no line from any logger between them | the event loop itself was blocked; a store-lock convoy alone would not silence every logger |
| orchestrator's probes over `probos.log.1` (411 route lines) | `total_ms` 3-6 s: 22 of 23 windows at least 70% log-silent vs 16.4% of 4,000 matched random windows; 1.5-3 s: 7 of 11 vs 21.9%; dream lines within 20 s of 9 of 26 lines with `total_ms` >= 3 s vs 17.9% of matched windows | the large stalls are vessel-wide loop blocks; dreaming is a real contributor and a minority of the cause |
| `dreaming.py`:3184-3186 `record_activity`; callers `runtime.py`:5837, :6230 only (Absence Verified) | a spoken conversation (DM, meeting, TTS) calls neither | the idle clock runs during an interview: with the Captain's `config/system.yaml`:221-222 (`idle_threshold_seconds: 300.0`, `dream_interval_seconds: 600.0`) the monitor (`dreaming.py`:3333-3349) starts a full dream 5 minutes into a spoken conversation |
| `rg -i "loop_lag|loop lag|event.loop.(lag|block|stall)|slow_callback_duration|set_debug\(|_current_frames" src` (Absence Verified) | one docstring, `novelty_gate.py`:65 | no probe names the code that blocks the loop; the numbers that would choose a store fix do not exist |
| attachments index (orchestrator, metadata only) | `.index.json` 217.4 KB, last write 2026-11-24; about 165-180 bytes per entry (`filesystem_store.py`:243-257, :361-369), so about 1.2-1.4 K entries against 11,952 files | the consult's "12 K stale entries, O(n^2) at boot" hazard is withdrawn; the live `index_entries=` field of `BF-930: attachment write slow` (`filesystem_store.py`:384-385) gives the exact count |
| live log since 2026-10-31 | no `BF-930:` line and no route line (the vessel last ran old code on 2026-11-24) | the slice-1 timing lines (`resident.py`:450, `filesystem_store.py`:384, :406) have never run live |

## 2. Overview

Three slices, all on by default, none needing a Captain decision:

- **S1, client buffer (M1).** The pipelined queue prepares up to three sentences ahead, and holds the first sentence until at least 3 s of audio is ready (or all lookahead items are ready). A stall of one sentence is hidden behind the audio already held. Backend-independent (Piper today, Kokoro in AD-738g).
- **S2, speech holds off the idle full dream (M2).** The TTS route records each accepted request on the dream scheduler through a new bounded method, so an idle full dream does not start during a spoken conversation; one stretch of speech can hold it off for at most `SPEECH_DREAM_DEFER_CAP_SECONDS` (2 h). The idle full dream logs its start and finish, so the Captain can see the dream state before recording.
- **S3, loop-lag probe (M3).** A daemon watchdog thread, started by the vessel's `_serve` beside its heartbeat, sends the loop a heartbeat each second; if the loop has not answered within 1 s it logs one rate-limited `BF-930: event loop blocked ...` WARNING with the lag and the loop thread's stack as `dir/file.py:function:line` frames (no locals). Log-only. Generic, so BF-932 can reuse `probos.utils.loop_lag`.

Rejected, one line each:
- **S4, write-behind of spoken audio (the consult's slice 2):** left out of this contract (D1). The log-silent windows show the loop blocked, which moving the store write does not fix; there is no `behind=` evidence of a lock convoy yet; it is the riskiest change (new module, three routes, task lifecycle).
- A separate store or lock domain for `tts_audio`; audio inline in the response: rejected in the consult (they break `filesystem_store.py`:473-475's one-instance rule or AD-731, `avatars.py`:289-290).
- Making lookahead or the start buffer config fields: D2.
- `record_activity()` unbounded from the route: continuous machine-driven speech (crew meetings through `useMeetingVoice.ts`:158) could starve the full dream for ever.
- asyncio debug mode (`slow_callback_duration`): global slowdown of the whole loop, and it names the callback, not the line it is stuck in.
- A dependency (pyleak, aiodebug, LoopSentry): about 100 lines of stdlib code do the job.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Slices S1, S2, S3 in this order, one PR; trackers last. The weekend floor is S1 + S2 (+ trackers). S3 rides in the same batch; if review finds a Critical or High defect in S3 that rounds 1-2 do not settle, S3 moves to a follow-up PR and S1 + S2 ship. S4 is not in this contract | S1 hides stalls up to the buffered audio (about 3 sentences, 10-14 s); S2 removes the one contributor we can name (dreams mid-conversation; a dream was running in the 17.8 s window, `probos.log.1`:64413 per the consult); S3 is log-only and produces the numbers that decide any store work. **S4 trigger:** after this ships, a live window where a route line has `store_ms` >= 1000, its `BF-930: attachment write slow` line shows `behind=` > 0 or `lock_wait_ms` >= 500, and no `BF-930: event loop blocked` line falls within 5 s of it. Then the consult's write-behind design (its section 2, slice 2) is drafted as its own slice |
| D2 | `TTS_PREFETCH_LOOKAHEAD = 3` and `TTS_START_BUFFER_MS = 3000` hold for Kokoro on CPU (0.5-1.5 s per sentence) and stay module constants in `voice.ts` | a sentence of 2-5 s audio synthesized in at most 1.5 s keeps the queue ahead (real-time factor <= 0.75), and three ahead accumulates 6-15 s of cushion; a short first sentence waits at most one more synthesis (<= 1.5 s). A config field would have to cross the wire (`/api/avatars/tts/status`) into the browser, widening a contract with no measured need; the live check's `bf918:sentence-gap` measure is the evidence that would reopen it |
| D3 | S2's bound: a "stretch" begins at the first spoken reply after the last full dream; while the stretch is younger than `SPEECH_DREAM_DEFER_CAP_SECONDS = 7200.0`, each reply resets the idle clock; once older, speech no longer writes the clock, so the full dream starts at most `idle_threshold_seconds` later; the reply after that dream begins a new stretch | by construction: past the cap, `record_speech_activity` never writes `_last_activity_time`, so nothing speech does can stop the monitor's predicate (`dreaming.py`:3336-3339) from becoming true. Two hours covers a recording session; micro dreams (every 10 s, unconditional, :3292) are unaffected. A module constant, not config: it is a safety bound, and the operator's lever stays `idle_threshold_seconds` |
| D4 | S2's call sits in the route after validation and before synthesis; a runtime without a scheduler (`getattr(runtime, "dream_scheduler", None)`, the same style as `voice_synthesis` at :271) skips it | every accepted request is activity, including one whose synthesis stalls or degrades; the stand-in runtimes of the existing route tests have no scheduler |
| D5 | S3 lives in `src/probos/utils/loop_lag.py`, started in `__main__._serve` after the heartbeat task and stopped first in its `finally`; `stop()` never joins (it is called on the loop thread, and a join could wait on a check that waits on the loop) | `_serve` is the live vessel's only path; booted tests never run it, so no booted test gains a thread or a WARNING. The thread is a daemon; a stopped probe never logs |
| D6 | S3 thresholds: heartbeat every 1.0 s, blocked at 1.0 s, report wait 30 s, at most one report per 30 s with a `suppressed=` count, the 25 innermost frames | a 1 s block is audible; a report per 30 s caps the log at 120 lines/h (about 2 KB each) under a pathological loop while `suppressed=` keeps the frequency; 25 frames reach from the blocking line out through the dream step that called it |
| D7 | The S1 buffer counts a sentence of unknown duration (0 or missing) or a failed prepare (`null`) as a full 3000 ms | both then start exactly as today; only a known-short first sentence waits |

## 4. Milestones and commits

Commit each milestone separately, explicit paths only. No subject carries an `AD-` or `BF-` token or the words close, fix or resolve.

| M | Pairs | Commit subject |
|---|---|---|
| M1 | 6.1-6.5 | `Spoken replies buffer three sentences ahead and hold a short first sentence until the next is ready` |
| M2 | 6.6-6.8 | `A spoken reply holds off the idle full dream for up to two hours, and the idle dream logs its start and finish` |
| M3 | 6.9-6.11 | `The vessel logs a blocked event loop with the loop thread's stack` |
| M4 | 6.12-6.13, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change | `Trackers record the spoken-reply buffer, the speech dream guard and the loop-lag probe` |

Each body ends `Refs #1668.` and the attribution lines of the session.

## 5. Builder: may and may not

- **May:** apply the pairs in order, create the three new files, run `gen_ad_ledger.py`, `git diff --check`, `git diff --stat`.
- **May not:** run tests, commit, edit an unnamed file (never `config/system.yaml`), add `skip` or a retry, reword an anchor, or touch `voice.ts`:548-570 or `avatars.py`:250-262. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

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

### 6.9 `src/probos/utils/loop_lag.py` (new file)

```python
"""BF-930 (#1668): a log-only watchdog for a blocked asyncio event loop.

A daemon thread sends the loop a heartbeat (``call_soon_threadsafe``) every
``interval_s``. When the loop has not run it within ``threshold_s`` the loop is
blocked: the probe takes the loop thread's stack at that moment, waits up to
``report_wait_s`` for the heartbeat, and logs one WARNING::

    BF-930: event loop blocked lag_ms=<n> still_blocked=<0|1> suppressed=<n> stack=<frames>

``stack`` is the loop thread's innermost frames, outermost first, each
``dir/file.py:function:line``: code locations only, never locals, arguments or
values. At most one report per ``report_every_s``; ``suppressed`` counts the
reports held back since the last one. The probe changes nothing it observes.
Generic: any owner of a running loop may start one (BF-932 may reuse it).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

#: How often the watchdog thread sends the loop a heartbeat.
LOOP_LAG_INTERVAL_S = 1.0
#: A loop that has not run the heartbeat after this long is blocked.
LOOP_LAG_THRESHOLD_S = 1.0
#: How long one report waits for a blocked loop to answer before it logs it as still blocked.
LOOP_LAG_REPORT_WAIT_S = 30.0
#: At most one report per this many seconds; the ones in between are counted.
LOOP_LAG_REPORT_EVERY_S = 30.0
#: The innermost frames a report carries.
LOOP_LAG_MAX_FRAMES = 25


def thread_stack(thread_id: int, max_frames: int = LOOP_LAG_MAX_FRAMES) -> list[str]:
    """The ``max_frames`` innermost frames of one thread, outermost first, as ``dir/file.py:function:line``.

    Only code locations: no locals, arguments or values. Empty when the thread is gone.
    """
    frame = sys._current_frames().get(thread_id)
    frames: list[str] = []
    while frame is not None:
        code = frame.f_code
        directory, name = os.path.split(code.co_filename)
        frames.append(f"{os.path.basename(directory)}/{name}:{code.co_name}:{frame.f_lineno}")
        frame = frame.f_back
    frames.reverse()
    return frames[-max_frames:]


class LoopLagProbe:
    """Watches one event loop from a daemon thread and logs when it is blocked (log only)."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        loop_thread_id: int,
        interval_s: float = LOOP_LAG_INTERVAL_S,
        threshold_s: float = LOOP_LAG_THRESHOLD_S,
        report_wait_s: float = LOOP_LAG_REPORT_WAIT_S,
        report_every_s: float = LOOP_LAG_REPORT_EVERY_S,
        clock: Callable[[], float] = time.monotonic,
        stack: Callable[[int], list[str]] = thread_stack,
    ) -> None:
        self._loop = loop
        self._loop_thread_id = loop_thread_id
        self._interval_s = interval_s
        self._threshold_s = threshold_s
        self._report_wait_s = report_wait_s
        self._report_every_s = report_every_s
        self._clock = clock
        self._stack = stack
        self._last_report: float | None = None
        self._suppressed = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def for_running_loop(cls, **kwargs: object) -> LoopLagProbe:
        """A probe for the loop running in the calling thread. Call it from a coroutine."""
        return cls(asyncio.get_running_loop(), loop_thread_id=threading.get_ident(), **kwargs)  # type: ignore[arg-type]

    def start(self) -> None:
        """Start the watchdog thread (a daemon). A second call does nothing."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="probos-loop-lag", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread to end. Never blocks: it may be called on the loop thread, whose
        block a join could wait on. The thread ends at its next wait and logs nothing more."""
        self._stop.set()
        self._thread = None

    def check_once(self) -> float | None:
        """One heartbeat. Returns the lag in ms when the loop was blocked past the threshold,
        else None. Must not run on the loop's own thread (it would wait on itself)."""
        if threading.get_ident() == self._loop_thread_id:
            raise RuntimeError("LoopLagProbe.check_once must not run on the loop thread")
        answered = threading.Event()
        sent = self._clock()
        try:
            self._loop.call_soon_threadsafe(answered.set)
        except RuntimeError:  # the loop is closed: nothing left to watch
            self._stop.set()
            return None
        if answered.wait(self._threshold_s):
            return None
        frames = self._stack(self._loop_thread_id)
        still_blocked = not answered.wait(self._report_wait_s)
        ended = self._clock()
        if self._stop.is_set():
            return None
        lag_ms = (ended - sent) * 1000.0
        self._report(lag_ms, still_blocked, frames, ended)
        return lag_ms

    def _report(self, lag_ms: float, still_blocked: bool, frames: list[str], at: float) -> None:
        if self._last_report is not None and at - self._last_report < self._report_every_s:
            self._suppressed += 1
            return
        logger.warning(
            "BF-930: event loop blocked lag_ms=%.0f still_blocked=%d suppressed=%d stack=%s",
            lag_ms, int(still_blocked), self._suppressed, " > ".join(frames) or "-",
        )
        self._last_report = at
        self._suppressed = 0

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            try:
                self.check_once()
            except Exception:  # log-and-degrade: the probe must never take the vessel down
                logger.warning("BF-930: loop lag probe check failed", exc_info=True)
```

### 6.10 `src/probos/__main__.py`

**P24.** SEARCH:
```python
    heartbeat_task = asyncio.create_task(_heartbeat_loop(), name="serve-heartbeat")

    try:
        if interactive:
```
REPLACE:
```python
    heartbeat_task = asyncio.create_task(_heartbeat_loop(), name="serve-heartbeat")
    # BF-930 (#1668): a log-only watchdog for a blocked event loop; each report carries the
    # loop thread's stack as file:function:line frames. Stopped first in the finally below.
    from probos.utils.loop_lag import LoopLagProbe
    loop_lag_probe = LoopLagProbe.for_running_loop()
    loop_lag_probe.start()

    try:
        if interactive:
```

**P25.** SEARCH:
```python
        # Cancel heartbeat first so we stop emitting "alive" once shutdown begins.
        heartbeat_task.cancel()
```
REPLACE:
```python
        # BF-930: shutdown work may block the loop by design; stop the watchdog before it.
        loop_lag_probe.stop()
        # Cancel heartbeat first so we stop emitting "alive" once shutdown begins.
        heartbeat_task.cancel()
```

### 6.11 `tests/test_bf930_loop_lag_probe.py` (new file)

```python
"""BF-930 (#1668) M3: the loop-lag probe logs a blocked event loop with the loop thread's stack.

A real event loop runs in its own thread and is held by a callback that waits on a
``threading.Event``; only the probe's clock is injected. No assertion is on a duration
of wall time: each timeout is a liveness bound, or a wait that cannot end early because
the test holds the loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from probos.utils.loop_lag import LoopLagProbe, thread_stack

_LOGGER = "probos.utils.loop_lag"
_SENTINEL = "bf930-local-value-never-logged"
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"


class _Clock:
    def __init__(self, *values: float) -> None:
        self._values = list(values)

    def __call__(self) -> float:
        return self._values.pop(0)

    @property
    def unused(self) -> list[float]:
        return list(self._values)


def _blocking_callback(entered: threading.Event, release: threading.Event) -> None:
    secret = _SENTINEL  # a local the report must not carry
    entered.set()
    release.wait()
    del secret


@pytest.fixture
def held_loop() -> Iterator[tuple[asyncio.AbstractEventLoop, int, threading.Event]]:
    loop = asyncio.new_event_loop()
    started = threading.Event()
    idents: list[int] = []

    def _run() -> None:
        asyncio.set_event_loop(loop)
        idents.append(threading.get_ident())
        started.set()
        loop.run_forever()

    thread = threading.Thread(target=_run, name="bf930-test-loop", daemon=True)
    thread.start()
    assert started.wait(30)  # liveness only
    release = threading.Event()
    try:
        yield loop, idents[0], release
    finally:
        release.set()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(30)
        loop.close()


def _hold(loop: asyncio.AbstractEventLoop, release: threading.Event) -> None:
    entered = threading.Event()
    loop.call_soon_threadsafe(_blocking_callback, entered, release)
    assert entered.wait(30)  # liveness only


def _reports(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]


def test_a_blocked_loop_is_reported_with_the_loop_threads_stack_and_no_values(held_loop, caplog) -> None:
    loop, loop_thread, release = held_loop
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    clock = _Clock(100.0, 103.5)
    probe = LoopLagProbe(loop, loop_thread_id=loop_thread, threshold_s=0.01, report_wait_s=0.01, clock=clock)
    _hold(loop, release)

    assert probe.check_once() == pytest.approx(3500.0)

    (line,) = _reports(caplog)
    assert line.startswith("BF-930: event loop blocked lag_ms=3500 still_blocked=1 suppressed=0 stack=")
    frames = line.split("stack=", 1)[1].split(" > ")
    names = [frame.rsplit(":", 2)[1] for frame in frames]
    assert any(f.startswith("tests/test_bf930_loop_lag_probe.py:_blocking_callback:") for f in frames)
    assert names.index("_blocking_callback") < names.index("wait")  # outermost first: the wait it is stuck in is inner
    assert _SENTINEL not in line
    assert clock.unused == []


def test_a_loop_that_answers_during_the_report_is_logged_with_its_whole_lag(held_loop, caplog) -> None:
    loop, loop_thread, release = held_loop
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    def _stack_then_release(thread_id: int) -> list[str]:
        frames = thread_stack(thread_id)
        release.set()
        return frames

    probe = LoopLagProbe(
        loop, loop_thread_id=loop_thread, threshold_s=0.01, report_wait_s=30.0,  # 30 s: liveness only
        clock=_Clock(10.0, 12.25), stack=_stack_then_release,
    )
    _hold(loop, release)

    assert probe.check_once() == pytest.approx(2250.0)

    (line,) = _reports(caplog)
    assert "lag_ms=2250 still_blocked=0 suppressed=0 " in line
    assert ":_blocking_callback:" in line


def test_a_loop_that_answers_in_time_logs_nothing(held_loop, caplog) -> None:
    loop, loop_thread, _release = held_loop
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    clock = _Clock(5.0)
    probe = LoopLagProbe(loop, loop_thread_id=loop_thread, threshold_s=30.0, clock=clock)  # 30 s: liveness only

    assert probe.check_once() is None
    assert _reports(caplog) == []
    assert clock.unused == []


def test_reports_are_rate_limited_and_count_what_they_held_back(held_loop, caplog) -> None:
    loop, loop_thread, release = held_loop
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    probe = LoopLagProbe(
        loop, loop_thread_id=loop_thread, threshold_s=0.01, report_wait_s=0.01, report_every_s=30.0,
        clock=_Clock(0.0, 2.0, 5.0, 7.0, 40.0, 42.0),
    )
    _hold(loop, release)

    for _ in range(3):
        assert probe.check_once() == pytest.approx(2000.0)

    lines = _reports(caplog)
    assert len(lines) == 2
    assert "suppressed=0" in lines[0]
    assert "suppressed=1" in lines[1]


def test_thread_stack_keeps_the_innermost_frames(held_loop) -> None:
    loop, loop_thread, release = held_loop
    _hold(loop, release)
    whole = thread_stack(loop_thread, max_frames=1000)
    assert len(whole) > 2
    assert thread_stack(loop_thread, max_frames=2) == whole[-2:]


def test_a_stopped_probe_does_not_report(held_loop, caplog) -> None:
    loop, loop_thread, release = held_loop
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    probe = LoopLagProbe(loop, loop_thread_id=loop_thread, threshold_s=0.01, report_wait_s=0.01, clock=_Clock(0.0, 9.0))
    _hold(loop, release)
    probe.stop()

    assert probe.check_once() is None
    assert _reports(caplog) == []


def test_a_closed_loop_ends_the_check_without_a_report(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    loop = asyncio.new_event_loop()
    loop.close()
    probe = LoopLagProbe(loop, loop_thread_id=-1, threshold_s=0.01)
    assert probe.check_once() is None
    assert _reports(caplog) == []


def test_start_runs_one_daemon_thread_and_stop_ends_it(held_loop) -> None:
    loop, loop_thread, _release = held_loop
    before = {t for t in threading.enumerate() if t.name == "probos-loop-lag"}
    probe = LoopLagProbe(loop, loop_thread_id=loop_thread, interval_s=0.01, threshold_s=30.0)
    probe.start()
    probe.start()
    mine = [t for t in threading.enumerate() if t.name == "probos-loop-lag" and t not in before]
    assert len(mine) == 1
    assert mine[0].daemon
    probe.stop()
    mine[0].join(30)  # liveness only
    assert not mine[0].is_alive()


@pytest.mark.asyncio
async def test_for_running_loop_binds_the_running_loop_and_refuses_a_check_on_it() -> None:
    probe = LoopLagProbe.for_running_loop(threshold_s=30.0)  # 30 s: liveness only
    with pytest.raises(RuntimeError):
        probe.check_once()  # on the loop thread it would wait on itself
    assert await asyncio.to_thread(probe.check_once) is None  # from a worker thread, the running loop answers


# The real ``_serve`` in a separate process (it ends in ``os._exit``), with its runtime, web server
# and browser replaced, as ``tests/test_ad1341_s1_reset_and_erase.py``'s vessel does.
_VESSEL = '''
import asyncio
import sys
import webbrowser
from pathlib import Path

import uvicorn

import probos.api
from probos import __main__ as cli
from probos.config import SystemConfig
from probos.utils import loop_lag

data_dir, signals = Path(sys.argv[1]), Path(sys.argv[2])
_start, _stop = loop_lag.LoopLagProbe.start, loop_lag.LoopLagProbe.stop


def _recorded_start(self):
    (signals / "started").write_text("1", encoding="utf-8")
    _start(self)


def _recorded_stop(self):
    (signals / "stopped").write_text("1", encoding="utf-8")
    _stop(self)


loop_lag.LoopLagProbe.start = _recorded_start
loop_lag.LoopLagProbe.stop = _recorded_stop


class _Runtime:
    async def stop(self):
        return None


class _Server:
    def __init__(self, config):
        self.should_exit = False

    async def serve(self):
        return None


async def _boot(config_path, fresh, data_dir_arg, console, verbose=False):
    return _Runtime(), SystemConfig(), console


cli._boot_runtime = _boot
probos.api.create_app = lambda runtime: None
uvicorn.Config = lambda *args, **kwargs: None
uvicorn.Server = _Server
webbrowser.open = lambda *args, **kwargs: True
asyncio.run(cli._serve(data_dir=data_dir))
sys.exit(9)  # not reached: _serve ends in os._exit
'''


def test_the_vessel_starts_the_probe_and_stops_it_on_shutdown(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    signals = tmp_path / "signals"
    signals.mkdir()
    script = tmp_path / "vessel.py"
    script.write_text(_VESSEL, encoding="utf-8")
    env = {
        **os.environ, "PYTHONPATH": str(_SRC_DIR), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "COLUMNS": "200", "PROBOS_SKIP_EPISODIC_HEALTH_CHECK": "1",
    }
    done = subprocess.run(
        [sys.executable, str(script), str(data_dir), str(signals)],
        env=env, capture_output=True, timeout=300,  # liveness only
    )
    assert done.returncode == 0, (done.stdout[-2000:], done.stderr[-2000:])
    assert (signals / "started").exists()
    assert (signals / "stopped").exists()
```

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
| `TTS_PREFETCH_LOOKAHEAD` | the pipelined path only (`status.sentence_pipelining_enabled`, `voice.ts`:579); pipelined UI tests exist only in `voice.prefetch.bf918.test.tsx` and `voice.pipelining.test.tsx` (Absence Verified) | P1, P2, P14 and two pipelining tests changed in place; P3, P6, P8, P9, P15-P20 hold (two-sentence replies, holds, or post-hoc assertions) |
| `PreparedSpeech` | built only at `voice.ts`:692 | gains `durationMs` |
| `ProfileChatTab.bf918.test.tsx` M6/M7 (:533-680) | pipelined two-sentence replies with no `duration_ms` | unknown duration: start at once; lookahead irrelevant for two sentences |
| TTS route | `test_bf918_tts_latency.py`, `test_bf930_voice_path_timing.py`, `test_ad738_piper_tts.py`, `test_ad738e_1_per_emotion_prosody.py`, `test_bf291_piper_voice_catalog.py`, `test_ad721b1_rhubarb_backend.py`, `test_ad721e_animation_manifest.py`, `test_ad1071_tts_pipelining.py`, `test_bf918_tts_retention.py`, `test_bf918_attachment_io.py` | their stand-in runtimes have no `dream_scheduler` (SimpleNamespace) or a MagicMock one: skipped or a no-op call |
| `DreamScheduler` | `runtime.py`:3286 (holds it), `test_dreaming.py` (:420, :448, :489-504, :619-627 set or read `_last_activity_time`), `test_bf1002_full_dream_complete_event.py` | one new field, one new method, two INFO lines; `record_activity` unchanged |
| `__main__._serve` | source scans `test_ad708e_mdns_discovery.py`:158 (`build_advertiser(`, `.stop()`), `test_bf207_shutdown_episodic_integrity.py`:309 (`runtime.stop(), timeout=10`, `adapter.stop(), timeout=5`); subprocess `test_ad1341_s1_reset_and_erase.py`:157, :886, :970 | strings unchanged; the subprocess vessels now also start and stop the probe |
| live log readers | the Captain's live check (section 12) | three new line kinds, all prefixed `BF-930:` |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts
- Each SEARCH of section 6 counted at its turn: 1 each; the three new files do not exist.
- A/B on main (the new tests and the changed UI tests on the base without the source pairs):
  - UI: V1 (played before release), V4 (`posted` has two), V5 (a `start:One.` event), Q7 (first `toEqual`), and the changed P1, P2, P14 and two pipelining tests fail on assertions; Q8 fails by vitest's test timeout (on main `a` plays and its `play` never ends). V2, V3, V6 pass on both trees (preservation).
  - Python: `test_a_spoken_reply_keeps_a_due_idle_full_dream_from_starting` fails on main at `await_count == 0` (the route does not touch the scheduler) once the import of `SPEECH_DREAM_DEFER_CAP_SECONDS` is satisfied; record the rest of that file and all of `test_bf930_loop_lag_probe.py` as new-API cases (they fail on import on main), not as A/B evidence. The control test passes on both trees apart from its log-line asserts.

### 8.2 Focused checks on the candidate
```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf930_speech_defers_idle_dream.py tests/test_bf930_loop_lag_probe.py tests/test_dreaming.py tests/test_bf1002_full_dream_complete_event.py tests/test_bf918_tts_latency.py tests/test_bf930_voice_path_timing.py tests/test_ad738_piper_tts.py tests/test_ad738e_1_per_emotion_prosody.py tests/test_bf291_piper_voice_catalog.py tests/test_ad721b1_rhubarb_backend.py tests/test_ad721e_animation_manifest.py tests/test_ad1071_tts_pipelining.py tests/test_bf918_tts_retention.py tests/test_bf918_attachment_io.py tests/test_ad708e_mdns_discovery.py tests/test_bf207_shutdown_episodic_integrity.py tests/test_ad1341_s1_reset_and_erase.py -n 0 -q
rg -l -g 'test_*.py' -e 'rglob\("\*\.py"\)' -e 'os\.walk\(' -e 'cognitive\.dreaming' -e 'DreamScheduler' -e 'probos\.__main__' -e 'probos\.utils' tests
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
| U4 | voice.ts: `held += prepared !== null && prepared.durationMs > 0 ? prepared.durationMs : TTS_START_BUFFER_MS;` | `held += prepared !== null ? prepared.durationMs : TTS_START_BUFFER_MS;` | V3 |
| U5 | the same line | `held += prepared !== null && prepared.durationMs > 0 ? prepared.durationMs : 0;` | V3, V6 |
| U6 | voice.ts: `? data.duration_ms` | `? 0` | V1 |
| U7 | voice.ts: `_startBufferFilled,` | (line deleted) | V1, V5 |
| D1 | avatars.py: `dream_scheduler.record_speech_activity()` | `pass` | spoken-reply chain test |
| D2 | avatars.py: same line | `dream_scheduler.record_activity()` | route cap test |
| D3 | dreaming.py: `if at - self._speech_since >= SPEECH_DREAM_DEFER_CAP_SECONDS:` | `if False:` | cap unit test, first-reply test, route cap test |
| D4 | dreaming.py: `if self._speech_since is None or self._last_dream_time > self._speech_since:` | `if self._speech_since is None:` | new-stretch test |
| D5 | dreaming.py: `logger.info("BF-930: idle full dream starting idle_s=%.0f", idle_time)` | (line deleted) | control test |
| L1 | loop_lag.py: `still_blocked = not answered.wait(self._report_wait_s)` | `still_blocked = False` | blocked-report test |
| L2 | loop_lag.py: `if self._last_report is not None and at - self._last_report < self._report_every_s:` | `if False:` | rate-limit test |
| L3 | loop_lag.py: `frames.reverse()` | (line deleted) | blocked-report test (order; the innermost-frames test compares two unreversed lists and does not kill it) |
| L4 | loop_lag.py: `return frames[-max_frames:]` | `return frames[:max_frames]` | innermost-frames test |
| L5 | loop_lag.py: `frames.append(f"{os.path.basename(directory)}/{name}:{code.co_name}:{frame.f_lineno}")` | the same f-string with `:{frame.f_locals}` appended | blocked-report test (sentinel) |
| L6 | loop_lag.py: `if self._stop.is_set():` | `if False:` | stopped-probe test |
| L7 | __main__.py: `loop_lag_probe.start()` | (line deleted) | vessel subprocess test |
| L8 | __main__.py: `loop_lag_probe.stop()` | (line deleted) | vessel subprocess test |

### 8.4 The gate
`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-930-speech --receipt logs/gates/bf-930-speech.receipt.json` once on the committed head, after merging the base. The gate lock is shared with the main orchestrator: queue behind its gate, never run two at once.

## 9. Diff Reviewer: properties to verify

The change claims that a spoken reply's later sentences are synthesized up to three ahead and a short first sentence waits for the next, that a spoken request keeps an idle full dream from starting for at most two hours of continuous speech, and that the vessel logs a blocked loop with its stack. Consumers that must accept it: the HXI voice path (`speakResponse` through `runPrefetchQueue`), the dream monitor loop, and the operator reading `probos.log`.
1. With the default `startWhen`, `runPrefetchQueue` behaves byte-for-byte as before (Q1-Q6 unchanged); with `startWhen`, the first item starts after at most `lookahead` more preparations, and a stop during the wait plays nothing and discards each prepared item exactly once.
2. A sentence whose duration is unknown, or whose preparation failed, never delays the first audio.
3. `voice.ts`:548-570 (the backend gate) and `avatars.py`:250-262 (`voice_name`) are byte-identical to the base.
4. `record_speech_activity` cannot write `_last_activity_time` once its stretch is at or past the cap, so speech alone cannot keep the monitor's full-dream predicate false; a full dream completed after the stretch began starts a new stretch; `record_activity` is unchanged.
5. The route records activity once per accepted request, after validation and before synthesis, and a runtime without a scheduler is unaffected.
6. The probe never runs code on the loop except `threading.Event.set`, never logs locals, arguments or values, logs at most once per `report_every_s`, logs nothing after `stop()`, and its thread is a daemon; `stop()` never blocks.
7. The probe starts only in `__main__._serve` and is stopped in its `finally` before the heartbeat is cancelled; no booted-runtime path starts it.
8. Each changed UI test keeps every assertion it had, changed only where lookahead 3 changes the value, with the reason inline; nothing is deleted or skipped.
9. No file of BF-932 changes; ASCII and LF in the new text; no file outside the scope line changes; `config/system.yaml` is untouched.
10. Each absolute word of the new text (each, every, no, only, never, none) holds against sections 1 and 7 and the Absence Verified list.

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

### Absence Verified (2026-11-27)

- CLAIM: only `process_natural_language` and `decompose_only` reset the dream idle clock. RUN: Grep `record_activity|_last_activity_time` over `src` and `tests`. FOUND in `src`: `runtime.py`:5837, :6230 (dream scheduler), :4522, :4744 (emergent detector, a different clock); `dreaming.py`:3161, :3184-3193, :3333. HOLDS.
- CLAIM: no loop-lag monitor exists. RUN: Grep `-i "loop_lag|loop lag|event.loop.(lag|block|stall)|slow_callback_duration|set_debug\(|_current_frames"` over `src`. FOUND: `novelty_gate.py`:65 (a docstring). HOLDS.
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
- Dream step 7g's pairwise Jaccard (`dreaming.py`:1079-1088): a suspect only; the probe's stacks decide.
- Any config field or default; `config/system.yaml`.

## 12. Issue text (#1668, on merge) and the Captain's live check

Wave comment:

```text
BF-930 shipped in PR #<PR> (contract prompts/bf-930-spoken-reply-pause-fix.md). Refs #1668; the issue stays open for the live re-measurement.
- Client buffer: the sentence queue synthesizes up to three sentences ahead (was one) and holds a first sentence shorter than 3 s of audio until the next is ready, so one stalled sentence is covered by the audio already held. Unknown durations and failed syntheses start as before.
- Dream guard: each TTS request counts as activity for the idle full dream, so a dream does not start during a spoken conversation; one stretch of speech holds it off for at most 2 h. The idle dream now logs "BF-930: idle full dream starting/finished".
- Loop-lag probe: the vessel logs "BF-930: event loop blocked lag_ms=... stack=..." when the loop does not answer within 1 s (at most once per 30 s, code locations only).
- Not built: write-behind of spoken audio. The 2026-10-30 stalls silenced every logger (a blocked loop). It is drafted only if a live window shows a store stall with behind>0 or lock_wait_ms>=500 and no loop-block line within 5 s.
- Corrected premise: the attachments index is about 1.2-1.4 K entries (217 KB), not 12 K; no boot-time reaper hazard.
```

The Captain's actions after the merge: update `D:\ProbOS` to main; `cd ui; npm run build`; restart the vessel; hard-reload the HXI (Ctrl+Shift+R). Before recording, let the vessel run a few minutes and check line 1.

Live check (PowerShell; `$L = "$env:LOCALAPPDATA\ProbOS\data\logs\probos.log"`):
1. `Select-String $L -Pattern 'BF-930: idle full dream (starting|finished)' | Select -Last 4` -- the last line should be `finished` (or none) before you start; `starting` with no `finished` after it means a dream is running: wait for `finished`.
2. `Select-String $L -Pattern 'BF-918: tts route' | Select -Last 30` -- `total_ms` per sentence.
3. `Select-String $L -Pattern 'BF-930: event loop blocked' | Select -Last 10` -- each line names the code that blocked the loop; paste them to #1668.
4. `Select-String $L -Pattern 'BF-930: (piper request slow|attachment write slow)' | Select -Last 10` -- where a slow sentence's time went (`resume_lag_ms`, `behind=`, `index_entries=`).
5. In the HXI devtools console: `performance.getEntriesByName('bf918:sentence-gap').map(m=>Math.round(m.duration))`.

**Pass:** over at least 20 spoken sentences with the camera on, no pause is heard in the middle of a reply, every sentence gap is under about 300 ms, and no `idle full dream starting` line falls between the interview's first and last route lines. Loop-block lines are evidence for the next slice, not a failure. **Operator note:** S2 covers only the idle dream; a dream already running, or one the Counselor forces, is not held off. For more margin the Captain may raise `dreaming.idle_threshold_seconds` in his own `config/system.yaml` (today 300.0) to, say, 1800.0 for the session; it is his file and no build step touches it.

PR title: `Spoken replies hold three sentences ahead, hold off the idle dream, and the vessel logs what blocks its loop`.

## 13. Prior art and blind spots

- Internal: BF-918 (#1626; the queue, deferred visemes, the route line), BF-930 slice 1 (the timing lines), AD-1071 (sentence pipelining), AD-731 (audio by sha only), BF-1002 (the full-dream emit sites this file now sits beside), the consult of 2026-11-27 (its slice 1 kept, slice 2 deferred, its boot hazard withdrawn).
- External (date used 2026-11-27; one search; `docs/research/reference-projects.md` not examined: no row is about loop monitoring or audio buffering):
  - Watchdog thread plus heartbeat plus `sys._current_frames` ([thehesiod gist](https://gist.github.com/thehesiod/0d2beed27c800e4f7286be6c3cd17a09), [imayhaveborkedit gist](https://gist.github.com/imayhaveborkedit/97ccc3fd654873b7b0c1540c94b5a069), [Hassette blocking detection](https://hassette.readthedocs.io/en/stable/pages/core-concepts/blocking-io-detection/)): adopted; it names the line, where a latency probe alone ([Mergify](https://mergify.com/blog/detecting-blocking-tasks-in-asyncio-by-measuring-event-loop-latency)) only reports the stall.
  - [pyleak](https://tessl.io/registry/tessl/pypi-pyleak/files/docs/blocking-detection.md), [aiodebug](https://pypi.python.org/project/aiodebug/), [LoopSentry](https://github.com/amzker/loopsentry), [blocksnoop](https://pypi.org/project/blocksnoop/0.1.0/): rejected as dependencies for about 100 lines of stdlib code; blocksnoop's eBPF does not run on the Captain's Windows host.
  - `faulthandler.dump_traceback_later`: rejected; it dumps every thread to a stream with no rate limit or lag value.
  - The client buffer is a playout (jitter) buffer of whole sentences; no search needed.
- Blind spots:
  - One stack sample per block is racy: it can catch a frame just after the culprit returned. Rate-limited samples across many blocks give the distribution; multi-sample comparison is considered, deferred.
  - A block inside C code that holds the GIL delays the watchdog itself; the report then comes late but the lag is still measured from the heartbeat, and the stack shows the Python frame that called into C.
  - The probe starts after boot, so boot-time blocks are not reported.
  - Barge-in now discards up to three syntheses instead of one (CPU only; Kokoro costs more per sentence).
  - The orchestrator's "boot dream" was not located in `src`; if one exists it is a dream outside the idle monitor and is not held off (section 11).

## 14. Acceptance criteria

1. The A/B of 8.1 holds; U1-U7, D1-D5 and L1-L8 are killed as 8.3 says.
2. The focused checks of 8.2 pass, the `rg` list and the vitest and build lines included; the pre-existing tests in those files pass unchanged apart from the five changed in place.
3. `git diff --check` is clean, the new text is ASCII, and no file outside the scope line changes; no BF-932 file and no `config/system.yaml` change.
4. The Diff Reviewer approves against section 9.
5. One receipted broad gate on the committed head is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
