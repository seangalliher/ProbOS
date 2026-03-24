import { useState } from 'react';

export function EndorsementButtons({ targetId, targetType, netScore }: {
  targetId: string;
  targetType: 'thread' | 'post';
  netScore: number;
}) {
  const [score, setScore] = useState(netScore);

  const endorse = async (direction: 'up' | 'down') => {
    const endpoint = targetType === 'thread'
      ? `/api/wardroom/threads/${targetId}/endorse`
      : `/api/wardroom/posts/${targetId}/endorse`;
    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voter_id: 'captain', direction }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setScore(data.net_score);
      }
    } catch { /* swallow */ }
  };

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span onClick={() => endorse('up')} style={{ cursor: 'pointer', color: '#50c878' }}>▲</span>
      <span style={{ fontSize: 12, minWidth: 16, textAlign: 'center' as const }}>{score}</span>
      <span onClick={() => endorse('down')} style={{ cursor: 'pointer', color: '#c84858' }}>▼</span>
    </span>
  );
}
