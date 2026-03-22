/* GlassDAGNodes — radial step nodes + dependency lines around expanded task card (AD-389) */

import { useState } from 'react';
import type { TaskStepView } from '../../store/types';
import { DEPT_COLORS } from '../bridge/BridgeCards';

interface GlassDAGNodesProps {
  steps: TaskStepView[];
  department: string;
  requiresAction: boolean;
}

const STEP_ICONS: Record<string, string> = {
  done: '\u25CF',
  in_progress: '\u25D0',
  pending: '\u25CB',
  failed: '\u2715',
};

const STEP_BORDER_COLORS: Record<string, string> = {
  done: 'rgba(72, 184, 96, 0.4)',
  pending: 'rgba(255, 255, 255, 0.1)',
  failed: 'rgba(200, 64, 64, 0.5)',
};

const STEP_ICON_COLORS: Record<string, string> = {
  done: '#48b860',
  pending: '#555',
  failed: '#c84040',
};

function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function GlassDAGNodes({ steps, department, requiresAction }: GlassDAGNodesProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const deptColor = DEPT_COLORS[department?.toLowerCase()] || '#666';

  if (steps.length === 0) return null;

  const radius = Math.min(160, 120 + steps.length * 4);
  // Card center is at (140, ~45) — half of card width=280, approximate card midheight
  const cx = 140;
  const cy = 45;

  // Compute node positions radially (clockwise from top)
  const nodePositions = steps.map((_, i) => {
    const angle = (2 * Math.PI * i) / steps.length - Math.PI / 2; // start from top
    return {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    };
  });

  return (
    <div
      data-testid="glass-dag-nodes"
      style={{
        position: 'absolute',
        top: requiresAction ? -20 : 0,
        left: 0,
        width: 280,
        height: 0,
        pointerEvents: 'none',
        transition: 'top 0.3s ease',
      }}
    >
      {/* SVG dependency lines */}
      <svg
        style={{
          position: 'absolute',
          top: cy - radius - 20,
          left: cx - radius - 20,
          width: (radius + 20) * 2,
          height: (radius + 20) * 2,
          pointerEvents: 'none',
          overflow: 'visible',
        }}
      >
        {steps.map((step, i) => {
          if (i === steps.length - 1) return null;
          const from = nodePositions[i];
          const to = nodePositions[i + 1];
          const off = radius + 20; // SVG origin offset
          const completed = step.status === 'done';
          return (
            <line
              key={`line-${i}`}
              x1={from.x - cx + off}
              y1={from.y - cy + off}
              x2={to.x - cx + off}
              y2={to.y - cy + off}
              stroke={completed ? deptColor : 'rgba(255, 255, 255, 0.08)'}
              strokeOpacity={completed ? 0.3 : 1}
              strokeWidth={1}
            />
          );
        })}
      </svg>

      {/* Step nodes */}
      {steps.map((step, i) => {
        const pos = nodePositions[i];
        const isActive = step.status === 'in_progress';
        const borderColor = isActive ? deptColor : (STEP_BORDER_COLORS[step.status] || 'rgba(255,255,255,0.1)');
        const iconColor = isActive ? deptColor : (STEP_ICON_COLORS[step.status] || '#555');

        return (
          <div
            key={i}
            data-testid="glass-dag-node"
            onMouseEnter={() => setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
            style={{
              position: 'absolute',
              left: pos.x - 14,
              top: pos.y - 14,
              width: 28,
              height: 28,
              borderRadius: '50%',
              background: 'rgba(26, 26, 46, 0.8)',
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
              border: `1px solid ${borderColor}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 12,
              color: iconColor,
              pointerEvents: 'auto',
              cursor: 'default',
              animation: isActive ? 'neural-pulse 2s ease-in-out infinite' : undefined,
              // Staggered fade-in
              opacity: 1,
              transform: 'scale(1)',
              transition: `opacity 0.2s ease-out ${i * 0.08}s, transform 0.2s ease-out ${i * 0.08}s`,
            }}
          >
            {STEP_ICONS[step.status] || '\u25CB'}

            {/* Hover tooltip */}
            {hoveredIdx === i && (
              <div style={{
                position: 'absolute',
                top: 34,
                left: '50%',
                transform: 'translateX(-50%)',
                whiteSpace: 'nowrap',
                padding: '3px 8px',
                borderRadius: 3,
                background: 'rgba(10, 10, 18, 0.9)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 10,
                color: '#808090',
                zIndex: 10,
                pointerEvents: 'none',
              }}>
                {step.label}
                {step.duration_ms > 0 && (
                  <span style={{ color: '#555', marginLeft: 6 }}>
                    {formatDurationMs(step.duration_ms)}
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
