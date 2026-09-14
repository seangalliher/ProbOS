/* Bridge System Panel — service status, shutdown, thread management (AD-436) */

import { useState, useEffect, useCallback } from 'react';
import { Lock, Unlock, StatusInProgress } from '../icons/Glyphs';
import { useServiceStatus } from '../../hooks/useServiceStatus';
import type { ServiceStatusResult } from '../../hooks/useServiceStatus';

interface ThreadSummary {
  id: string;
  title: string;
  author_callsign: string;
  locked: boolean;
  reply_count: number;
  channel_name: string;
}

/* ── Service Status List ── */
function ServiceStatusList() {
  const status = useServiceStatus();
  const { services } = status;

  const statusDot = (s: string) => {
    const color = s === 'online' ? '#50d070' : s === 'degraded' ? '#f0b060' : '#f04040';
    return (
      <span style={{
        display: 'inline-block', width: 6, height: 6,
        borderRadius: '50%', background: color, marginRight: 6,
      }} />
    );
  };

  return (
    <section aria-label="System services">
      <ServiceReadiness status={status} />
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 8px' }}>
      {services.map(s => (
        <div key={s.name} style={{
          fontSize: 9, color: '#aaa', padding: '2px 0',
          display: 'flex', alignItems: 'center',
        }}>
          {statusDot(s.status)}
          {s.name}: {s.status === 'online' ? 'initialized' : s.status === 'offline' ? 'not initialized' : 'degraded'}
        </div>
      ))}
    </div>
    </section>
  );
}

export function ServiceReadiness({ status }: { status: ServiceStatusResult }): React.JSX.Element {
  const { resource } = status;
  const scopeCounts = status.integrations.length > 0 && status.integrations.every(entry => entry.state !== 'unknown')
    ? {
      initialization: status.integrations.filter(entry => entry.scope === 'initialization').length,
      connection: status.integrations.filter(entry => entry.scope === 'connection').length,
    } : null;
  return (
    <div style={{ fontSize: 11, color: '#aaa', overflowWrap: 'anywhere' }}>
      <div role="status" aria-live="polite">
        {status.summary} {resource.stale && 'Stale snapshot. '}{resource.refreshing && 'Refreshing. '}
        {status.paused && 'Automatic refresh paused.'}
      </div>
      <button type="button" aria-label="Refresh service status" title="Refresh service status"
        disabled={resource.status === 'loading' || resource.refreshing} onClick={status.refresh}
        style={{ background: 'none', color: '#aaa', border: '1px solid #666680', borderRadius: 4, width: 28, height: 28, cursor: 'pointer' }}>
        <StatusInProgress size={14} />
      </button>
      {resource.data && <div>{resource.stale ? 'Last known: ' : ''}{status.population}</div>}
      {resource.lastSuccess === 'empty' && resource.data && <div>No components reported.</div>}
      {scopeCounts
        ? <div>{resource.stale ? 'Last known integration observations' : 'Integration observations'}: {scopeCounts.initialization} initialization checks, {scopeCounts.connection} current connection check{scopeCounts.connection === 1 ? '' : 's'}.</div>
        : <div>Integration observations unavailable.</div>}
      <ul style={{ listStyle: 'none', padding: 0, margin: '6px 0' }}>
        {status.integrations.map(entry => (
          <li key={entry.id} aria-label={`${entry.label} ${entry.scope}`}>
            {entry.label} ({entry.scope}): {entry.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── Shutdown Control ── */
function ShutdownControl() {
  const [reason, setReason] = useState('');
  const [confirming, setConfirming] = useState(false);

  const handleShutdown = async () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    try {
      await fetch('/api/system/shutdown', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
    } catch { /* swallow */ }
    setConfirming(false);
  };

  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
      <input
        type="text"
        placeholder="Shutdown reason..."
        value={reason}
        onChange={e => setReason(e.target.value)}
        style={{
          flex: 1, background: 'rgba(255,255,255,0.05)',
          border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: 4, padding: '4px 8px',
          color: '#ccc', fontSize: 10,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      />
      <button
        onClick={handleShutdown}
        onBlur={() => setTimeout(() => setConfirming(false), 200)}
        style={{
          background: confirming ? '#c02020' : 'rgba(200,40,40,0.2)',
          border: confirming ? '1px solid #f04040' : '1px solid rgba(200,40,40,0.3)',
          borderRadius: 4, padding: '4px 10px',
          color: confirming ? '#fff' : '#f08080',
          fontSize: 9, cursor: 'pointer',
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 700, letterSpacing: 1,
          textTransform: 'uppercase' as const,
        }}
      >
        {confirming ? 'CONFIRM' : 'SHUTDOWN'}
      </button>
    </div>
  );
}

/* ── Thread Management ── */
function ThreadManagement() {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchThreads = useCallback(async () => {
    try {
      const res = await fetch('/api/wardroom/activity?limit=10&sort=recent');
      const data = await res.json();
      setThreads((data.threads || []).map((t: any) => ({
        id: t.id,
        title: t.title,
        author_callsign: t.author_callsign || t.author_id,
        locked: t.locked,
        reply_count: t.reply_count,
        channel_name: t.channel_name || '',
      })));
    } catch { /* swallow */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchThreads(); }, [fetchThreads]);

  const toggleLock = async (threadId: string, currently: boolean) => {
    try {
      await fetch(`/api/wardroom/threads/${threadId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ locked: !currently }),
      });
      setThreads(prev => prev.map(t =>
        t.id === threadId ? { ...t, locked: !currently } : t
      ));
    } catch { /* swallow */ }
  };

  if (loading) return <div style={{ fontSize: 9, color: '#555' }}>Loading...</div>;
  if (threads.length === 0) return <div style={{ fontSize: 9, color: '#555', fontStyle: 'italic' }}>No threads</div>;

  return (
    <div>
      {threads.map(t => (
        <div key={t.id} style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '3px 0', borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <span style={{ fontSize: 9, color: '#888', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            <span style={{ color: '#666' }}>{t.channel_name ? `${t.channel_name}/` : ''}</span>
            {t.title}
            <span style={{ color: '#555', marginLeft: 4 }}>({t.reply_count})</span>
          </span>
          <button
            onClick={() => toggleLock(t.id, t.locked)}
            title={t.locked ? 'Unlock thread' : 'Lock thread'}
            style={{
              background: 'none', border: 'none',
              color: t.locked ? '#f0b060' : '#555',
              cursor: 'pointer', fontSize: 11, padding: '0 2px',
            }}
          >
            {t.locked ? <Lock size={11} /> : <Unlock size={11} />}
          </button>
        </div>
      ))}
    </div>
  );
}

/* ── Exported composites ── */
export function BridgeSystem() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div>
        <div style={{ fontSize: 9, color: '#666', marginBottom: 4, fontWeight: 600 }}>SERVICES</div>
        <ServiceStatusList />
      </div>
    </div>
  );
}

export function BridgeThreads() {
  return <ThreadManagement />;
}

export function BridgeShutdown() {
  return <ShutdownControl />;
}
