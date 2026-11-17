# Screen stream guards: one shared start, a stop that cancels a pending start, and uploads that wait for each other and for the server's 429 -- #1804, one issue

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16
**File in the repository:** `prompts/bf-973-screen-stream-guards.md`. No commit subject or tracker line in this issue carries an `AD-` or `BF-` token or this file's name (section 5).
**Status:** ready to build on `origin/main`. The Architect read the code on `4235580e` (tree `7db7edd7`). `git log --oneline 5275d008..4235580e -- ui/src/hooks ui/src/components/profile ui/src/components/perception ui/src/components/settings` prints nothing, so the issue's line numbers hold on this base.
**Numbers:** #1804 is BF-973, already allocated. Nothing is allocated here.
**Builder:** `claude-sonnet-5.5`, at most about 150 tool calls per milestone. Search first, then read the range. The Builder runs no test; the orchestrator runs every gate. **Diff Reviewer:** `gpt-6.1-sol` (section 9).
**Tests:** one new file, `ui/src/hooks/__tests__/useScreenStream.bf973.test.ts`, with 18 cases: 12 `built` (expected to fail until M2) and 6 controls. No existing test is edited and none is removed.

**Base blobs (read on `4235580e`).**

| File | Blob | Milestone |
|---|---|---|
| `ui/src/hooks/useScreenStream.ts` | `fbab469c2516f773a4921dc815ee5126fa4cd99f` | M2 |
| `ui/src/hooks/__tests__/useScreenStream.test.ts` | `54b1c6c200ba81ede59b1c91e6303aca131e29c8` | read, not edited |
| `ui/src/hooks/useCameraStream.ts` | `c16266a3b7dc868baee66db01ce5e2da1c4ce2d9` | read, not edited |
| `ui/src/store/useScreenStore.ts` | `0a07d53f7c67a440121e9ba700f3d7afbedbf1da` | read, not edited |
| `PROGRESS.md`, `DECISIONS.md` | move with the earlier batches | M3 (text anchors) |

## 1. Problem (re-derived on `4235580e`)

| Issue item | Evidence | Verdict |
|---|---|---|
| 1. Two overlapping starts both pass the guard | `useScreenStream.ts:112` (`if (_screenStream) return;`); `:119` assigns `_screenStream` after the `getDisplayMedia` await; `:153` assigns `_intervalId`. Two calls before the first await both call `getDisplayMedia`, and each sets the stream and the interval | Holds |
| 2. A stop while the picker is open | `:158-161` (`stopScreenStream` -> `_stopTracks`, `:44-56`) finds `_screenStream` null; the start then resumes at `:128` and reaches `:153` | Holds |
| 3. 429 and 413 dropped; no upload guard | `:101` (comment only); `:153-155` starts `_captureAndUpload` on every tick with no in-flight check | Holds. The frame route answers a 429 with `Retry-After: 1` (`src/probos/routers/perception.py:180-185`) and a 413 at `:188-189` |
| 4. `session_id` read after the encode | `:76-78` (the `toBlob` await), then `:83` reads `_sessionId`, which `_stopTracks` (`:55`) sets to null | Holds |

## 2. Solution overview

- Apply the camera hook's guards (#1671) to the screen hook, in `useScreenStream.ts` only:
  - one shared pending start;
  - a stop epoch, checked after `getDisplayMedia` and after `play()`;
  - an upload-in-flight guard owned by its epoch;
  - a 10 s upload deadline;
  - Retry-After or a doubling backoff on a 429.
- Add one check the camera hook lacks: the frame reads its epoch and session id before the encode, and posts nothing if a stop came during it.
- The exports keep their signatures and return shapes. The form fields `file`, `session_id` and `source` are unchanged.
- **Rejected:**
  - Aborting the upload in flight when a stop arrives. The camera hook does not, and what the server holds of a frame already sent would not change for the caller (L3).
  - Moving the loop into a shared helper used by both hooks. That edits the camera hook, which this issue does not need.
  - Clearing an old interval before setting a new one. One start per epoch reaches `setInterval`, so the existing clear in `_stopTracks` is enough.

## 3. Decisions

| # | Question | Decision and evidence |
|---|---|---|
| D1 | Mapping of the camera hook's mechanisms | **Start promise:** `useCameraStream.ts:42`, `:224-233`. Copied as is. **Epoch:** `:43`, bumped at `:86`, read at `:236`; the catch guard is at `:258-263`, the check after the camera at `:265-269`, the check after `play()` at `:287-288`. Copied at the same three points. **Upload guard:** `:44`, `:128-140`. Copied. **Deadline:** `:39`, `:181-183`, `:185`, `:209-212`. Copied. **Retry-After and backoff:** `:40-41`, `:45-46`, `:119-126`, `:196`, `:198-205`. Copied. **413:** `:206`, where the frame is dropped and the next tick tries again; the screen hook does the same. **Late answer:** `:186`, `:189`. Copied. **Where the screen hook differs.** A picker opens and can be dismissed: a dismissal is a rejection and reports `getDisplayMedia failed`, unless a stop cancelled the start (the same shape as the camera's catch). A stop cannot close the browser's picker (L2). The screen hook has no device id and no stream map. The `onended` handlers are set only after the epoch check, so a capture released after a stop never gets them. The encode check is new (D3) |
| D2 | `stopScreenStream` while a start is pending | `_stopTracks` advances `_epoch` and sets `_startInFlight` to null; nothing else is held. The pending start's promise stays pending until the picker settles: the browser offers no call to close it. Then: if the operator picked, every track of the picked stream is stopped and no module or store state is set; if the operator dismissed, no error is written. Either way the promise resolves to `undefined` and does not reject. A caller that awaited it, such as `ProfileChatTab.tsx:684`, then reads `active` as false |
| D3 | Frame loop | `_captureAndUpload` returns at once if an upload is in flight or a 429 pause runs; otherwise it takes the guard for its epoch. `_captureAndUploadFrame` reads `epoch` and `sessionId` before the encode. It then checks the epoch at three points: after the `toBlob` await (posts nothing if it changed), after the `fetch` await (the answer is not acted on) and after the 503 body read (the same). A slow upload makes each later tick return at once until the upload settles or the 10 s deadline aborts it, and the interval keeps its period. A stop clears the interval (`_stopTracks`, unchanged), and one start per epoch reaches `setInterval` |
| D4 | Tests | vitest fake timers with the system time fixed. Mocks: `navigator.mediaDevices.getDisplayMedia`, which the test settles by hand; `document.createElement` for `video` and `canvas`, where `play` and `toBlob` can be held; `document.visibilityState`; `fetch`, scripted or held. There are no wall-clock waits: time moves only by `vi.advanceTimersByTimeAsync`. Every held step that a case's assertions wait on is released by the case. Three cases end with an upload still in flight, as a stop leaves one in production (L3: a stop does not abort it): the second upload of S6 and of S8, which the case never releases, and the second upload of S12, which never answers. `_testReset()` in the `afterEach` stops the loop, `vi.useRealTimers()` drops that upload's 10 s deadline timer with the fake clock, and `vi.restoreAllMocks()` restores `fetch`, so nothing reaches the next case, whose `beforeEach` installs a new fake clock. The deadline timer's clearing on a 200, a 503, a 413 and a network error is checked by C3, C4 and C5 (row W15). "No upload after a stop" is checked by the `fetch` spy's call count after the test has advanced the fake clock (S2, S7). S7 also asserts that the encode was reached, so its empty send count cannot pass vacuously. The issue's four acceptance cases are S1, S2, S9 with S6, and S7. Mutation rows are in section 8 |
| D5 | Persisted state, config, flags | None. A search for `localStorage\|sessionStorage\|indexedDB` in `useScreenStream.ts` gives 0. The server's `perception.screen` settings (`config/system.yaml:1780`, `:1785`) are read by the route, not by this hook, and do not change. Not touched: the config reference, the facade baseline, `config/profiles` and the HXI settings |
| D6 | Type-check and build | `npx tsc -b` (the `include` in `ui/tsconfig.json` is `src`, so it covers the tests). The exports' types are unchanged, so the four importers and the two `vi.mock` factories compile as they are. `process.env` already appears in compiled tests, for example `ApprovalWave.test.tsx:667`. Before the push: `npm run build` (`tsc -b && vite build`), which CI runs too |

