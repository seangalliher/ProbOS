import React, { useEffect, useState } from 'react';

export interface BriefingItem {
  summary: string;
  detail: string;
}

export interface DailyBriefing {
  inboxSummary: string;
  calendarSummary: string;
  suggestedActions: string[];
}

export async function fetchDailyBriefing(): Promise<DailyBriefing> {
  const res = await fetch('/work/daily-briefing');
  if (!res.ok) throw new Error('Failed to fetch daily briefing');
  return res.json();
}

export const DailyBriefingPanel: React.FC = () => {
  const [briefing, setBriefing] = useState<DailyBriefing | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDailyBriefing()
      .then(setBriefing)
      .catch(e => setError(e.message));
  }, []);

  if (error) return <div>Error: {error}</div>;
  if (!briefing) return <div>Loading daily briefing...</div>;

  return (
    <div className="daily-briefing-panel">
      <h3>Daily Briefing</h3>
      <div>{briefing.inboxSummary}</div>
      <div>{briefing.calendarSummary}</div>
      <ul>
        {briefing.suggestedActions.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ul>
    </div>
  );
};
