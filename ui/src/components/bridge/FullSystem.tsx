/* Full System — full-width system management panel for main viewer (AD-436) */

import { useState, useEffect, useCallback } from 'react';
import { Lock, Unlock, Pin } from '../icons/Glyphs';

interface ServiceStatus {
  name: string;
  status: 'online' | 'offline' | 'degraded';
}

interface ThreadSummary {
  id: string;
  title: string;
  author_callsign: string;
  locked: boolean;
  pinned: boolean;
  reply_count: number;
  channel_name: string;
  thread_mode: string;
  created_at: number;
}

const STATUS_COLORS: Record<string, string> = {
  online: '#50d070',
  degraded: '#f0b060',
  offline: '#f04040',
};

function ServiceCard({ service }: { service: ServiceStatus }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: `1px solid ${service.status === 'online' ? 'rgba(80,208,112,0.2)' : 'rgba(240,64,64,0.3)'}`,
      borderRadius: 6, padding: '12px 16px',
      display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <span style={{
        display: 'inline-block', width: 8, height: 8,
        borderRadius: '50%',
        background: STATUS_COLORS[service.status] || '#555',
        boxShadow: service.status === 'online' ? '0 0 6px rgba(80,208,112,0.4)' : undefined,
      }} />
      <span style={{ fontSize: 12, color: '#ccc', fontWeight: 500 }}>{service.name}</span>
      <span style={{
        marginLeft: 'auto', fontSize: 9, color: STATUS_COLORS[service.status] || '#555',
        fontWeight: 600, letterSpacing: 1, textTransform: 'uppercase' as const,
      }}>
        {service.status}
      </span>
    </div>
  );
}

function ServicesGrid() {
  const [services, setServices] = useState<ServiceStatus[]>([]);

  const fetchServices = useCallback(async () => {
    try {
      const res = await fetch('/api/system/services');
      const data = await res.json();
      setServices(data.services || []);
    } catch { /* swallow */ }
  }, []);

  useEffect(() => {
    fetchServices();
    const interval = setInterval(fetchServices, 10000);
    return () => clearInterval(interval);
  }, [fetchServices]);

  const online = services.filter(s => s.status === 'online').length;

  return (
    <div>
      <div style={{
        fontSize: 10, color: '#666', marginBottom: 8, fontWeight: 600, letterSpacing: 1,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        SERVICES
        <span style={{ color: '#888', fontWeight: 400 }}>
          {online}/{services.length} online
        </span>
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: 6,
      }}>
        {services.map(s => <ServiceCard key={s.name} service={s} />)}
      </div>
    </div>
  );
}

