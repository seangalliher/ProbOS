/** AD-921: useMeetingVoice hook tests. The sequencer (``./meetingVoice``) and
 *  the audio layer (``./voice``) are MOCKED; the Zustand store is the REAL
 *  store seeded via ``useStore.setState`` (BF-287 -- never MagicMock at the
 *  store boundary). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  speakRepliesSequentially: vi.fn(),
}));

vi.mock('../meetingVoice', () => ({
  speakRepliesSequentially: mocks.speakRepliesSequentially,
  createVoiceProfileResolver: vi.fn(() => async () => undefined),
}));

vi.mock('../voice', () => ({
  speakResponse: vi.fn(),
  flushSpeechQueue: vi.fn(),
  onSpeechEvent: vi.fn(() => () => {}),
  stripMarkdownForSpeech: (s: string) => s,
  prewarmTts: vi.fn(),
}));

import { useMeetingVoice } from '../useMeetingVoice';
import { useStore } from '../../store/useStore';
import type { PerAgentReply } from '../meetingVoice';
import useMeetingVoiceSource from '../useMeetingVoice?raw';
import { flushSpeechQueue, prewarmTts, speakResponse } from '../voice';
import { createVoiceProfileResolver } from '../meetingVoice';

beforeEach(() => {
  mocks.speakRepliesSequentially.mockReset();
  mocks.speakRepliesSequentially.mockImplementation(() => new Promise<void>(() => {}));
  vi.mocked(speakResponse).mockClear();
  vi.mocked(flushSpeechQueue).mockClear();
  useStore.setState({ callAudioEnabled: false });
});

const reply = (id: string): PerAgentReply => ({ agent_id: id, text: `text-${id}` });

function pendingBatch(): { promise: Promise<void>; resolve: () => void; reject: (error: Error) => void } {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('useMeetingVoice', () => {
  it('settles once after the batch while revealing only each completed author', async () => {
    const batch = pendingBatch();
    mocks.speakRepliesSequentially.mockReturnValueOnce(batch.promise);
    useStore.setState({ callAudioEnabled: true });
    const { result, unmount } = renderHook(() => useMeetingVoice({ meetingActive: true }));
    const onBatchSettled = vi.fn();
    const onUtteranceEnd = vi.fn();
    const replies = [reply('first'), reply('second')];
    act(() => { result.current.speakReplies(replies, { onBatchSettled, onUtteranceEnd }); });
    const deps = mocks.speakRepliesSequentially.mock.calls[0][1];
    act(() => { deps.onSpeakingChange('first'); deps.onUtteranceStart(replies[0]); });
    expect(onUtteranceEnd).not.toHaveBeenCalled();
    expect(onBatchSettled).not.toHaveBeenCalled();
    act(() => { deps.onUtteranceEnd(replies[0]); });
    expect(onUtteranceEnd.mock.calls).toEqual([[replies[0]]]);
    expect(onBatchSettled).not.toHaveBeenCalled();
    act(() => { deps.onUtteranceEnd(replies[1]); });
    expect(onUtteranceEnd.mock.calls).toEqual([[replies[0]], [replies[1]]]);
    await act(async () => { batch.resolve(); });
    expect(onBatchSettled).toHaveBeenCalledTimes(1);
    expect(result.current.speakingAgentId).toBeNull();
    unmount();
    expect(onBatchSettled).toHaveBeenCalledTimes(1);
  });

  it.each(['empty', 'inactive', 'muted', 'rejected', 'unmounted'] as const)(
    'settles %s input exactly once without starting speech', (scenario) => {
      useStore.setState({ callAudioEnabled: scenario !== 'muted' });
      const { result, unmount } = renderHook(() => useMeetingVoice({ meetingActive: scenario !== 'inactive' }));
      const speakReplies = result.current.speakReplies;
      if (scenario === 'unmounted') unmount();
      const onBatchSettled = vi.fn();
      act(() => {
        speakReplies(scenario === 'empty' ? [] : [reply('first')], {
          onBatchSettled, shouldContinue: () => scenario !== 'rejected',
        });
      });
      expect(onBatchSettled).toHaveBeenCalledTimes(1);
      expect(mocks.speakRepliesSequentially).not.toHaveBeenCalled();
      if (scenario !== 'unmounted') unmount();
      expect(onBatchSettled).toHaveBeenCalledTimes(1);
    },
  );

  it.each(['throw', 'reject'] as const)('settles once when the sequencer fails by %s', async (scenario) => {
    const batch = pendingBatch();
    mocks.speakRepliesSequentially.mockImplementationOnce(() => {
      if (scenario === 'throw') throw new Error('sequencer failed');
      return batch.promise;
    });
    useStore.setState({ callAudioEnabled: true });
    const { result, unmount } = renderHook(() => useMeetingVoice({ meetingActive: true }));
    const onBatchSettled = vi.fn();
    await act(async () => {
      result.current.speakReplies([reply('first')], { onBatchSettled });
      if (scenario === 'reject') batch.reject(new Error('sequencer failed'));
    });
    expect(onBatchSettled).toHaveBeenCalledTimes(1);
    unmount();
    expect(onBatchSettled).toHaveBeenCalledTimes(1);
  });

  it.each(['unmount', 'mute', 'scope', 'meeting', 'owner'] as const)(
    'settles pending speech promptly on %s and ignores late completion', async (scenario) => {
      const batch = pendingBatch();
      mocks.speakRepliesSequentially.mockReturnValueOnce(batch.promise);
      useStore.setState({ callAudioEnabled: true });
      const { result, rerender, unmount } = renderHook((opts) => useMeetingVoice(opts), {
        initialProps: { meetingActive: true, scopeKey: 'origin', owner: 'surface-origin' },
      });
      const onBatchSettled = vi.fn();
      const onUtteranceEnd = vi.fn();
      act(() => { result.current.speakReplies([reply('first')], { onBatchSettled, onUtteranceEnd }); });
      const deps = mocks.speakRepliesSequentially.mock.calls[0][1];
      expect(deps.shouldContinue()).toBe(true);
      expect(onBatchSettled).not.toHaveBeenCalled();
      if (scenario === 'unmount') unmount();
      else if (scenario === 'mute') act(() => { useStore.getState().setCallAudioEnabled(false); });
      else rerender({
        meetingActive: scenario !== 'meeting',
        scopeKey: scenario === 'scope' ? 'destination' : 'origin',
        owner: scenario === 'owner' ? 'surface-next' : 'surface-origin',
      });
      expect(onBatchSettled).toHaveBeenCalledTimes(1);
      expect(flushSpeechQueue).toHaveBeenCalledTimes(1);
      expect(flushSpeechQueue).toHaveBeenCalledWith('meeting-context-ended', 'surface-origin');
      expect(deps.shouldContinue()).toBe(false);
      await act(async () => { deps.onUtteranceEnd(reply('first')); batch.resolve(); });
      expect(onUtteranceEnd).not.toHaveBeenCalled();
      expect(onBatchSettled).toHaveBeenCalledTimes(1);
    },
  );

  it('supersedes once without letting old settlement or a rejected receipt clear the next batch', async () => {
    const oldBatch = pendingBatch();
    const nextBatch = pendingBatch();
    mocks.speakRepliesSequentially.mockReturnValueOnce(oldBatch.promise).mockReturnValueOnce(nextBatch.promise);
    useStore.setState({ callAudioEnabled: true });
    const { result, unmount } = renderHook(() => useMeetingVoice({ meetingActive: true, owner: 'surface' }));
    const oldSettled = vi.fn();
    const nextSettled = vi.fn();
    const rejectedSettled = vi.fn();
    act(() => { result.current.speakReplies([reply('old')], { onBatchSettled: oldSettled }); });
    const oldDeps = mocks.speakRepliesSequentially.mock.calls[0][1];
    act(() => { result.current.speakReplies([reply('next')], { onBatchSettled: nextSettled }); });
    const nextDeps = mocks.speakRepliesSequentially.mock.calls[1][1];
    act(() => { nextDeps.onSpeakingChange('next'); });
    expect(oldSettled).toHaveBeenCalledTimes(1);
    expect(nextSettled).not.toHaveBeenCalled();
    act(() => {
      result.current.speakReplies([reply('stale-room')], {
        onBatchSettled: rejectedSettled, shouldContinue: () => false,
      });
    });
    await act(async () => { oldBatch.resolve(); oldDeps.onSpeakingChange(null); });
    expect(rejectedSettled).toHaveBeenCalledTimes(1);
    expect(oldSettled).toHaveBeenCalledTimes(1);
    expect(nextSettled).not.toHaveBeenCalled();
    expect(result.current.speakingAgentId).toBe('next');
    expect(nextDeps.shouldContinue()).toBe(true);
    unmount();
    expect(nextSettled).toHaveBeenCalledTimes(1);
    await act(async () => { nextBatch.resolve(); });
    expect(nextSettled).toHaveBeenCalledTimes(1);
  });

  it.each(['gate-exit', 'empty-supersession'] as const)('settles pending speech on %s', async (scenario) => {
    const batch = pendingBatch();
    mocks.speakRepliesSequentially.mockReturnValueOnce(batch.promise);
    useStore.setState({ callAudioEnabled: true });
    const { result, unmount } = renderHook(() => useMeetingVoice({ meetingActive: true }));
    let allowed = true;
    const onBatchSettled = vi.fn();
    const emptySettled = vi.fn();
    act(() => {
      result.current.speakReplies([reply('first')], { onBatchSettled, shouldContinue: () => allowed });
    });
    const deps = mocks.speakRepliesSequentially.mock.calls[0][1];
    expect(deps.shouldContinue()).toBe(true);
    expect(onBatchSettled).not.toHaveBeenCalled();
    act(() => {
      if (scenario === 'gate-exit') allowed = false;
      else result.current.speakReplies([], { onBatchSettled: emptySettled });
      expect(deps.shouldContinue()).toBe(false);
    });
    expect(onBatchSettled).toHaveBeenCalledTimes(1);
    expect(emptySettled).toHaveBeenCalledTimes(scenario === 'empty-supersession' ? 1 : 0);
    expect(mocks.speakRepliesSequentially).toHaveBeenCalledTimes(1);
    await act(async () => { batch.resolve(); });
    unmount();
    expect(onBatchSettled).toHaveBeenCalledTimes(1);
    expect(emptySettled).toHaveBeenCalledTimes(scenario === 'empty-supersession' ? 1 : 0);
  });

  it('test_no_speak_when_meeting_inactive', () => {
    useStore.setState({ callAudioEnabled: true });
    const { result } = renderHook(() => useMeetingVoice({ meetingActive: false }));
    act(() => { result.current.speakReplies([reply('a')]); });
    expect(mocks.speakRepliesSequentially).not.toHaveBeenCalled();
  });

  it.each([false, true])('does not flush narration without a meeting batch (active=%s)', (meetingActive) => {
    const { unmount } = renderHook(() => useMeetingVoice({ meetingActive, owner: 'solo-narration-owner' }));
    act(() => { useStore.setState({ callAudioEnabled: true }); });
    act(() => { useStore.setState({ callAudioEnabled: false }); });
    unmount();
    expect(mocks.speakRepliesSequentially).not.toHaveBeenCalled();
    expect(flushSpeechQueue).not.toHaveBeenCalled();
  });

  it('test_speaks_when_meeting_active_and_call_audio_enabled', () => {
    useStore.setState({ callAudioEnabled: true });
    const { result } = renderHook(() => useMeetingVoice({ meetingActive: true }));
    const replies = [reply('a'), reply('b')];
    act(() => { result.current.speakReplies(replies); });
    expect(mocks.speakRepliesSequentially).toHaveBeenCalledTimes(1);
    expect(mocks.speakRepliesSequentially.mock.calls[0][0]).toBe(replies);
  });

  it('test_no_speak_when_call_audio_disabled', () => {
    useStore.setState({ callAudioEnabled: false });
    const { result } = renderHook(() => useMeetingVoice({ meetingActive: true }));
    act(() => { result.current.speakReplies([reply('a')]); });
    expect(mocks.speakRepliesSequentially).not.toHaveBeenCalled();
  });

  it('test_speaking_agent_id_reflects_sequencer', () => {
    useStore.setState({ callAudioEnabled: true });
    const { result } = renderHook(() => useMeetingVoice({ meetingActive: true }));
    act(() => { result.current.speakReplies([reply('bones')]); });
    const deps = mocks.speakRepliesSequentially.mock.calls[0][1];
    act(() => { deps.onSpeakingChange('bones'); });
    expect(result.current.speakingAgentId).toBe('bones');
    act(() => { deps.onSpeakingChange(null); });
    expect(result.current.speakingAgentId).toBeNull();
  });

  it('test_second_batch_supersedes_first', () => {
    useStore.setState({ callAudioEnabled: true });
    const { result } = renderHook(() => useMeetingVoice({ meetingActive: true }));
    act(() => { result.current.speakReplies([reply('a')]); });
    const deps1 = mocks.speakRepliesSequentially.mock.calls[0][1];
    act(() => { result.current.speakReplies([reply('b')]); });
    const deps2 = mocks.speakRepliesSequentially.mock.calls[1][1];
    // The new batch sets the current speaker.
    act(() => { deps2.onSpeakingChange('b'); });
    expect(result.current.speakingAgentId).toBe('b');
    // A stale callback from the superseded first batch must NOT clobber it.
    act(() => { deps1.onSpeakingChange('a'); });
    expect(result.current.speakingAgentId).toBe('b');
    // The generation token also tells the old batch to stop.
    expect(deps1.shouldContinue()).toBe(false);
    expect(deps2.shouldContinue()).toBe(true);
  });

  // AD-972: prewarm the TTS probe + the room's voice profiles on meeting open
  // so the first reply's TTS is not gated on a cold profile/status round-trip.
  it('test_prewarms_tts_and_profiles_when_meeting_opens', () => {
    useStore.setState({ callAudioEnabled: true });
    const resolver = vi.fn(async () => undefined);
    vi.mocked(createVoiceProfileResolver).mockReturnValueOnce(resolver);
    renderHook(() =>
      useMeetingVoice({ meetingActive: true, participantAgentIds: ['scout1', 'bones1'] }),
    );
    expect(prewarmTts).toHaveBeenCalled();
    expect(resolver).toHaveBeenCalledWith('scout1');
    expect(resolver).toHaveBeenCalledWith('bones1');
  });

  it('test_no_prewarm_when_meeting_inactive', () => {
    vi.mocked(prewarmTts).mockClear();
    const resolver = vi.fn(async () => undefined);
    vi.mocked(createVoiceProfileResolver).mockReturnValueOnce(resolver);
    renderHook(() =>
      useMeetingVoice({ meetingActive: false, participantAgentIds: ['scout1'] }),
    );
    expect(prewarmTts).not.toHaveBeenCalled();
    expect(resolver).not.toHaveBeenCalled();
  });

  // #1340: the sequencer speaks as the REPLY's agent, which in a room is
  // routinely a peer rather than the mounted tab. So the surface that owns the
  // queue has to be stamped separately, or the tab cannot drop these entries
  // when it unmounts and the Captain keeps hearing the room after leaving it.
  it('test_speak_stamps_the_owning_surface_not_the_speaker', () => {
    useStore.setState({ callAudioEnabled: true });
    const { result, unmount } = renderHook(() =>
      useMeetingVoice({ meetingActive: true, owner: 'profile-chat-7' }),
    );
    const onUtteranceStart = vi.fn();
    const onUtteranceEnd = vi.fn();
    act(() => { result.current.speakReplies([reply('peer-1')], { onUtteranceStart, onUtteranceEnd }); });

    const deps = mocks.speakRepliesSequentially.mock.calls[0][1];
    expect(deps.shouldContinue()).toBe(true);
    deps.speak('text-peer-1', undefined, 'peer-1');

    // Attribution is still the speaker; only the owner names the surface.
    expect(vi.mocked(speakResponse)).toHaveBeenCalledWith(
      'text-peer-1', undefined, 'peer-1', undefined, 'narration', 'profile-chat-7',
    );
    unmount();
    expect(flushSpeechQueue).toHaveBeenCalledTimes(1);
    expect(flushSpeechQueue).toHaveBeenCalledWith('meeting-context-ended', 'profile-chat-7');
    expect(deps.shouldContinue()).toBe(false);
    act(() => {
      deps.onUtteranceStart(reply('peer-1'));
      deps.onUtteranceEnd(reply('peer-1'));
    });
    expect(onUtteranceStart).not.toHaveBeenCalled();
    expect(onUtteranceEnd).not.toHaveBeenCalled();
  });

  it.each([undefined, ''])('does not globally flush empty batches without owner %s', (owner) => {
    useStore.setState({ callAudioEnabled: true });
    const { result, unmount } = renderHook(() => useMeetingVoice({ meetingActive: true, owner }));
    act(() => { result.current.speakReplies([]); });
    expect(mocks.speakRepliesSequentially).not.toHaveBeenCalled();
    unmount();
    expect(flushSpeechQueue).not.toHaveBeenCalled();
  });
});

describe('useMeetingVoice source hygiene', () => {
  it('source module contains no emoji (HXI #3)', () => {
    expect(useMeetingVoiceSource).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
