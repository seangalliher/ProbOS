/* AD-905: ClinicalPanel — the Counselor's clinical-observation surface.
 *
 * A Counselor/Captain-only view into an agent's longitudinal cognitive health,
 * lives as the "Clinical" tab of the Crew Personnel Console. Self-contained: it
 * owns its own agent picker (it deliberately does NOT reuse the roster
 * master-detail) and consumes the committed AD-903/904 endpoints read-only:
 *
 *   GET  /api/crew/roster                          → the picker
 *   GET  /api/counselor/clinical/{id}              → five health streams
 *   GET  /api/counselor/notes/{id}                 → clinical notes (newest-first)
 *   POST /api/counselor/notes/{id}  {body}         → append a note
 *
 * The server `require_crew_scope` gate is the REAL access boundary. HXI calls
 * OMIT `as_agent_id`, which the gate reads as Captain authority (allowed) —
 * byte-identical to the committed AD-903 gate. The `authorized` prop is a
 * presentation placeholder only; a server 403 is what actually swaps this panel
 * to its access-denied state.
 *
 * Per HXI #4, each stream gets a visualization matched to its SHAPE, not five
 * identical lines: continuous trends → Sparkline, categorical zone history →
 * ZoneStrip, a single drift scalar → a directional glyph, duty reliability → a
 * bar. HXI #3: stroke-only SVG glyphs, amber active / dim inactive, no emoji.
 *
 * Deps-injectable: an optional `fetchImpl` keeps the panel testable without
 * stubbing globals (mirrors SkillRequestPanel).
 */

import {
  useState,
  useEffect,
  useCallback,
  type ReactNode,
  type KeyboardEvent,
} from 'react';
import { Sparkline } from './Sparkline';
import { ZoneStrip, zoneColor } from './ZoneStrip';

// ── HXI tokens ─────────────────────────────────────────────────────
const AMBER = '#f0b060';
const DIM = '#666680';
const DENY_RED = '#d05050';
const SCIENCE_TEAL = '#4fd0c0';
const HEAL_GREEN = '#60c070';

// ── Stream shapes (mirror the AD-903 serializer, consumed read-only) ──
interface TrustEvent {
  timestamp: number;
  success: boolean;
  old_score: number;
  new_score: number;
  intent_type: string;
}
interface TrustStream {
  events: TrustEvent[];
  raw: [number, number] | null;
}
interface ZonePoint {
  zone: string;
  timestamp: number;
}
interface SelfSimPoint {
  timestamp: number;
  similarity: number;
}
interface HebbianDrift {
  drift_trend: number | null;
  assessments: unknown[];
}
interface DutyStream {
  execution_count: number;
  last_executed: number;
  success_rate: number | null;
}
interface ClinicalStreams {
  trust: TrustStream;
  zones: ZonePoint[];
  self_similarity: SelfSimPoint[];
  hebbian_drift: HebbianDrift;
  duty: DutyStream;
}

interface ClinicalNote {
  id: string;
  target_agent_id: string;
  author_agent_id: string;
  body: string;
  disclosure_level: number;
  created_at: number;
}

interface RosterRow {
  agent_id: string;
  callsign?: string;
  agent_type?: string;
  department?: string | null;
}

const EMPTY_STREAMS: ClinicalStreams = {
  trust: { events: [], raw: null },
  zones: [],
  self_similarity: [],
  hebbian_drift: { drift_trend: null, assessments: [] },
  duty: { execution_count: 0, last_executed: 0, success_rate: null },
};

// ── Pure helpers ───────────────────────────────────────────────────

/** Coerce a possibly-partial server payload into a complete, defaulted shape so
 * every accessor below is total (honest-degrade — a missing stream renders as
 * empty rather than throwing). */
