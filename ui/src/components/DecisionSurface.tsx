/* Decision Surface — Status bar + Legend + Audio controls */

import { useState, useEffect, useRef } from 'react';
import { useStore } from '../store/useStore';
import { soundEngine } from '../audio/soundEngine';
import { getAvailableVoices, setPreferredVoiceName, getCurrentVoiceName, speakResponse } from '../audio/voice';

export function DecisionSurface() {
  const agents = useStore((s) => s.agents);
  const systemMode = useStore((s) => s.systemMode);
  const tcN = useStore((s) => s.tcN);
  const routingEntropy = useStore((s) => s.routingEntropy);
  const connected = useStore((s) => s.connected);
  const showLegend = useStore((s) => s.showLegend);
  const setShowLegend = useStore((s) => s.setShowLegend);
  const soundEnabled = useStore((s) => s.soundEnabled);
  const setSoundEnabled = useStore((s) => s.setSoundEnabled);
  const voiceEnabled = useStore((s) => s.voiceEnabled);
  const setVoiceEnabled = useStore((s) => s.setVoiceEnabled);

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

  const crewAgents = Array.from(agents.values()).filter(a => a.isCrew);
  const crewCount = crewAgents.length;
  const avgHealth = crewCount > 0
    ? crewAgents.reduce((s, a) => s + a.confidence, 0) / crewCount
    : 0;

  const modeColor = systemMode === 'dreaming' ? '#e8963c'
    : systemMode === 'active' ? '#80c878' : '#6a6a80';

  const healthColor = avgHealth > 0.7 ? '#f0b060' : avgHealth > 0.4 ? '#88a4c8' : '#c84858';

  const btnStyle = (active: boolean) => ({
    background: active ? 'rgba(240, 176, 96, 0.15)' : 'rgba(128, 128, 160, 0.1)',
    border: '1px solid rgba(128, 128, 160, 0.2)',
    borderRadius: 4, padding: '2px 8px', cursor: 'pointer',
    color: active ? '#f0b060' : '#8888a0', fontSize: 11, fontFamily: 'monospace',
  } as const);

  return (
    <div style={{
      position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 10,
      pointerEvents: 'none',
    }}>
      {/* Status bar — atmospheric glass */}
      <div style={{
        display: 'flex', gap: 16, padding: '7px 16px', alignItems: 'center',
        background: 'rgba(10, 10, 18, 0.6)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderTop: '1px solid rgba(240, 176, 96, 0.12)',
        fontSize: 11, fontFamily: 'monospace', color: '#8888a0',
        pointerEvents: 'auto',
      }}>
        {/* Connection + agent count */}
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: connected ? '#80c878' : '#c84858',
            boxShadow: connected ? '0 0 4px #80c878' : '0 0 4px #c84858',
          }} />
          <span style={{ color: connected ? '#a0c0a0' : '#c84858' }}>
            {connected ? `Live \u2014 ${crewCount} crew` : 'Disconnected'}
          </span>
        </span>

        {/* Health */}
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}
              title="Average agent confidence">
          <span style={{ color: '#666680' }}>Health</span>
          <span style={{ color: healthColor }}>{avgHealth.toFixed(2)}</span>
        </span>

        {/* Mode */}
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%', background: modeColor,
            boxShadow: `0 0 4px ${modeColor}`,
          }} />
          <span style={{ color: modeColor }}>{systemMode}</span>
        </span>

        {/* TC_N */}
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}
              title="Total Correlation \u2014 how much agents cooperate">
          <span style={{ color: '#666680' }}>TC_N</span>
          <span style={{ color: '#88a4c8' }}>{tcN.toFixed(3)}</span>
        </span>

        {/* Routing Entropy */}
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}
              title="Routing Entropy \u2014 diversity of intent routing paths">
          <span style={{ color: '#666680' }}>Entropy</span>
          <span style={{ color: '#88a4c8' }}>{routingEntropy.toFixed(3)}</span>
        </span>

        {/* Spacer */}
        <span style={{ flex: 1 }} />

        {/* Sound toggle */}
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
            }}
            title={`Volume: ${Math.round(volume * 100)}%`}
          />
        )}

        {/* Voice output toggle */}
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

        {showVoicePicker && (
          <div ref={voicePickerRef} style={{
            position: 'absolute',
            bottom: 40,
            right: 60,
            background: 'rgba(10, 10, 18, 0.92)',
            backdropFilter: 'blur(12px)',
            border: '1px solid rgba(240, 176, 96, 0.2)',
            borderRadius: 8,
            padding: '8px 0',
            maxHeight: 200,
            overflowY: 'auto',
            zIndex: 30,
            minWidth: 250,
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
                {voice.name.includes('Online (Natural)') && ' \u2726'}
                {voice.name.includes('Online') && !voice.name.includes('Natural') && ' \u25CB'}
              </div>
            ))}
          </div>
        )}

        {/* Legend toggle */}
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
      </div>

      {/* Legend overlay */}
      {showLegend && (
        <div style={{
          position: 'absolute', bottom: 36, right: 16,
          background: 'rgba(10, 10, 18, 0.85)', backdropFilter: 'blur(12px)',
          border: '1px solid rgba(240, 176, 96, 0.2)', borderRadius: 8,
          padding: '12px 16px', color: '#e0dcd4', fontSize: 12,
          lineHeight: 1.8, pointerEvents: 'auto', maxWidth: 300,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 4, color: '#f0b060' }}>Visual Legend</div>
          <div><span style={{ color: '#f0b060' }}>{'\u25CF'}</span> High trust &nbsp;
               <span style={{ color: '#88a4c8' }}>{'\u25CF'}</span> Medium &nbsp;
               <span style={{ color: '#7060a8' }}>{'\u25CF'}</span> Low</div>
          <div>Brighter = more confident</div>
          <div>Larger = domain agent &nbsp; Smaller = core agent</div>
          <div><span style={{ color: '#c8a070' }}>{'\u25CB'}</span> Pulsing = heartbeat &nbsp;
               <span style={{ color: '#e8c870' }}>{'\u2726'}</span> Flash = consensus</div>
          <div style={{ color: '#8888a0', fontSize: 11, marginTop: 4 }}>Curves = learned Hebbian routing</div>
        </div>
      )}
    </div>
  );
}
