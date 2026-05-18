/* AD-741 — Settings panel sidebar. Grouped by domain in canonical order. */

import { useSettingsStore } from '../../store/useSettingsStore';
import type { SectionDescriptorDTO } from '../../store/useSettingsStore';
import { ControlPanelIcon, SectionIcon } from './icons';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';

function matches(section: SectionDescriptorDTO, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  if (section.label.toLowerCase().includes(needle)) return true;
  for (const f of section.fields) {
    if (f.label.toLowerCase().includes(needle)) return true;
    if (f.field_id.toLowerCase().includes(needle)) return true;
  }
  return false;
}

export default function SettingsSidebar() {
  const snapshot = useSettingsStore(s => s.snapshot);
  const selectedSectionId = useSettingsStore(s => s.selectedSectionId);
  const selectSection = useSettingsStore(s => s.selectSection);
  const search = useSettingsStore(s => s.search);
  const setSearch = useSettingsStore(s => s.setSearch);
  const openYaml = useSettingsStore(s => s.openYaml);

  if (!snapshot) return null;

  const filtered = snapshot.sections.filter(s => matches(s, search));
  const byDomain: Record<string, SectionDescriptorDTO[]> = {};
  for (const s of filtered) {
    if (!byDomain[s.domain]) byDomain[s.domain] = [];
    byDomain[s.domain].push(s);
  }
  const domainCount = Object.keys(snapshot.domain_counts ?? {}).length;

  return (
    <div
      data-testid="settings-sidebar"
      style={{
        width: 280,
        flex: '0 0 280px',
        borderRight: '1px solid rgba(240,176,96,0.12)',
        padding: '16px 12px',
        overflowY: 'auto',
        background: 'rgba(10,10,18,0.45)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <ControlPanelIcon size={14} active />
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.5,
            color: '#c0a070',
          }}
        >
          CONTROL PANEL
        </span>
      </div>
      <div
        style={{
          fontSize: 10,
          color: '#888899',
          marginBottom: 10,
          letterSpacing: 0.5,
        }}
      >
        {snapshot.section_count} sections · {domainCount} domains
      </div>
      <div
        style={{
          fontSize: 10,
          color: '#666680',
          marginBottom: 14,
          paddingBottom: 8,
          borderBottom: '1px solid rgba(240,176,96,0.08)',
          lineHeight: 1.4,
        }}
      >
        Per-agent settings live in the Crew Roster.
      </div>

      <input
        type="text"
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="⌕ Search settings…"
        data-testid="settings-search"
        style={{
          width: '100%',
          background: 'rgba(20,20,32,0.6)',
          border: '1px solid rgba(240,176,96,0.18)',
          color: '#c8c8d8',
          padding: '6px 8px',
          fontSize: 11,
          fontFamily: "'JetBrains Mono', monospace",
          marginBottom: 14,
          borderRadius: 4,
          outline: 'none',
        }}
      />

      {(snapshot.domain_order ?? Object.keys(byDomain)).map(domain => {
        const sections = byDomain[domain];
        if (!sections || sections.length === 0) return null;
        return (
          <div key={domain} style={{ marginBottom: 18 }}>
            <div
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 2,
                color: '#888899',
                marginBottom: 6,
              }}
            >
              {domain.toUpperCase()}
            </div>
            {sections.map(section => {
              const active = section.section_id === selectedSectionId;
              return (
                <div
                  key={section.section_id}
                  onClick={() => selectSection(section.section_id)}
                  data-testid={`settings-section-${section.section_id}`}
                  style={{
                    padding: '6px 8px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    background: active ? 'rgba(240,176,96,0.08)' : 'transparent',
                    border: active
                      ? '1px solid rgba(240,176,96,0.25)'
                      : '1px solid transparent',
                    borderRadius: 4,
                    color: active ? STROKE_AMBER : '#a0a0b0',
                    fontSize: 11,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  <SectionIcon sectionId={section.section_id} size={12} active={active} />
                  <span style={{ flex: 1 }}>{section.label}</span>
                </div>
              );
            })}
          </div>
        );
      })}

      {filtered.length === 0 && (
        <div
          data-testid="settings-search-no-results"
          style={{ fontSize: 10, color: '#666680', textAlign: 'center', marginTop: 24 }}
        >
          no settings match “{search}”
        </div>
      )}

      <div
        style={{
          marginTop: 24,
          paddingTop: 14,
          borderTop: '1px solid rgba(240,176,96,0.08)',
        }}
      >
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1,
            color: '#888899',
            marginBottom: 4,
          }}
        >
          Advanced configuration
        </div>
        <div style={{ fontSize: 10, color: STROKE_DIM, lineHeight: 1.4, marginBottom: 8 }}>
          Edit system.yaml directly.
        </div>
        <button
          onClick={openYaml}
          data-testid="settings-open-yaml"
          style={{
            background: 'transparent',
            border: `1px solid ${STROKE_AMBER}`,
            color: STROKE_AMBER,
            padding: '4px 10px',
            fontSize: 10,
            letterSpacing: 1,
            cursor: 'pointer',
            borderRadius: 3,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          Open YAML editor →
        </button>
      </div>
    </div>
  );
}
