/** AD-1075: persisted, clamped height for the meeting transcript so the Captain
 *  can drag the chat's top edge to make it taller — independent of the AD-974
 *  avatar-gallery scale. In a meeting the avatar gallery (MeetingView) is
 *  `flex:1` and the transcript was a fixed condensed strip, so shrinking the
 *  avatars left dead space the chat could not reclaim. A draggable divider above
 *  the transcript drives this height; the gallery (flex:1) shrinks + scrolls to
 *  absorb the rest. Pure helpers — DOM/localStorage-tolerant for unit tests. */
export const MEETING_CHAT_HEIGHT_KEY = 'hxi_meeting_chat_height';
export const MEETING_CHAT_HEIGHT_MIN = 80;
export const MEETING_CHAT_HEIGHT_MAX = 900;
export const MEETING_CHAT_HEIGHT_DEFAULT = 200;

/** Clamp to a usable range; non-finite input falls back to the default. */
export function clampMeetingChatHeight(v: number): number {
  if (!Number.isFinite(v)) return MEETING_CHAT_HEIGHT_DEFAULT;
  return Math.min(MEETING_CHAT_HEIGHT_MAX, Math.max(MEETING_CHAT_HEIGHT_MIN, v));
}

/** Load the persisted height (clamped), defaulting when unset/unavailable. */
export function loadMeetingChatHeight(): number {
  try {
    const raw =
      typeof localStorage !== 'undefined'
        ? localStorage.getItem(MEETING_CHAT_HEIGHT_KEY)
        : null;
    return raw != null ? clampMeetingChatHeight(parseFloat(raw)) : MEETING_CHAT_HEIGHT_DEFAULT;
  } catch {
    return MEETING_CHAT_HEIGHT_DEFAULT;
  }
}
