/** AD-922: meeting push-to-talk button. Pure presentational -- the capture
 *  lifecycle lives in ``useMeetingMic``. Local inline mic SVG (HXI #3 -- no
 *  emoji, no ``Glyphs.tsx`` export so the ``Glyphs.test.tsx`` count is
 *  untouched; mirrors the GroupChatHeader meeting-toggle convention). Amber
 *  while capturing, dim idle, muted treatment when an agent is speaking
 *  (echo-gate visual) or the mic is unavailable. */

interface MeetingMicButtonProps {
  capturing: boolean;
  /** Permission denied/unavailable -> muted + disabled. */
  blocked: boolean;
  /** An agent is speaking -> muted (echo-gate visual). */
  speaking: boolean;
  onToggle: () => void;
}

export function MeetingMicButton({ capturing, blocked, speaking, onToggle }: MeetingMicButtonProps) {
  const muted = blocked || speaking;
  const color = capturing ? '#f0b060' : muted ? '#3a3a48' : '#666680';
  const ariaLabel = capturing ? 'Stop talking to the room' : 'Talk to the room';
  const title = blocked ? 'Microphone unavailable' : ariaLabel;

  return (
    <button
      type="button"
      data-testid="meeting-mic"
      aria-pressed={capturing}
      aria-label={ariaLabel}
      title={title}
      disabled={blocked}
      onClick={onToggle}
      style={{
        background: 'none',
        border: 'none',
        cursor: blocked ? 'default' : 'pointer',
        color,
        display: 'inline-flex',
        alignItems: 'center',
        padding: 2,
        opacity: muted ? 0.5 : 1,
      }}
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" />
        <path d="M3.5 7.5 a4.5 4.5 0 0 0 9 0" />
        <line x1="8" y1="12" x2="8" y2="14.5" />
        <line x1="5.5" y1="14.5" x2="10.5" y2="14.5" />
      </svg>
    </button>
  );
}
