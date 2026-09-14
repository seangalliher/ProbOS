/** #787 — Voice end-to-end smoke test (deterministic Vitest integration).
 *
 * Wires the REAL <ProfileChatTab> against the REAL transformers.js STT module
 * (`../audio/transformersStt`, Xenova/whisper-tiny.en), mocking ONLY the two
 * stable boundaries that already expose injection seams:
 *   - the Web Worker (via `_setTransformersWorkerOverride`), and
 *   - the PCM tap (`subscribePcm` from `../audio/voiceActivity`).
 * Everything between — the PTT mic button, the BF-308 arm wiring, the BF-310
 * pre-roll, the BF-311 worker round-trip, the BF-294 mic state machine, and the
 * transcript→composer-input hand-off — runs REAL. This is the single red test
 * for the "voice doesn't work" regression class.
 *
 * Coverage map (honest):
 *   CAUGHT:
 *     - BF-308: PCM subscription + worker arm on mic press.
 *     - BF-310: pre-roll prepend (pre-speech frames lead the posted utterance).
 *     - BF-311: worker transcribe round-trip (samples + sampleRate reach the worker).
 *     - BF-294: idle → listening → processing → idle mic state machine.
 *     - the ProfileChatTab ↔ transformersStt transcript-to-input wiring
 *       ("voice produced text" lands in the composer).
 *   NOT CAUGHT (documented residual — forward marker, needs a real-browser
 *   Playwright spec, out of the per-commit gate):
 *     - BF-305: server model-artifact serving + real getUserMedia.
 *     - BF-306/307: real ORT / transformers dependency + dynamic-import specifier
 *       (the FakeWorker bypasses the real module load).
 *     - BF-309/315: worker-internal `_isMeaningfulTranscript` filter.
 *
 * Mock patterns are copied from `transformersStt.bf301.test.tsx` (FakeWorker +
 * subscribePcm capture) and `ProfileChatTab.bf294.test.tsx` / `.ad826.test.tsx`
 * (peripheral audio mocks + voice-health fetch). Two adaptations vs. those
 * sources, both forced by exercising the REAL component end-to-end:
 *   (a) the subscribePcm capture is an ARRAY, not a single slot — ProfileChatTab's
 *       BF-294b amplitude meter ALSO subscribes a tap on listening=true, so the
 *       test selects the STT tap (the one exposing `onSpeechStart`); and
 *   (b) `/api/voice/health` reports a transformers-primary + healthy engine so the
 *       PTT click reaches the REAL `armTransformersStt` branch (mirrors ad826).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import React from 'react';

// PCM-tap boundary (copied mechanism from transformersStt.bf301.test.tsx; the
// single `captured.handler` slot is widened to an array because the REAL
// ProfileChatTab subscribes a SECOND tap (BF-294b amplitude) while listening).
const pcm = vi.hoisted(() => {
  const handlers: any[] = [];
  const subscribePcmMock = vi.fn((handler: any) => {
    handlers.push(handler);
    return () => {
      const i = handlers.indexOf(handler);
      if (i >= 0) handlers.splice(i, 1);
    };
  });
  return { handlers, subscribePcmMock };
});

vi.mock('../audio/voiceActivity', () => ({
  subscribePcm: pcm.subscribePcmMock,
}));

// Peripheral audio modules — mocked exactly as ProfileChatTab.bf294.test.tsx so
// mount is clean. transformersStt and ProfileChatTab are deliberately REAL.
const mocks = vi.hoisted(() => ({
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  armConversationModeMock: vi.fn(() => () => {}),
  disarmConversationModeMock: vi.fn(),
  markAgentReplyCompleteMock: vi.fn(),
  speakResponseMock: vi.fn(),
  onSpeechEventMock: vi.fn(() => () => {}),
}));

vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  onSpeechEvent: mocks.onSpeechEventMock,
}));

vi.mock('../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

vi.mock('../audio/conversationController', () => ({
  armConversationMode: mocks.armConversationModeMock,
  disarmConversationMode: mocks.disarmConversationModeMock,
  markAgentReplyComplete: mocks.markAgentReplyCompleteMock,
}));

import {
  _setTransformersWorkerOverride,
  _resetTransformersStt,
} from '../audio/transformersStt';
import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

/** Minimal MessageChannel-free fake Worker (verbatim from transformersStt.bf301.test.tsx). */
class FakeWorker {
  static instances: FakeWorker[] = [];
  posted: any[] = [];
  terminated = false;
  listeners = new Map<string, Set<(event: MessageEvent) => void>>();

