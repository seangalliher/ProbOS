/* Agent tooltip — hover info + click-to-pin + task info (Fix 10, AD-324) */

import { useEffect, useRef } from 'react';
import { useStore } from '../store/useStore';

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

function formatElapsed(startedAt: number): string {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  if (min < 60) return `${min}m ${rem}s`;
  const hr = Math.floor(min / 60);
  return `${hr}h ${min % 60}m`;
}

export function AgentTooltip() {
  const hovered = useStore((s) => s.hoveredAgent);
  const pinned = useStore((s) => s.pinnedAgent);
  const pos = useStore((s) => s.tooltipPos);
  const agentTasks = useStore((s) => s.agentTasks);
  const poolToGroup = useStore((s) => s.poolToGroup);
  const tooltipRef = useRef<HTMLDivElement>(null);

  // Dismiss pinned tooltip on click outside
  useEffect(() => {
    if (!pinned) return;

    function handleClickOutside(e: MouseEvent) {
      if (tooltipRef.current && !tooltipRef.current.contains(e.target as Node)) {
        useStore.getState().setPinnedAgent(null);
      }
    }

    // Delay listener to avoid immediately dismissing on the same click that pinned
    const timer = setTimeout(() => {
      document.addEventListener('click', handleClickOutside);
    }, 100);

    return () => {
      clearTimeout(timer);
      document.removeEventListener('click', handleClickOutside);
    };
  }, [pinned]);

  const agent = pinned || hovered;
  if (!agent) return null;

  const trustLabel = agent.trust >= 0.7 ? 'high' : agent.trust >= 0.35 ? 'medium' : 'low';
  const trustColor = agent.trust >= 0.7 ? '#f0b060' : agent.trust >= 0.35 ? '#88a4c8' : '#7060a8';
  const department = poolToGroup?.[agent.pool] || '';
  const deptColor = DEPT_COLORS[department?.toLowerCase()] || '#666';

  const currentTask = agentTasks?.find(
    t => t.agent_id === agent.id && (t.status === 'working' || t.status === 'review')
  );

  return (
    <div
      ref={tooltipRef}
      style={{
        position: 'absolute',
        left: pinned ? undefined : Math.min(pos.x + 16, window.innerWidth - 300),
        top: pinned ? undefined : Math.max(pos.y - 60, 8),
        right: pinned ? 16 : undefined,
        bottom: pinned ? 48 : undefined,
        background: 'rgba(10, 10, 18, 0.88)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: `1px solid rgba(${agent.trust >= 0.7 ? '240, 176, 96' : '136, 164, 200'}, 0.25)`,
        borderRadius: 8,
        padding: '10px 14px',
        color: '#e0dcd4',
        fontSize: 13,
        lineHeight: 1.6,
        pointerEvents: pinned ? 'auto' : 'none',
        zIndex: 20,
        maxWidth: 300,
        minWidth: 180,
      }}
    >
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>
        {agent.callsign ? `${agent.callsign} (${agent.agentType})` : (agent.agentType || agent.pool)}
      </div>
      <div style={{ color: '#8888a0', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
        <span>Pool: {agent.pool}</span>
        <span>{'\u00B7'}</span>
        <span>{agent.tier}</span>
        {department && (
          <>
            <span>{'\u00B7'}</span>
            <span style={{ color: deptColor, textTransform: 'capitalize' }}>{department}</span>
          </>
        )}
      </div>
      <div style={{ marginTop: 4 }}>
        <span style={{ color: '#8888a0' }}>Trust: </span>
        <span style={{ color: trustColor, fontWeight: 500 }}>
          {(agent.trust * 100).toFixed(0)}%
        </span>
        <span style={{ color: '#666680', fontSize: 11 }}> ({trustLabel})</span>
      </div>
      <div>
        <span style={{ color: '#8888a0' }}>Confidence: </span>
        <span style={{ color: '#e0dcd4' }}>{(agent.confidence * 100).toFixed(0)}%</span>
      </div>
      <div>
        <span style={{ color: '#8888a0' }}>State: </span>
        <span style={{ color: agent.state === 'active' ? '#80c878' : '#f0b060' }}>{agent.state}</span>
      </div>
      <div style={{ color: '#555568', fontSize: 10, marginTop: 4, wordBreak: 'break-all' }}>
        {agent.id}
      </div>

      {/* Current task section (AD-324) */}
      {currentTask && (
        <>
          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', margin: '6px 0' }} />
          <div style={{ fontSize: 11 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
              <span style={{ fontWeight: 600, color: '#c8d0e0' }}>
                {currentTask.title.length > 50
                  ? currentTask.title.slice(0, 50) + '\u2026'
                  : currentTask.title}
              </span>
              {currentTask.requires_action && (
                <span style={{ color: '#f0b060', fontSize: 10, fontWeight: 600 }}>
                  {'\u26A0'} Needs attention
                </span>
              )}
            </div>

            {/* Step label */}
            {currentTask.step_total > 0 && (
              <div style={{ color: '#8888a0', fontSize: 10 }}>
                Step {currentTask.step_current} of {currentTask.step_total}
                {currentTask.steps?.[currentTask.step_current - 1]?.label &&
                  `: ${currentTask.steps[currentTask.step_current - 1].label}`}
              </div>
            )}

            {/* Elapsed time */}
            {currentTask.started_at > 0 && (
              <div style={{ color: '#666680', fontSize: 10 }}>
                Elapsed: {formatElapsed(currentTask.started_at)}
              </div>
            )}

            {/* Progress bar */}
            {currentTask.step_total > 0 && (
              <div style={{
                height: 4,
                borderRadius: 2,
                background: 'rgba(255,255,255,0.06)',
                marginTop: 4,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${(currentTask.step_current / currentTask.step_total) * 100}%`,
                  background: deptColor || '#5090d0',
                  borderRadius: 2,
                  transition: 'width 0.3s ease',
                }} />
              </div>
            )}
          </div>

          {/* Click-through to Activity Drawer when pinned */}
          {pinned && (
            <button
              onClick={() => useStore.setState({ bridgeOpen: true })}
              style={{
                background: 'none',
                border: 'none',
                color: '#5090d0',
                fontSize: 10,
                cursor: 'pointer',
                padding: '4px 0 0',
                textDecoration: 'underline',
              }}
            >
              Open Bridge
            </button>
          )}
        </>
      )}

      {pinned && !currentTask && (
        <div style={{ color: '#666680', fontSize: 10, marginTop: 4 }}>
          Click elsewhere to dismiss
        </div>
      )}
      {pinned && currentTask && (
        <div style={{ color: '#666680', fontSize: 10, marginTop: 2 }}>
          Click elsewhere to dismiss
        </div>
      )}
    </div>
  );
}
