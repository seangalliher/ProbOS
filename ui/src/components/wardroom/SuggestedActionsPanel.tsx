import React, { useEffect, useState } from 'react';

export interface SuggestedAction {
  id: string;
  label: string;
  svgIcon: React.ReactNode;
  agent: string;
  score: number;
  metadata: { intent: string; context: string };
}

function ReviewIcon(): JSX.Element {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M2 7h10M7 2v10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ApproveIcon(): JSX.Element {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M2 7l3 3 7-7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export async function fetchSuggestedActions(): Promise<SuggestedAction[]> {
  const res = await fetch('/work/suggested-actions');
  if (!res.ok) throw new Error('Failed to fetch suggested actions');
  const data = await res.json();
  // Map emoji to SVG icons (OSS: no emoji)
  return data.map((item: any) => ({
    ...item,
    svgIcon: item.label.includes('Review') ? <ReviewIcon /> : <ApproveIcon />,
  }));
}

export const SuggestedActionsPanel: React.FC = () => {
  const [actions, setActions] = useState<SuggestedAction[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSuggestedActions()
      .then(setActions)
      .catch(e => setError(e.message));
  }, []);

  if (error) return <div>Error: {error}</div>;
  if (!actions.length) return <div>Loading suggested actions...</div>;

  return (
    <div className="suggested-actions-panel">
      <h3>Suggested Actions</h3>
      <ul>
        {actions.map(action => (
          <li key={action.id}>
            <span className="icon">{action.svgIcon}</span>
            <span className="label">{action.label}</span>
            <span className="agent">({action.agent})</span>
            <span className="score">{(action.score * 100).toFixed(0)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
};
