/* View Switcher — top-left tab switcher for main viewer mode (AD-325) */

import { useEffect } from 'react';
import { useStore } from '../store/useStore';

export function ViewSwitcher() {
  const mainViewer = useStore(s => s.mainViewer);
  // KANBAN (Mission Control) only surfaces the build/design pipeline. Hide it
  // when there are no active builds so it isn't a confusing empty board next to
  // the crew WORK board (HXI progressive-disclosure, AD-325).
  const buildCount = useStore(s => s.missionControlTasks?.length ?? 0);
  const hasBuilds = buildCount > 0;

  // If the Kanban tab is hidden out from under the viewer, fall back to WORK.
  useEffect(() => {
    if (mainViewer === 'kanban' && !hasBuilds) {
      useStore.setState({ mainViewer: 'work' });
    }
  }, [mainViewer, hasBuilds]);

  if (mainViewer === 'canvas') return null;

  const tabs: { key: 'canvas' | 'kanban' | 'system' | 'work' | 'bills'; label: string }[] = [
    { key: 'canvas', label: 'CANVAS' },
    ...(hasBuilds ? [{ key: 'kanban' as const, label: 'KANBAN' }] : []),
    { key: 'system', label: 'SYSTEM' },
    { key: 'work', label: 'WORK' },
    { key: 'bills', label: 'BILLS' },
  ];

  return (
    <div style={{
      position: 'fixed', top: 12, left: 12, zIndex: 25,
      display: 'flex', gap: 4, pointerEvents: 'auto',
    }}>
      {tabs.map(tab => (
        <button
          key={tab.key}
          onClick={() => useStore.setState({ mainViewer: tab.key })}
          style={{
            padding: '3px 8px',
            borderRadius: 4,
            fontSize: 9,
            fontWeight: 600,
            letterSpacing: 1,
            cursor: 'pointer',
            fontFamily: "'JetBrains Mono', monospace",
            background: mainViewer === tab.key ? 'rgba(240,176,96,0.15)' : 'rgba(10,10,18,0.6)',
            border: `1px solid ${mainViewer === tab.key ? 'rgba(240,176,96,0.4)' : 'rgba(255,255,255,0.15)'}`,
            color: mainViewer === tab.key ? '#f0b060' : '#888',
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
