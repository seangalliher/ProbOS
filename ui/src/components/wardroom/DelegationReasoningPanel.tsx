import React, { useEffect, useState } from 'react';

export interface DelegationTrace {
  from: string;
  to: string;
  reason: string;
  status: string;
}

export async function fetchDelegationTrace(dagId: string): Promise<DelegationTrace[]> {
  const res = await fetch(`/dag/${dagId}/delegation-trace`);
  if (!res.ok) throw new Error('Failed to fetch delegation trace');
  return res.json();
}

export const DelegationReasoningPanel: React.FC<{ dagId: string }> = ({ dagId }) => {
  const [trace, setTrace] = useState<DelegationTrace[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDelegationTrace(dagId)
      .then(setTrace)
      .catch(e => setError(e.message));
  }, [dagId]);

  if (error) return <div>Error: {error}</div>;
  if (!trace.length) return <div>Loading delegation trace...</div>;

  return (
    <div className="delegation-reasoning-panel">
      <h3>Delegation Reasoning</h3>
      <ul>
        {trace.map((t, i) => (
          <li key={i}>
            {t.from} → {t.to}<br />
            <b>Reason:</b> {t.reason}<br />
            <b>Status:</b> {t.status}
          </li>
        ))}
      </ul>
    </div>
  );
};
