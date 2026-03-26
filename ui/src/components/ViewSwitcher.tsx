/* View Switcher — top-left tab switcher for main viewer mode (AD-325) */

import { useStore } from '../store/useStore';

export function ViewSwitcher() {
  const mainViewer = useStore(s => s.mainViewer);
  if (mainViewer === 'canvas') return null;

  const tabs: { key: 'canvas' | 'kanban' | 'system'; label: string }[] = [
    { key: 'canvas', label: 'CANVAS' },
    { key: 'kanban', label: 'KANBAN' },
    { key: 'system', label: 'SYSTEM' },
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
