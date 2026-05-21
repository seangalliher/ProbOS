/*
 * AD-796 — YeoEmptyGreeting
 *
 * Time-of-day greeting + one-line status surfaced on the empty-thread
 * Compact Yeo surface. Renders ONLY when the active conversation has
 * zero messages; the parent (CompactApp) is responsible for that gate.
 *
 * Data sources (all best-effort, log-and-degrade on failure):
 *   • Time of day → derived from `Date.now()` locally.
 *   • Captain name → defaults to "Captain"; can be overridden by the
 *     parent via the `captainName` prop. Wiring this to the Captain
 *     Card (AD-757) needs a small REST endpoint exposing `card.name` —
 *     filed inline as a follow-up below.
 *   • Crew count + ship health → GET /api/health.
 *   • Unread WardRoom threads → store.wardRoomUnread (already
 *     auto-refreshed via WS subscription per AD-654a).
 *
 * Failure modes: every fetch is wrapped; on any error we render only
 * what we have. Never blocks the chat surface.
 */
import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store/useStore';

const AMBER = '#f0b060';
const DIM = '#aaaab8';

/**
 * Time-of-day window. Mornings cut off at 12:00, afternoons at 18:00.
 * Exposed so unit tests can target the boundaries deterministically.
 */
export function greetingForHour(hour: number): string {
  if (hour < 0 || hour > 23) return 'Hello';
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

interface HealthSnapshot {
  crew_agents?: number;
  agents?: number;
  health?: number;
}

interface Props {
  captainName?: string;
  /** Override for unit testing — defaults to `new Date()`. */
  now?: Date;
}

export function YeoEmptyGreeting({ captainName = 'Captain', now }: Props) {
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const wardRoomUnread = useStore((s) => s.wardRoomUnread);

  const greeting = useMemo(() => {
    const d = now ?? new Date();
    return greetingForHour(d.getHours());
  }, [now]);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data) setHealth(data);
      })
      .catch(() => {
        /* tier-2: silent log-and-degrade — render greeting alone */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const totalUnread = Object.values(wardRoomUnread).reduce(
    (sum, n) => sum + (typeof n === 'number' ? n : 0),
    0,
  );

  const statusFragments: string[] = [];
  if (totalUnread > 0) {
    statusFragments.push(
      `${totalUnread} unread WardRoom thread${totalUnread === 1 ? '' : 's'}`,
    );
  }
  if (typeof health?.crew_agents === 'number' && health.crew_agents > 0) {
    statusFragments.push(`${health.crew_agents} crew online`);
  }
  const statusLine =
    statusFragments.length > 0 ? statusFragments.join(' • ') : 'All quiet.';

  return (
    <div
      data-testid="yeo-empty-greeting"
      style={{
        padding: '32px 24px 12px',
        textAlign: 'center',
        userSelect: 'none',
      }}
    >
      <div
        data-testid="yeo-empty-greeting-title"
        style={{
          fontSize: 20,
          fontWeight: 300,
          letterSpacing: 0.5,
          color: AMBER,
          marginBottom: 6,
        }}
      >
        {greeting}, {captainName}.
      </div>
      <div
        data-testid="yeo-empty-greeting-status"
        style={{ fontSize: 11, color: DIM, letterSpacing: 0.5 }}
      >
        {statusLine}
      </div>
    </div>
  );
}
