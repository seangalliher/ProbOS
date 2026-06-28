// AD-1075: meeting-transcript resize helper. Pure unit tests.
import { describe, it, expect, beforeEach } from 'vitest';
import {
  clampMeetingChatHeight,
  loadMeetingChatHeight,
  MEETING_CHAT_HEIGHT_KEY,
  MEETING_CHAT_HEIGHT_MIN,
  MEETING_CHAT_HEIGHT_MAX,
  MEETING_CHAT_HEIGHT_DEFAULT,
} from '../meetingChatHeight';

describe('AD-1075 clampMeetingChatHeight', () => {
  it('passes a value within range through', () => {
    expect(clampMeetingChatHeight(300)).toBe(300);
  });
  it('clamps below the minimum', () => {
    expect(clampMeetingChatHeight(10)).toBe(MEETING_CHAT_HEIGHT_MIN);
  });
  it('clamps above the maximum', () => {
    expect(clampMeetingChatHeight(5000)).toBe(MEETING_CHAT_HEIGHT_MAX);
  });
  it('falls back to the default for non-finite input', () => {
    expect(clampMeetingChatHeight(NaN)).toBe(MEETING_CHAT_HEIGHT_DEFAULT);
    expect(clampMeetingChatHeight(Infinity)).toBe(MEETING_CHAT_HEIGHT_DEFAULT);
  });
});

describe('AD-1075 loadMeetingChatHeight', () => {
  beforeEach(() => {
    try { localStorage.clear(); } catch { /* no localStorage in this env */ }
  });

  it('defaults when unset', () => {
    expect(loadMeetingChatHeight()).toBe(MEETING_CHAT_HEIGHT_DEFAULT);
  });

  it('loads and clamps a persisted value', () => {
    localStorage.setItem(MEETING_CHAT_HEIGHT_KEY, '350');
    expect(loadMeetingChatHeight()).toBe(350);
    localStorage.setItem(MEETING_CHAT_HEIGHT_KEY, '5000');
    expect(loadMeetingChatHeight()).toBe(MEETING_CHAT_HEIGHT_MAX);
  });

  it('defaults on an unparseable persisted value', () => {
    localStorage.setItem(MEETING_CHAT_HEIGHT_KEY, 'abc');
    expect(loadMeetingChatHeight()).toBe(MEETING_CHAT_HEIGHT_DEFAULT);
  });
});
