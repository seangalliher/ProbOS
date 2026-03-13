/* Agent tooltip — hover info + click-to-pin (Fix 10) */

import { useEffect, useRef } from 'react';
import { useStore } from '../store/useStore';

export function AgentTooltip() {
  const hovered = useStore((s) => s.hoveredAgent);
  const pinned = useStore((s) => s.pinnedAgent);
  const pos = useStore((s) => s.tooltipPos);
  const setPinnedAgent = useStore((s) => s.setPinnedAgent);
  const tooltipRef = useRef<HTMLDivElement>(null);

  // Dismiss pinned tooltip on click outside
  useEffect(() => {
    if (!pinned) return;

    function handleClickOutside(e: MouseEvent) {
      if (tooltipRef.current && !tooltipRef.current.contains(e.target as Node)) {
        setPinnedAgent(null);
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
  }, [pinned, setPinnedAgent]);

  const agent = pinned || hovered;
  if (!agent) return null;

  const trustLabel = agent.trust >= 0.7 ? 'high' : agent.trust >= 0.35 ? 'medium' : 'low';
  const trustColor = agent.trust >= 0.7 ? '#f0b060' : agent.trust >= 0.35 ? '#88a4c8' : '#7060a8';

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
        {agent.agentType || agent.pool}
      </div>
      <div style={{ color: '#8888a0', fontSize: 11 }}>
        Pool: {agent.pool} &middot; {agent.tier}
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
      {pinned && (
        <div style={{ color: '#666680', fontSize: 10, marginTop: 4 }}>
          Click elsewhere to dismiss
        </div>
      )}
    </div>
  );
}
