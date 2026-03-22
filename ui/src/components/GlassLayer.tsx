/* GlassLayer — frosted glass overlay with center-stage task cards (AD-388, AD-390) */

import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';
import type { AgentTaskView } from '../store/types';
import { DEPT_COLORS } from './bridge/BridgeCards';
import { GlassTaskCard } from './glass/GlassTaskCard';
import { GlassDAGNodes } from './glass/GlassDAGNodes';
import { ContextRibbon, deriveBridgeState } from './glass/ContextRibbon';
import type { BridgeState } from './glass/ContextRibbon';
import { BriefingCard } from './glass/BriefingCard';

const STATUS_ORDER: Record<string, number> = {
  working: 0,
  review: 1,
  queued: 2,
  done: 3,
  failed: 4,
};

function sortTasks(tasks: AgentTaskView[]): AgentTaskView[] {
  return [...tasks].sort((a, b) => {
    if (a.requires_action !== b.requires_action) return a.requires_action ? -1 : 1;
    const sa = STATUS_ORDER[a.status] ?? 9;
    const sb = STATUS_ORDER[b.status] ?? 9;
    if (sa !== sb) return sa - sb;
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

const EDGE_GLOW: Record<BridgeState, string> = {
  idle: 'inset 0 0 80px rgba(56, 200, 192, 0.04)',
  autonomous: 'inset 0 0 80px rgba(212, 160, 41, 0.06)',
  attention: 'inset 0 0 60px rgba(240, 174, 64, 0.1)',
};

export { EDGE_GLOW };

const INACTIVITY_THRESHOLD_MS = 3 * 60 * 1000; // 3 minutes
const BRIEFING_DURATION_MS = 8000;

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

  const positions: React.CSSProperties[] = [];
  const topCount = Math.ceil(count / 2);
  const bottomCount = count - topCount;
  const gap = 296;

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
  const notifications = useStore((s) => s.notifications);
  const expandedGlassTask = useStore((s) => s.expandedGlassTask);

  // Briefing state (local, not store)
  const [showBriefing, setShowBriefing] = useState(false);
  const [briefingData, setBriefingData] = useState<{
    completedCount: number;
    newNotifCount: number;
  } | null>(null);

  // Activity tracking for return-to-bridge briefing
  const lastActivityRef = useRef(Date.now());
  const wasAwayRef = useRef(false);
  // Snapshot counts when Captain goes idle
  const snapshotRef = useRef<{ doneCount: number; notifCount: number }>({ doneCount: 0, notifCount: 0 });

  // Celebration tracking
  const prevStatusesRef = useRef<Map<string, string>>(new Map());
  const [celebrating, setCelebrating] = useState<Set<string>>(new Set());

  // Track activity
  const handleActivity = useCallback(() => {
    const now = Date.now();
    const elapsed = now - lastActivityRef.current;
    lastActivityRef.current = now;

    // If Captain was away (3+ min), check for briefing
    if (elapsed >= INACTIVITY_THRESHOLD_MS) {
      const currentDoneCount = agentTasks?.filter(t => t.status === 'done').length ?? 0;
      const currentNotifCount = notifications?.length ?? 0;
      const completedWhileAway = currentDoneCount - snapshotRef.current.doneCount;
      const newNotifs = currentNotifCount - snapshotRef.current.notifCount;

      if (completedWhileAway > 0 || newNotifs > 0) {
        setBriefingData({
          completedCount: Math.max(0, completedWhileAway),
          newNotifCount: Math.max(0, newNotifs),
        });
        setShowBriefing(true);
      }
    }
    wasAwayRef.current = false;
  }, [agentTasks, notifications]);

  // Mark idle after threshold — snapshot current counts
  useEffect(() => {
    const interval = setInterval(() => {
      const elapsed = Date.now() - lastActivityRef.current;
      if (elapsed >= INACTIVITY_THRESHOLD_MS && !wasAwayRef.current) {
        wasAwayRef.current = true;
        snapshotRef.current = {
          doneCount: agentTasks?.filter(t => t.status === 'done').length ?? 0,
          notifCount: notifications?.length ?? 0,
        };
      }
    }, 10000);
    return () => clearInterval(interval);
  }, [agentTasks, notifications]);

  // Auto-dismiss briefing
  useEffect(() => {
    if (!showBriefing) return;
    const timer = setTimeout(() => {
      setShowBriefing(false);
      setBriefingData(null);
    }, BRIEFING_DURATION_MS);
    return () => clearTimeout(timer);
  }, [showBriefing]);

  // Celebration detection
  useEffect(() => {
    if (!agentTasks) return;
    const newCelebrations = new Set<string>();
    for (const task of agentTasks) {
      const prev = prevStatusesRef.current.get(task.id);
      if (prev && prev !== 'done' && prev !== 'failed' && task.status === 'done') {
        newCelebrations.add(task.id);
      }
      prevStatusesRef.current.set(task.id, task.status);
    }
    if (newCelebrations.size > 0) {
      setCelebrating(prev => new Set([...prev, ...newCelebrations]));
      // Clear celebrations after bloom duration
      setTimeout(() => {
        setCelebrating(prev => {
          const next = new Set(prev);
          for (const id of newCelebrations) next.delete(id);
          return next;
        });
      }, 600);
    }
  }, [agentTasks]);

  // Only render on canvas view
  if (mainViewer !== 'canvas') return null;

  const activeTasks = agentTasks?.filter(
    t => t.status !== 'done' && t.status !== 'failed'
  ) ?? [];

  const bridgeState = deriveBridgeState(agentTasks, notifications);

  // Render if active tasks exist OR briefing is pending
  if (activeTasks.length === 0 && !showBriefing) return null;

  const sorted = sortTasks(activeTasks);
  const compact = sorted.length >= 6;
  const positions = constellationPositions(sorted.length);

  return (
    <div
      data-testid="glass-layer"
      onMouseMove={handleActivity}
      onKeyDown={handleActivity}
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 5,
        pointerEvents: 'none',
        backdropFilter: frostBlur(sorted.length),
        WebkitBackdropFilter: frostBlur(sorted.length),
        background: frostBg(sorted.length),
        boxShadow: EDGE_GLOW[bridgeState],
        transition: 'backdrop-filter 0.5s ease, background 0.5s ease, box-shadow 1.2s linear',
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

      {/* Context Ribbon (AD-390) */}
      <ContextRibbon bridgeState={bridgeState} />

      {/* Task cards in constellation layout */}
      {sorted.map((task, idx) => {
        const isExpanded = expandedGlassTask === task.id;
        const isCelebrating = celebrating.has(task.id);
        const deptColor = DEPT_COLORS[task.department?.toLowerCase()] || '#666';
        return (
          <div
            key={task.id}
            data-testid="glass-task-card-wrapper"
            style={{
              ...(positions[idx] || { position: 'absolute', top: '40%', left: '50%', transform: 'translateX(-50%)' }),
              transform: `${(positions[idx]?.transform as string) || 'translateX(-50%)'} ${compact ? 'scale(0.9)' : ''} ${task.requires_action ? 'translateY(-20px)' : ''}`.trim(),
              transition: 'transform 0.3s ease, box-shadow 0.6s ease-out',
              boxShadow: isCelebrating ? `0 0 40px ${deptColor}4d` : 'none',
            } as React.CSSProperties}
          >
            <GlassTaskCard
              task={task}
              elevated={false}
            />
            {isExpanded && task.steps && task.steps.length > 0 && (
              <GlassDAGNodes
                steps={task.steps}
                department={task.department}
                requiresAction={task.requires_action}
              />
            )}
          </div>
        );
      })}

      {/* Briefing card (AD-390) */}
      {showBriefing && briefingData && (
        <BriefingCard
          completedCount={briefingData.completedCount}
          newNotifCount={briefingData.newNotifCount}
          bridgeState={bridgeState}
          onDismiss={() => {
            setShowBriefing(false);
            setBriefingData(null);
          }}
        />
      )}

      {/* Keyframe animations */}
      <style>{`
        @keyframes glass-attention {
          0%, 100% { box-shadow: 0 2px 12px rgba(240, 176, 96, 0.15), 0 2px 8px rgba(0, 0, 0, 0.4); }
          50% { box-shadow: 0 2px 20px rgba(240, 176, 96, 0.3), 0 2px 8px rgba(0, 0, 0, 0.4); }
        }
        @keyframes briefing-fade-in {
          from { opacity: 0; transform: translateX(-50%) translateY(10px); }
          to { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
      `}</style>
    </div>
  );
}