function ThreadTable() {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchThreads = useCallback(async () => {
    try {
      const res = await fetch('/api/wardroom/activity?limit=25&sort=recent');
      const data = await res.json();
      setThreads((data.threads || []).map((t: any) => ({
        id: t.id,
        title: t.title,
        author_callsign: t.author_callsign || t.author_id,
        locked: t.locked,
        pinned: t.pinned || false,
        reply_count: t.reply_count || 0,
        channel_name: t.channel_name || '',
        thread_mode: t.thread_mode || 'discuss',
        created_at: t.created_at || 0,
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

  const modeColor = (mode: string) => {
    switch (mode) {
      case 'inform': return '#5090d0';
      case 'discuss': return '#888';
      case 'action': return '#f0b060';
      case 'announce': return '#50d070';
      default: return '#666';
    }
  };

  const formatAge = (ts: number) => {
    if (!ts) return '';
    const secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 60) return `${secs}s`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h`;
    return `${Math.floor(secs / 86400)}d`;
  };

  if (loading) return <div style={{ fontSize: 10, color: '#555' }}>Loading threads...</div>;

  return (
    <div>
      <div style={{
        fontSize: 10, color: '#666', marginBottom: 8, fontWeight: 600, letterSpacing: 1,
      }}>
        WARD ROOM THREADS ({threads.length})
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '32px 60px 1fr 80px 50px 40px 32px',
        gap: '0',
        fontSize: 10,
      }}>
        {/* Header */}
        {['', 'MODE', 'TITLE', 'AUTHOR', 'AGE', 'POSTS', ''].map((h, i) => (
          <div key={i} style={{
            padding: '4px 6px', color: '#555', fontWeight: 600,
            borderBottom: '1px solid rgba(255,255,255,0.08)',
            letterSpacing: 0.5,
          }}>{h}</div>
        ))}
        {/* Rows */}
        {threads.map(t => (
          <>
            <div key={`${t.id}-lock`} style={{
              padding: '6px', display: 'flex', alignItems: 'center',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>
              {t.locked && <span style={{ color: '#f0b060', fontSize: 11 }}><Lock size={11} /></span>}
              {t.pinned && <span style={{ color: '#5090d0', fontSize: 11 }}><Pin size={11} /></span>}
            </div>
            <div key={`${t.id}-mode`} style={{
              padding: '6px', display: 'flex', alignItems: 'center',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>
              <span style={{
                fontSize: 8, color: modeColor(t.thread_mode),
                fontWeight: 600, letterSpacing: 0.5,
                textTransform: 'uppercase' as const,
              }}>{t.thread_mode}</span>
            </div>
            <div key={`${t.id}-title`} style={{
              padding: '6px', color: '#bbb',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>{t.title}</div>
            <div key={`${t.id}-author`} style={{
              padding: '6px', color: '#888',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>{t.author_callsign}</div>
            <div key={`${t.id}-age`} style={{
              padding: '6px', color: '#666',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>{formatAge(t.created_at)}</div>
            <div key={`${t.id}-count`} style={{
              padding: '6px', color: '#888', textAlign: 'center',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>{t.reply_count}</div>
            <div key={`${t.id}-actions`} style={{
              padding: '6px', display: 'flex', alignItems: 'center',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>
              <button
                onClick={() => toggleLock(t.id, t.locked)}
                title={t.locked ? 'Unlock thread' : 'Lock thread'}
                style={{
                  background: 'none', border: 'none',
                  color: t.locked ? '#f0b060' : '#444',
                  cursor: 'pointer', fontSize: 10, padding: 0,
                }}
              >
                {t.locked ? <Unlock size={10} /> : <Lock size={10} />}
              </button>
            </div>
          </>
        ))}
      </div>
    </div>
  );
}

function ShutdownPanel() {
  const [reason, setReason] = useState('');
  const [confirming, setConfirming] = useState(false);

  const handleShutdown = async () => {
    if (!confirming) { setConfirming(true); return; }
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
    <div>
      <div style={{
        fontSize: 10, color: '#666', marginBottom: 8, fontWeight: 600, letterSpacing: 1,
      }}>
        SHUTDOWN
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', maxWidth: 400 }}>
        <input
          type="text" placeholder="Shutdown reason..."
          value={reason} onChange={e => setReason(e.target.value)}
          style={{
            flex: 1, background: 'rgba(255,255,255,0.05)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 4, padding: '6px 10px',
            color: '#ccc', fontSize: 11,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        />
        <button
          onClick={handleShutdown}
          onBlur={() => setTimeout(() => setConfirming(false), 200)}
          style={{
            background: confirming ? '#c02020' : 'rgba(200,40,40,0.15)',
            border: confirming ? '1px solid #f04040' : '1px solid rgba(200,40,40,0.25)',
            borderRadius: 4, padding: '6px 14px',
            color: confirming ? '#fff' : '#f08080',
            fontSize: 10, cursor: 'pointer',
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 700, letterSpacing: 1,
            textTransform: 'uppercase' as const,
          }}
        >
          {confirming ? 'CONFIRM SHUTDOWN' : 'SHUTDOWN'}
        </button>
      </div>
    </div>
  );
}

export function FullSystem() {
  return (
    <div style={{
      position: 'absolute', inset: 0,
      background: 'rgba(6, 6, 14, 0.95)',
      overflow: 'auto',
      padding: '24px 32px',
      fontFamily: "'JetBrains Mono', monospace",
    }}>
      <div style={{
        fontSize: 13, fontWeight: 700, letterSpacing: 2,
        textTransform: 'uppercase' as const, color: '#70a0d0',
        marginBottom: 24,
      }}>
        System Management
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        <ServicesGrid />
        <ThreadTable />
        <ShutdownPanel />
      </div>
    </div>
  );
}
