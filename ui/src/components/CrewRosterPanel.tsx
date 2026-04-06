/**
 * AD-513: Crew Roster Panel — Ship's Complement directory.
 *
 * Floating panel showing department-grouped crew with status, rank, trust.
 * Click-to-profile navigation. Follows AgentProfilePanel floating pattern.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { useStore } from '../store/useStore';
import type { CrewManifestEntry } from '../store/types';

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

const RANK_LABELS: Record<string, string> = {
  ensign: 'ENS',
  lieutenant: 'LT',
  commander: 'CMDR',
  senior_officer: 'SR',
};

const RANK_COLORS: Record<string, string> = {
  ensign: '#8888a0',
  lieutenant: '#88a4c8',
  commander: '#f0b060',
  senior_officer: '#e0c070',
};

function trustColor(score: number): string {
  if (score > 0.7) return '#f0b060';
  if (score > 0.35) return '#88a4c8';
  return '#7060a8';
}

function deptColor(dept: string): string {
  return DEPT_COLORS[dept.toLowerCase()] || '#8888a0';
}

export default function CrewRosterPanel() {
  const open = useStore(s => s.crewManifestOpen);
  const manifest = useStore(s => s.crewManifest);
  const close = useStore(s => s.closeCrewManifest);
  const openProfile = useStore(s => s.openAgentProfile);

  const [filter, setFilter] = useState<string | null>(null);
  const [pos, setPos] = useState({ x: 60, y: 60 });
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true);
    dragOffset.current = { x: e.clientX - pos.x, y: e.clientY - pos.y };
  }, [pos]);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const newX = Math.max(0, Math.min(window.innerWidth - 360, e.clientX - dragOffset.current.x));
      const newY = Math.max(0, Math.min(window.innerHeight - 100, e.clientY - dragOffset.current.y));
      setPos({ x: newX, y: newY });
    };
    const onUp = () => setIsDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isDragging]);

  if (!open) return null;

  const filtered = manifest
    ? (filter ? manifest.filter(e => e.department === filter) : manifest)
    : [];

  // Group by department
  const departments: Record<string, CrewManifestEntry[]> = {};
  for (const entry of filtered) {
    const dept = entry.department || 'unassigned';
    if (!departments[dept]) departments[dept] = [];
    departments[dept].push(entry);
  }

  const deptNames = Object.keys(departments).sort();
  const uniqueDepts = manifest
    ? [...new Set(manifest.map(e => e.department || 'unassigned'))].sort()
    : [];

  return (
    <div style={{
      position: 'fixed',
      left: pos.x,
      top: pos.y,
      width: 360,
      height: 520,
      zIndex: 25,
      background: 'rgba(10, 10, 18, 0.92)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      border: '1px solid rgba(240, 176, 96, 0.2)',
      borderRadius: 12,
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      fontFamily: "'JetBrains Mono', monospace",
      color: '#e0dcd4',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Title bar */}
      <div
        onMouseDown={onMouseDown}
        style={{
          padding: '10px 14px',
          borderBottom: '1px solid rgba(240, 176, 96, 0.1)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          cursor: isDragging ? 'grabbing' : 'grab',
          userSelect: 'none',
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, flex: 1 }}>
          SHIP'S COMPLEMENT
        </span>
        {manifest && (
          <span style={{
            background: 'rgba(240, 176, 96, 0.2)',
            color: '#f0b060',
            borderRadius: 8,
            padding: '1px 7px',
            fontSize: 9,
            fontWeight: 700,
          }}>{filtered.length}</span>
        )}
        <div
          onClick={close}
          style={{
            cursor: 'pointer',
            fontSize: 14,
            color: '#8888a0',
            lineHeight: 1,
          }}
        >x</div>
      </div>

      {/* Filter chips */}
      <div style={{
        padding: '6px 12px',
        display: 'flex',
        flexWrap: 'wrap',
        gap: 4,
        borderBottom: '1px solid rgba(240, 176, 96, 0.06)',
      }}>
        <FilterChip label="ALL" active={!filter} onClick={() => setFilter(null)} color="#8888a0" />
        {uniqueDepts.map(d => (
          <FilterChip
            key={d}
            label={d.toUpperCase().slice(0, 4)}
            active={filter === d}
            onClick={() => setFilter(filter === d ? null : d)}
            color={deptColor(d)}
          />
        ))}
      </div>

      {/* Crew list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {!manifest && (
          <div style={{ padding: 20, textAlign: 'center', color: '#8888a0', fontSize: 11 }}>
            Loading...
          </div>
        )}
        {deptNames.map(dept => (
          <div key={dept}>
            <div style={{
              padding: '6px 14px 2px',
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: 1.2,
              color: deptColor(dept),
              textTransform: 'uppercase',
            }}>{dept}</div>
            {departments[dept].map(entry => (
              <CrewRow
                key={entry.agentType}
                entry={entry}
                onClickProfile={() => {
                  if (entry.agentId) openProfile(entry.agentId);
                }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function FilterChip({ label, active, onClick, color }: {
  label: string;
  active: boolean;
  onClick: () => void;
  color: string;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: '2px 8px',
        fontSize: 8,
        fontWeight: 700,
        letterSpacing: 1,
        borderRadius: 4,
        cursor: 'pointer',
        userSelect: 'none',
        background: active ? `${color}33` : 'transparent',
        color: active ? color : '#666680',
        border: `1px solid ${active ? `${color}44` : 'rgba(136, 136, 160, 0.15)'}`,
      }}
    >{label}</div>
  );
}

function CrewRow({ entry, onClickProfile }: {
  entry: CrewManifestEntry;
  onClickProfile: () => void;
}) {
  const dept = entry.department || 'unassigned';
  const rankLabel = RANK_LABELS[entry.rank] || entry.rank?.toUpperCase()?.slice(0, 4) || '?';
  const rankColor = RANK_COLORS[entry.rank] || '#8888a0';

  return (
    <div
      onClick={onClickProfile}
      style={{
        padding: '5px 14px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        cursor: entry.agentId ? 'pointer' : 'default',
        borderRadius: 4,
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(240, 176, 96, 0.06)')}
      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
    >
      {/* Department dot */}
      <div style={{
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: deptColor(dept),
        flexShrink: 0,
      }} />

      {/* Name + post */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#e0dcd4' }}>
          {entry.callsign}
        </div>
        <div style={{
          fontSize: 9,
          color: '#8888a0',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>{entry.post}</div>
      </div>

      {/* Rank badge */}
      <span style={{
        fontSize: 8,
        fontWeight: 700,
        letterSpacing: 0.8,
        color: rankColor,
        padding: '1px 5px',
        border: `1px solid ${rankColor}44`,
        borderRadius: 3,
        flexShrink: 0,
      }}>{rankLabel}</span>

      {/* Trust bar */}
      <div style={{
        width: 30,
        height: 3,
        borderRadius: 1.5,
        background: 'rgba(136, 136, 160, 0.15)',
        flexShrink: 0,
      }}>
        <div style={{
          width: `${Math.round(entry.trustScore * 100)}%`,
          height: '100%',
          borderRadius: 1.5,
          background: trustColor(entry.trustScore),
        }} />
      </div>
    </div>
  );
}
