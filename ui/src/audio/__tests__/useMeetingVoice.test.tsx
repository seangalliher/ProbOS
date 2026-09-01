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
  onSpeechEvent: vi.fn(() => () => {}),
  stripMarkdownForSpeech: (s: string) => s,
  prewarmTts: vi.fn(),
}));

import { useMeetingVoice } from '../useMeetingVoice';
import { useStore } from '../../store/useStore';
import type { PerAgentReply } from '../meetingVoice';
import useMeetingVoiceSource from '../useMeetingVoice?raw';
import { prewarmTts, speakResponse } from '../voice';
import { createVoiceProfileResolver } from '../meetingVoice';

beforeEach(() => {
  mocks.speakRepliesSequentially.mockReset();
  vi.mocked(speakResponse).mockClear();
  useStore.setState({ callAudioEnabled: false });
});

const reply = (id: string): PerAgentReply => ({ agent_id: id, text: `text-${id}` });

describe('useMeetingVoice', () => {
  it('test_no_speak_when_meeting_inactive', () => {
    useStore.setState({ callAudioEnabled: true });
    const { result } = renderHook(() => useMeetingVoice({ meetingActive: false }));
    act(() => { result.current.speakReplies([reply('a')]); });
    expect(mocks.speakRepliesSequentially).not.toHaveBeenCalled();
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
    const { result } = renderHook(() =>
      useMeetingVoice({ meetingActive: true, owner: 'profile-chat-7' }),
    );
    act(() => { result.current.speakReplies([reply('peer-1')]); });

    const deps = mocks.speakRepliesSequentially.mock.calls[0][1];
    deps.speak('text-peer-1', undefined, 'peer-1');

    // Attribution is still the speaker; only the owner names the surface.
    expect(vi.mocked(speakResponse)).toHaveBeenCalledWith(
      'text-peer-1', undefined, 'peer-1', undefined, 'narration', 'profile-chat-7',
    );
  });
});

describe('useMeetingVoice source hygiene', () => {
  it('source module contains no emoji (HXI #3)', () => {
    expect(useMeetingVoiceSource).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
