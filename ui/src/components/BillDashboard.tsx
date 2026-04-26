/* Bill Dashboard — Bill System HXI (AD-618d) */

import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
import type { BillDefinitionView, BillInstanceView } from '../store/types';

// ── Status colors ─────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  pending: '#8888a0',
  active: '#50b0d0',
  completed: '#50b080',
  failed: '#d05050',
  cancelled: '#a08040',
  skipped: '#888',
  blocked: '#665500',
};

// ── Bill Definition Card ──────────────────────────────────────────
function BillCard({ defn, onActivate }: {
  defn: BillDefinitionView;
  onActivate: (billId: string) => void;
}) {
  return (
    <div style={{
      background: '#1a1a2e', border: '1px solid #333', borderRadius: 6,
      padding: 12, marginBottom: 8, cursor: 'pointer',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 600, color: '#e0e0e0' }}>{defn.title}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onActivate(defn.bill_id); }}
          style={{
            background: '#304060', border: '1px solid #5090d0', borderRadius: 4,
            color: '#5090d0', padding: '4px 12px', cursor: 'pointer', fontSize: 12,
          }}
        >
          SET CONDITION
        </button>
      </div>
      <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>{defn.description}</div>
      <div style={{ color: '#666', fontSize: 11, marginTop: 6 }}>
        {defn.role_count} roles · {defn.step_count} steps
        {defn.activation?.trigger ? ` · trigger: ${defn.activation.trigger}` : ''}
      </div>
    </div>
  );
}

// ── Step Progress Bar ─────────────────────────────────────────────
function StepProgress({ instance }: { instance: BillInstanceView }) {
  const steps = Object.entries(instance.step_states);
  if (steps.length === 0) return null;
  return (
    <div style={{ display: 'flex', gap: 2, marginTop: 8 }}>
      {steps.map(([stepId, ss]) => (
        <div
          key={stepId}
          title={`${stepId}: ${ss.status}${ss.assigned_agent_callsign ? ` (${ss.assigned_agent_callsign})` : ''}`}
          style={{
            flex: 1, height: 6, borderRadius: 2,
            background: STATUS_COLORS[ss.status] ?? '#444',
          }}
        />
      ))}
    </div>
  );
}