  constructor() {
    FakeWorker.instances.push(this);
  }

  postMessage(message: any, _transfer?: any[]): void {
    this.posted.push(message);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  terminate(): void {
    this.terminated = true;
  }

  /** Simulate a worker → main thread message. */
  emit(data: any, type: string = 'message'): void {
    const event = { data } as MessageEvent;
    for (const listener of [...this.listeners.get(type) ?? []]) listener(event);
  }
}

// Extends bf294's setDefaultFetch with the ad826 voice-health branch: a
// transformers-primary + healthy engine, so the PTT handler takes the REAL
// `armTransformersStt` branch instead of falling through to browser SR.
function setDefaultFetch(primary: 'transformers' | 'browser' = 'transformers'): void {
  global.fetch = vi.fn((url: any) => {
    const target = String(url);
    if (target.endsWith('/api/voice/health')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          primary_stt: primary,
          engine: primary,
          backend_available: true,
          healthy: true,
          model: 'Xenova/whisper-tiny.en',
        }),
      }) as any;
    }
    if (target.endsWith('/chat/history')) {
      return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
    }
    if (target.endsWith('/profile')) {
      return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
    }
    if (target.endsWith('/chat')) {
      return Promise.resolve({ ok: true, json: async () => ({ response: 'Acknowledged.' }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
  }) as any;
}

/** Drain the mount-effect promise chain (fetch → json → setState). Fake timers
 *  do NOT fake the microtask queue, so awaiting resolved promises advances it. */
async function flushMicrotasks(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 10; i++) {
      await Promise.resolve();
    }
  });
}