## 4. Milestones and gates

All UI commands run from `ui/` on the host (PowerShell, Node v24.14.0) with the junctioned `node_modules`. `PY` = `d:/ProbOS/.venv/Scripts/python.exe` from the worktree root, with `PROBOS_EMBEDDINGS=local`.

- **M0:** record the test counts of the focused set (G2) on the base.
- **G1 (M1):**
  - `npx vitest run src/hooks/__tests__/useScreenStream.bf973.test.ts`. Expected: 18 tests and 0 failed; the 12 `built` cases are reported as passed or as expected fail, and the 6 controls pass.
  - Then `$env:BF973_RUNXFAIL='1'; npx vitest run src/hooks/__tests__/useScreenStream.bf973.test.ts; Remove-Item Env:BF973_RUNXFAIL`. Expected: 12 failed and 6 passed. Each failure must be at the `expect` named in section 8's "base stop" column, never at an import, a mock or a helper.
  - `npx tsc -b`: clean.
- **G2 (M2):**
  - `npx vitest run src/hooks/__tests__/useScreenStream.bf973.test.ts src/hooks/__tests__/useScreenStream.test.ts src/hooks/__tests__/useCameraStream.bf933.test.ts src/hooks/__tests__/useScreenShare.test.ts src/__tests__/ProfileChatTab.screenShare.test.tsx src/components/profile/__tests__/MeetingView.captain.test.tsx src/components/perception/__tests__ src/components/settings/sections/__tests__ src/components/settings/__tests__/PerceptionParentChild.test.tsx src/__tests__/PerceptionLivePanel.sourceBindings.test.tsx src/audio/__tests__/whisperStt.test.ts`. Expected: M0 + 18 passed, 0 failed.
  - The same command with `BF973_RUNXFAIL=1` gives the same result (the marker is now `it`).
  - `npx tsc -b`: clean.
  - `PY -P scripts/check_architecture_principles.py --check`, `PY -P scripts/check_config_facade.py --check` and `PY -P scripts/check_config_profiles.py --check`: each passes as on the base (no Python or config file changes).
- **G3 (M3):** `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. The ledger reads `PROGRESS.md`, `DECISIONS.md`, commit subjects and issues; this issue's lines carry no number token. Expected: no number row moves, and only the git-layer row and the snapshot change. A changed number row is a hard stop.

**Orchestrator, once, after the Diff Reviewer's findings are repaired and the tree is committed:**
- `npm run build` (clean);
- the mutation rows of section 8, restoring the file after each and leaving no `.mutbak`, `.mut_bak` or `.mut.bak` file (`run_test_gate.py:69`);
- `PY scripts/run_test_gate.py --label screen-stream-guards --receipt logs/gates/screen-stream-guards.receipt.json`.

The broad gate scans `ui/src/` (`run_test_gate.py:40`, `:795`), so the new test file is committed before it runs.

**Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing new case at G2, or any existing test that changes, goes back to the Architect.

**Consumer search (run 2026-11-16 on `4235580e`; Grep for `useScreenStream|startScreenStream|stopScreenStream|getScreenStream` in `ui/src`, `useScreenStream|ScreenStream` in `tests/` and `scripts/`).**

| Reader | What it uses | Action |
|---|---|---|
| `components/settings/sections/PerceptionLivePanel.tsx:23`, `:645`, `:647` | `startScreenStream({ fps: 1 })` and `stopScreenStream()` on a toggle | Unchanged. In G2, through its two section tests, `PerceptionParentChild.test.tsx` and `PerceptionLivePanel.sourceBindings.test.tsx`, which load the real module |
| `components/profile/MeetingView.tsx:21`, `:205` | `getScreenStream()` | Unchanged; null while a start is pending, as on the base |
| `components/profile/ProfileChatTab.tsx:82`, `:684`, `:699`, `:2392` | awaits start, then reads `active`; stop in the cleanup and in `selectScreenMode` | Unchanged (L1 records the cleanup's `active` check at `:697`) |
| `components/perception/CameraLiveIndicator.tsx:18`, `:440` | `stopScreenStream()` | Unchanged. Its four test files load the real module; in G2 |
| `__tests__/ProfileChatTab.screenShare.test.tsx:32-35` | `vi.mock` with `startScreenStream` and `stopScreenStream` | The mock replaces the module; in G2 |
| `components/profile/__tests__/MeetingView.captain.test.tsx:45-46` | `vi.mock` with `getScreenStream` | The same; in G2 |
| `hooks/useScreenShare.ts:3`, `hooks/__tests__/useScreenShare.test.ts:4` | comments only | In G2 |
| `hooks/__tests__/useScreenStream.test.ts` | the five AD-733-2 cases, with real timers | Checked against the M2 code: the sequential second start finds `_startInFlight` cleared by the attempt's `finally` and `_screenStream` set, so `getDisplayMedia` is called once. In G2 |
| `hooks/__tests__/useCameraStream.bf933.test.ts` | the camera hook only | Not edited; in G2 as a control |
| `tests/test_ad1270e2c_experience_models.py:52`, `:74`, `:181`, `:289` | Python `ScreenStreamConfig` | Config model only; not touched |

## 5. Commit messages

Every body ends with `Refs #1804.`, followed by the committing agent's trailer paragraph. No subject carries an `AD-` or `BF-` token. No message uses close, fix or resolve in any form, including inside a compound, a hyphenated word or a quotation.

