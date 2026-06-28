// AD-1075: ProfileChatTab autoscroll + resizable-chat wiring. Source-level
// guards — ProfileChatTab is too audio/three-dep-heavy to mount under jsdom, so
// the pure logic lives in scrollAnchor.ts / meetingChatHeight.ts (unit-tested)
// and these assertions pin the integration wiring (the BF-637 / AD-1056 idiom).
import { describe, it, expect } from 'vitest';
import source from '../ProfileChatTab.tsx?raw';

describe('AD-1075 ProfileChatTab autoscroll fix', () => {
  it('uses the pure decideScrollOnUpdate decision', () => {
    expect(source).toContain('decideScrollOnUpdate({');
  });

  it('scrolls the CONTAINER to its true bottom after a rAF (lands-short fix)', () => {
    expect(source).toContain('requestAnimationFrame(');
    expect(source).toContain("c.scrollTo({ top: c.scrollHeight, behavior: 'smooth' })");
  });

  it("always follows the Captain's own send", () => {
    expect(source).toContain("lastRole === 'user' || lastRole === 'captain'");
  });
});

describe('AD-1075 ProfileChatTab resizable chat divider', () => {
  it('imports the persisted meeting-chat-height helpers', () => {
    expect(source).toContain("from '../../chat/meetingChatHeight'");
    expect(source).toContain('clampMeetingChatHeight(');
  });

  it('renders a drag-to-resize divider in a meeting', () => {
    expect(source).toContain('data-testid="meeting-chat-resize"');
    expect(source).toContain('onMouseDown={onChatResizeMouseDown}');
    expect(source).toContain("cursor: 'ns-resize'");
  });

  it('drives the transcript height from the resizable state', () => {
    expect(source).toContain('height: meetingChatHeight');
  });

  it('persists the dragged height to localStorage on mouse-up', () => {
    expect(source).toContain('localStorage.setItem(MEETING_CHAT_HEIGHT_KEY');
  });
});
