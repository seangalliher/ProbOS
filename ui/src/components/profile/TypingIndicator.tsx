/** AD-952: typing indicator bubble. Shown in the group-chat transcript while
 *  ``revealRepliesProgressively`` is composing the next crew reply — the
 *  text-chat equivalent of the AD-923 meeting speaking indicator.
 *
 *  HXI #3 (no emoji) + #4 (motion = state): three amber dots pulse in sequence
 *  (animation = "alive / composing"). The keyframe is self-contained in a
 *  <style> tag (the app uses inline styles; there is no global CSS file), so
 *  the component carries its own motion with no external dependency. The label
 *  reads "{callsign} is typing"; a generic fallback covers a missing callsign.
 */

interface TypingIndicatorProps {
  callsign: string;
  /** AD-962: the verb shown after the name. "typing" (default) for the AD-952
   *  per-agent compose beat; "thinking" for the AD-962 pre-reply generation
   *  phase (the crew is being asked, no reply exists yet); BF-621 "speaking"
   *  for a live meeting while the agent's voice utterance plays (text is
   *  revealed after it finishes). */
  verb?: 'typing' | 'thinking' | 'speaking';
}

const _AMBER = '#f0b060';

export function TypingIndicator({ callsign, verb = 'typing' }: TypingIndicatorProps) {
  const who = callsign && callsign.trim() ? callsign.trim() : 'Someone';
  const dotStyle = (delay: string): React.CSSProperties => ({
    width: 5,
    height: 5,
    borderRadius: '50%',
    background: _AMBER,
    display: 'inline-block',
    animation: 'hxi-typing-blink 1.1s ease-in-out infinite',
    animationDelay: delay,
  });
  return (
    <div
      data-testid="typing-indicator"
      aria-live="polite"
      aria-label={`${who} is ${verb}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 10px',
        margin: '2px 0',
        fontSize: 11,
        color: '#888',
      }}
    >
      <style>{
        '@keyframes hxi-typing-blink{0%,80%,100%{opacity:0.25}40%{opacity:1}}'
      }</style>
      <span style={{ color: _AMBER }}>{who}</span>
      <span style={{ color: '#666680' }}>is {verb}</span>
      <span style={{ display: 'inline-flex', gap: 3, marginLeft: 2 }}>
        <span style={dotStyle('0s')} />
        <span style={dotStyle('0.18s')} />
        <span style={dotStyle('0.36s')} />
      </span>
    </div>
  );
}
