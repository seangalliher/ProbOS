/* AD-763 — Connectors section for the Settings panel.
 *
 * Microsoft 365 subsection — only rendered when an M365 OAuth session is
 * present (mail-folders endpoint returns 401 otherwise; UI honest-degrades
 * to a "Sign in to Microsoft 365" hint). Mail folders + calendars are
 * populated from /api/connectors/m365/mail-folders and /m365/calendars.
 *
 * HXI Design Principles:
 *  - #3: no emoji; inline SVG glyphs only.
 *  - #5: subsections collapsed by default, expand on click.
 */
import { useEffect, useState } from 'react';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';
const PANEL_BG = 'rgba(18, 20, 30, 0.45)';

type MailFolder = {
  id: string;
  displayName: string;
  parentFolderId?: string | null;
  totalItemCount?: number;
};

type Calendar = {
  id: string;
  name: string;
  owner?: unknown;
  canEdit?: boolean;
  isDefaultCalendar?: boolean;
};

type ScanConfig = {
  inbox: {
    folders: string[];
    lookback_hours: number;
    importance_filter: 'any' | 'high';
    unread_only: boolean;
    sender_allowlist: string[];
    sender_denylist: string[];
  };
  calendar: {
    calendar_ids: string[];
    lookahead_hours: number;
    include_declined: boolean;
  };
};

const DEFAULT_CONFIG: ScanConfig = {
  inbox: {
    folders: ['Inbox'],
    lookback_hours: 24,
    importance_filter: 'any',
    unread_only: false,
    sender_allowlist: [],
    sender_denylist: [],
  },
  calendar: {
    calendar_ids: ['primary'],
    lookahead_hours: 24,
    include_declined: false,
  },
};

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke={STROKE_AMBER}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 120ms' }}
    >
      <path d="M4 2 L8 6 L4 10" />
    </svg>
  );
}

function MultiSelect<T extends { id: string }>({
  options,
  selected,
  onToggle,
  labelOf,
  emptyText,
  testIdPrefix,
}: {
  options: T[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  labelOf: (opt: T) => string;
  emptyText: string;
  testIdPrefix: string;
}) {
  if (options.length === 0) {
    return <div style={{ color: STROKE_DIM, fontSize: 10 }}>{emptyText}</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
      {options.map(opt => {
        const isSelected = selected.has(opt.id);
        return (
          <label
            key={opt.id}
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#c8c8d8', cursor: 'pointer' }}
          >
            <input
              type="checkbox"
              checked={isSelected}
              onChange={() => onToggle(opt.id)}
              data-testid={`${testIdPrefix}-${opt.id}`}
            />
            <span>{labelOf(opt)}</span>
          </label>
        );
      })}
    </div>
  );
}

function Subsection({
  title,
  open,
  onToggle,
  children,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        margin: '8px 0',
        border: `1px solid rgba(240,176,96,0.14)`,
        borderRadius: 8,
        padding: '8px 10px',
        background: PANEL_BG,
      }}
    >
      <button
        onClick={onToggle}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: 'transparent',
          border: 'none',
          color: STROKE_AMBER,
          fontSize: 11,
          letterSpacing: 1,
          fontWeight: 700,
          cursor: 'pointer',
          padding: 0,
        }}
        aria-expanded={open}
      >
        <Chevron open={open} />
        <span>{title}</span>
      </button>
      {open && <div style={{ marginTop: 10 }}>{children}</div>}
    </div>
  );
}