function mergeStreams(raw: unknown): ClinicalStreams {
  const s = (raw ?? {}) as Partial<ClinicalStreams>;
  const trust = (s.trust ?? {}) as Partial<TrustStream>;
  const hebbian = (s.hebbian_drift ?? {}) as Partial<HebbianDrift>;
  const duty = (s.duty ?? {}) as Partial<DutyStream>;
  return {
    trust: {
      events: Array.isArray(trust.events) ? trust.events : [],
      raw: Array.isArray(trust.raw) && trust.raw.length === 2 ? trust.raw : null,
    },
    zones: Array.isArray(s.zones) ? s.zones : [],
    self_similarity: Array.isArray(s.self_similarity) ? s.self_similarity : [],
    hebbian_drift: {
      drift_trend: typeof hebbian.drift_trend === 'number' ? hebbian.drift_trend : null,
      assessments: Array.isArray(hebbian.assessments) ? hebbian.assessments : [],
    },
    duty: {
      execution_count: typeof duty.execution_count === 'number' ? duty.execution_count : 0,
      last_executed: typeof duty.last_executed === 'number' ? duty.last_executed : 0,
      success_rate: typeof duty.success_rate === 'number' ? duty.success_rate : null,
    },
  };
}

/** Trust readout. Prefers the Beta-distribution mean alpha/(alpha+beta) when the
 * raw (alpha,beta) pair is present and well-formed — it's the true stored trust
 * value — and honest-degrades to the latest observed new_score otherwise. Purely
 * defensive: never throws on a malformed pair. */
function trustReadout(trust: TrustStream): string {
  if (Array.isArray(trust.raw) && trust.raw.length === 2) {
    const [alpha, beta] = trust.raw;
    if (
      typeof alpha === 'number' &&
      typeof beta === 'number' &&
      isFinite(alpha) &&
      isFinite(beta) &&
      alpha + beta > 0
    ) {
      return (alpha / (alpha + beta)).toFixed(2);
    }
  }
  const evs = trust.events;
  if (evs.length > 0) {
    const latest = evs[evs.length - 1].new_score;
    if (typeof latest === 'number' && isFinite(latest)) return latest.toFixed(2);
  }
  return '\u2014';
}

/** Epoch SECONDS → locale string. 0/absent → "never" (used by duty's
 * last_executed). Notes use the *(... * 1000)* form directly for clarity. */
function humanizeEpoch(sec: number): string {
  if (!sec || sec <= 0) return 'never';
  return new Date(sec * 1000).toLocaleString();
}

// ── Inline SVG glyphs (stroke-based, no emoji — HXI #3) ─────────────

function LockGlyph({ color }: { color: string }) {
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
      <rect x="5" y="11" width="14" height="9" rx="1" />
      <path d="M8 11 V7 a4 4 0 0 1 8 0 v4" />
    </svg>
  );
}

/** Directional drift glyph: up (>0), down (<0), flat dash (0 or null). */
function DriftGlyph({ trend }: { trend: number | null }) {
  let color = DIM;
  let path = 'M5 12 L19 12';
  if (trend !== null && isFinite(trend) && trend > 0) {
    color = HEAL_GREEN;
    path = 'M12 19 L12 5 M6 11 L12 5 L18 11';
  } else if (trend !== null && isFinite(trend) && trend < 0) {
    color = DENY_RED;
    path = 'M12 5 L12 19 M6 13 L12 19 L18 13';
  } else if (trend === 0) {
    color = AMBER;
  }
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}

// ── Layout primitives ──────────────────────────────────────────────

