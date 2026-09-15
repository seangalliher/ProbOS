/* AD-611: Memory tab for agent profile panel. */

import { useState } from 'react';
import MemoryGraph3D from './MemoryGraph3D';
import { memoryGraphSampleTime, validMemoryGraph, type MemoryGraphResponse } from './memoryGraphTypes';
import { useProfileResource } from '../../hooks/useProfileResource';

interface ProfileMemoryTabProps {
  agentId: string;
  subjectId?: string;
}

export function ProfileMemoryTab({ agentId, subjectId }: ProfileMemoryTabProps): React.JSX.Element {
  const [shipWide, setShipWide] = useState(false);
  const resource = useProfileResource({
    identity: JSON.stringify([agentId, subjectId, shipWide]),
    url: `/api/agent/${encodeURIComponent(agentId)}/memory-graph?ship_wide=${shipWide}`,
    eligible: Boolean(agentId),
    independentReads: true,
    validate: (payload): payload is MemoryGraphResponse => validMemoryGraph(payload, agentId, shipWide, subjectId),
    isEmpty: payload => payload.nodes.length === 0,
    sampleTime: memoryGraphSampleTime,
  });
  const data = resource.state.data;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Controls bar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '8px 12px', borderBottom: '1px solid #333', flexShrink: 0,
      }}>
        <div style={{ fontSize: 11, color: '#a0a0b8', minWidth: 0, overflowWrap: 'anywhere' }}>
          {data && (
            <>
              <div>Displayed bounded {shipWide ? 'registered-crew' : 'agent'} sample: {data.meta.nodes_shown} episodes; {data.edges.length} edges</div>
              <div>Selected-agent stored membership: {data.meta.total_episodes ?? 'Unknown'} episodes</div>
              <div>{data.meta.total_measurement
                ? `${data.meta.total_measurement.status}; sampled ${data.meta.total_measurement.sample_completed_at ?? 'unknown'}`
                : 'Stored total sample time/scope unverified.'}</div>
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

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 12px', color: '#a0a0b8', fontSize: 10 }}>
        <span role="status" style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{resource.message}</span>
        <button onClick={resource.refresh} aria-label="Refresh memory graph" title="Refresh memory graph"
          style={{ background: 'none', border: 'none', color: '#f0b060', width: 24, height: 24, flexShrink: 0, cursor: 'pointer' }}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M13 6a5 5 0 1 0 0 4M13 2v4H9" />
          </svg>
        </button>
      </div>

      {/* Graph area */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {data?.nodes.length === 0 && <div style={{ padding: 12, color: '#a0a0b8', fontSize: 12 }}>No episodes in this bounded selection.</div>}
        {data && data.nodes.length > 0 && (
          <MemoryGraph3D data={data} />
        )}
      </div>
    </div>
  );
}
