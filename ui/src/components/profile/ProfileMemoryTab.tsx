/* AD-611: Memory tab for agent profile panel. */

import React, { useState, useEffect, useCallback } from 'react';
import MemoryGraph3D from './MemoryGraph3D';
import type { MemoryGraphResponse } from './memoryGraphTypes';

interface ProfileMemoryTabProps {
  agentId: string;
}

export function ProfileMemoryTab({ agentId }: ProfileMemoryTabProps) {
  const [data, setData] = useState<MemoryGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [shipWide, setShipWide] = useState(false);

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(
        `/api/agent/${agentId}/memory-graph?ship_wide=${shipWide}`,
      );
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const json: MemoryGraphResponse = await resp.json();
      setData(json);
    } catch (err: any) {
      setError(err.message || 'Failed to load memory graph');
    } finally {
      setLoading(false);
    }
  }, [agentId, shipWide]);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Controls bar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '8px 12px', borderBottom: '1px solid #333', flexShrink: 0,
      }}>
        <div style={{ fontSize: 12, color: '#999' }}>
          {data && !loading && (
            <>
              Showing {data.meta.nodes_shown} of {data.meta.total_episodes} episodes
              {' | '}{data.edges.length} edges
            </>
          )}
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#ccc', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={shipWide}
            onChange={(e) => setShipWide(e.target.checked)}
            style={{ accentColor: '#f0b060' }}
          />
          Ship-wide
        </label>
      </div>

      {/* Graph area */}
      <div style={{ flex: 1, position: 'relative' }}>
        {loading && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            color: '#888', fontSize: 14,
          }}>
            Loading memory graph...
          </div>
        )}
        {error && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 12,
            color: '#ff6b6b', fontSize: 14,
          }}>
            <div>{error}</div>
            <button
              onClick={fetchGraph}
              style={{
                background: '#333', border: '1px solid #555', color: '#ccc',
                padding: '6px 16px', borderRadius: 4, cursor: 'pointer',
              }}
            >
              Retry
            </button>
          </div>
        )}
        {data && !loading && !error && (
          <MemoryGraph3D data={data} />
        )}
      </div>
    </div>
  );
}
