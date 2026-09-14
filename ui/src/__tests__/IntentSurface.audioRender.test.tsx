// AD-720e (Wave 159): audio attachment renders as <audio controls>; non-image,
// non-audio falls back to file icon; image still renders as <img>.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act, waitFor } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';
import { useSettingsStore } from '../store/useSettingsStore';
import * as voiceActivity from '../audio/voiceActivity';
import * as wakeWord from '../audio/wakeWord';
import { soundEngine } from '../audio/soundEngine';

function uploadResponse(mime: string, sha: string) {
  return {
    ok: true,
    json: async () => ({
      attachment_id: sha,
      url: '/api/chat/attachments/' + sha,
      mime,
      sha256: sha,
      size_bytes: 8,
    }),
  };
}

describe('issue1367 ownership IntentSurface real STT', () => {
  type PostedJob = {
    type: 'transcribe'; samples: Float32Array; sampleRate: number;
    captureId?: string; jobId?: string;
  };

  async function setupCapture() {
    const stt = await vi.importActual<typeof import('../audio/transformersStt')>('../audio/transformersStt');
    stt._resetTransformersStt();
    vi.useFakeTimers();
    const previousSettings = useSettingsStore.getState();
    const previousStore = useStore.getState();
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
    vi.spyOn(voiceActivity, 'subscribePcm').mockImplementation((handler) => {
      taps.add(handler);
      return () => { taps.delete(handler); };
    });
    vi.spyOn(wakeWord, 'startWakeWordLoop').mockResolvedValue(undefined);
    vi.spyOn(wakeWord, 'stopWakeWordLoop').mockImplementation(() => {});
    vi.spyOn(soundEngine, 'playIntentRouting').mockImplementation(() => {});
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ response: 'Acknowledged.' }),
    } as Response);
    const submissions = () => fetchSpy.mock.calls.filter(([url, options]) =>
      String(url) === '/api/chat' && options?.method === 'POST');
    stt._setTransformersWorkerOverride(() => worker as unknown as Worker);
    const armSpy = vi.spyOn(stt, 'armTransformersStt');
    const subscribeSpy = vi.spyOn(stt, 'onTransformersTranscript');
    useSettingsStore.setState({ snapshot: {
      config: { cognitive: { offline_stt_enabled: true } }, secret_present: {},
      sections: [], domain_counts: {}, domain_order: [], section_count: 0,
      config_path: '', uptime_seconds: 0, csrf_token: '',
    } });
    useStore.setState({ wakeWordEnabled: true, voiceEnabled: false, processing: false, bridgeOpen: false });
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
      useSettingsStore.setState(previousSettings, true);
      useStore.setState(previousStore, true);
      vi.clearAllTimers();
      vi.useRealTimers();
    };
    return { stt, taps, jobs, worker, armSpy, subscribeSpy, submissions, start, frame, end, utterance, reply, finish, dispose };
  }

  it.each(['success', 'empty', 'error'] as const)('arm-before-subscribe routes a genuine legacy job: %s', async (outcome) => {
    const capture = await setupCapture();
    try {
      render(<IntentSurface />);
      expect(capture.armSpy).toHaveBeenCalledWith();
      expect(capture.armSpy.mock.invocationCallOrder[0]).toBeLessThan(capture.subscribeSpy.mock.invocationCallOrder[0]);
      expect(capture.stt._isArmed()).toBe(true);
      let posted: PostedJob[] = [];
      act(() => { posted = capture.utterance([0.125, 0.25, 0.5]); });
      expect(posted).toHaveLength(1);
      const job = posted[0];
      expect(Array.from(job.samples)).toEqual([0.125, 0.25, 0.5]);
      expect(job.sampleRate).toBe(16000);
      expect(job.captureId).toEqual(expect.any(String));
      expect(job.jobId).toEqual(expect.any(String));
      act(() => {
        if (outcome === 'error') capture.reply(job, { type: 'complete', outcome: 'error' });
        else capture.finish(job, outcome === 'empty' ? '   ' : 'legacy surface report');
      });
      if (outcome === 'success') {
        expect(screen.getByPlaceholderText('Ask ProbOS...')).toHaveValue('legacy surface report');
      }
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      if (outcome === 'success') {
        expect(capture.submissions()).toHaveLength(1);
        expect(JSON.parse(String(capture.submissions()[0][1]?.body)).message).toBe('legacy surface report');
        expect(useStore.getState().chatHistory.filter((message) => message.role === 'user').map((message) => message.text))
          .toEqual(['legacy surface report']);
        expect(screen.getByText('legacy surface report')).toBeTruthy();
      } else {
        expect(capture.submissions()).toEqual([]);
        expect(useStore.getState().chatHistory).toEqual([]);
      }
      act(() => { capture.finish(job, 'late settled surface text'); });
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(capture.submissions()).toHaveLength(outcome === 'success' ? 1 : 0);
    } finally { capture.dispose(); }
  });

  it.each(['disable', 'unmount'] as const)('%s preserves scoped PCM and fences late legacy replies from the restarted UI', async (shutdown) => {
    const capture = await setupCapture();
    const releases: Array<() => void> = [];
    try {
      let surface = render(<IntentSurface />);
      let oldJobs: PostedJob[] = [];
      act(() => { oldJobs = capture.utterance([0.125]); });
      expect(oldJobs).toHaveLength(1);
      expect(Array.from(oldJobs[0].samples)).toEqual([0.125]);
      const scope = Symbol('surface sibling');
      const scopedTranscript = vi.fn();
      releases.push((capture.stt.onTransformersTranscript as (listener: (text: string) => void, scope?: symbol) => () => void)(scopedTranscript, scope));
      releases.push((capture.stt.armTransformersStt as (scope?: symbol) => () => void)(scope));
      act(() => { capture.start(); capture.frame([0.5, 0.25]); });
      if (shutdown === 'disable') act(() => { useStore.setState({ wakeWordEnabled: false }); });
      else surface.unmount();
      const before = capture.jobs.length;
      act(() => { capture.frame([0.75]); capture.end(); });
      const survivors = capture.jobs.slice(before);
      expect(survivors).toHaveLength(1);
      const survivor = survivors[0];
      expect(Array.from(survivor.samples)).toEqual([0.5, 0.25, 0.75]);
      expect(survivor.captureId).toEqual(expect.any(String));
      expect(survivor.captureId).not.toBe(oldJobs[0].captureId);
      expect(capture.worker.terminate).not.toHaveBeenCalled();
      expect(capture.worker.postMessage.mock.calls.filter(([message]) => message.type === 'init')).toHaveLength(1);
      if (shutdown === 'disable') act(() => { useStore.setState({ wakeWordEnabled: true }); });
      else surface = render(<IntentSurface />);
      act(() => {
        capture.finish(oldJobs[0], 'cancelled surface text');
        capture.finish(survivor, 'private scoped surface text');
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(scopedTranscript.mock.calls).toEqual([['private scoped surface text']]);
      expect(capture.submissions()).toEqual([]);
      expect(useStore.getState().chatHistory).toEqual([]);
      expect(screen.queryByDisplayValue(/cancelled surface|private scoped/)).toBeNull();
      let fresh: PostedJob[] = [];
      act(() => { fresh = capture.utterance([0.875]); });
      expect(fresh).toHaveLength(2);
      const legacy = fresh.find((job) => job.captureId !== survivor.captureId)!;
      const sibling = fresh.find((job) => job.captureId === survivor.captureId)!;
      expect(legacy).toBeDefined();
      expect(sibling).toBeDefined();
      expect(Array.from(legacy.samples)).toEqual([0.875]);
      act(() => { capture.finish(legacy, 'fresh surface report'); capture.finish(sibling, 'fresh scoped report'); });
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(capture.submissions()).toHaveLength(1);
      expect(JSON.parse(String(capture.submissions()[0][1]?.body)).message).toBe('fresh surface report');
      expect(scopedTranscript.mock.calls).toEqual([['private scoped surface text'], ['fresh scoped report']]);
      expect(useStore.getState().chatHistory.filter((message) => message.role === 'user').map((message) => message.text))
        .toEqual(['fresh surface report']);
      surface.unmount();
    } finally {
      for (const release of releases.reverse()) release();
      capture.dispose();
    }
  });
});