// ── Instance Detail ───────────────────────────────────────────────
function InstanceDetail({ instance }: { instance: BillInstanceView }) {
  const roles = Object.entries(instance.role_assignments);
  const steps = Object.entries(instance.step_states);

  return (
    <div style={{ padding: 12, background: '#12122a', borderRadius: 6, marginTop: 8 }}>
      <h4 style={{ margin: 0, color: '#e0e0e0' }}>{instance.bill_title}</h4>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
        {instance.id} · {instance.status}
      </div>

      {/* Role Assignments */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>ROLE ASSIGNMENTS</div>
        {roles.map(([roleId, ra]) => (
          <div key={roleId} style={{ fontSize: 12, color: '#ccc', padding: '2px 0' }}>
            <span style={{ color: '#5090d0' }}>{roleId}</span>
            {' → '}
            <span style={{ color: '#50b080' }}>{ra.callsign || ra.agent_type}</span>
          </div>
        ))}
        {roles.length === 0 && (
          <div style={{ fontSize: 12, color: '#666' }}>No assignments</div>
        )}
      </div>

      {/* Step Timeline */}
      <div>
        <div style={{ fontSize: 12, color: '#aaa', marginBottom: 4 }}>STEP PROGRESSION</div>
        {steps.map(([stepId, ss]) => (
          <div key={stepId} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '4px 0', borderBottom: '1px solid #222',
          }}>
            <div style={{
              width: 8, height: 8, borderRadius: '50%',
              background: STATUS_COLORS[ss.status] ?? '#444',
            }} />
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 12, color: '#ccc' }}>{stepId}</span>
              {ss.assigned_agent_callsign && (
                <span style={{ fontSize: 11, color: '#888', marginLeft: 6 }}>
                  ({ss.assigned_agent_callsign})
                </span>
              )}
            </div>
            <span style={{
              fontSize: 11, color: STATUS_COLORS[ss.status] ?? '#888',
            }}>{ss.status}</span>
            {ss.error && (
              <span style={{ fontSize: 11, color: '#d05050', marginLeft: 4 }}>
                {ss.error}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Instance Card ─────────────────────────────────────────────────
function InstanceCard({ instance, selected, onSelect }: {
  instance: BillInstanceView;
  selected: boolean;
  onSelect: () => void;
}) {
  const statusColor = STATUS_COLORS[instance.status] ?? '#888';
  const steps = Object.values(instance.step_states);
  return (
    <div>
      <div
        onClick={onSelect}
        style={{
          background: selected ? '#1a1a3e' : '#1a1a2e',
          border: `1px solid ${selected ? '#5090d0' : '#333'}`,
          borderRadius: 6, padding: 10, cursor: 'pointer', marginBottom: 4,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 600, color: '#e0e0e0', fontSize: 13 }}>
            {instance.bill_title}
          </span>
          <span style={{ fontSize: 11, color: statusColor, fontWeight: 600 }}>
            {instance.status.toUpperCase()}
          </span>
        </div>
        <StepProgress instance={instance} />
        <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>
          {Object.keys(instance.role_assignments).length} assigned ·{' '}
          {steps.filter(s => s.status === 'completed').length}/{steps.length} steps
        </div>
      </div>
      {selected && <InstanceDetail instance={instance} />}
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────
export default function BillDashboard() {
  const definitions = useStore(s => s.billDefinitions);
  const instances = useStore(s => s.billInstances);
  const selectedId = useStore(s => s.billSelectedInstanceId);
  const fetchDefs = useStore(s => s.fetchBillDefinitions);
  const fetchInstances = useStore(s => s.fetchBillInstances);
  const activate = useStore(s => s.activateBill);
  const selectInstance = useStore(s => s.selectBillInstance);

  const [filter, setFilter] = useState<'all' | 'active' | 'completed'>('all');

  useEffect(() => {
    fetchDefs();
    fetchInstances();
  }, [fetchDefs, fetchInstances]);

  const filteredInstances = filter === 'all'
    ? instances
    : instances.filter(i => filter === 'active'
        ? ['pending', 'active'].includes(i.status)
        : ['completed', 'failed', 'cancelled'].includes(i.status)
      );

  const handleActivate = async (billId: string) => {
    const inst = await activate(billId);
    if (inst) selectInstance(inst.id);
  };

  return (
    <div style={{ display: 'flex', height: '100%', gap: 16, padding: 16, color: '#e0e0e0' }}>
      {/* Left: Bill Catalog */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <h3 style={{ margin: '0 0 12px', color: '#aaa', fontSize: 14 }}>
          BILL CATALOG ({definitions.length})
        </h3>
        {definitions.map(d => (
          <BillCard key={d.bill_id} defn={d} onActivate={handleActivate} />
        ))}
        {definitions.length === 0 && (
          <div style={{ color: '#666', fontSize: 13 }}>No bills loaded</div>
        )}
      </div>

      {/* Right: Active Instances */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0, color: '#aaa', fontSize: 14 }}>
            INSTANCES ({filteredInstances.length})
          </h3>
          <div style={{ display: 'flex', gap: 4 }}>
            {(['all', 'active', 'completed'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  background: filter === f ? '#304060' : 'transparent',
                  border: `1px solid ${filter === f ? '#5090d0' : '#444'}`,
                  color: filter === f ? '#5090d0' : '#888',
                  borderRadius: 3, padding: '2px 8px', cursor: 'pointer', fontSize: 11,
                }}
              >
                {f.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        {filteredInstances.map(i => (
          <InstanceCard
            key={i.id}
            instance={i}
            selected={selectedId === i.id}
            onSelect={() => selectInstance(
              selectedId === i.id ? null : i.id
            )}
          />
        ))}
        {filteredInstances.length === 0 && (
          <div style={{ color: '#666', fontSize: 13 }}>No instances</div>
        )}
      </div>
    </div>
  );
}