beforeEach(() => {
  // Fake timers keep every setTimeout deterministic — in particular the
  // transcript handler's trailing setTimeout(sendText, 100) (which clears the
  // input) never auto-fires, so the transcript-to-input assertion is stable.
  vi.useFakeTimers();
  FakeWorker.instances = [];
  pcm.handlers.length = 0;
  pcm.subscribePcmMock.mockClear();
  Object.values(mocks).forEach((m) => {
    if (typeof m === 'function' && 'mockReset' in m) (m as any).mockReset();
  });
  mocks.armConversationModeMock.mockReturnValue(() => {});
  mocks.startListeningMock.mockImplementation(() => ({ cancel: vi.fn() }));
  mocks.speakResponseMock.mockResolvedValue(undefined);
  mocks.onSpeechEventMock.mockReturnValue(() => {});
  localStorage.clear();
  _resetTransformersStt();
  _setTransformersWorkerOverride(() => new FakeWorker() as unknown as Worker);
  useStore.setState({
    voiceEnabled: true,
    agentConversations: new Map(),
  });
  setDefaultFetch();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cleanup();
  _resetTransformersStt();
  vi.useRealTimers();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('#787 voice end-to-end smoke (REAL ProfileChatTab ↔ REAL transformersStt)', () => {
  it.each(['thread', 'away-and-back', 'unmount'] as const)('issue1367 ownership fences a posted job after %s and a fresh explicit capture', async change => {
    useStore.setState({ voiceEnabled: false, activeProfileThreadId: null, threadIdByAgent: new Map() });
    const view = render(<ProfileChatTab agentId="owner" threadId="thread-one" />);
    await flushMicrotasks();
    fireEvent.click(screen.getByLabelText('Voice input'));
    const oldTap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    expect(oldTap).toBeTruthy();
    act(() => {
      oldTap.onSpeechStart(0);
      oldTap.onFrame(new Float32Array([1, 2]), 16000);
      oldTap.onSpeechEnd(100);
    });
    const worker = FakeWorker.instances[0];
    const oldJobs = worker.posted.filter(message => message.type === 'transcribe');
    expect(oldJobs).toHaveLength(1);
    const oldJob = oldJobs[0];
    expect(Array.from(oldJob.samples)).toEqual([1, 2]);
    if (change === 'unmount') {
      view.unmount();
      render(<ProfileChatTab agentId="owner" threadId="thread-one" />);
    } else if (change === 'thread') {
      view.rerender(<ProfileChatTab agentId="owner" threadId="thread-two" />);
    } else {
      view.rerender(<ProfileChatTab agentId="other-owner" threadId="thread-two" />);
      await flushMicrotasks();
      view.rerender(<ProfileChatTab agentId="owner" threadId="thread-one" />);
    }
    await flushMicrotasks();
    expect(pcm.handlers).not.toContain(oldTap);
    fireEvent.click(screen.getByLabelText('Voice input'));
    const freshTap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    expect(freshTap).toBeTruthy();
    expect(freshTap).not.toBe(oldTap);
    act(() => worker.emit({ ...oldJob, type: 'transcript', text: 'retired destination text', isPartial: false, sequence: 1 }));
    await act(async () => vi.advanceTimersByTimeAsync(150));
    expect(screen.getByPlaceholderText('Message...')).toHaveValue('');
    expect(vi.mocked(global.fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toEqual([]);
    expect(mocks.speakResponseMock).not.toHaveBeenCalled();
    act(() => {
      oldTap.onFrame(new Float32Array([99]), 16000);
      oldTap.onSpeechEnd(200);
      freshTap.onSpeechStart(300);
      freshTap.onFrame(new Float32Array([7, 8]), 16000);
      freshTap.onSpeechEnd(400);
    });
    const freshJobs = worker.posted.filter(message => message.type === 'transcribe');
    expect(freshJobs).toHaveLength(2);
    expect(Array.from(freshJobs[1].samples)).toEqual([7, 8]);
    expect(freshJobs[1].captureId).not.toBe(oldJob.captureId);
    expect(worker.terminated).toBe(false);
  });

  it.each([false, true])('issue1367 ownership drops cancelled pre-roll and pending speech window (started=%s)', async started => {
    const view = render(<ProfileChatTab agentId="first" />);
    await flushMicrotasks();
    fireEvent.click(screen.getByLabelText('Voice input'));
    const oldTap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    expect(oldTap).toBeTruthy();
    act(() => {
      oldTap.onFrame(new Float32Array([31, 32]), 16000);
      if (started) oldTap.onSpeechStart(0);
      oldTap.onFrame(new Float32Array([33, 34]), 16000);
    });
    const worker = FakeWorker.instances[0];
    expect(worker.posted.filter(message => message.type === 'transcribe')).toHaveLength(0);
    fireEvent.click(screen.getByLabelText('Stop listening'));
    view.rerender(<ProfileChatTab agentId="second" />);
    await flushMicrotasks();
    fireEvent.click(screen.getByLabelText('Voice input'));
    const freshTap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    expect(freshTap).not.toBe(oldTap);
    act(() => {
      oldTap.onFrame(new Float32Array([99]), 16000);
      oldTap.onSpeechEnd(100);
      freshTap.onFrame(new Float32Array([77]), 16000);
      freshTap.onSpeechEnd(100);
    });
    expect(worker.posted.filter(message => message.type === 'transcribe')).toHaveLength(0);
    act(() => {
      freshTap.onSpeechStart(200);
      freshTap.onFrame(new Float32Array([7, 8]), 16000);
      freshTap.onSpeechEnd(300);
    });
    const jobs = worker.posted.filter(message => message.type === 'transcribe');
    expect(jobs).toHaveLength(1);
    expect(Array.from(jobs[0].samples)).toEqual([7, 8]);
  });

  it('issue1367 ownership keeps a sibling capture and processing alive when another profile unmounts', async () => {
    const first = render(<ProfileChatTab agentId="first" />);
    const second = render(<ProfileChatTab agentId="second" />);
    await flushMicrotasks();
    fireEvent.click(within(first.container).getByLabelText('Voice input'));
    const firstTap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    fireEvent.click(within(second.container).getByLabelText('Voice input'));
    const secondTap = pcm.handlers.filter(handler => typeof handler.onSpeechStart === 'function').slice(-1)[0];
    expect(firstTap).toBeTruthy();
    expect(secondTap).toBeTruthy();
    expect(secondTap).not.toBe(firstTap);
    act(() => {
      for (const tap of [firstTap, secondTap]) {
        tap.onSpeechStart(0);
        tap.onFrame(new Float32Array([1, 2]), 16000);
        tap.onSpeechEnd(100);
      }
    });
    const worker = FakeWorker.instances[0];
    const jobs = worker.posted.filter(message => message.type === 'transcribe');
    expect(jobs).toHaveLength(2);
    expect(within(first.container).getByTestId('mic-indicator')).toHaveAttribute('data-bf294-state', 'processing');
    expect(within(second.container).getByTestId('mic-indicator')).toHaveAttribute('data-bf294-state', 'processing');
    first.unmount();
    expect(pcm.handlers).not.toContain(firstTap);
    expect(pcm.handlers).toContain(secondTap);
    act(() => {
      worker.emit({ ...jobs[0], type: 'transcribing', active: true, sequence: 1 });
      worker.emit({ ...jobs[0], type: 'transcript', text: 'retired sibling', isPartial: false, sequence: 2 });
      worker.emit({ ...jobs[1], type: 'transcript', text: 'unfinished sibling', isPartial: true, sequence: 1 });
    });
    expect(within(second.container).getByTestId('mic-indicator')).toHaveAttribute('data-bf294-state', 'processing');
    expect(screen.getByPlaceholderText('Message...')).toHaveValue('');
    act(() => {
      for (const sequence of [2, 2, 3]) {
        worker.emit({ ...jobs[1], type: 'transcript', text: 'valid sibling', isPartial: false, sequence });
      }
    });
    expect(pcm.handlers).not.toContain(secondTap);
    expect(mocks.speakResponseMock).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTimeAsync(150));
    const posts = vi.mocked(global.fetch).mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe('/api/agent/second/chat');
    expect(JSON.parse(String(posts[0][1]?.body)).message).toBe('valid sibling');
    expect(mocks.speakResponseMock).toHaveBeenCalledTimes(1);
    expect(worker.terminated).toBe(false);
  });

  it('issue1367 ownership uses a fresh local capture after two empty browser results', async () => {
    setDefaultFetch('browser');
    render(<ProfileChatTab agentId="fallback-owner" />);
    await flushMicrotasks();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      fireEvent.click(screen.getByLabelText('Voice input'));
      const empty = mocks.startListeningMock.mock.calls[attempt][1];
      act(() => empty());
    }
    expect(FakeWorker.instances).toHaveLength(0);
    fireEvent.click(screen.getByLabelText('Voice input'));
    expect(FakeWorker.instances).toHaveLength(1);
    const tap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    expect(tap).toBeTruthy();
    act(() => {
      tap.onSpeechStart(0);
      tap.onFrame(new Float32Array([3, 4]), 16000);
      tap.onSpeechEnd(100);
    });
    const worker = FakeWorker.instances[0];
    const jobs = worker.posted.filter(message => message.type === 'transcribe');
    expect(jobs).toHaveLength(1);
    act(() => worker.emit({ ...jobs[0], type: 'transcript', text: 'fallback text', isPartial: false, sequence: 1 }));
    expect(pcm.handlers).not.toContain(tap);
    await act(async () => vi.advanceTimersByTimeAsync(150));
    const posts = vi.mocked(global.fetch).mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe('/api/agent/fallback-owner/chat');
    expect(JSON.parse(String(posts[0][1]?.body)).message).toBe('fallback text');
  });

  it('issue1367 ownership does not arm during StrictMode replay and recovers from a failed explicit start', async () => {
    const view = render(<ProfileChatTab agentId="strict-owner" />, { reactStrictMode: true });
    await flushMicrotasks();
    expect(FakeWorker.instances).toHaveLength(0);
    _setTransformersWorkerOverride(() => { throw new Error('controlled worker startup failure'); });
    fireEvent.click(screen.getByLabelText('Voice input'));
    expect(screen.getByTestId('mic-indicator')).toHaveAttribute('data-bf294-state', 'idle');
    expect(pcm.handlers).toHaveLength(0);
    _setTransformersWorkerOverride(() => new FakeWorker() as unknown as Worker);
    fireEvent.click(screen.getByLabelText('Voice input'));
    expect(FakeWorker.instances).toHaveLength(1);
    expect(pcm.handlers.filter(handler => typeof handler.onSpeechStart === 'function')).toHaveLength(1);
    view.unmount();
    expect(pcm.handlers).toHaveLength(0);
    expect(FakeWorker.instances[0].terminated).toBe(false);
  });

  it.each(['error', 'messageerror', 'model-error'] as const)('issue1367 ownership returns a failed %s capture to idle without inventing text', async failure => {
    render(<ProfileChatTab agentId="fault-owner" />);
    await flushMicrotasks();
    fireEvent.click(screen.getByLabelText('Voice input'));
    const worker = FakeWorker.instances[0];
    const tap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    expect(tap).toBeTruthy();
    act(() => {
      tap.onSpeechStart(0);
      tap.onFrame(new Float32Array([1, 2]), 16000);
      tap.onSpeechEnd(100);
    });
    expect(worker.posted.filter(message => message.type === 'transcribe')).toHaveLength(1);
    expect(screen.getByTestId('mic-indicator')).toHaveAttribute('data-bf294-state', 'processing');
    act(() => {
      if (failure === 'model-error') worker.emit({ type: 'progress', event: { status: 'error' } });
      else worker.emit({}, failure);
    });
    expect(screen.getByTestId('mic-indicator')).toHaveAttribute('data-bf294-state', 'idle');
    expect(pcm.handlers).not.toContain(tap);
    expect(screen.getByPlaceholderText('Message...')).toHaveValue('');
    await act(async () => vi.advanceTimersByTimeAsync(150));
    expect(vi.mocked(global.fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toEqual([]);
    expect(mocks.speakResponseMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('Voice input'));
    expect(pcm.handlers.filter(handler => typeof handler.onSpeechStart === 'function')).toHaveLength(1);
    expect(FakeWorker.instances).toHaveLength(failure === 'model-error' ? 1 : 2);
  });

  it('issue1367 ownership rejects an old posted job after a new participant explicitly starts capture', async () => {
    useStore.setState({ voiceEnabled: false, activeProfileThreadId: null, threadIdByAgent: new Map() });
    const view = render(<ProfileChatTab agentId="first-participant" />);
    await flushMicrotasks();
    fireEvent.click(screen.getByLabelText('Voice input'));
    expect(screen.getByLabelText('Stop listening')).toBeTruthy();
    const tap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    expect(tap).toBeTruthy();
    act(() => {
      tap.onFrame(new Float32Array([0.1, 0.2]), 16000);
      tap.onSpeechStart(0);
      tap.onFrame(new Float32Array([0.3, 0.4]), 16000);
      tap.onSpeechEnd(100);
    });
    expect(FakeWorker.instances).toHaveLength(1);
    const worker = FakeWorker.instances[0];
    const jobs = worker.posted.filter(message => message.type === 'transcribe');
    expect(jobs).toHaveLength(1);
    const oldJob = jobs[0];
    expect(oldJob.samples.length).toBeGreaterThan(0);
    expect(screen.getByTestId('mic-indicator')).toHaveAttribute('data-bf294-state', 'processing');
    fireEvent.click(screen.getByLabelText('Transcribing speech'));
    view.rerender(<ProfileChatTab agentId="second-participant" />);
    await flushMicrotasks();
    fireEvent.click(screen.getByLabelText('Voice input'));
    expect(screen.getByLabelText('Stop listening')).toBeTruthy();

    act(() => worker.emit({
      type: 'transcript', text: 'retired capture text', isPartial: false,
      captureId: oldJob.captureId, jobId: oldJob.jobId, sequence: 1,
    }));
    await act(async () => vi.advanceTimersByTimeAsync(150));

    expect(screen.getByPlaceholderText('Message...')).toHaveValue('');
    const posts = vi.mocked(global.fetch).mock.calls.filter(([url, options]) =>
      String(url).endsWith('/chat') && options?.method === 'POST');
    expect(posts).toEqual([]);
    expect(useStore.getState().agentConversations.get('second-participant')?.messages ?? []).toEqual([]);
    expect(mocks.speakResponseMock).not.toHaveBeenCalled();
    expect(worker.terminated).toBe(false);
    expect(screen.getByLabelText('Stop listening')).toBeTruthy();
    const nextTap = pcm.handlers.find(handler => typeof handler.onSpeechStart === 'function');
    expect(nextTap).toBeTruthy();
    expect(nextTap).not.toBe(tap);
    act(() => {
      nextTap.onSpeechStart(200);
      nextTap.onFrame(new Float32Array([7, 8]), 16000);
      nextTap.onSpeechEnd(300);
    });
    const currentJobs = worker.posted.filter(message => message.type === 'transcribe');
    expect(currentJobs).toHaveLength(2);
    const nextJob = currentJobs[1];
    expect(Array.from(nextJob.samples)).toEqual([7, 8]);
    expect(nextJob.captureId).not.toBe(oldJob.captureId);
    expect(nextJob.jobId).not.toBe(oldJob.jobId);
    act(() => worker.emit({
      type: 'transcript', text: 'new capture text', isPartial: false,
      captureId: nextJob.captureId, jobId: nextJob.jobId, sequence: 1,
    }));
    expect(screen.getByPlaceholderText('Message...')).toHaveValue('new capture text');
    await act(async () => vi.advanceTimersByTimeAsync(150));
    const freshPosts = vi.mocked(global.fetch).mock.calls.filter(([url, options]) =>
      String(url).endsWith('/chat') && options?.method === 'POST');
    expect(freshPosts).toHaveLength(1);
    expect(freshPosts[0][0]).toBe('/api/agent/second-participant/chat');
    expect(JSON.parse(String(freshPosts[0][1]?.body)).message).toBe('new capture text');
  });

  it('mic press → arm → utterance → transcribing → transcript-to-input → idle', async () => {
    render(<ProfileChatTab agentId="yeo" />);
    // Settle mount effects so /api/voice/health is applied before the click.
    await flushMicrotasks();

    // (3) idle by default.
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');

    // voiceHealth applied → the button title reflects the transformers engine,
    // confirming the PTT handler will take the local-STT branch.
    const micButton = screen.getByLabelText('Voice input');
    expect(micButton.getAttribute('title')).toMatch(/transformers/);

    // (4) press the mic — REAL armTransformersStt instantiates the (fake) worker
    // and posts init; mic flips to listening. (BF-308 arm wiring)
    fireEvent.click(micButton);
    expect(FakeWorker.instances).toHaveLength(1);
    expect(FakeWorker.instances[0].posted[0]).toMatchObject({
      type: 'init',
      model: 'Xenova/whisper-tiny.en',
    });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('listening');

    // (5) drive an utterance through the captured PCM tap. ProfileChatTab's
    // BF-294b amplitude meter ALSO subscribes on listening=true, so select the
    // STT tap (the one exposing onSpeechStart). Pre-speech frames seed the
    // BF-310 pre-roll; the prepend makes the posted sample count exceed the
    // in-speech frames. (BF-310 pre-roll + BF-311 worker round-trip)
    const tap = pcm.handlers.find((h) => typeof h?.onSpeechStart === 'function');
    expect(tap).toBeTruthy();
    act(() => {
      tap.onFrame(new Float32Array([0.01, 0.02]), 16000);
      tap.onFrame(new Float32Array([0.03]), 16000);
      tap.onSpeechStart(0);
      tap.onFrame(new Float32Array([0.1, 0.2, 0.3]), 16000);
      tap.onFrame(new Float32Array([0.4, 0.5]), 16000);
      tap.onSpeechEnd(0);
    });

    const worker = FakeWorker.instances[0];
    const transcribeMsg = worker.posted.find((m) => m.type === 'transcribe');
    expect(transcribeMsg).toBeTruthy();
    expect(transcribeMsg.sampleRate).toBe(16000);
    const inSpeechSamples = 5; // [0.1,0.2,0.3] + [0.4,0.5]
    expect(transcribeMsg.samples.length).toBeGreaterThanOrEqual(inSpeechSamples);
    // 3 pre-roll + 5 in-speech — the strict inequality proves the BF-310 prepend.
    expect(transcribeMsg.samples.length).toBe(8);
    const identity = { captureId: transcribeMsg.captureId, jobId: transcribeMsg.jobId };

    // (6) worker signals transcribing → mic flips to processing. (BF-294)
    act(() => {
      worker.emit({ ...identity, type: 'transcribing', active: true, sequence: 1 });
    });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('processing');

    // (7) worker delivers the transcript → REAL transformersStt fans it out to the
    // ProfileChatTab listener, which lands it in the composer input. This is the
    // unique "voice produced text" integration seam.
    act(() => {
      worker.emit({ ...identity, type: 'transcript', text: 'hello world', isPartial: false, sequence: 2 });
    });
    const composer = screen.getByPlaceholderText('Message...') as HTMLInputElement;
    expect(composer.value).toBe('hello world');

    // (8) worker clears transcribing → mic returns to idle. (BF-294)
    act(() => {
      worker.emit({ ...identity, type: 'transcribing', active: false, sequence: 3 });
      worker.emit({ ...identity, type: 'complete', outcome: 'success', sequence: 4 });
    });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
  });
});