beforeEach(() => {
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    agents: new Map(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function openShell() {
  render(<IntentSurface />);
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

function makeDropEvent(file: File) {
  return {
    preventDefault: vi.fn(),
    dataTransfer: {
      files: [file],
      types: ['Files'],
    },
  };
}

async function dropFile(blob: Blob, name: string, mime: string) {
  const form = document.querySelector('form');
  if (!form) throw new Error('composer form not mounted');
  const file = new File([blob], name, { type: mime });
  await act(async () => {
    fireEvent.drop(form, makeDropEvent(file));
  });
}

describe('IntentSurface AD-720e — audio attachment render', () => {
  it('audio/mpeg attachment renders as <audio controls>', async () => {
    global.fetch = vi.fn().mockResolvedValue(uploadResponse('audio/mpeg', 'aa'.repeat(32))) as unknown as typeof fetch;
    openShell();
    const blob = new Blob([new Uint8Array([0x49, 0x44, 0x33, 0x03])], { type: 'audio/mpeg' });
    await dropFile(blob, 'clip.mp3', 'audio/mpeg');
    await waitFor(() => {
      expect(screen.queryByTestId('attachment-preview')).toBeTruthy();
    });
    const audio = document.querySelector('audio[controls]');
    expect(audio).toBeTruthy();
    expect((audio as HTMLAudioElement).src).toContain('/api/chat/attachments/' + 'aa'.repeat(32));
  });

  it('image/png attachment still renders as <img> (regression)', async () => {
    global.fetch = vi.fn().mockResolvedValue(uploadResponse('image/png', 'bb'.repeat(32))) as unknown as typeof fetch;
    openShell();
    const blob = new Blob([new Uint8Array([0x89, 0x50])], { type: 'image/png' });
    await dropFile(blob, 'pic.png', 'image/png');
    await waitFor(() => {
      expect(screen.queryByTestId('attachment-preview')).toBeTruthy();
    });
    expect(document.querySelector('img')).toBeTruthy();
    expect(document.querySelector('audio')).toBeNull();
  });

  it('application/pdf attachment renders the file-icon fallback', async () => {
    global.fetch = vi.fn().mockResolvedValue(uploadResponse('application/pdf', 'cc'.repeat(32))) as unknown as typeof fetch;
    openShell();
    const blob = new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46])], { type: 'application/pdf' });
    await dropFile(blob, 'doc.pdf', 'application/pdf');
    await waitFor(() => {
      expect(screen.queryByTestId('attachment-preview')).toBeTruthy();
    });
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('audio')).toBeNull();
    // File-icon branch renders an inline svg next to the filename.
    const preview = screen.getByTestId('attachment-preview');
    expect(preview.querySelector('svg')).toBeTruthy();
  });
});
