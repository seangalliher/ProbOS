/* AD-945: Environment station config — the four environment/sensory toggles
 * (ambient sound / voice output / wake-word / visual legend) relocated out of
 * DecisionSurface's bottom-right cluster into the Ship's-Computer command layer
 * (Bridge → Engineering → Environment). This is a RELOCATION: the same store
 * actions fire with the same side effects; the audio / VAD / wake-word / legend
 * engines are untouched. The wake-word single-owner lifecycle stays in
 * IntentSurface.tsx (AD-705) — this toggle only flips wakeWordEnabled. Stroke-SVG
 * glyphs only, no emoji (HXI Principle #3). */

import { useState, useEffect, useRef } from 'react';
import { useStore } from '../../store/useStore';
import { soundEngine } from '../../audio/soundEngine';
import { Sparkle, StatusPending } from '../icons/Glyphs';
import { getAvailableVoices, setPreferredVoiceName, getCurrentVoiceName, speakResponse } from '../../audio/voice';

export function BridgeEnvironment() {
  const showLegend = useStore((s) => s.showLegend);
  const setShowLegend = useStore((s) => s.setShowLegend);
  const soundEnabled = useStore((s) => s.soundEnabled);
  const setSoundEnabled = useStore((s) => s.setSoundEnabled);
  const voiceEnabled = useStore((s) => s.voiceEnabled);
  const setVoiceEnabled = useStore((s) => s.setVoiceEnabled);
  // AD-705: always-on wake-word voice loop opt-in.
  const wakeWordEnabled = useStore((s) => s.wakeWordEnabled);
  const setWakeWordEnabled = useStore((s) => s.setWakeWordEnabled);

  const [showVolume, setShowVolume] = useState(false);
  const [volume, setVolume] = useState(soundEngine.volume);
  const [showVoicePicker, setShowVoicePicker] = useState(false);
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);
  const voicePickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (showVoicePicker) {
      setAvailableVoices(getAvailableVoices());
    }
  }, [showVoicePicker]);

  useEffect(() => {
    if (!showVoicePicker) return;
    const handler = (e: MouseEvent) => {
      if (voicePickerRef.current && !voicePickerRef.current.contains(e.target as Node)) {
        setShowVoicePicker(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showVoicePicker]);

  const btnStyle = (active: boolean) => ({
    background: active ? 'rgba(240, 176, 96, 0.15)' : 'rgba(128, 128, 160, 0.1)',
    border: '1px solid rgba(128, 128, 160, 0.2)',
    borderRadius: 4, padding: '2px 8px', cursor: 'pointer',
    color: active ? '#f0b060' : '#8888a0', fontSize: 11, fontFamily: 'monospace',
  } as const);

  const sectionStyle = {
    marginBottom: 16,
    padding: '12px',
    background: 'rgba(255,255,255,0.02)',
    borderRadius: 6,
    border: '1px solid rgba(255,255,255,0.04)',
  } as const;

  const labelStyle = {
    fontSize: 10, letterSpacing: 1, fontWeight: 700 as const,
    color: '#8888a0', textTransform: 'uppercase' as const,
    marginBottom: 8, display: 'block' as const,
  } as const;

  const rowStyle = {
    display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8,
  } as const;

  const rowLabelStyle = {
    fontSize: 12, color: '#c0bab0', fontFamily: "'Inter', sans-serif",
  } as const;

  return (
    <div style={{ padding: '8px 0' }}>
      <span style={labelStyle}>Environment</span>
      <div style={sectionStyle}>
        {/* Sound toggle */}
        <div style={rowStyle}>
          <button
            onClick={() => setSoundEnabled(!soundEnabled)}
            onContextMenu={(e) => { e.preventDefault(); setShowVolume(!showVolume); }}
            style={btnStyle(soundEnabled)}
            title={soundEnabled ? 'Mute ambient sounds (right-click: volume)' : 'Enable ambient sounds'}
          >
            {soundEnabled ? (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#ffcc66" strokeWidth="2" strokeLinecap="round" style={{ filter: 'drop-shadow(0 0 4px #ffcc66) drop-shadow(0 0 8px rgba(255, 204, 102, 0.5))' }}>
                <path d="M2 6v4l3 3h1V3H5L2 6z" />
                <path d="M9 5.5c.7.7 1 1.5 1 2.5s-.3 1.8-1 2.5" />
                <path d="M11 3.5c1.2 1.2 2 2.7 2 4.5s-.8 3.3-2 4.5" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#8888aa" strokeWidth="2" strokeLinecap="round" style={{ filter: 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))' }}>
                <path d="M2 6v4l3 3h1V3H5L2 6z" />
                <path d="M14 5l-5 6" />
              </svg>
            )}
          </button>
          <span style={rowLabelStyle}>Ambient sound</span>
        </div>

        {/* Volume slider (shown on right-click of sound button) */}
        {showVolume && (
          <input
            type="range"
            min="0" max="1" step="0.05"
            value={volume}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              setVolume(v);
              soundEngine.setVolume(v);
            }}
            style={{
              width: 60, height: 4, cursor: 'pointer',
              accentColor: '#f0b060',
              marginBottom: 8,
            }}
            title={`Volume: ${Math.round(volume * 100)}%`}
          />
        )}

        {/* Voice output toggle */}
        <div style={rowStyle}>
          <button
            onClick={() => setVoiceEnabled(!voiceEnabled)}
            onContextMenu={(e) => { e.preventDefault(); setShowVoicePicker(!showVoicePicker); }}
            style={btnStyle(voiceEnabled)}
            title={voiceEnabled ? 'Disable voice (right-click: choose voice)' : 'Enable voice output'}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke={voiceEnabled ? '#ffcc66' : '#8888aa'} strokeWidth="2" strokeLinecap="round" style={{ filter: voiceEnabled ? 'drop-shadow(0 0 4px #ffcc66) drop-shadow(0 0 8px rgba(255, 204, 102, 0.5))' : 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))' }}>
              <line x1="4" y1="5" x2="4" y2="11" />
              <line x1="8" y1="3" x2="8" y2="13" />
              <line x1="12" y1="6" x2="12" y2="10" />
            </svg>
          </button>
          <span style={rowLabelStyle}>Voice output</span>
        </div>

        {/* Voice-picker dropdown (shown on right-click of voice button) —
            AD-945: re-anchored inline (relative) under the voice row, was
            position:absolute bottom:40 right:60 on the old status bar. */}
        {showVoicePicker && (
          <div ref={voicePickerRef} style={{
            position: 'relative',
            background: 'rgba(10, 10, 18, 0.92)',
            backdropFilter: 'blur(12px)',
            border: '1px solid rgba(240, 176, 96, 0.2)',
            borderRadius: 8,
            padding: '8px 0',
            maxHeight: 200,
            overflowY: 'auto',
            zIndex: 30,
            minWidth: 250,
            marginBottom: 8,
          }}>
            <div style={{
              padding: '4px 12px 8px',
              fontSize: 11,
              color: '#888',
              borderBottom: '1px solid rgba(240, 176, 96, 0.1)',
            }}>
              Choose voice
            </div>
            {availableVoices.map((voice) => (
              <div
                key={voice.name}
                onClick={() => {
                  setPreferredVoiceName(voice.name);
                  setShowVoicePicker(false);
                  if (voiceEnabled) {
                    speakResponse('Voice selected');
                  }
                }}
                style={{
                  padding: '6px 12px',
                  fontSize: 12,
                  cursor: 'pointer',
                  color: voice.name === getCurrentVoiceName() ? '#f0b060' : '#c8d0e0',
                  background: voice.name === getCurrentVoiceName() ? 'rgba(240, 176, 96, 0.08)' : 'transparent',
                  fontFamily: "'Inter', sans-serif",
                }}
                onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'rgba(240, 176, 96, 0.15)'; }}
                onMouseLeave={(e) => { (e.target as HTMLElement).style.background = voice.name === getCurrentVoiceName() ? 'rgba(240, 176, 96, 0.08)' : 'transparent'; }}
              >
                {voice.name.replace(/ - English.*$/, '')}
                {voice.name.includes('Online (Natural)') && <>{' '}<Sparkle size={10} /></>}
                {voice.name.includes('Online') && !voice.name.includes('Natural') && <>{' '}<StatusPending size={10} /></>}
              </div>
            ))}
          </div>
        )}

        {/* AD-705: wake-word loop toggle. Default OFF — Captain explicitly
            opts in. Stroke-only inline SVG; no emoji (HXI Principle #3). */}
        <div style={rowStyle}>
          <button
            data-testid="wake-word-toggle"
            onClick={() => setWakeWordEnabled(!wakeWordEnabled)}
            style={btnStyle(wakeWordEnabled)}
            title={wakeWordEnabled ? 'Disable wake-word listening' : 'Enable wake-word listening ("Computer\u2026")'}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              stroke={wakeWordEnabled ? '#ffcc66' : '#8888aa'}
              strokeWidth="1.5"
              strokeLinecap="round"
              style={{
                filter: wakeWordEnabled
                  ? 'drop-shadow(0 0 4px #ffcc66) drop-shadow(0 0 8px rgba(255, 204, 102, 0.5))'
                  : 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))',
              }}
            >
              {/* Concentric arcs evoke a radio wave / wake signal. */}
              <circle cx="8" cy="8" r="2" />
              <path d="M4 8 a4 4 0 0 1 8 0" />
              <path d="M2 8 a6 6 0 0 1 12 0" strokeOpacity="0.6" />
            </svg>
          </button>
          <span style={rowLabelStyle}>Wake-word</span>
        </div>

        {/* Legend toggle */}
        <div style={{ ...rowStyle, marginBottom: 0 }}>
          <button
            onClick={() => setShowLegend(!showLegend)}
            style={btnStyle(showLegend)}
            title="Toggle visual legend"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" strokeWidth="2" style={{ filter: showLegend ? 'drop-shadow(0 0 4px #ffcc66) drop-shadow(0 0 8px rgba(255, 204, 102, 0.5))' : 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))' }}>
              <circle cx="8" cy="8" r="5" stroke={showLegend ? '#ffcc66' : '#8888aa'} />
              <circle cx="8" cy="8" r="1.5" fill={showLegend ? '#ffcc66' : '#8888aa'} />
            </svg>
          </button>
          <span style={rowLabelStyle}>Visual legend</span>
        </div>
      </div>
    </div>
  );
}
