/**
 * AD-719b: Copilot-style left rail.
 *
 * Self-contained shell component. Returns null when the localStorage flag
 * `hxi_left_rail_enabled` is not "true" (default-OFF for v1).
 *
 * Consumer wires the rail's data via props - online agents + recent threads
 * - so the rail itself is a pure presentational component. Zustand-store
 * wiring is a parent concern (deferred to AD-719b-parent-wire).
 *
 * Per HXI Design Principle #3: inline SVG glyphs only (stroke-based, no
 * emoji). Active state amber `#f0b060`; inactive `#666680`.
 * Per HXI Design Principle #5: progressive disclosure - first-time users
 * see fewer entries; veteran (visit count >10) see denser lists.
 */
import React, { useEffect, useState } from 'react';

export interface LeftRailAgent {
  agent_id: string;
  callsign: string;
  department?: string;
  status: 'online' | 'offline' | 'degraded';
}

export interface LeftRailThread {
  thread_id: string;
  title: string;
  is_dm?: boolean;
}

export interface LeftRailProps {
  agents: LeftRailAgent[];
  recentThreads: LeftRailThread[];
  onSelectAgent?: (agentId: string) => void;
  onSelectThread?: (threadId: string) => void;
}

const STORAGE_ENABLED = 'hxi_left_rail_enabled';
const STORAGE_COLLAPSED = 'hxi_left_rail_collapsed';
const STORAGE_VISITS = 'hxi_visit_count';

const COLOR_ACTIVE = '#f0b060';
const COLOR_INACTIVE = '#666680';

/**
 * AD-766: Pin the Captain's Yeoman to the top of the 1:1 DM list.
 * Stable secondary order preserved for the rest of the agents.
 */
export function sortYeomanFirst<T extends { callsign: string }>(
  agents: readonly T[],
): T[] {
  const yeoIndex = agents.findIndex((a) => a.callsign === 'Yeo');
  if (yeoIndex <= 0) return [...agents];
  const yeo = agents[yeoIndex];
  return [yeo, ...agents.slice(0, yeoIndex), ...agents.slice(yeoIndex + 1)];
}

function readBool(key: string): boolean {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(key) === 'true';
  } catch {
    return false;
  }
}

function readInt(key: string): number {
  try {
    if (typeof window === 'undefined') return 0;
    const raw = window.localStorage.getItem(key);
    return raw ? parseInt(raw, 10) || 0 : 0;
  } catch {
    return 0;
  }
}

function writeKey(key: string, value: string): void {
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(key, value);
    }
  } catch {
    // ignore
  }
}

/**
 * Stroke-based glyphs. Each accepts a `color` prop; no fills.
 */
function GlyphAgents({ color }: { color: string }) {
  return (
    <svg
      width="16" height="16" viewBox="0 0 16 16" fill="none" stroke={color}
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
    >
      <circle cx="8" cy="6" r="2.5" />
      <path d="M3 14c0-2.5 2.3-4.5 5-4.5s5 2 5 4.5" />
    </svg>
  );
}

function GlyphThreads({ color }: { color: string }) {
  return (
    <svg
      width="16" height="16" viewBox="0 0 16 16" fill="none" stroke={color}
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
    >
      <path d="M2 5h12M2 9h10M2 13h8" />
    </svg>
  );
}

function GlyphCollapse({ color, collapsed }: { color: string; collapsed: boolean }) {
  return (
    <svg
      width="14" height="14" viewBox="0 0 16 16" fill="none" stroke={color}
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
    >
      {collapsed ? (
        <path d="M5 3l6 5-6 5" />
      ) : (
        <path d="M11 3l-6 5 6 5" />
      )}
    </svg>
  );
}

export function LeftRail({
  agents,
  recentThreads,
  onSelectAgent,
  onSelectThread,
}: LeftRailProps) {
  const [enabled] = useState<boolean>(() => readBool(STORAGE_ENABLED));
  const [collapsed, setCollapsed] = useState<boolean>(() => readBool(STORAGE_COLLAPSED));
  const [visits] = useState<number>(() => readInt(STORAGE_VISITS));

  // Increment visit counter once per mount.
  useEffect(() => {
    writeKey(STORAGE_VISITS, String(visits + 1));
    // intentionally only run once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!enabled) {
    return null;
  }

  const isVeteran = visits >= 10;
  const maxAgents = isVeteran ? 12 : 5;
  const maxThreads = isVeteran ? 8 : 3;

  const visibleAgents = sortYeomanFirst(
    agents.filter((a) => a.status === 'online'),
  ).slice(0, maxAgents);
  const visibleThreads = recentThreads.slice(0, maxThreads);

  const width = collapsed ? 56 : 240;

  return (
    <div
      data-testid="hxi-left-rail"
      style={{
        width,
        background: 'rgba(0, 0, 0, 0.4)',
        borderRight: `1px solid ${COLOR_INACTIVE}33`,
        color: '#ccccd8',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        padding: 8,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        transition: 'width 120ms ease',
      }}
    >
      <button
        data-testid="hxi-left-rail-collapse-toggle"
        onClick={() => {
          const next = !collapsed;
          setCollapsed(next);
          writeKey(STORAGE_COLLAPSED, String(next));
        }}
        aria-label={collapsed ? 'Expand left rail' : 'Collapse left rail'}
        style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: COLOR_ACTIVE, display: 'flex', alignItems: 'center',
          padding: 0,
        }}
      >
        <GlyphCollapse color={COLOR_ACTIVE} collapsed={collapsed} />
      </button>

      <div data-testid="hxi-left-rail-agents-section">
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            color: COLOR_INACTIVE, marginBottom: 4,
          }}
        >
          <GlyphAgents color={COLOR_INACTIVE} />
          {!collapsed && <span>Agents online</span>}
        </div>
        {visibleAgents.map((a) => (
          <button
            key={a.agent_id}
            data-testid={`hxi-left-rail-agent-${a.agent_id}`}
            onClick={() => onSelectAgent?.(a.agent_id)}
            title={collapsed ? a.callsign : undefined}
            style={{
              background: 'none', border: 'none', color: '#ccccd8',
              cursor: 'pointer', padding: 2, textAlign: 'left',
              width: '100%', display: 'flex', alignItems: 'center', gap: 4,
            }}
          >
            <span
              style={{
                width: 6, height: 6, borderRadius: 3,
                background: COLOR_ACTIVE, display: 'inline-block',
              }}
            />
            {!collapsed && <span>{a.callsign}</span>}
          </button>
        ))}
      </div>

      <div data-testid="hxi-left-rail-recent-section">
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            color: COLOR_INACTIVE, marginBottom: 4,
          }}
        >
          <GlyphThreads color={COLOR_INACTIVE} />
          {!collapsed && <span>Recent</span>}
        </div>
        {visibleThreads.map((t) => (
          <button
            key={t.thread_id}
            data-testid={`hxi-left-rail-thread-${t.thread_id}`}
            onClick={() => onSelectThread?.(t.thread_id)}
            title={collapsed ? t.title : undefined}
            style={{
              background: 'none', border: 'none', color: '#ccccd8',
              cursor: 'pointer', padding: 2, textAlign: 'left',
              width: '100%',
              display: 'block',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {!collapsed ? t.title : '·'}
          </button>
        ))}
      </div>
    </div>
  );
}