function TrendCard({
  testId,
  label,
  children,
}: {
  testId: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <div
      data-testid={testId}
      style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 6,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: 9,
          letterSpacing: 1.5,
          fontWeight: 700,
          color: DIM,
          textTransform: 'uppercase',
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function NoData() {
  return <div style={{ fontSize: 11, color: DIM }}>No trend data yet</div>;
}

// ── Panel ──────────────────────────────────────────────────────────

export default function ClinicalPanel({
  fetchImpl,
  authorized = true,
}: { fetchImpl?: typeof fetch; authorized?: boolean } = {}) {
  const doFetch: typeof fetch = fetchImpl ?? ((...a) => fetch(...a));

  const [roster, setRoster] = useState<RosterRow[]>([]);
  const [rosterLoaded, setRosterLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState(false);
  const [streams, setStreams] = useState<ClinicalStreams | null>(null);
  const [notes, setNotes] = useState<ClinicalNote[]>([]);
  const [noteText, setNoteText] = useState('');
  const [noteError, setNoteError] = useState<string | null>(null);

  // Roster fetch (the picker source). The client placeholder short-circuits
  // BEFORE any network call — the unauthorized presentation must never fetch.
  useEffect(() => {
    if (authorized === false) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await doFetch('/api/crew/roster');
        if (!resp.ok) {
          if (!cancelled) setRoster([]);
          return;
        }
        const data = await resp.json();
        if (!cancelled) setRoster(Array.isArray(data?.crew) ? data.crew : []);
      } catch {
        // Tier-1 honest-degrade — an empty picker beats a crashed shell.
        if (!cancelled) setRoster([]);
      } finally {
        if (!cancelled) setRosterLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authorized, doFetch]);

  const selectAgent = useCallback(
    async (id: string) => {
      setSelectedId(id);
      setLoadingDetail(true);
      setDetailError(false);
      setStreams(null);
      setNotes([]);
      setNoteError(null);
      try {
        // Calls OMIT as_agent_id (Captain authority = allowed at the gate).
        const [clinicalResp, notesResp] = await Promise.all([
          doFetch(`/api/counselor/clinical/${encodeURIComponent(id)}`),
          doFetch(`/api/counselor/notes/${encodeURIComponent(id)}`),
        ]);
        // A 403 on EITHER endpoint is the real access boundary → swap the panel.
        if (clinicalResp.status === 403 || notesResp.status === 403) {
          setUnauthorized(true);
          return;
        }
        if (!clinicalResp.ok || !notesResp.ok) {
          setDetailError(true);
          setStreams(EMPTY_STREAMS);
          setNotes([]);
          return;
        }
        const clinicalData = await clinicalResp.json();
        const notesData = await notesResp.json();
        setStreams(mergeStreams(clinicalData?.streams));
        setNotes(Array.isArray(notesData?.notes) ? notesData.notes : []);
      } catch {
        // Honest-degrade — surface the error banner over an empty shell.
        setDetailError(true);
        setStreams(EMPTY_STREAMS);
        setNotes([]);
      } finally {
        setLoadingDetail(false);
      }
    },
    [doFetch],
  );

  const onRowKey = useCallback(
    (e: KeyboardEvent, id: string) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        void selectAgent(id);
      }
    },
    [selectAgent],
  );

  const submitNote = useCallback(async () => {
    if (!selectedId) return;
    const body = noteText.trim();
    if (!body) return;
    setNoteError(null);
    try {
      const resp = await doFetch(`/api/counselor/notes/${encodeURIComponent(selectedId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body }),
      });
      if (!resp.ok) {
        // Keep the typed text so the Counselor can retry.
        setNoteError('Failed to save note. Try again.');
        return;
      }
      const data = await resp.json();
      // Optimistic prepend (newest-first) + clear the box.
      const newNote: ClinicalNote = {
        id: data?.id ?? `local-${Date.now()}`,
        target_agent_id: selectedId,
        author_agent_id: 'captain',
        body,
        disclosure_level: 3,
        created_at: Date.now() / 1000,
      };
      setNotes(prev => [newNote, ...prev]);
      setNoteText('');
    } catch {
      setNoteError('Failed to save note. Try again.');
    }
  }, [doFetch, selectedId, noteText]);

  // ── Access-denied (client placeholder OR server 403 swap) ─────────
  if (authorized === false || unauthorized) {
    return (
      <div
        data-testid="clinical-unauthorized"
        role="status"
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 10,
          padding: 40,
          color: DIM,
          textAlign: 'center',
        }}
      >
        <LockGlyph color={DENY_RED} />
        <div style={{ fontSize: 12, color: '#c8c8d4' }}>Counselor access only</div>
        <div style={{ fontSize: 10 }}>
          Clinical observations are restricted to the Counselor and the Captain.
        </div>
      </div>
    );
  }

  const s = streams ?? EMPTY_STREAMS;
  const latestZone = s.zones.length > 0 ? s.zones[s.zones.length - 1].zone : null;
  const latestSim =
    s.self_similarity.length > 0
      ? s.self_similarity[s.self_similarity.length - 1].similarity
      : null;

  return (
    <div
      data-testid="clinical-panel"
      style={{ display: 'flex', gap: 16, minHeight: 0, alignItems: 'stretch' }}
    >
      {/* ── Picker rail ── */}
      <div
        data-testid="clinical-picker"
        style={{
          width: 200,
          flexShrink: 0,
          borderRight: '1px solid rgba(255,255,255,0.06)',
          paddingRight: 12,
          overflowY: 'auto',
        }}
      >
        <div
          style={{
            fontSize: 9,
            letterSpacing: 1.5,
            fontWeight: 700,
            color: AMBER,
            textTransform: 'uppercase',
            marginBottom: 8,
          }}
        >
          Crew
        </div>
        {!rosterLoaded ? (
          <div style={{ fontSize: 11, color: DIM }}>Loading roster...</div>
        ) : roster.length === 0 ? (
          <div data-testid="clinical-roster-empty" style={{ fontSize: 11, color: DIM }}>
            No crew aboard
          </div>
        ) : (
          roster.map(entry => {
            const sel = entry.agent_id === selectedId;
            const label = entry.callsign || entry.agent_type || entry.agent_id;
            return (
              <div
                key={entry.agent_id}
                role="button"
                tabIndex={0}
                aria-label={`Open clinical view for ${label}`}
                aria-pressed={sel}
                data-testid={`clinical-agent-row-${entry.agent_id}`}
                onClick={() => void selectAgent(entry.agent_id)}
                onKeyDown={e => onRowKey(e, entry.agent_id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '6px 8px',
                  borderRadius: 4,
                  cursor: 'pointer',
                  color: sel ? AMBER : '#c8c8d4',
                  background: sel ? 'rgba(240,176,96,0.12)' : 'transparent',
                  borderLeft: sel ? '2px solid #f0b060' : '2px solid transparent',
                  fontSize: 12,
                }}
              >
                <span
                  aria-hidden="true"
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    flexShrink: 0,
                    background: entry.department ? '#5090d0' : DIM,
                  }}
                />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {label}
                </span>
              </div>
            );
          })
        )}
      </div>

      {/* ── Detail ── */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {selectedId === null ? (
          <div
            data-testid="clinical-empty"
            style={{
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: DIM,
              fontSize: 11,
              textAlign: 'center',
              padding: 24,
            }}
          >
            Select a crew member to review their clinical streams.
          </div>
        ) : loadingDetail ? (
          <div data-testid="clinical-loading" style={{ color: DIM, fontSize: 11, padding: 8 }}>
            Loading clinical streams...
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {detailError && (
              <div
                data-testid="clinical-error"
                role="alert"
                style={{
                  fontSize: 11,
                  color: DENY_RED,
                  background: 'rgba(208,80,80,0.1)',
                  border: `1px solid ${DENY_RED}55`,
                  borderRadius: 4,
                  padding: '6px 10px',
                }}
              >
                Could not load clinical streams. Showing an empty record.
              </div>
            )}

            {/* ── Trend cards (one viz per stream shape, not five lines) ── */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: 10,
              }}
            >
              {/* 1 — Trust (continuous → sparkline) */}
              <TrendCard testId="clinical-stream-trust" label="Trust">
                {s.trust.events.length === 0 ? (
                  <NoData />
                ) : (
                  <>
                    <Sparkline
                      values={s.trust.events.map(e => e.new_score)}
                      color={AMBER}
                      testId="clinical-sparkline-trust"
                      ariaLabel="Trust score trend"
                    />
                    <div style={{ fontSize: 16, fontWeight: 700, color: AMBER }}>
                      {trustReadout(s.trust)}
                    </div>
                  </>
                )}
              </TrendCard>

              {/* 2 — Cognitive zone (categorical → strip) */}
              <TrendCard testId="clinical-stream-zones" label="Cognitive Zone">
                <ZoneStrip
                  zones={s.zones}
                  testId="clinical-zonestrip"
                  ariaLabel="Cognitive zone history"
                />
                {latestZone === null ? (
                  <NoData />
                ) : (
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 700,
                      letterSpacing: 1,
                      color: zoneColor(latestZone),
                    }}
                  >
                    {latestZone.toUpperCase()}
                  </div>
                )}
              </TrendCard>

              {/* 3 — Self-similarity (bounded 0..1 → sparkline) */}
              <TrendCard testId="clinical-stream-self_similarity" label="Self-Similarity">
                {s.self_similarity.length === 0 ? (
                  <NoData />
                ) : (
                  <>
                    <Sparkline
                      values={s.self_similarity.map(p => p.similarity)}
                      min={0}
                      max={1}
                      color={SCIENCE_TEAL}
                      testId="clinical-sparkline-self_similarity"
                      ariaLabel="Self-similarity trend"
                    />
                    <div style={{ fontSize: 16, fontWeight: 700, color: SCIENCE_TEAL }}>
                      {latestSim !== null ? latestSim.toFixed(2) : '\u2014'}
                    </div>
                  </>
                )}
              </TrendCard>

              {/* 4 — Hebbian drift (single scalar → directional glyph) */}
              <TrendCard testId="clinical-stream-hebbian" label="Hebbian Drift">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <DriftGlyph trend={s.hebbian_drift.drift_trend} />
                  <span style={{ fontSize: 16, fontWeight: 700, color: '#c8c8d4' }}>
                    {s.hebbian_drift.drift_trend === null
                      ? '\u2014'
                      : s.hebbian_drift.drift_trend.toFixed(3)}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: DIM }}>
                  {s.hebbian_drift.assessments.length} assessments
                </div>
              </TrendCard>

              {/* 5 — Duty reliability (rate → bar) */}
              <TrendCard testId="clinical-stream-duty" label="Duty Reliability">
                {s.duty.success_rate === null ? (
                  <div style={{ fontSize: 11, color: DIM }}>No outcomes yet</div>
                ) : (
                  <>
                    <div
                      role="img"
                      aria-label={`Duty success rate ${Math.round(
                        Math.max(0, Math.min(1, s.duty.success_rate)) * 100,
                      )} percent`}
                      style={{
                        height: 8,
                        borderRadius: 4,
                        background: 'rgba(255,255,255,0.08)',
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          width: `${Math.max(0, Math.min(1, s.duty.success_rate)) * 100}%`,
                          height: '100%',
                          background: HEAL_GREEN,
                        }}
                      />
                    </div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: HEAL_GREEN }}>
                      {Math.round(Math.max(0, Math.min(1, s.duty.success_rate)) * 100)}%
                    </div>
                  </>
                )}
                <div style={{ fontSize: 10, color: DIM }}>
                  {s.duty.execution_count} executions · last {humanizeEpoch(s.duty.last_executed)}
                </div>
              </TrendCard>
            </div>

            {/* ── Confidential notes ── */}
            <div data-testid="clinical-notes" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 9,
                  letterSpacing: 1,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  color: DENY_RED,
                }}
              >
                <LockGlyph color={DENY_RED} />
                Confidential &mdash; Counselor / Captain only
              </div>

              {notes.length === 0 ? (
                <div data-testid="clinical-notes-empty" style={{ fontSize: 11, color: DIM }}>
                  No notes recorded
                </div>
              ) : (
                <div data-testid="clinical-notes-list" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {notes.map(note => (
                    <div
                      key={note.id}
                      data-testid={`clinical-note-${note.id}`}
                      style={{
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid rgba(255,255,255,0.06)',
                        borderRadius: 4,
                        padding: '8px 10px',
                      }}
                    >
                      <div style={{ fontSize: 12, color: '#e0dcd4', whiteSpace: 'pre-wrap' }}>
                        {note.body}
                      </div>
                      <div style={{ fontSize: 9, color: DIM, marginTop: 4 }}>
                        {note.author_agent_id} · {new Date(note.created_at * 1000).toLocaleString()}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {noteError && (
                <div
                  data-testid="clinical-note-error"
                  role="alert"
                  style={{ fontSize: 11, color: DENY_RED }}
                >
                  {noteError}
                </div>
              )}

              <textarea
                data-testid="clinical-note-input"
                aria-label="New clinical note"
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                placeholder="Record a clinical observation..."
                rows={2}
                style={{
                  resize: 'vertical',
                  fontFamily: 'inherit',
                  fontSize: 12,
                  color: '#e0dcd4',
                  background: 'rgba(0,0,0,0.25)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 4,
                  padding: '6px 8px',
                }}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  data-testid="clinical-note-submit"
                  aria-label="Save clinical note"
                  disabled={noteText.trim().length === 0}
                  onClick={() => void submitNote()}
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: 0.5,
                    color: noteText.trim().length === 0 ? DIM : AMBER,
                    background: 'transparent',
                    border: `1px solid ${noteText.trim().length === 0 ? DIM : AMBER}55`,
                    borderRadius: 4,
                    padding: '5px 12px',
                    cursor: noteText.trim().length === 0 ? 'default' : 'pointer',
                  }}
                >
                  Save Note
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