export function ConnectorsSection() {
  const [folders, setFolders] = useState<MailFolder[]>([]);
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [config, setConfig] = useState<ScanConfig>(DEFAULT_CONFIG);
  const [m365Available, setM365Available] = useState<boolean>(true);
  const [m365Open, setM365Open] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [saveStatus, setSaveStatus] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const cfgRes = await fetch('/api/connectors/scan-config');
        if (cfgRes.ok) {
          const cfg = (await cfgRes.json()) as ScanConfig;
          if (!cancelled) setConfig(cfg);
        }
      } catch {
        // honest-degrade to defaults
      }
      try {
        const foldersRes = await fetch('/api/connectors/m365/mail-folders');
        if (foldersRes.status === 401) {
          if (!cancelled) setM365Available(false);
          return;
        }
        if (foldersRes.ok) {
          const data = await foldersRes.json();
          if (!cancelled) setFolders(data.folders ?? []);
        }
      } catch {
        if (!cancelled) setM365Available(false);
        return;
      }
      try {
        const calRes = await fetch('/api/connectors/m365/calendars');
        if (calRes.ok) {
          const data = await calRes.json();
          if (!cancelled) setCalendars(data.calendars ?? []);
        }
      } catch {
        // partial-load OK
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleFolder = (id: string): void => {
    setConfig(prev => {
      const set = new Set(prev.inbox.folders);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      return { ...prev, inbox: { ...prev.inbox, folders: Array.from(set) } };
    });
  };

  const toggleCalendar = (id: string): void => {
    setConfig(prev => {
      const set = new Set(prev.calendar.calendar_ids);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      return { ...prev, calendar: { ...prev.calendar, calendar_ids: Array.from(set) } };
    });
  };

  const handleSave = async (): Promise<void> => {
    setSaving(true);
    setSaveStatus('');
    try {
      const res = await fetch('/api/connectors/scan-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (res.ok) {
        const persisted = (await res.json()) as ScanConfig;
        setConfig(persisted);
        setSaveStatus('Saved');
      } else {
        setSaveStatus(`Save failed (${res.status})`);
      }
    } catch {
      setSaveStatus('Save failed (network)');
    } finally {
      setSaving(false);
    }
  };

  const inboxFolderSet = new Set(config.inbox.folders);
  const calendarIdSet = new Set(config.calendar.calendar_ids);

  return (
    <div data-testid="connectors-section">
      <Subsection title="MICROSOFT 365" open={m365Open} onToggle={() => setM365Open(o => !o)}>
        {!m365Available ? (
          <div style={{ fontSize: 11, color: STROKE_DIM, lineHeight: 1.5 }}>
            Sign in to Microsoft 365 in the auth panel to scope inbox folders and calendars.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <div style={{ fontSize: 10, color: STROKE_AMBER, marginBottom: 4, letterSpacing: 1 }}>MAIL FOLDERS</div>
              <MultiSelect
                options={folders}
                selected={inboxFolderSet}
                onToggle={toggleFolder}
                labelOf={f => f.displayName || f.id}
                emptyText="No mail folders discovered."
                testIdPrefix="folder"
              />
            </div>

            <div>
              <div style={{ fontSize: 10, color: STROKE_AMBER, marginBottom: 4, letterSpacing: 1 }}>CALENDARS</div>
              <MultiSelect
                options={calendars}
                selected={calendarIdSet}
                onToggle={toggleCalendar}
                labelOf={c => c.name || c.id}
                emptyText="No calendars discovered."
                testIdPrefix="calendar"
              />
            </div>

            <div style={{ display: 'flex', gap: 16 }}>
              <label style={{ fontSize: 11, color: '#c8c8d8', display: 'flex', flexDirection: 'column', gap: 4 }}>
                Inbox lookback (hours)
                <input
                  type="number"
                  min={1}
                  max={336}
                  value={config.inbox.lookback_hours}
                  onChange={e =>
                    setConfig(p => ({ ...p, inbox: { ...p.inbox, lookback_hours: parseInt(e.target.value || '24', 10) } }))
                  }
                  data-testid="lookback-hours"
                  style={{ width: 80, background: 'rgba(20,20,32,0.6)', border: `1px solid ${STROKE_DIM}`, color: '#c8c8d8', padding: '3px 6px' }}
                />
              </label>
              <label style={{ fontSize: 11, color: '#c8c8d8', display: 'flex', flexDirection: 'column', gap: 4 }}>
                Calendar lookahead (hours)
                <input
                  type="number"
                  min={1}
                  max={720}
                  value={config.calendar.lookahead_hours}
                  onChange={e =>
                    setConfig(p => ({ ...p, calendar: { ...p.calendar, lookahead_hours: parseInt(e.target.value || '24', 10) } }))
                  }
                  data-testid="lookahead-hours"
                  style={{ width: 80, background: 'rgba(20,20,32,0.6)', border: `1px solid ${STROKE_DIM}`, color: '#c8c8d8', padding: '3px 6px' }}
                />
              </label>
            </div>

            <div>
              <div style={{ fontSize: 10, color: STROKE_AMBER, marginBottom: 4, letterSpacing: 1 }}>IMPORTANCE</div>
              <div style={{ display: 'flex', gap: 12, fontSize: 11, color: '#c8c8d8' }}>
                <label style={{ display: 'flex', gap: 4, cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="importance"
                    checked={config.inbox.importance_filter === 'any'}
                    onChange={() => setConfig(p => ({ ...p, inbox: { ...p.inbox, importance_filter: 'any' } }))}
                    data-testid="importance-any"
                  />
                  Any
                </label>
                <label style={{ display: 'flex', gap: 4, cursor: 'pointer' }}>
                  <input
                    type="radio"
                    name="importance"
                    checked={config.inbox.importance_filter === 'high'}
                    onChange={() => setConfig(p => ({ ...p, inbox: { ...p.inbox, importance_filter: 'high' } }))}
                    data-testid="importance-high"
                  />
                  High only
                </label>
              </div>
            </div>

            <label style={{ fontSize: 11, color: '#c8c8d8', display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                type="checkbox"
                checked={config.inbox.unread_only}
                onChange={e => setConfig(p => ({ ...p, inbox: { ...p.inbox, unread_only: e.target.checked } }))}
                data-testid="unread-only"
              />
              Unread only
            </label>

            <label style={{ fontSize: 11, color: '#c8c8d8', display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                type="checkbox"
                checked={config.calendar.include_declined}
                onChange={e => setConfig(p => ({ ...p, calendar: { ...p.calendar, include_declined: e.target.checked } }))}
                data-testid="include-declined"
              />
              Include declined calendar events
            </label>

            <div style={{ display: 'flex', gap: 16 }}>
              <label style={{ fontSize: 11, color: '#c8c8d8', display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
                Sender allowlist (one per line)
                <textarea
                  rows={3}
                  value={config.inbox.sender_allowlist.join('\n')}
                  onChange={e =>
                    setConfig(p => ({
                      ...p,
                      inbox: {
                        ...p.inbox,
                        sender_allowlist: e.target.value.split('\n').map(s => s.trim()).filter(Boolean),
                      },
                    }))
                  }
                  data-testid="sender-allowlist"
                  style={{ background: 'rgba(20,20,32,0.6)', border: `1px solid ${STROKE_DIM}`, color: '#c8c8d8', padding: 4, fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}
                />
              </label>
              <label style={{ fontSize: 11, color: '#c8c8d8', display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
                Sender denylist (one per line)
                <textarea
                  rows={3}
                  value={config.inbox.sender_denylist.join('\n')}
                  onChange={e =>
                    setConfig(p => ({
                      ...p,
                      inbox: {
                        ...p.inbox,
                        sender_denylist: e.target.value.split('\n').map(s => s.trim()).filter(Boolean),
                      },
                    }))
                  }
                  data-testid="sender-denylist"
                  style={{ background: 'rgba(20,20,32,0.6)', border: `1px solid ${STROKE_DIM}`, color: '#c8c8d8', padding: 4, fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}
                />
              </label>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button
                onClick={() => { void handleSave(); }}
                disabled={saving}
                data-testid="connectors-save"
                style={{
                  background: 'rgba(240,176,96,0.12)',
                  border: `1px solid ${STROKE_AMBER}`,
                  color: STROKE_AMBER,
                  padding: '4px 14px',
                  fontSize: 11,
                  letterSpacing: 1,
                  cursor: saving ? 'wait' : 'pointer',
                  borderRadius: 3,
                }}
              >
                {saving ? 'SAVING…' : 'SAVE'}
              </button>
              {saveStatus && (
                <span data-testid="connectors-save-status" style={{ fontSize: 10, color: STROKE_DIM }}>
                  {saveStatus}
                </span>
              )}
            </div>
          </div>
        )}
      </Subsection>
    </div>
  );
}

export default ConnectorsSection;
