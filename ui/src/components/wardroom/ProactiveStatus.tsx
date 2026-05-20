import { useEffect, useMemo, useState } from 'react';

type ProactiveStatusPayload = {
  next_inbox_scan: string;
  next_calendar_scan: string;
  work_hours_active: boolean;
  quiet_hours_active: boolean;
  last_scan_count: Record<string, number>;
};

const SOFT_DISABLE_KEY = 'probos.proactive.softDisable';

function formatIso(value: string): string {
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return 'unknown';
  return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function ProactiveStatus() {
  const [status, setStatus] = useState<ProactiveStatusPayload | null>(null);
  const [error, setError] = useState<string>('');
  const [softDisabled, setSoftDisabled] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SOFT_DISABLE_KEY) === '1';
    } catch {
      return false;
    }
  });

  const totalFindings = useMemo(() => {
    if (!status?.last_scan_count) return 0;
    return Object.values(status.last_scan_count).reduce((acc, value) => acc + value, 0);
  }, [status]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const res = await fetch('/api/proactive/status');
        if (!res.ok) throw new Error(`status ${res.status}`);
        const payload = (await res.json()) as ProactiveStatusPayload;
        if (!cancelled) {
          setStatus(payload);
          setError('');
        }
      } catch {
        if (!cancelled) {
          setError('Unavailable');
        }
      }
    };

    void load();
    const timer = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const toggleSoftDisable = () => {
    const next = !softDisabled;
    setSoftDisabled(next);
    try {
      localStorage.setItem(SOFT_DISABLE_KEY, next ? '1' : '0');
    } catch {
      // localStorage write failures are non-fatal for this client-only toggle.
    }
  };

  return (
    <div style={{
      margin: '8px 16px 10px 16px',
      border: '1px solid rgba(240,176,96,0.14)',
      borderRadius: 8,
      padding: '8px 10px',
      background: 'rgba(18, 20, 30, 0.45)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontSize: 10, letterSpacing: 1.1, color: '#f0b060', fontWeight: 700 }}>PROACTIVE STATUS</span>
        <label style={{ fontSize: 10, color: '#9a9ab2', display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={softDisabled} onChange={toggleSoftDisable} />
          Disable proactive
        </label>
      </div>

      {error ? (
        <div style={{ fontSize: 11, color: '#c28b8b' }}>{error}</div>
      ) : (
        <>
          <div style={{ fontSize: 11, color: '#b0a9a0', marginBottom: 4 }}>
            Next inbox scan: <strong>{formatIso(status?.next_inbox_scan || '')}</strong>
          </div>
          <div style={{ fontSize: 11, color: '#b0a9a0', marginBottom: 4 }}>
            Next calendar scan: <strong>{formatIso(status?.next_calendar_scan || '')}</strong>
          </div>
          <div style={{ display: 'flex', gap: 12, fontSize: 10, color: '#8e8ea8', marginBottom: 4 }}>
            <span>Work-hours: {status?.work_hours_active ? 'active' : 'inactive'}</span>
            <span>Quiet-hours: {status?.quiet_hours_active ? 'active' : 'inactive'}</span>
          </div>
          <div style={{ fontSize: 10, color: '#8e8ea8' }}>
            Last scan findings: {totalFindings}
          </div>
        </>
      )}
    </div>
  );
}