- Contract (the orchestrator's): `Screen stream guards (#1804): contract for one shared start, a stop that cancels a pending start, and uploads that wait for each other and for the server's 429`
- M1: `Screen stream guards M1: tests for overlapping starts, a stop while the picker is open, a stop during the encode, a slow upload and a 429, expected to fail until built (#1804)`, then `Adds one hook test file: 18 cases, 12 of them marked to fail until the hook is built.`
- M2: `Screen stream guards M2: overlapping screen starts share one picker, a stop cancels a pending start, and ticks wait for an upload in flight or a 429 pause (#1804)`, then this paragraph as written:
  `The screen hook takes the camera hook's loop guards. Concurrent starts share one pending start, so the picker opens once. Each stop advances an epoch that a pending start compares after the picker and after play(); a capture picked after a stop has its tracks stopped and sets no state, and a picker dismissed after a stop reports no error. A frame reads its epoch and session id before the encode and posts nothing when a stop came during it; an answer that arrives after a stop is not acted on. A tick returns while an upload is in flight, and each upload is aborted after 10 s. A 429 pauses the uploads for its Retry-After, else 1 s doubling up to 30 s, and a 200 ends the doubling; a 413 drops the frame. The exports keep their signatures. The new test file's marker becomes it.`
- M3: `Screen stream guards M3: trackers and ledger (#1804)`

With `BASE` = the `origin/main` commit the issue is built on, both scans must print nothing:
- `git log --format=%B BASE..HEAD | rg -n -i "\bClos[e]s\b"`
- `git log --format=%B BASE..HEAD | rg -n -i "(clos[e]|fix|resolv[e])"`

The orchestrator closes the issue after the gate.

## 6. Recorded limits

- **L1.** The cleanup in `ProfileChatTab.tsx:695-702` calls `stopScreenStream` only when `active` is true (`:697`). An unmount or an agent switch while the picker is open therefore does not cancel the start, and the capture runs after the pick until a stop. This is a caller outside the hook and is left unchanged.
- **L2.** A stop cannot close the browser's picker. The capture picked after a stop has its tracks stopped when the picker returns it, and the pending start's promise settles only then.
- **L3.** An upload already in flight at a stop is not aborted; the caller does not act on its answer. This change does not bound what the server holds of that frame.
- **L4.** On a 503 the hook writes `screen disabled by server: ...`, and the stop that follows calls `reset()`, which sets `error` to null (`useScreenStore.ts:32`). The camera hook does the same (`useCameraStore.ts:145`). This is base behaviour and is unchanged.
- **L5.** The camera hook reads `_sessionId` after its encode, with no epoch check between (`useCameraStream.ts:162-169`). That is item 4 of this issue in the camera hook, and it is unchanged here.

## 7. The contract

The SEARCH text is LF and ASCII. It starts at a line start and matches once in its file, after the earlier blocks for that file have been applied in label order. Each SEARCH avoids the hook's non-ASCII lines (`useScreenStream.ts:1`, `:4`, `:13`, `:85`, `:103`, `:129`), which stay as they are.

### M1

**N1-1** (`ui/src/hooks/__tests__/useScreenStream.bf973.test.ts`: new file)

```ts
/** BF-973 (#1804): the screen capture loop under overlapping starts, a stop while the picker is open, a stop during
 * the encode, a slow upload and a 429.
 *
 * The defect: `startScreenStream` returned early only when `_screenStream` was set, and `_screenStream` is assigned
 * after the `getDisplayMedia` await, so two overlapping calls both passed, each opened the picker and each created a
 * `setInterval`. A stop that arrived while the picker was open found nothing to stop, and the start then ran. A 429
 * was dropped with no pause, nothing kept a tick from starting a capture while the previous upload was in flight,
 * and the session id was read after the encode.
 *
 * The fixtures are synthetic, as in useCameraStream.bf933.test.ts: a fake picker whose `getDisplayMedia` the test
 * settles by hand, a fake `<video>` and `<canvas>`, and a stubbed `fetch`. The cases the unbuilt hook fails are
 * `built`, which is `it.fails` until BF-973 M2 sets it to `it`; with BF973_RUNXFAIL=1 they run as ordinary cases,
 * so each can be seen to stop at its own assertion. Time is vitest's fake clock with the system time fixed; no case
 * waits on the wall clock. Every case restores the module (`_testReset`), the timers, the spies and
 * `navigator.mediaDevices`. Each title names its case and the contract's mutation rows (W) that it kills.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  getScreenStream,
  startScreenStream,
  stopScreenStream,
  _testReset,
} from '../useScreenStream';
import { useScreenStore } from '../../store/useScreenStore';

const built = process.env.BF973_RUNXFAIL === '1' ? it : it.fails;

class FakeTrack {
  stopped = false;
  onended: (() => void) | null = null;
  stop() { this.stopped = true; }
}

class FakeMediaStream {
  tracks: FakeTrack[] = [new FakeTrack()];
  getTracks() { return this.tracks; }
  get released() { return this.tracks.every((t) => t.stopped); }
}

/** A picker the test settles by hand: each getDisplayMedia call stays pending until the test picks or dismisses. */
function installPicker() {
  const streams: FakeMediaStream[] = [];
  const pick: Array<() => void> = [];
  const dismiss: Array<(error: Error) => void> = [];
  const getDisplayMedia = vi.fn(
    () =>
      new Promise<MediaStream>((resolve, reject) => {
        const stream = new FakeMediaStream();
        streams.push(stream);
        pick.push(() => resolve(stream as unknown as MediaStream));
        dismiss.push(reject);
      }),
  );
  Object.defineProperty(global.navigator, 'mediaDevices', {
    value: { getDisplayMedia },
    configurable: true,
    writable: true,
  });
  return { getDisplayMedia, streams, pick, dismiss };
}

/** A fake <video> that is ready and a fake <canvas> whose encoder answers at once unless the case holds it. */
function installElements(options: { play?: () => Promise<void>; toBlob?: (done: BlobCallback) => void } = {}) {
  const real = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation(((tag: string, init?: ElementCreationOptions) => {
    if (tag === 'video') {
      return {
        videoWidth: 1280,
        videoHeight: 720,
        autoplay: false,
        playsInline: false,
        muted: false,
        srcObject: null,
        play: options.play ?? (async () => undefined),
      } as unknown as HTMLVideoElement;
    }
    if (tag === 'canvas') {
      return {
        width: 0,
        height: 0,
        getContext: () => ({ drawImage: () => undefined }),
        toBlob: options.toBlob ?? ((done: BlobCallback) => done(new Blob(['frame'], { type: 'image/jpeg' }))),
      } as unknown as HTMLCanvasElement;
    }
    return real(tag, init);
  }) as typeof document.createElement);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
}

const ok = (): Response => new Response('{}', { status: 200 });
const limited = (retryAfter?: string): Response =>
  new Response('{"error":"rate_limited"}', {
    status: 429,
    headers: retryAfter === undefined ? {} : { 'Retry-After': retryAfter },
  });

/** A fetch whose n-th call answers script[n] (the last entry repeats). */
function installFetch(script: Array<() => Response>) {
  let calls = 0;
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () => script[Math.min(calls++, script.length - 1)](),
  );
}

/** A fetch that never answers on its own: each call waits for the test to release it. */
function installHeldFetch() {
  const release: Array<() => void> = [];
  const send = vi.spyOn(globalThis, 'fetch').mockImplementation(
    () => new Promise<Response>((resolve) => { release.push(() => resolve(ok())); }),
  );
  return { send, release };
}

async function startRunning(picker: ReturnType<typeof installPicker>, index = 0): Promise<void> {
  const started = startScreenStream({ fps: 1 });
  picker.pick[index]();
  await started;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2030-01-01T00:00:00.000Z'));
  useScreenStore.setState({ active: false, sessionId: null, error: null, framesSent: 0 });
});

afterEach(() => {
  _testReset();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete (navigator as { mediaDevices?: unknown }).mediaDevices;
});

describe('BF-973: overlapping starts and a stop during a start', () => {
  built('S1 [W1] two overlapping starts open one picker and one capture interval, and one stop releases every track', async () => {
    const picker = installPicker();
    installElements();
    const intervals = vi.spyOn(window, 'setInterval');
    const first = startScreenStream({ fps: 1 });
    const second = startScreenStream({ fps: 1 });
    expect(picker.getDisplayMedia).toHaveBeenCalledTimes(1);
    picker.pick[0]();
    await Promise.all([first, second]);
    expect(intervals).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    expect(useScreenStore.getState().active).toBe(true);
    await stopScreenStream();
    expect(vi.getTimerCount()).toBe(0);
    expect(picker.streams.every((s) => s.released)).toBe(true);
    expect(getScreenStream()).toBeNull();
  });

  built('S2 [W2] a stop while the picker is open releases the picked capture, starts no loop and posts nothing', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([ok]);
    const pending = startScreenStream({ fps: 1 });
    await stopScreenStream();
    picker.pick[0]();
    await pending;
    expect(picker.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(useScreenStore.getState().active).toBe(false);
    expect(getScreenStream()).toBeNull();
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).not.toHaveBeenCalled();
  });

  built('S3 [W3] a stop while the video is starting releases the capture and starts no loop', async () => {
    const picker = installPicker();
    let finishPlay!: () => void;
    installElements({ play: () => new Promise<void>((resolve) => { finishPlay = resolve; }) });
    const pending = startScreenStream({ fps: 1 });
    picker.pick[0]();
    await vi.advanceTimersByTimeAsync(0);
    await stopScreenStream();
    finishPlay();
    await pending;
    expect(vi.getTimerCount()).toBe(0);
    expect(useScreenStore.getState().active).toBe(false);
    expect(picker.streams[0].released).toBe(true);
  });

  built('S4 [W2, W4] a start after a stop, while the first picker is open, runs one loop and releases the first capture', async () => {
    const picker = installPicker();
    installElements();
    const first = startScreenStream({ fps: 1 });
    await stopScreenStream();
    const second = startScreenStream({ fps: 1 });
    expect(picker.getDisplayMedia).toHaveBeenCalledTimes(2);
    picker.pick[0]();
    picker.pick[1]();
    await Promise.all([first, second]);
    expect(picker.streams[0].released).toBe(true);
    expect(picker.streams[1].released).toBe(false);
    expect(vi.getTimerCount()).toBe(1);
    expect(useScreenStore.getState().active).toBe(true);
    await stopScreenStream();
    expect(picker.streams[1].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  built('S5 [W5] a cancelled start whose picker is then dismissed reports nothing and leaves the newer start alone', async () => {
    const picker = installPicker();
    installElements();
    const first = startScreenStream({ fps: 1 });
    await stopScreenStream();
    const second = startScreenStream({ fps: 1 });
    picker.pick[1]();
    await second;
    picker.dismiss[0](new Error('NotAllowedError'));
    await first;
    expect(useScreenStore.getState().error).toBeNull();
    expect(useScreenStore.getState().active).toBe(true);
  });
});

describe('BF-973: the frame loop', () => {
  built('S6 [W6] ticks during a pending upload send nothing, and the first tick after it settles sends again', async () => {
    const picker = installPicker();
    installElements();
    const { send, release } = installHeldFetch();
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(1);
    release[0]();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('S7 [W8] a stop during the encode posts nothing', async () => {
    const picker = installPicker();
    const encodes: BlobCallback[] = [];
    installElements({ toBlob: (done) => { encodes.push(done); } });
    const send = installFetch([ok]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(encodes).toHaveLength(1);
    await stopScreenStream();
    encodes[0](new Blob(['frame'], { type: 'image/jpeg' }));
    await vi.advanceTimersByTimeAsync(0);
    expect(send).not.toHaveBeenCalled();
  });

  built('S8 [W7] an upload that settles after a stop and a restart does not release the new loop\'s guard', async () => {
    const picker = installPicker();
    installElements();
    const { send, release } = installHeldFetch();
    await startRunning(picker, 0);
    await vi.advanceTimersByTimeAsync(1000);
    await stopScreenStream();
    await startRunning(picker, 1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
    release[0]();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('S12 [W13] an upload that never answers is aborted after ten seconds, and the loop sends again', async () => {
    const picker = installPicker();
    installElements();
    const send = vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('S13 [W14] a 429 that answers after a stop and a restart does not pause the new loop', async () => {
    const picker = installPicker();
    installElements();
    let answerFirst!: (response: Response) => void;
    let calls = 0;
    const send = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      calls += 1;
      if (calls === 1) return new Promise<Response>((resolve) => { answerFirst = resolve; });
      return Promise.resolve(ok());
    });
    await startRunning(picker, 0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await stopScreenStream();
    await startRunning(picker, 1);
    answerFirst(limited('30'));
    await vi.advanceTimersByTimeAsync(2000);
    expect(send).toHaveBeenCalledTimes(3);
    expect(useScreenStore.getState().active).toBe(true);
  });
});

describe('BF-973: a 429 is honoured', () => {
  built('S9 [W9, W10] a 429 with Retry-After: 3 posts nothing for three seconds, then the uploads resume', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([() => limited('3'), ok]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('S10 [W9, W12] without a usable Retry-After the pause doubles from one second, and a 200 starts it over', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([() => limited(), () => limited('soon'), ok, () => limited(), ok]);
    await startRunning(picker);
    const calls: number[] = [];
    for (let second = 1; second <= 6; second += 1) {
      await vi.advanceTimersByTimeAsync(1000);
      calls.push(send.mock.calls.length);
    }
    expect(calls).toEqual([1, 2, 2, 3, 4, 5]);
  });

  built('S11 [W9, W10, W11] a long Retry-After is capped at thirty seconds', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([() => limited('3600'), ok]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(29_000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });
});

describe('BF-973: what must not change', () => {
  it('C1 a single start opens one picker and one capture loop, and a stop releases both', async () => {
    const picker = installPicker();
    installElements();
    await startRunning(picker);
    expect(picker.getDisplayMedia).toHaveBeenCalledTimes(1);
    expect(getScreenStream()).toBe(picker.streams[0] as unknown as MediaStream);
    expect(vi.getTimerCount()).toBe(1);
    expect(useScreenStore.getState().active).toBe(true);
    await stopScreenStream();
    expect(picker.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(useScreenStore.getState().active).toBe(false);
  });

  it('C2 a start while the capture runs changes nothing', async () => {
    const picker = installPicker();
    installElements();
    await startRunning(picker);
    await startScreenStream({ fps: 1 });
    expect(picker.getDisplayMedia).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('C3 a 200 counts a frame, the form carries the session id and source=screen, and a stop leaves no timer', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([ok]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(useScreenStore.getState().framesSent).toBe(1);
    const form = send.mock.calls[0][1]?.body as FormData;
    expect(form.get('session_id')).toBe(useScreenStore.getState().sessionId);
    expect(form.get('source')).toBe('screen');
    await stopScreenStream();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('C4 a 503 from the server stops the capture, as before', async () => {
    const picker = installPicker();
    installElements();
    installFetch([() => new Response('{"error":"screen_disabled"}', { status: 503 })]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(useScreenStore.getState().active).toBe(false);
    expect(picker.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('C5 a 413 and a network error drop one frame each and keep the loop alive', async () => {
    const picker = installPicker();
    installElements();
    const send = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(async () => new Response('{}', { status: 413 }))
      .mockImplementationOnce(async () => { throw new TypeError('network'); })
      .mockImplementation(async () => ok());
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(3);
    expect(useScreenStore.getState().framesSent).toBe(1);
    expect(useScreenStore.getState().active).toBe(true);
    expect(vi.getTimerCount()).toBe(1);
  });
});
```

### M2

**P2-1** (`ui/src/hooks/useScreenStream.ts`: header note and the guards)

SEARCH:
```
 * gate.
 */
import { useScreenStore } from '../store/useScreenStore';

const FRAME_ENDPOINT = '/api/perception/camera/frame';
```
REPLACE:
```
 * gate.
 *
 * BF-973: the loop carries useCameraStream's BF-933 guards. Overlapping starts share one pending start, so the
 * picker opens once; a stop cancels a pending start, and a capture picked after the stop has its tracks stopped as
 * soon as the picker returns it; a frame whose loop was stopped during its encode is not posted; a tick returns
 * while an upload is in flight (each upload is aborted after 10 s); a 429 pauses the uploads for its Retry-After,
 * else 1 s, 2 s, 4 s ... up to 30 s; a 413 drops the frame.
 */
import { useScreenStore } from '../store/useScreenStore';

const FRAME_ENDPOINT = '/api/perception/camera/frame';
// BF-973: the loop's guards. A start is one shared promise; every stop advances the epoch, which is how a start
// still waiting on the picker or on play(), and a frame still in its encode or its upload, learns that its loop was
// stopped; an upload in flight holds the next tick off; a 429 holds it off until _resumeAtMs.
const FRAME_UPLOAD_TIMEOUT_MS = 10_000;
const BACKOFF_BASE_MS = 1_000;
const RETRY_AFTER_MAX_MS = 30_000;
let _startInFlight: Promise<void> | null = null;
let _epoch = 0;
let _uploading = false;
let _resumeAtMs = 0;
let _rateLimited = 0;
```

**P2-2** (`_stopTracks` cancels; the Retry-After parser, the upload guard and the frame's epoch)

SEARCH:
```
  _video = null;
  _canvas = null;
  _sessionId = null;
}

async function _captureAndUpload() {
  if (!_video || !_canvas || !_sessionId) return;
```
REPLACE:
```
  _video = null;
  _canvas = null;
  _sessionId = null;
  // BF-973: every stop is also a cancel. A pending start sees a new epoch and releases any capture it is given; a
  // frame in its encode posts nothing, and an answer that arrives later is not acted on; the old loop's upload guard
  // and 429 pause do not outlive it. _testReset goes through here, so a test resets all of it.
  _epoch += 1;
  _startInFlight = null; // a call after a stop is not held to the cancelled start
  _uploading = false;
  _resumeAtMs = 0;
  _rateLimited = 0;
}

/** BF-973: RFC 9110 Retry-After is delta-seconds or an HTTP-date; anything else is no advice (as useCameraStream). */
function _parseRetryAfterMs(raw: string | null): number | null {
  if (raw === null) return null;
  const value = raw.trim();
  if (/^\d+$/.test(value)) return Number(value) * 1000;
  const at = Date.parse(value);
  return Number.isNaN(at) ? null : Math.max(0, at - Date.now());
}

/** BF-973: one capture-and-upload at a time. A tick that finds the previous upload still in flight, or the loop
 *  paused by a 429, returns at once. The flag belongs to the epoch that set it: an upload that settles after a stop
 *  (and perhaps a new start) does not release a newer loop's guard. */
async function _captureAndUpload() {
  if (_uploading || Date.now() < _resumeAtMs) return;
  const epoch = _epoch;
  _uploading = true;
  try {
    await _captureAndUploadFrame();
  } finally {
    if (epoch === _epoch) _uploading = false;
  }
}

async function _captureAndUploadFrame() {
  // BF-973: the epoch and the session id this frame belongs to, both read before the encode.
  const epoch = _epoch;
  const sessionId = _sessionId;
  if (!_video || !_canvas || !sessionId) return;
```

**P2-3** (the encode check and the session id read before it)

SEARCH:
```
  if (!blob) return;

  const form = new FormData();
  form.append('file', blob, 'screen.jpg');
  form.append('session_id', _sessionId);
```
REPLACE:
```
  if (!blob) return;
  if (epoch !== _epoch) return; // a stop came during the encode: post nothing

  const form = new FormData();
  form.append('file', blob, 'screen.jpg');
  form.append('session_id', sessionId);
```

**P2-4** (the deadline, the late-answer checks, 200, 429 and 413)

SEARCH:
```
  try {
    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form });
    if (resp.status === 503) {
      const body = await resp.json().catch(() => ({}));
      useScreenStore.getState().setError(
        `screen disabled by server: ${body.error ?? 'unknown'}`,
      );
      await stopScreenStream();
      return;
    }
    if (resp.status === 200) {
      useScreenStore.getState().incrementFramesSent();
    }
    // 429 / 413: drop the frame; the next interval tick retries.
  } catch {
```
REPLACE:
```
  // BF-973: bound the upload, so a request that never answers cannot hold the in-flight guard for good.
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), FRAME_UPLOAD_TIMEOUT_MS);
  try {
    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form, signal: controller.signal });
    if (epoch !== _epoch) return; // a stop came during the upload: its answer is not for the loop that runs now
    if (resp.status === 503) {
      const body = await resp.json().catch(() => ({}));
      if (epoch !== _epoch) return; // a stop came while the body was read: the same
      useScreenStore.getState().setError(
        `screen disabled by server: ${body.error ?? 'unknown'}`,
      );
      await stopScreenStream();
      return;
    }
    if (resp.status === 200) {
      useScreenStore.getState().incrementFramesSent();
      _rateLimited = 0; // a 200 ends the doubling
    }
    if (resp.status === 429) {
      // BF-973: the server's rate bucket said slow down. Honour Retry-After; without a usable one back off 1 s, 2 s,
      // 4 s ... The interval keeps its period; ticks inside the pause return without capturing.
      _rateLimited += 1;
      const advised = _parseRetryAfterMs(resp.headers.get('Retry-After'));
      const waitMs = advised ?? BACKOFF_BASE_MS * 2 ** (_rateLimited - 1);
      _resumeAtMs = Date.now() + Math.min(waitMs, RETRY_AFTER_MAX_MS);
    }
    // 413: drop the frame; the next interval tick tries again.
  } catch {
```

**P2-5** (the deadline is cleared; one shared start; the epoch after the picker)

SEARCH:
```
  }
}

export async function startScreenStream(opts?: {
  fps?: number;
  jpegQuality?: number;
  maxDimension?: number;
}): Promise<void> {
  if (_screenStream) return; // idempotent
  _fps = opts?.fps ?? 1;
  _jpegQuality = opts?.jpegQuality ?? 0.6;
  _maxDim = opts?.maxDimension ?? 512;
  useScreenStore.getState().setError(null);

  try {
    _screenStream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: _fps },
      audio: false,
    });
  } catch (err) {
    useScreenStore.getState().setError(`getDisplayMedia failed: ${String(err)}`);
    return;
  }
```
REPLACE:
```
  } finally {
    window.clearTimeout(timeout); // the upload deadline, on every way out of the try
  }
}

export async function startScreenStream(opts?: {
  fps?: number;
  jpegQuality?: number;
  maxDimension?: number;
}): Promise<void> {
  // BF-973: concurrent callers share the one pending start, so the picker opens once (the guard below only sees a
  // capture already granted); a call after a stop starts afresh, because the stop dropped the pending start.
  if (_startInFlight) return _startInFlight;
  if (_screenStream) return; // idempotent
  const attempt: Promise<void> = _startScreen(opts).finally(() => {
    if (_startInFlight === attempt) _startInFlight = null;
  });
  _startInFlight = attempt;
  return attempt;
}

async function _startScreen(opts: Parameters<typeof startScreenStream>[0]): Promise<void> {
  const epoch = _epoch;
  _fps = opts?.fps ?? 1;
  _jpegQuality = opts?.jpegQuality ?? 0.6;
  _maxDim = opts?.maxDimension ?? 512;
  useScreenStore.getState().setError(null);

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: _fps },
      audio: false,
    });
  } catch (err) {
    // BF-973: a dismissed or failed picker reports its error, unless a stop cancelled this start while it was open.
    if (epoch === _epoch) useScreenStore.getState().setError(`getDisplayMedia failed: ${String(err)}`);
    return;
  }
  if (epoch !== _epoch) { // a stop came while the picker was open: release what was picked, start no loop
    stream.getTracks().forEach((t) => t.stop());
    return;
  }
  _screenStream = stream;
```

**P2-6** (the epoch after `play()`)

SEARCH:
```
  try {
    await _video.play();
  } catch {
    /* play promise may reject on hidden tabs; capture loop skips until visible */
  }
  _canvas = document.createElement('canvas');
```
REPLACE:
```
  try {
    await _video.play();
  } catch {
    /* play promise may reject on hidden tabs; capture loop skips until visible */
  }
  if (epoch !== _epoch) return; // a stop came during play(): the stream is already released, start no loop
  _canvas = document.createElement('canvas');
```

**P2-7** (`ui/src/hooks/__tests__/useScreenStream.bf973.test.ts`: the marker)

SEARCH:
```
const built = process.env.BF973_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```
const built = it;
```

The lines kept from the base after P2-5 (`:128-142` on the base: the `onended` handlers, the session id, the video set-up) read `_screenStream`. TypeScript narrows it to `MediaStream` from the assignment `_screenStream = stream;` with no await in between, as the base narrowed it from its own assignment at `:119`.

### M3

**P3-1** (`PROGRESS.md`: the entry under the title)

SEARCH:
```
# ProbOS Progress
```
REPLACE:
```
# ProbOS Progress

**The screen stream shares one pending start, a stop cancels a pending start, and its uploads wait for the one in flight and for the server's 429 (2026-11-16), #1804.**
- **Base.** `startScreenStream` checked only for a capture already granted, so two overlapping starts each opened the picker and each set the capture interval; the second overwrote the first's stream and interval, which no stop then reached. A stop while the picker was open found nothing to stop, and the start then ran its loop. A 429 or a 413 dropped the frame with no pause, a tick could start a capture while the previous upload was in flight, and the session id was read after the encode.
- **Change.** The screen hook takes the camera hook's guards from #1671. Overlapping starts share one pending start, so the picker opens once. Each stop advances an epoch that a pending start compares after the picker and after play(); a capture picked after a stop has its tracks stopped and sets no state, and a picker dismissed after a stop reports no error. A frame reads its epoch and session id before the encode and posts nothing if a stop came during it; an answer that arrives after a stop is not acted on. A tick returns while an upload is in flight, and each upload is aborted after 10 s. A 429 pauses the uploads for its Retry-After, else 1 s doubling up to 30 s, and a 200 ends the doubling; a 413 drops the frame. The exports keep their signatures. A stop cannot close the browser's picker, and an upload already in flight at a stop is not aborted. A new hook test file adds 18 cases. Refs #1804.
```

**P3-2** (`DECISIONS.md`: the new heading before the M3e4d9 heading)

SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### The screen stream takes the camera loop's guards (2026-11-16, #1804)

- *Scope.* `ui/src/hooks/useScreenStream.ts`; one new test file. The server's frame route, its rate buckets and the camera hook are unchanged.
- *G1 (start).* One shared pending start; a stop advances an epoch compared after the picker and after play(); a capture picked after a stop has its tracks stopped as soon as the picker returns it. A pending start's promise settles when the picker does and resolves without a value.
- *G2 (frame).* The epoch and the session id are read before the encode; a frame whose loop was stopped during the encode is not posted, and an answer that arrives after a stop is not acted on. Considered, deferred: aborting the upload in flight at a stop (the camera hook does not either).
- *G3 (pacing).* An upload in flight holds the next tick, bounded at 10 s; a 429 pauses for its Retry-After, or 1 s doubling up to 30 s. The frame route sends `Retry-After: 1` with its 429.
- *Rollout.* No flag, config or persisted state. *Residual.* L1 to L5 of the contract. *Reversal.* Revert the issue's commits in reverse order.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

## 8. Mutation rows (campaign on the M2 tree; `ui/src/hooks/useScreenStream.ts`)

Each original line occurs once in the M2 file. Run each row with `npx vitest run src/hooks/__tests__/useScreenStream.bf973.test.ts`, restore the file, and remove any backup.

| Row | Original line | Mutant | Killed by |
|---|---|---|---|
| W1 | `  if (_startInFlight) return _startInFlight;` | line deleted | S1 |
| W2 | `  if (epoch !== _epoch) { // a stop came while the picker was open: release what was picked, start no loop` | `  if (false) {` | S2, S4 (the issue's row) |
| W3 | `  if (epoch !== _epoch) return; // a stop came during play(): the stream is already released, start no loop` | line deleted | S3 |
| W4 | `  _startInFlight = null; // a call after a stop is not held to the cancelled start` | line deleted | C1 to C5, S4 to S13 (S4 is the case written for the row: its second start returns the cancelled first start, so its assert on the number of `getDisplayMedia` calls fails before the case answers the first picker; the other 14 fail after it, because that first start never settles and stays in `_startInFlight`, which `_testReset` clears only through this line, so a later case's start returns it instead of opening its own picker: S5 and 13 more fail at a `picker.pick[...]` that no start opened) |
| W5 | `    if (epoch === _epoch) useScreenStore.getState().setError(`getDisplayMedia failed: ${String(err)}`);` | `    useScreenStore.getState().setError(`getDisplayMedia failed: ${String(err)}`);` | S5 |
| W6 | `  if (_uploading \|\| Date.now() < _resumeAtMs) return;` | `  if (Date.now() < _resumeAtMs) return;` | S6, S8, S12 (S6 is the case written for the row; S8 and S12 also count the sends that ticks make while an upload is pending, S8 after a restart and S12 while an upload never answers; without the guard S6 sees 4 sends where it expects 1, S8 sees 3 where it expects 2 and S12 sees 12 where it expects 2) |
| W7 | `    if (epoch === _epoch) _uploading = false;` | `    _uploading = false;` | S8 |
| W8 | `  if (epoch !== _epoch) return; // a stop came during the encode: post nothing` | line deleted | S7 |
| W9 | `      _resumeAtMs = Date.now() + Math.min(waitMs, RETRY_AFTER_MAX_MS);` | line deleted | S9, S10, S11 |
| W10 | `      const advised = _parseRetryAfterMs(resp.headers.get('Retry-After'));` | `      const advised = null;` | S9, S11 |
| W11 | `      _resumeAtMs = Date.now() + Math.min(waitMs, RETRY_AFTER_MAX_MS);` | `      _resumeAtMs = Date.now() + waitMs;` | S11 |
| W12 | `      _rateLimited = 0; // a 200 ends the doubling` | line deleted | S10 |
| W13 | `    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form, signal: controller.signal });` | `    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form });` | S12 |
| W14 | `    if (epoch !== _epoch) return; // a stop came during the upload: its answer is not for the loop that runs now` | line deleted | S13 |
| W15 | `    window.clearTimeout(timeout); // the upload deadline, on every way out of the try` | line deleted | C3, C4, C5 (each asserts the timer count at its end, C3 and C4 after the capture stopped and C5 with the loop running; the deadline timer of each answered or failed upload stays, so C3 and C4 see 1 where they expect 0 and C5 sees 4 where it expects 1) |

(In W6 the table escapes `|` as `\|`; the original line has `||`.)

**Base stop (G1 with `BF973_RUNXFAIL=1`, base hook):**
- S1: `getDisplayMedia` called times 1 (2 calls).
- S2: `streams[0].released` true.
- S3: `vi.getTimerCount()` 0 (1 timer).
- S4: `streams[0].released` true.
- S5: `error` null.
- S6: the second count of 1 (4 sends).
- S7: `send` not called.
- S8: the last count of 2 (3 sends).
- S9: the second count of 1.
- S10: `calls` equal `[1, 2, 2, 3, 4, 5]`.
- S11: the second count of 1.
- S12: the count of 2.

These are the Architect's traces of the base code; the orchestrator measures them. The controls S13 and C1 to C5 pass on the base and at M2.

## 9. Diff Reviewer properties (`gpt-6.1-sol`)

The consumers that must accept the change: the four importers in section 4's table, the two `vi.mock` factories, and `useScreenStream.test.ts`.
1. `startScreenStream(opts?: { fps?, jpegQuality?, maxDimension? }): Promise<void>`, `stopScreenStream(): Promise<void>`, `getScreenStream(): MediaStream | null` and `_testReset(): void` keep their signatures. No export is added or removed.
2. In `_startScreen`, after each await (`getDisplayMedia`, `play`), the epoch is compared before any module variable or store field is written. A start whose epoch changed writes nothing and stops every track of a stream it received.
3. In `_captureAndUploadFrame`, after each await (`toBlob`, `fetch`, `resp.json`), no store write, stop or guard change happens for an epoch other than the current one.
4. `_stopTracks` resets `_epoch`, `_startInFlight`, `_uploading`, `_resumeAtMs` and `_rateLimited`, and `_testReset` goes through it.
5. The upload deadline timer is cleared on every path out of the `try`.
6. The form fields, the endpoint, the 503 handling and the `onended` auto-stop behave as on the base for a single uninterrupted start.
7. The new test file uses fake timers only. Every held step (picker, `play`, `toBlob`, `fetch`) that a case's assertions wait on is released by the case; the uploads that S6, S8 and S12 leave in flight at their end are dropped with the fake clock, as D4 records, and reach no later case.

## 10. What this does not change

- `useCameraStream.ts` and its tests (L5).
- The server's frame route and rate buckets.
- The callers' components (L1).
- `useScreenStore.ts` (L4).
- `useScreenShare.ts`, the one-shot capture.
- No config, persisted state, flag or Python file.

## 11. Acceptance criteria

- G1, G2 and G3 as in section 4, and every row of section 8 kills its named cases.
- `npx tsc -b` and `npm run build` are clean.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 12. Prior art and blind spots

- This is a bug fix that copies an in-repo pattern (#1671), so there was no external search and no review of `docs/research/reference-projects.md`.
- RFC 9110's Retry-After forms are already parsed by the camera hook (`useCameraStream.ts:119-126`); the parser is copied.
- Blind spots found: the caller cleanup at `ProfileChatTab.tsx:697` (L1); the 503 error text cleared by `reset()` (L4); the camera hook's session id read after its encode (L5). Each is recorded, not built here.

## Verified Against Codebase (2026-11-16, tree `7db7edd7`, commit `4235580e`)

```
Read ui/src/hooks/useScreenStream.ts (166 lines)
  112: if (_screenStream) return; // idempotent     119: _screenStream = await navigator.mediaDevices.getDisplayMedia({
  153: _intervalId = window.setInterval(() => {     101: // 429 / 413: drop the frame; the next interval tick retries.
  83: form.append('session_id', _sessionId);        44-56: function _stopTracks
Read ui/src/hooks/useCameraStream.ts (307 lines)
  42-46 guards; 86-90 reset in _stopTracks; 119-126 _parseRetryAfterMs; 131-140 wrapper; 162-169 encode then _sessionId;
  181-212 deadline, epoch checks, 429; 224-233 shared start; 258-269 catch and post-camera check; 287-288 post-play check
Grep [^\x00-\x7F] ui/src/hooks/useScreenStream.ts -> 1, 4, 13, 85, 103, 129
Grep useScreenStream|startScreenStream|stopScreenStream|getScreenStream ui/src -> section 4 table
  PerceptionLivePanel.tsx:23,645,647  MeetingView.tsx:21,205  ProfileChatTab.tsx:82,684,699,2392  CameraLiveIndicator.tsx:18,440
  ProfileChatTab.screenShare.test.tsx:32-35  MeetingView.captain.test.tsx:45-46
Read ProfileChatTab.tsx:678-703 -> 697: if (!useScreenStore.getState().active) return;
Read useScreenStore.ts:32 -> reset: () => set({ active: false, sessionId: null, error: null, framesSent: 0 }),
Grep reset: ui/src/store/useCameraStore.ts -> 145 (error: null)
Read src/probos/routers/perception.py:180-189 -> 429 with headers={"Retry-After": "1"}; 413 frame_too_large
Grep "screen" config/system.yaml -> 1780: screen:  1785: screen_max_fps_server: 2
Read ui/tsconfig.json -> "include": ["src"]; ui/vitest.config.ts -> environment: 'jsdom'
Grep process\.env ui/src -> ApprovalWave.test.tsx:667 (and others)
Grep ui/src|mutbak scripts/run_test_gate.py -> 40: "ui/src/", 69: _MUTATION_BACKUP_SUFFIXES, 795
Grep ^### AD-1346 M3e4d9 -- part \(a\) DECISIONS.md -> 1863 (once); Grep "ProbOS Progress" PROGRESS.md -> 1 (once)
git ls-files --eol -> PROGRESS.md, DECISIONS.md, useScreenStream.ts: i/lf w/crlf
```

## Absence Verified (2026-11-16)

```
CLAIM: no test or script reads useScreenStream.ts as text
RUN:   Grep \?raw ui/src; Grep useScreenStream|ScreenStream tests/ scripts/
FOUND: 30+ ?raw imports, none of useScreenStream; tests/ only test_ad1270e2c (ScreenStreamConfig); scripts/ 0
HOLDS: yes
CLAIM: no Python test reads the hook or the four caller components
RUN:   Grep "ui/src/hooks|ui[\\/]src[\\/]hooks|useCameraStream|ui/src/components/(perception|profile|settings)" tests/
FOUND: 0
HOLDS: yes
CLAIM: the hook persists nothing
RUN:   Grep localStorage|sessionStorage|indexedDB ui/src/hooks/useScreenStream.ts
FOUND: 0
HOLDS: yes
CLAIM: the new test file does not exist on the base
RUN:   Glob ui/src/hooks/__tests__/useScreen*
FOUND: useScreenShare.test.ts, useScreenStream.test.ts
HOLDS: yes
```
