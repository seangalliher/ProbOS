/* GlassLayer — frosted glass overlay with center-stage task cards (AD-388, AD-390, AD-391, AD-392) */

import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';
import type { AgentTaskView } from '../store/types';
import { DEPT_COLORS } from './bridge/BridgeCards';
import { GlassTaskCard } from './glass/GlassTaskCard';
import { GlassDAGNodes } from './glass/GlassDAGNodes';
import { ContextRibbon, deriveBridgeState, STATE_COLORS } from './glass/ContextRibbon';
import type { BridgeState } from './glass/ContextRibbon';
import { BriefingCard } from './glass/BriefingCard';
import { ScanLineOverlay } from './glass/ScanLineOverlay';
import { DataRainOverlay } from './glass/DataRainOverlay';
import { soundEngine } from '../audio/soundEngine';
import { useBreakpoint } from '../hooks/useBreakpoint';

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

const INACTIVITY_THRESHOLD_MS = 3 * 60 * 1000;
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
  const soundEnabled = useStore((s) => s.soundEnabled);

  // Atmosphere preferences (AD-391)
  const scanLinesEnabled = useStore((s) => s.scanLinesEnabled);
  const chromaticAberrationEnabled = useStore((s) => s.chromaticAberrationEnabled);
  const dataRainEnabled = useStore((s) => s.dataRainEnabled);
  const atmosphereIntensity = useStore((s) => s.atmosphereIntensity);

  // Agent trust lookup (AD-392)
  const agents = useStore((s) => s.agents);

  // Responsive breakpoint (AD-392)
  const breakpoint = useBreakpoint();
  const isCompact = breakpoint === 'tablet' || breakpoint === 'mobile';

  // Captain's Gaze — throttled mouse-nearest task promotion (AD-392)
  const [gazedTaskId, setGazedTaskId] = useState<string | null>(null);
  const gazeRef = useRef<{ x: number; y: number } | null>(null);
  const gazeTimestampRef = useRef(0);

  // Briefing state (local, not store)
  const [showBriefing, setShowBriefing] = useState(false);
  const [briefingData, setBriefingData] = useState<{
    completedCount: number;
    newNotifCount: number;
  } | null>(null);

  // Activity tracking for return-to-bridge briefing
  const lastActivityRef = useRef(Date.now());
  const wasAwayRef = useRef(false);
  const snapshotRef = useRef<{ doneCount: number; notifCount: number }>({ doneCount: 0, notifCount: 0 });

  // Celebration tracking
  const prevStatusesRef = useRef<Map<string, string>>(new Map());
  const [celebrating, setCelebrating] = useState<Set<string>>(new Set());

  // Luminance ripple tracking (AD-391)
  const prevBridgeStateRef = useRef<BridgeState | null>(null);
  const [rippleActive, setRippleActive] = useState(false);

  // Track activity
  const handleActivity = useCallback(() => {
    const now = Date.now();
    const elapsed = now - lastActivityRef.current;
    lastActivityRef.current = now;

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
        if (soundEnabled) soundEngine.playCaptainReturn();
      }
    }
    wasAwayRef.current = false;
  }, [agentTasks, notifications, soundEnabled]);

  // Mark idle after threshold
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
      setTimeout(() => {
        setCelebrating(prev => {
          const next = new Set(prev);
          for (const id of newCelebrations) next.delete(id);
          return next;
        });
      }, 600);
    }
  }, [agentTasks]);

  // Ctrl+Shift+D toggle for data rain (AD-391)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        useStore.getState().setDataRainEnabled(!useStore.getState().dataRainEnabled);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Only render on canvas view
  if (mainViewer !== 'canvas') return null;

  const activeTasks = agentTasks?.filter(
    t => t.status !== 'done' && t.status !== 'failed'
  ) ?? [];

  const bridgeState = deriveBridgeState(agentTasks, notifications);

  // Luminance ripple on bridge state change (AD-391)
  if (prevBridgeStateRef.current !== null && prevBridgeStateRef.current !== bridgeState && !rippleActive) {
    setRippleActive(true);
    setTimeout(() => setRippleActive(false), 800);
  }
  prevBridgeStateRef.current = bridgeState;

  // Render if active tasks exist OR briefing is pending
  if (activeTasks.length === 0 && !showBriefing) return null;

  const sorted = sortTasks(activeTasks);
  const compact = isCompact || sorted.length >= 6;
  const positions = constellationPositions(sorted.length);

  // Chromatic aberration offset scales with intensity
  const caOffset = atmosphereIntensity * 1.5;

  return (
    <div
      data-testid="glass-layer"
      onMouseMove={(e) => {
        handleActivity();
        gazeRef.current = { x: e.clientX, y: e.clientY };
        // Throttle gaze calculation to 100ms
        const now = Date.now();
        if (now - gazeTimestampRef.current < 100) return;
        gazeTimestampRef.current = now;
        // Find nearest task card wrapper
        const wrappers = e.currentTarget.querySelectorAll<HTMLElement>('[data-testid="glass-task-card-wrapper"]');
        let closestId: string | null = null;
        let closestDist = Infinity;
        wrappers.forEach((el) => {
          const rect = el.getBoundingClientRect();
          const cx = rect.left + rect.width / 2;
          const cy = rect.top + rect.height / 2;
          const dist = Math.hypot(e.clientX - cx, e.clientY - cy);
          if (dist < closestDist) {
            closestDist = dist;
            closestId = el.getAttribute('data-task-id');
          }
        });
        setGazedTaskId(closestDist < 300 ? closestId : null);
      }}
      onMouseLeave={() => {
        gazeRef.current = null;
        setGazedTaskId(null);
      }}
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
        filter: chromaticAberrationEnabled ? 'url(#chromatic-aberration)' : undefined,
      }}
    >
      {/* SVG filter for chromatic aberration (AD-391) */}
      {chromaticAberrationEnabled && (
        <svg style={{ position: 'absolute', width: 0, height: 0 }}>
          <defs>
            <filter id="chromatic-aberration">
              <feColorMatrix type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="red" />
              <feOffset in="red" dx={caOffset} dy={0} result="red-shifted" />
              <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="blue" />
              <feOffset in="blue" dx={-caOffset} dy={0} result="blue-shifted" />
              <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="green" />
              <feBlend in="red-shifted" in2="green" mode="screen" result="rg" />
              <feBlend in="rg" in2="blue-shifted" mode="screen" />
            </filter>
          </defs>
        </svg>
      )}

      {/* Noise texture overlay */}
      <div style={{
        position: 'absolute', inset: 0,
        opacity: 0.03,
        backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
        backgroundSize: '128px 128px',
        pointerEvents: 'none',
      }} />

      {/* Scan lines (AD-391) */}
      {scanLinesEnabled && <ScanLineOverlay intensity={atmosphereIntensity} />}

      {/* Data rain (AD-391) */}
      {dataRainEnabled && (
        <DataRainOverlay
          intensity={atmosphereIntensity}
          stateColor={STATE_COLORS[bridgeState]}
        />
      )}

      {/* Luminance ripple (AD-391) */}
      {rippleActive && (
        <div style={{
          position: 'absolute', inset: 0,
          pointerEvents: 'none',
          zIndex: 3,
          animation: 'luminance-ripple 0.8s ease-out forwards',
        }} />
      )}

      {/* Context Ribbon (AD-390, AD-392) */}
      <ContextRibbon bridgeState={bridgeState} compact={isCompact} />

      {/* Task cards in constellation layout */}
      {sorted.map((task, idx) => {
        const isExpanded = expandedGlassTask === task.id;
        const isCelebrating = celebrating.has(task.id);
        const deptColor = DEPT_COLORS[task.department?.toLowerCase()] || '#666';
        const agentTrust = agents.get(task.agent_id)?.trust ?? 0.5;
        return (
          <div
            key={task.id}
            data-testid="glass-task-card-wrapper"
            data-task-id={task.id}
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
              trust={agentTrust}
              compact={compact}
              isGazed={gazedTaskId === task.id}
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
        @keyframes luminance-ripple {
          0% { background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.04) 50%, rgba(255,255,255,0) 100%); background-position: -100% 0; }
          100% { background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.04) 50%, rgba(255,255,255,0) 100%); background-position: 200% 0; }
        }
      `}</style>
    </div>
  );
}
