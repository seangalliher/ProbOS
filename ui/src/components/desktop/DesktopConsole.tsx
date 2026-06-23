/* Desktop-integration status console — read-only HXI readout (AD-841 v1)
 *
 * A thin, READ-ONLY surface for the AD-751 Desktop UX Surface. It reports the
 * operator's *configured* desktop settings plus a derived "wired-this-boot"
 * presence signal (GET /api/desktop/status). It is NOT live OS truth, does NOT
 * enumerate apps/windows, and exposes NO launch/start/stop control (that is the
 * deferred AD-841b half).
 *
 * Standalone: deliberately NOT mounted in App.tsx. Deps-injectable: an optional
 * fetchImpl prop (defaults to the global fetch) keeps the panel testable without
 * global stubbing. HXI Design Principle #3: inline stroke-SVG glyphs only (no
 * emoji), amber active / dim inactive. Self-gating: a hard fetch failure / no
 * data renders nothing; an `enabled:false` payload renders a calm "Off" readout
 * (off IS informative — it does not self-gate).
 */

import { useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';

// ── Status shape (mirrors the GET /api/desktop/status serializer) ──
export interface DesktopStatusView {
  enabled: boolean;
  active: boolean;
  tray: { active: boolean; autostart: boolean };
  hotkey: { active: boolean; binding: string };
  notifications: { active: boolean; timeout_sec: number };
  quiet_hours: { start: string; end: string };
  autostart_enabled: boolean;
  lock: { name: string; present: boolean };
}

type FetchImpl = typeof fetch;

const ACTIVE_AMBER = '#f0b060';
const DIM = '#666680';

// ── Stroke-SVG status dot (no emoji; HXI #3) ───────────────────────
function StatusDot({ active }: { active: boolean }) {
  const color = active ? ACTIVE_AMBER : DIM;
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="6" />
    </svg>
  );
}

// ── Single read-only status row ────────────────────────────────────
function Row({
  testid,
  label,
  value,
  active,
}: {
  testid: string;
  label: string;
  value: string;
  active?: boolean;
}) {
  return (
    <div
      data-testid={testid}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '5px 2px',
        fontSize: 11,
        borderBottom: '1px solid rgba(255,255,255,0.05)',
      }}
    >
      {active !== undefined ? <StatusDot active={active} /> : <span style={{ width: 12 }} />}
      <span style={{ color: '#9098b0', minWidth: 96 }}>{label}</span>
      <span style={{ marginLeft: 'auto', color: '#c8d0e0', fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function panelShell(children: ReactNode) {
  return (
    <div data-testid="desktop-console" style={{ padding: '8px 0' }}>
      <div
        style={{
          fontSize: 10,
          textTransform: 'uppercase',
          letterSpacing: 1,
          color: ACTIVE_AMBER,
          fontWeight: 700,
          marginBottom: 6,
          padding: '0 2px',
        }}
      >
        Desktop Integration
      </div>
      {children}
    </div>
  );
}

// ── Console ────────────────────────────────────────────────────────
export default function DesktopConsole({ fetchImpl }: { fetchImpl?: FetchImpl } = {}) {
  const doFetch: FetchImpl = fetchImpl ?? ((...args) => fetch(...args));
  const [status, setStatus] = useState<DesktopStatusView | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const resp = await doFetch('/api/desktop/status');
      if (!resp.ok) return;
      const data = await resp.json();
      if (data && typeof data === 'object') {
        setStatus(data as DesktopStatusView);
      }
    } catch {
      // Tier-1 swallow: a hard fetch failure self-gates (renders nothing).
    } finally {
      setLoaded(true);
    }
  }, [doFetch]);

  useEffect(() => {
    void load();
  }, [load]);

  // Self-gate: still loading, or a hard failure / no data → render nothing.
  if (!loaded || status === null) {
    return null;
  }

  // enabled:false → calm "Off" readout (off IS informative; do NOT self-gate).
  if (!status.enabled) {
    return panelShell(
      <div data-testid="desktop-off" style={{ fontSize: 11, color: DIM, padding: '5px 2px' }}>
        Desktop integration: Off
      </div>
    );
  }

  const lockValue = status.lock.name
    ? `${status.lock.name} (${status.lock.present ? 'present' : 'absent'})`
    : '-';

  return panelShell(
    <>
      <Row testid="desktop-row-enabled" label="Enabled" value="Yes" active={status.enabled} />
      <Row
        testid="desktop-row-active"
        label="Active"
        value={status.active ? 'Wired' : 'Not wired'}
        active={status.active}
      />
      <Row
        testid="desktop-row-tray"
        label="Tray"
        value={status.tray.autostart ? 'Autostart on' : 'Autostart off'}
        active={status.tray.active}
      />
      <Row
        testid="desktop-row-hotkey"
        label="Hotkey"
        value={status.hotkey.binding || '-'}
        active={status.hotkey.active}
      />
      <Row
        testid="desktop-row-notifications"
        label="Notifications"
        value={`${status.notifications.timeout_sec}s`}
        active={status.notifications.active}
      />
      <Row
        testid="desktop-row-quiet-hours"
        label="Quiet Hours"
        value={`${status.quiet_hours.start} to ${status.quiet_hours.end}`}
      />
      <Row
        testid="desktop-row-autostart"
        label="Autostart"
        value={status.autostart_enabled ? 'On' : 'Off'}
        active={status.autostart_enabled}
      />
      <Row
        testid="desktop-row-lock"
        label="Lock"
        value={lockValue}
        active={status.lock.present}
      />
    </>
  );
}
