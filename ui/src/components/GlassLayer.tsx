/* GlassLayer — frosted glass overlay with center-stage task cards (AD-388) */

import { useStore } from '../store/useStore';
import type { AgentTaskView } from '../store/types';
import { GlassTaskCard } from './glass/GlassTaskCard';

const STATUS_ORDER: Record<string, number> = {
  working: 0,
  review: 1,
  queued: 2,
  done: 3,
  failed: 4,
};

function sortTasks(tasks: AgentTaskView[]): AgentTaskView[] {
  return [...tasks].sort((a, b) => {
    // requires_action first
    if (a.requires_action !== b.requires_action) return a.requires_action ? -1 : 1;
    // then by status
    const sa = STATUS_ORDER[a.status] ?? 9;
    const sb = STATUS_ORDER[b.status] ?? 9;
    if (sa !== sb) return sa - sb;
    // then by priority (lower = higher)
    return a.priority - b.priority;
  });
}

function frostBlur(count: number): string {
  if (count <= 0) return 'blur(0px)';
  if (count <= 2) return 'blur(2px)';
  if (count <= 5) return 'blur(4px)';
  return 'blur(6px)';
}

function frostBg(count: number): string {
  if (count <= 0) return 'rgba(10, 10, 18, 0.0)';
  if (count <= 2) return 'rgba(10, 10, 18, 0.05)';
  if (count <= 5) return 'rgba(10, 10, 18, 0.1)';
  return 'rgba(10, 10, 18, 0.15)';
}

/** Compute positions for the constellation layout */
function constellationPositions(count: number): React.CSSProperties[] {
  if (count === 1) {
    return [{ position: 'absolute', top: '38%', left: '50%', transform: 'translateX(-50%)' }];
  }
  if (count === 2) {
    return [
      { position: 'absolute', top: '38%', left: '50%', transform: 'translateX(calc(-50% - 152px))' },
      { position: 'absolute', top: '38%', left: '50%', transform: 'translateX(calc(-50% + 152px))' },
    ];
  }
  if (count === 3) {
    return [
      { position: 'absolute', top: '32%', left: '50%', transform: 'translateX(-50%)' },
      { position: 'absolute', top: '50%', left: '50%', transform: 'translateX(calc(-50% - 152px))' },
      { position: 'absolute', top: '50%', left: '50%', transform: 'translateX(calc(-50% + 152px))' },
    ];
  }

  // 4-5 tasks: 2-3 top row, 2 bottom row
  const positions: React.CSSProperties[] = [];
  const topCount = Math.ceil(count / 2);
  const bottomCount = count - topCount;
  const gap = 296; // card width (280) + 16px gap

  for (let i = 0; i < topCount; i++) {
    const offset = (i - (topCount - 1) / 2) * gap;
    positions.push({
      position: 'absolute', top: '30%', left: '50%',
      transform: `translateX(calc(-50% + ${offset}px))`,
    });
  }
  for (let i = 0; i < bottomCount; i++) {
    const offset = (i - (bottomCount - 1) / 2) * gap;
    positions.push({
      position: 'absolute', top: '52%', left: '50%',
      transform: `translateX(calc(-50% + ${offset}px))`,
    });
  }
  return positions;
}

export function GlassLayer() {
  const mainViewer = useStore((s) => s.mainViewer);
  const agentTasks = useStore((s) => s.agentTasks);

  // Only render on canvas view
  if (mainViewer !== 'canvas') return null;

  // Filter to active tasks (not done/failed)
  const activeTasks = agentTasks?.filter(
    t => t.status !== 'done' && t.status !== 'failed'
  ) ?? [];

  // Render nothing when no active tasks
  if (activeTasks.length === 0) return null;

  const sorted = sortTasks(activeTasks);
  const compact = sorted.length >= 6;
  const positions = constellationPositions(sorted.length);

  return (
    <div
      data-testid="glass-layer"
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 5,
        pointerEvents: 'none',
        backdropFilter: frostBlur(sorted.length),
        WebkitBackdropFilter: frostBlur(sorted.length),
        background: frostBg(sorted.length),
        transition: 'backdrop-filter 0.5s ease, background 0.5s ease',
      }}
    >
      {/* Noise texture overlay */}
      <div style={{
        position: 'absolute', inset: 0,
        opacity: 0.03,
        backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
        backgroundSize: '128px 128px',
        pointerEvents: 'none',
      }} />

      {/* Task cards in constellation layout */}
      {sorted.map((task, idx) => (
        <div
          key={task.id}
          data-testid="glass-task-card-wrapper"
          style={{
            ...(positions[idx] || { position: 'absolute', top: '40%', left: '50%', transform: 'translateX(-50%)' }),
            transform: `${(positions[idx]?.transform as string) || 'translateX(-50%)'} ${compact ? 'scale(0.9)' : ''}`.trim(),
          } as React.CSSProperties}
        >
          <GlassTaskCard
            task={task}
            elevated={task.requires_action}
          />
        </div>
      ))}

      {/* Keyframe for attention pulse */}
      <style>{`
        @keyframes glass-attention {
          0%, 100% { box-shadow: 0 2px 12px rgba(240, 176, 96, 0.15), 0 2px 8px rgba(0, 0, 0, 0.4); }
          50% { box-shadow: 0 2px 20px rgba(240, 176, 96, 0.3), 0 2px 8px rgba(0, 0, 0, 0.4); }
        }
      `}</style>
    </div>
  );
}
