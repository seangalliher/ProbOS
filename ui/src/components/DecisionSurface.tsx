/* Decision Surface — Status bar + Legend (Pulse Input redesign) */

import { useStore } from '../store/useStore';

export function DecisionSurface() {
  const agents = useStore((s) => s.agents);
  const systemMode = useStore((s) => s.systemMode);
  const tcN = useStore((s) => s.tcN);
  const routingEntropy = useStore((s) => s.routingEntropy);
  const connected = useStore((s) => s.connected);
  const showLegend = useStore((s) => s.showLegend);
  const setShowLegend = useStore((s) => s.setShowLegend);

  const agentCount = agents.size;
  const avgHealth = agentCount > 0
    ? Array.from(agents.values()).reduce((s, a) => s + a.confidence, 0) / agentCount
    : 0;

  const modeColor = systemMode === 'dreaming' ? '#e8963c'
    : systemMode === 'active' ? '#80c878' : '#6a6a80';

  const healthColor = avgHealth > 0.7 ? '#f0b060' : avgHealth > 0.4 ? '#88a4c8' : '#c84858';

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
            {connected ? `Live \u2014 ${agentCount} agents` : 'Disconnected'}
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

        {/* Legend toggle (Fix 11) */}
        <button
          onClick={() => setShowLegend(!showLegend)}
          style={{
            background: showLegend ? 'rgba(240, 176, 96, 0.15)' : 'rgba(128, 128, 160, 0.1)',
            border: '1px solid rgba(128, 128, 160, 0.2)',
            borderRadius: 4, padding: '2px 8px', cursor: 'pointer',
            color: showLegend ? '#f0b060' : '#8888a0', fontSize: 11, fontFamily: 'monospace',
          }}
          title="Toggle visual legend"
        >
          ?
        </button>
      </div>

      {/* Legend overlay (Fix 11) */}
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
