// AD-1058: Teams-style call control for a 1:1 crew chat. When idle it is a call
// button that opens a dropdown — "Video call" / "Audio call"; once a call is
// active it becomes an "End call" button. The Captain can start a call from a
// FRESH chat (no message sent yet) — the parent ensures the canonical 1:1 thread
// on demand, so this is reachable the moment the chat is selected.
//
// Presentational only: the parent owns the side effects (ensure thread, set
// meeting_active, start/stop the camera). Video call => camera on; Audio call =>
// camera off (the in-call MeetingView toggle can flip it later either way).
//
// HXI #3: inline stroke-SVG glyphs (strokeWidth 1.5, round caps), amber when
// active, dim otherwise, glow on hover — NO emoji, no Glyphs.tsx export (keeps
// the Glyphs.test.tsx count untouched).
import { useEffect, useRef, useState, type CSSProperties } from 'react';

interface CallMenuProps {
  /** True when a call (meeting_active) is live for this chat. */
  active: boolean;
  /** Disables the control while a start/end request is in flight. */
  busy?: boolean;
  onVideoCall: () => void;
  onAudioCall: () => void;
  onEndCall: () => void;
}

const AMBER = '#f0b060';

function CameraGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="1.5" y="4" width="9" height="8" rx="1.5" />
      <path d="M10.5 7 L14.5 5 V11 L10.5 9 Z" />
    </svg>
  );
}

function PhoneGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 2.5h2.2l1 2.6-1.4 1a8 8 0 003.6 3.6l1-1.4 2.6 1V13a1.4 1.4 0 01-1.5 1.4A11 11 0 013 4a1.4 1.4 0 011.4-1.5" />
    </svg>
  );
}

function PhoneOffGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 2.5h2.2l1 2.6-1.4 1a8 8 0 003.6 3.6l1-1.4 2.6 1V13a1.4 1.4 0 01-1.5 1.4A11 11 0 013 4a1.4 1.4 0 011.4-1.5" />
      <path d="M2 2l12 12" />
    </svg>
  );
}

function Caret() {
  return (
    <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 4.5 L6 7.5 L9 4.5" />
    </svg>
  );
}

export function CallMenu({ active, busy = false, onVideoCall, onAudioCall, onEndCall }: CallMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Dismiss the dropdown on outside-click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (active) {
    return (
      <button
        type="button"
        data-testid="call-end"
        aria-label="End call"
        title="End call"
        disabled={busy}
        onClick={() => onEndCall()}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          background: 'rgba(240, 96, 96, 0.12)',
          border: '1px solid rgba(240, 96, 96, 0.4)',
          borderRadius: 6, color: '#f08080',
          cursor: busy ? 'wait' : 'pointer',
          padding: '4px 10px', fontSize: 12, fontWeight: 600,
        }}
      >
        <PhoneOffGlyph />
        End call
      </button>
    );
  }

  return (
    <div ref={rootRef} style={{ position: 'relative', display: 'inline-flex' }}>
      <button
        type="button"
        data-testid="call-start"
        aria-label="Start call"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Start call"
        disabled={busy}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          background: open ? 'rgba(240, 176, 96, 0.12)' : 'transparent',
          border: `1px solid ${open ? 'rgba(240, 176, 96, 0.5)' : 'rgba(240, 176, 96, 0.3)'}`,
          borderRadius: 6, color: AMBER,
          cursor: busy ? 'wait' : 'pointer',
          padding: '4px 10px', fontSize: 12, fontWeight: 600,
          filter: open ? 'drop-shadow(0 0 4px rgba(240, 176, 96, 0.35))' : 'none',
        }}
      >
        <CameraGlyph />
        Call
        <Caret />
      </button>
      {open && (
        <div
          role="menu"
          data-testid="call-menu"
          style={{
            position: 'absolute', top: 'calc(100% + 6px)', right: 0,
            minWidth: 150, zIndex: 30,
            background: 'rgba(10, 10, 18, 0.97)',
            border: '1px solid rgba(240, 176, 96, 0.25)',
            borderRadius: 8, padding: 4,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
          }}
        >
          <button
            role="menuitem" type="button" data-testid="call-video"
            onClick={() => { setOpen(false); onVideoCall(); }}
            style={menuItemStyle}
          >
            <CameraGlyph />
            Video call
          </button>
          <button
            role="menuitem" type="button" data-testid="call-audio"
            onClick={() => { setOpen(false); onAudioCall(); }}
            style={menuItemStyle}
          >
            <PhoneGlyph />
            Audio call
          </button>
        </div>
      )}
    </div>
  );
}

const menuItemStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, width: '100%',
  background: 'transparent', border: 'none', borderRadius: 6,
  color: '#e0dcd4', cursor: 'pointer',
  padding: '7px 10px', fontSize: 12, textAlign: 'left',
};
