import React, { useEffect, useState } from 'react';

interface BudgetSnapshot {
  session_id: string;
  calls_this_session: Record<string, number>;
  calls_today: Record<string, number>;
  total_session: number;
  total_today: number;
  session_ceiling_estimate: number;
  next_allowed_in_seconds: number;
  consumer_wired: boolean;
}

const POLL_INTERVAL_MS = 5000;

export function VisionBudgetBadge() {
  const [snapshot, setSnapshot] = useState<BudgetSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const resp = await fetch('/api/perception/budget', { credentials: 'same-origin' });
        if (!resp.ok) return;
        const data: BudgetSnapshot = await resp.json();
        if (!cancelled) setSnapshot(data);
      } catch {
        // tier-2 log-and-degrade: silent. Badge just stays hidden.
      }
    }
    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // HXI Principle #5: progressive disclosure. Hidden when no calls yet.
  if (!snapshot || snapshot.total_session === 0) {
    return null;
  }

  const {
    total_session,
    session_ceiling_estimate,
    calls_this_session,
    calls_today,
    next_allowed_in_seconds,
  } = snapshot;
  const ceiling = session_ceiling_estimate > 0 ? session_ceiling_estimate : 120;
  const pct = total_session / ceiling;
  // Amber 0-80%; dim-red 80-100%; bright-red above ceiling.
  const color = pct >= 1.0 ? '#e04030' : pct >= 0.8 ? '#c84030' : '#f0b060';

  const todayTotal =
    (calls_today.vision || 0) + (calls_today.vision_fast || 0);
  const titleParts = [
    `vision: ${calls_this_session.vision || 0} calls`,
    `vision_fast: ${calls_this_session.vision_fast || 0} calls`,
    `today: ${todayTotal}`,
    next_allowed_in_seconds > 0
      ? `next in ${next_allowed_in_seconds.toFixed(1)}s`
      : 'ready',
  ];

  return (
    <span
      style={{ display: 'flex', gap: 4, alignItems: 'center' }}
      title={titleParts.join(' \u00b7 ')}
      data-testid="vision-budget-badge"
    >
      <span style={{ color: '#666680' }}>Vis</span>
      <span style={{ color }}>
        {total_session}/{ceiling}
      </span>
    </span>
  );
}
