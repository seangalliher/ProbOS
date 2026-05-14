import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  speakResponse,
  stopSpeaking,
  getAvailableVoices,
  setPreferredVoiceName,
  getCurrentVoiceName,
} from '../audio/voice';

interface FakeVoice { name: string; lang: string; default?: boolean; localService?: boolean; voiceURI?: string; }

class FakeUtterance {
  text: string;
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: FakeVoice | null = null;
  constructor(text: string) { this.text = text; }
}

describe('voice.ts (AD-474a)', () => {
  let speakSpy: ReturnType<typeof vi.fn>;
  let cancelSpy: ReturnType<typeof vi.fn>;
  let getVoicesSpy: ReturnType<typeof vi.fn>;
  let voiceList: FakeVoice[] = [];

  beforeEach(() => {
    voiceList = [];
    speakSpy = vi.fn();
    cancelSpy = vi.fn();
    getVoicesSpy = vi.fn(() => voiceList);
    vi.stubGlobal('speechSynthesis', {
      speak: speakSpy,
      cancel: cancelSpy,
      getVoices: getVoicesSpy,
      addEventListener: vi.fn(),
    });
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance as unknown as typeof SpeechSynthesisUtterance);
    // AD-738: route through synchronous browser fallback by removing fetch.
    vi.stubGlobal('fetch', undefined);
    localStorage.clear();
    setPreferredVoiceName(null);  // reset module cache
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('speakResponse no-ops when speechSynthesis is unavailable', () => {
    vi.unstubAllGlobals();  // remove speechSynthesis stub
    expect(() => speakResponse('hello')).not.toThrow();
  });

  it('speakResponse cancels prior utterance, sets rate/pitch/volume, and calls speak', () => {
    voiceList = [{ name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' }];
    speakResponse('hello world');
    expect(cancelSpy).toHaveBeenCalled();
    expect(speakSpy).toHaveBeenCalledTimes(1);
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.text).toBe('hello world');
    expect(utt.rate).toBeCloseTo(0.95);
    expect(utt.pitch).toBeCloseTo(0.9);
    expect(utt.volume).toBeCloseTo(0.8);
  });

  it('stopSpeaking calls speechSynthesis.cancel', () => {
    stopSpeaking();
    expect(cancelSpy).toHaveBeenCalled();
  });

  it('stopSpeaking is a no-op when speechSynthesis is unavailable', () => {
    vi.unstubAllGlobals();
    expect(() => stopSpeaking()).not.toThrow();
  });

  it('findPreferredVoice prefers the saved hxi_voice_name from localStorage', () => {
    voiceList = [
      { name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' },
      { name: 'Custom Pick', lang: 'en-GB' },
    ];
    localStorage.setItem('hxi_voice_name', 'Custom Pick');
    setPreferredVoiceName('Custom Pick');  // ensures cache reset; also writes through
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice?.name).toBe('Custom Pick');
  });

  it('findPreferredVoice falls back to Online (Natural) Edge neural voice', () => {
    voiceList = [
      { name: 'Microsoft David - English (United States)', lang: 'en-US' },
      { name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' },
      { name: 'Google US English', lang: 'en-US' },
    ];
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice?.name).toContain('Online (Natural)');
  });

  it('findPreferredVoice falls back to Google US English when no Online voice present', () => {
    voiceList = [
      { name: 'Microsoft David - English (United States)', lang: 'en-US' },
      { name: 'Google US English', lang: 'en-US' },
    ];
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice?.name).toBe('Google US English');
  });

  it('findPreferredVoice ultimate fallback is the first en-* voice', () => {
    voiceList = [
      { name: 'Microsoft Hazel - English (Great Britain)', lang: 'en-GB' },
    ];
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice?.lang).toMatch(/^en/);
  });

  it('findPreferredVoice returns no voice when getVoices is empty (utt.voice unset)', () => {
    voiceList = [];
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice).toBeNull();
  });

  it('getAvailableVoices filters to en-* voices only', () => {
    voiceList = [
      { name: 'EN Voice', lang: 'en-US' },
      { name: 'JP Voice', lang: 'ja-JP' },
      { name: 'EN UK Voice', lang: 'en-GB' },
    ];
    const result = getAvailableVoices();
    expect(result).toHaveLength(2);
    expect(result.every(v => v.lang.startsWith('en'))).toBe(true);
  });

  it('setPreferredVoiceName(name) writes to localStorage; null clears it', () => {
    setPreferredVoiceName('Custom Pick');
    expect(localStorage.getItem('hxi_voice_name')).toBe('Custom Pick');
    setPreferredVoiceName(null);
    expect(localStorage.getItem('hxi_voice_name')).toBeNull();
  });

  it('getCurrentVoiceName returns voice.name when a preferred voice resolves', () => {
    voiceList = [{ name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' }];
    expect(getCurrentVoiceName()).toContain('Online (Natural)');
  });

  it('getCurrentVoiceName returns "Default" fallback when no voice resolves', () => {
    voiceList = [];
    expect(getCurrentVoiceName()).toBe('Default');
  });
});
