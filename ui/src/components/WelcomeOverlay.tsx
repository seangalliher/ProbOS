/* Welcome overlay — first-visit onboarding (Fix 11) */

import { useStore } from '../store/useStore';
import { StatusDone } from './icons/Glyphs';

export function WelcomeOverlay() {
  const showIntro = useStore((s) => s.showIntro);
  const setShowIntro = useStore((s) => s.setShowIntro);

  if (!showIntro) return null;

  function dismiss() {
    setShowIntro(false);
    try {
      localStorage.setItem('hxi_seen_intro', 'true');
    } catch {
      // localStorage unavailable
    }
  }

  return (
    <div
      style={{
        position: 'absolute', inset: 0, zIndex: 100,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(5, 5, 10, 0.7)',
        backdropFilter: 'blur(6px)',
      }}
      onClick={dismiss}
    >
      <div
        style={{
          background: 'rgba(10, 10, 18, 0.92)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(240, 176, 96, 0.2)',
          borderRadius: 16,
          padding: '32px 40px',
          maxWidth: 440,
          color: '#e0dcd4',
          textAlign: 'center',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h1 style={{
          fontSize: 24, fontWeight: 600, marginBottom: 8,
          color: '#f0b060',
          letterSpacing: 1,
        }}>
          Welcome to ProbOS
        </h1>
        <p style={{
          fontSize: 14, lineHeight: 1.7, color: '#b0acc0', marginBottom: 16,
        }}>
          You're looking at a living cognitive mesh &mdash; {' '}
          <span style={{ color: '#e0dcd4' }}>47 AI agents</span>{' '}
          self-organizing to handle your requests.
        </p>
        <div style={{
          textAlign: 'left', fontSize: 13, lineHeight: 2, color: '#a0a0b8',
          padding: '0 8px',
        }}>
          <div><span style={{ color: '#f0b060' }}><StatusDone size={8} /></span> Each glowing node is an autonomous agent</div>
          <div><span style={{ color: '#88a4c8' }}>{'\u2500'}</span> Curves show learned routing between intents and agents</div>
          <div>Brighter = higher confidence &nbsp;|&nbsp; Warmer = higher trust</div>
          <div>Ask it anything in the input box above</div>
        </div>
        <p style={{
          fontSize: 12, color: '#8888a0', marginTop: 16, fontStyle: 'italic',
        }}>
          Try: "What's the weather in Tokyo?" or "Summarize a URL"
        </p>
        <button
          onClick={dismiss}
          style={{
            marginTop: 20, padding: '10px 32px', borderRadius: 8,
            border: '1px solid rgba(240, 176, 96, 0.3)',
            background: 'rgba(240, 176, 96, 0.12)',
            color: '#f0b060', fontSize: 14, cursor: 'pointer',
            fontWeight: 500, letterSpacing: 0.5,
            transition: 'background 0.2s',
          }}
        >
          Got it
        </button>
      </div>
    </div>
  );
}
