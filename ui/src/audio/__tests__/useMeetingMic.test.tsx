/** AD-922: useMeetingMic hook tests. The STT (`../transformersStt`), the SR
 *  availability probe (`../speechInput`), and the mic-permission source
 *  (`../wakeWord`) are MOCKED; `submit` is a fake. No real audio, no real mic.
 *  The hook is a pure-DI lifecycle (it also accepts a `deps` seam), so these
 *  tests drive it through the default module mocks to prove the real wiring. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import * as voiceActivity from '../voiceActivity';

const mocks = vi.hoisted(() => ({
  arm: vi.fn(() => () => {}),
  disarm: vi.fn(),
  transcriptListeners: new Set<(t: string) => void>(),
  onTranscript: vi.fn(),
  isSupported: vi.fn(() => true),
  micListeners: new Set<(s: string) => void>(),
  getMicState: vi.fn(() => 'granted'),
  onMicState: vi.fn(),
}));

vi.mock('../transformersStt', () => ({
  armTransformersStt: mocks.arm,
  disarmTransformersStt: mocks.disarm,
  onTransformersTranscript: (l: (t: string) => void) => {
    mocks.onTranscript(l);
    mocks.transcriptListeners.add(l);
    return () => mocks.transcriptListeners.delete(l);
  },
}));

vi.mock('../speechInput', () => ({
  isSpeechRecognitionSupported: () => mocks.isSupported(),
}));

vi.mock('../wakeWord', () => ({
  getMicPermissionState: () => mocks.getMicState(),
  onMicPermissionState: (l: (s: string) => void) => {
    mocks.micListeners.add(l);
    return () => mocks.micListeners.delete(l);
  },
}));

import { useMeetingMic } from '../useMeetingMic';
import useMeetingMicSource from '../useMeetingMic?raw';

function fireTranscript(text: string): void {
  for (const l of Array.from(mocks.transcriptListeners)) l(text);
}

describe('issue1367 ownership useMeetingMic real STT', () => {
  type PostedJob = {
    type: 'transcribe'; samples: Float32Array; sampleRate: number;
    captureId?: string; jobId?: string;
  };

  async function setupCapture() {
    const stt = await vi.importActual<typeof import('../transformersStt')>('../transformersStt');
    stt._resetTransformersStt();
    const taps = new Set<voiceActivity.PcmTapHandler>();
    const jobs: PostedJob[] = [];
    const sequences = new Map<PostedJob, number>();
    const events = new Map<string, Set<EventListener>>();
    const worker = {
      postMessage: vi.fn((message: { type: string }) => {
        if (message.type === 'transcribe') jobs.push(message as PostedJob);
      }),
      addEventListener: (type: string, listener: EventListener) => {
        if (!events.has(type)) events.set(type, new Set());
        events.get(type)!.add(listener);
      },
      removeEventListener: (type: string, listener: EventListener) => { events.get(type)?.delete(listener); },
      terminate: vi.fn(),
    };
    const pcmSpy = vi.spyOn(voiceActivity, 'subscribePcm').mockImplementation((handler) => {
      taps.add(handler);
      return () => { taps.delete(handler); };
    });
    stt._setTransformersWorkerOverride(() => worker as unknown as Worker);
    const deps = {
      arm: vi.fn(() => stt.armTransformersStt()),
      disarm: vi.fn(() => stt.disarmTransformersStt()),
      onTranscript: vi.fn((listener: (text: string) => void) => stt.onTransformersTranscript(listener)),
    };
    const start = (): void => { for (const tap of [...taps]) tap.onSpeechStart?.(0); };
    const frame = (samples: number[]): void => {
      for (const tap of [...taps]) tap.onFrame(new Float32Array(samples), 16000);
    };
    const end = (): void => { for (const tap of [...taps]) tap.onSpeechEnd?.(30); };
    const utterance = (samples: number[]): PostedJob[] => {
      const before = jobs.length;
      start(); frame(samples); end();
      return jobs.slice(before);
    };
    const reply = (job: PostedJob, payload: Record<string, unknown>): void => {
      const sequence = (sequences.get(job) ?? 0) + 1;
      sequences.set(job, sequence);
      const event = new MessageEvent('message', {
        data: { ...payload, captureId: job.captureId, jobId: job.jobId, sequence },
      });
      for (const listener of [...(events.get('message') ?? [])]) listener(event);
    };
    const finish = (job: PostedJob, text: string): void => {
      reply(job, { type: 'transcribing', active: true });
      reply(job, { type: 'transcript', text, isPartial: false });
      reply(job, { type: 'transcribing', active: false });
      reply(job, { type: 'complete', outcome: 'success' });
    };
    const dispose = (): void => {
      cleanup();
      stt._resetTransformersStt();
      taps.clear();
      pcmSpy.mockRestore();
    };
    return { stt, deps, taps, jobs, worker, start, frame, end, utterance, reply, finish, dispose };
  }

  it.each(['success', 'empty', 'error'] as const)('subscribe-before-arm routes a genuine legacy job: %s', async (outcome) => {
    const capture = await setupCapture();
    const submit = vi.fn();
    try {
      const { result } = renderHook(() => useMeetingMic({ meetingActive: true, speaking: false, submit, deps: capture.deps }));
      act(() => { result.current.toggleCapture(); });
      expect(capture.deps.arm).toHaveBeenCalledWith();
      expect(capture.deps.onTranscript.mock.invocationCallOrder[0]).toBeLessThan(capture.deps.arm.mock.invocationCallOrder[0]);
      expect(result.current.capturing).toBe(true);
      expect(capture.stt._isArmed()).toBe(true);
      const posted = capture.utterance([0.125, 0.25, 0.5]);
      expect(posted).toHaveLength(1);
      const job = posted[0];
      expect(Array.from(job.samples)).toEqual([0.125, 0.25, 0.5]);
      expect(job.sampleRate).toBe(16000);
      expect(job.captureId).toEqual(expect.any(String));
      expect(job.jobId).toEqual(expect.any(String));
      act(() => {
        if (outcome === 'error') capture.reply(job, { type: 'complete', outcome: 'error' });
        else capture.finish(job, outcome === 'empty' ? '   ' : '  legacy meeting report  ');
      });
      if (outcome === 'success') {
        expect(submit.mock.calls).toEqual([['legacy meeting report']]);
        expect(result.current.capturing).toBe(false);
        expect(capture.deps.disarm).toHaveBeenCalledTimes(1);
        expect(capture.taps.size).toBe(0);
      } else {
        expect(submit).not.toHaveBeenCalled();
        expect(result.current.capturing).toBe(true);
      }
      act(() => { capture.finish(job, 'late settled meeting text'); });
      expect(submit).toHaveBeenCalledTimes(outcome === 'success' ? 1 : 0);
    } finally { capture.dispose(); }
  });

  it.each(['cancel', 'unmount', 'delivery'] as const)('%s globally disarms legacy capture without cancelling scoped PCM', async (shutdown) => {
    const capture = await setupCapture();
    const releases: Array<() => void> = [];
    const submit = vi.fn();
    const scopedTranscript = vi.fn();
    try {
      let hook = renderHook(() => useMeetingMic({ meetingActive: true, speaking: false, submit, deps: capture.deps }));
      act(() => { hook.result.current.toggleCapture(); });
      const oldJobs = capture.utterance([0.125]);
      expect(oldJobs).toHaveLength(1);
      expect(Array.from(oldJobs[0].samples)).toEqual([0.125]);
      const scope = Symbol('meeting sibling');
      releases.push((capture.stt.onTransformersTranscript as (listener: (text: string) => void, scope?: symbol) => () => void)(scopedTranscript, scope));
      releases.push((capture.stt.armTransformersStt as (scope?: symbol) => () => void)(scope));
      capture.start(); capture.frame([0.5, 0.25]);
      if (shutdown === 'unmount') hook.unmount();
      else if (shutdown === 'cancel') act(() => { hook.result.current.toggleCapture(); });
      else {
        expect(oldJobs[0].captureId).toEqual(expect.any(String));
        expect(oldJobs[0].jobId).toEqual(expect.any(String));
        act(() => { capture.finish(oldJobs[0], 'accepted meeting report'); });
        expect(submit.mock.calls).toEqual([['accepted meeting report']]);
        submit.mockClear();
      }
      expect(capture.deps.disarm).toHaveBeenCalledTimes(1);
      const before = capture.jobs.length;
      capture.frame([0.75]); capture.end();
      const survivors = capture.jobs.slice(before);
      expect(survivors).toHaveLength(1);
      const survivor = survivors[0];
      expect(Array.from(survivor.samples)).toEqual([0.5, 0.25, 0.75]);
      expect(survivor.captureId).toEqual(expect.any(String));
      expect(survivor.captureId).not.toBe(oldJobs[0].captureId);
      expect(capture.worker.terminate).not.toHaveBeenCalled();
      if (shutdown === 'unmount') hook = renderHook(() => useMeetingMic({ meetingActive: true, speaking: false, submit, deps: capture.deps }));
      act(() => { hook.result.current.toggleCapture(); });
      expect(hook.result.current.capturing).toBe(true);
      act(() => {
        capture.finish(oldJobs[0], 'cancelled meeting text');
        capture.finish(survivor, 'private scoped meeting text');
      });
      expect(submit).not.toHaveBeenCalled();
      expect(hook.result.current.capturing).toBe(true);
      expect(scopedTranscript.mock.calls).toEqual([['private scoped meeting text']]);
      const fresh = capture.utterance([0.875]);
      expect(fresh).toHaveLength(2);
      const legacy = fresh.find((job) => job.captureId !== survivor.captureId)!;
      const sibling = fresh.find((job) => job.captureId === survivor.captureId)!;
      expect(legacy).toBeDefined();
      expect(sibling).toBeDefined();
      expect(Array.from(legacy.samples)).toEqual([0.875]);
      act(() => { capture.finish(legacy, 'fresh meeting report'); capture.finish(sibling, 'fresh scoped report'); });
      expect(submit.mock.calls).toEqual([['fresh meeting report']]);
      expect(hook.result.current.capturing).toBe(false);
      expect(scopedTranscript.mock.calls).toEqual([['private scoped meeting text'], ['fresh scoped report']]);
      expect(capture.worker.postMessage.mock.calls.filter(([message]) => message.type === 'init')).toHaveLength(1);
    } finally {
      for (const release of releases.reverse()) release();
      capture.dispose();
    }
  });
});

beforeEach(() => {
  mocks.arm.mockReset().mockReturnValue(() => {});
  mocks.disarm.mockReset();
  mocks.onTranscript.mockReset();
  mocks.isSupported.mockReset().mockReturnValue(true);
  mocks.getMicState.mockReset().mockReturnValue('granted');
  mocks.transcriptListeners.clear();
  mocks.micListeners.clear();
});

describe('useMeetingMic', () => {
  it('test_transcript_in_meeting_calls_submit_with_text', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    act(() => { fireTranscript('  status report  '); });
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith('status report');
  });

  it('test_arm_subscribes_and_disarms_after_transcript', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    expect(mocks.arm).toHaveBeenCalledTimes(1);
    act(() => { fireTranscript('hello'); });
    expect(mocks.disarm).toHaveBeenCalled();
    expect(result.current.capturing).toBe(false);
  });

  it('test_not_armed_when_meeting_inactive', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: false, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    expect(mocks.arm).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
  });

  it('test_not_armed_while_agent_speaking', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: true, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    expect(mocks.arm).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
  });

  it('test_blocked_when_mic_denied', () => {
    mocks.getMicState.mockReturnValue('denied');
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    expect(result.current.blocked).toBe(true);
    act(() => { result.current.toggleCapture(); });
    expect(mocks.arm).not.toHaveBeenCalled();
  });

  it('test_supported_false_when_sr_unavailable', () => {
    mocks.isSupported.mockReturnValue(false);
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    expect(result.current.supported).toBe(false);
  });

  it('test_second_toggle_cancels_capture', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    expect(result.current.capturing).toBe(true);
    act(() => { result.current.toggleCapture(); });
    expect(mocks.disarm).toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
    expect(result.current.capturing).toBe(false);
  });

  it('test_empty_transcript_does_not_submit', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    act(() => { fireTranscript('   '); });
    expect(submit).not.toHaveBeenCalled();
    expect(result.current.capturing).toBe(false);
  });

  it('test_one_shot_listener_torn_down', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    act(() => { fireTranscript('first'); });
    act(() => { fireTranscript('second'); });
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith('first');
  });

  it('test_no_emoji_in_source', () => {
    expect(useMeetingMicSource).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
