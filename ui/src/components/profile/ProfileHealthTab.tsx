import type { Agent, AgentProfileData } from '../../store/types';

interface Props {
  profileData: AgentProfileData | null;
  agent: Agent;
}

export function ProfileHealthTab({ profileData, agent }: Props) {
  const trust = profileData?.trust ?? agent.trust;
  const confidence = profileData?.confidence ?? agent.confidence;
  const trustColor = trust >= 0.7 ? '#f0b060' : trust >= 0.35 ? '#88a4c8' : '#7060a8';
  const stateColor = agent.state === 'active' ? '#80c878' : '#f0b060';

  function formatUptime(seconds: number): string {
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    const min = Math.floor(seconds / 60);
    if (min < 60) return `${min}m`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ${min % 60}m`;
    const days = Math.floor(hr / 24);
    return `${days}d ${hr % 24}h`;
  }

  return (
    <div style={{ padding: '12px 14px', overflowY: 'auto', height: '100%', fontSize: 12 }}>
      {/* Trust */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Trust
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 24, fontWeight: 600, color: trustColor }}>
            {(trust * 100).toFixed(0)}%
          </span>
          <span style={{ color: '#666680', fontSize: 11 }}>
            {trust >= 0.7 ? 'high' : trust >= 0.35 ? 'medium' : 'low'}
          </span>
        </div>
        {/* Trust history sparkline */}
        {profileData?.trustHistory && profileData.trustHistory.length > 1 && (
          <svg width="100%" height={30} style={{ marginTop: 4 }}>
            {(() => {
              const vals = profileData.trustHistory;
              const min = Math.min(...vals) * 0.95;
              const max = Math.max(...vals) * 1.05 || 1;
              const w = 380;
              const h = 28;
              const points = vals.map((v, i) => {
                const x = (i / (vals.length - 1)) * w;
                const y = h - ((v - min) / (max - min)) * h;
                return `${x},${y}`;
              }).join(' ');
              return <polyline points={points} fill="none" stroke={trustColor} strokeWidth={1.5} opacity={0.6} />;
            })()}
          </svg>
        )}
      </div>

      {/* Confidence */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Confidence
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            flex: 1, height: 6, borderRadius: 3,
            background: 'rgba(255,255,255,0.06)', overflow: 'hidden',
          }}>
            <div style={{
              height: '100%',
              width: `${confidence * 100}%`,
              background: '#5090d0',
              borderRadius: 3,
            }} />
          </div>
          <span style={{ color: '#e0dcd4', fontSize: 12 }}>
            {(confidence * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      {/* State */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Status
        </div>
        <span style={{ color: stateColor, textTransform: 'capitalize' }}>{agent.state}</span>
      </div>

      {/* Memory count */}
      {profileData && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Episodic Memory
          </div>
          <span style={{ color: '#e0dcd4' }}>
            {profileData.memoryCount} episode{profileData.memoryCount !== 1 ? 's' : ''}
          </span>
        </div>
      )}

      {/* Uptime */}
      {profileData && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Uptime
          </div>
          <span style={{ color: '#e0dcd4' }}>{formatUptime(profileData.uptime)}</span>
        </div>
      )}

      {/* Proactive Think Interval (Phase 28b) */}
      {profileData && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Proactive Think Interval
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="range"
              min={60}
              max={1800}
              step={30}
              value={profileData.proactiveCooldown}
              onChange={async (e) => {
                const cooldown = Number(e.target.value);
                try {
                  await fetch(`/api/agent/${agent.id}/proactive-cooldown`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cooldown }),
                  });
                } catch { /* fail silently */ }
              }}
              style={{ flex: 1, accentColor: '#5090d0' }}
            />
            <span style={{ color: '#e0dcd4', fontSize: 12, minWidth: 36, textAlign: 'right' }}>
              {profileData.proactiveCooldown < 120
                ? `${Math.floor(profileData.proactiveCooldown)}s`
                : `${Math.floor(profileData.proactiveCooldown / 60)}m`}
            </span>
          </div>
          <div style={{ color: '#555568', fontSize: 10, marginTop: 2 }}>
            How often this crew member reviews activity independently
          </div>
        </div>
      )}

      {/* Agent ID */}
      <div>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Agent ID
        </div>
        <span style={{ color: '#555568', fontSize: 10, wordBreak: 'break-all' }}>
          {agent.id}
        </span>
      </div>
    </div>
  );
}
