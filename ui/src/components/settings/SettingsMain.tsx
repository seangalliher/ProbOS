/* AD-741 — Settings main panel. Renders fields for the selected section. */

import { useSettingsStore } from '../../store/useSettingsStore';
import type { FieldDescriptorDTO, SectionDescriptorDTO } from '../../store/useSettingsStore';
import { SectionIcon } from './icons';
import PerceptionLivePanel from './sections/PerceptionLivePanel';
import ProactiveStatusSection from './sections/ProactiveStatusSection';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';

function getNested(obj: Record<string, any>, path: string): any {
  const parts = path.split('.');
  let cursor: any = obj;
  for (const p of parts) {
    if (cursor == null || typeof cursor !== 'object') return undefined;
    cursor = cursor[p];
  }
  return cursor;
}

function FieldRow({
  field,
  initialValue,
  draftValue,
  secretPresent,
  errors,
  onChange,
  disabled = false,
  disabledReason = '',
}: {
  field: FieldDescriptorDTO;
  initialValue: any;
  draftValue: any;
  secretPresent: boolean | undefined;
  errors: { msg: string }[];
  onChange: (value: any) => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const value = draftValue !== undefined ? draftValue : initialValue;
  const dirty = draftValue !== undefined;

  let control: any = null;
  if (field.kind === 'readonly') {
    control = (
      <div data-testid={`field-readonly-${field.field_id}`} style={{ color: STROKE_DIM, fontSize: 11 }}>
        {String(initialValue ?? '')}
      </div>
    );
  } else if (field.kind === 'secret_present_only') {
    control = (
      <div data-testid={`field-secret-${field.field_id}`} style={{ fontSize: 11 }}>
        <span
          style={{
            padding: '2px 8px',
            border: `1px solid ${secretPresent ? STROKE_AMBER : STROKE_DIM}`,
            color: secretPresent ? STROKE_AMBER : STROKE_DIM,
            borderRadius: 10,
            fontSize: 9,
            letterSpacing: 1,
          }}
        >
          {secretPresent ? 'CONFIGURED' : 'NOT CONFIGURED'}
        </span>
        <span style={{ color: STROKE_DIM, marginLeft: 8, fontSize: 9 }}>edit via system.yaml</span>
      </div>
    );
  } else if (field.kind === 'bool') {
    control = (
      <button
        onClick={() => { if (!disabled) onChange(!value); }}
        disabled={disabled}
        aria-disabled={disabled}
        title={disabled ? disabledReason : undefined}
        data-testid={`field-bool-${field.field_id}`}
        style={{
          background: value ? 'rgba(240,176,96,0.12)' : 'transparent',
          border: `1px solid ${value ? STROKE_AMBER : STROKE_DIM}`,
          color: value ? STROKE_AMBER : STROKE_DIM,
          padding: '3px 10px',
          fontSize: 10,
          letterSpacing: 1,
          cursor: disabled ? 'not-allowed' : 'pointer',
          borderRadius: 3,
          opacity: disabled ? 0.4 : 1,
        }}
      >
        {value ? 'ON' : 'OFF'}
      </button>
    );
  } else if (field.kind === 'enum') {
    control = (
      <div data-testid={`field-enum-${field.field_id}`} style={{ display: 'flex', gap: 4 }}>
        {field.enum_values.map(opt => {
          const selected = String(value) === opt;
          return (
            <button
              key={opt}
              onClick={() => { if (!disabled) onChange(opt); }}
              disabled={disabled}
              aria-disabled={disabled}
              title={disabled ? disabledReason : undefined}
              style={{
                background: selected ? 'rgba(240,176,96,0.12)' : 'transparent',
                border: `1px solid ${selected ? STROKE_AMBER : STROKE_DIM}`,
                color: selected ? STROKE_AMBER : '#a0a0b0',
                padding: '3px 8px',
                fontSize: 10,
                letterSpacing: 0.5,
                cursor: disabled ? 'not-allowed' : 'pointer',
                borderRadius: 3,
                opacity: disabled ? 0.4 : 1,
              }}
            >
              {opt}
            </button>
          );
        })}
      </div>
    );
  } else if (field.kind === 'int' || field.kind === 'float') {
    control = (
      <input
        type="number"
        value={value ?? ''}
        disabled={disabled}
        aria-disabled={disabled}
        title={disabled ? disabledReason : undefined}
        data-testid={`field-number-${field.field_id}`}
        onChange={e => {
          const raw = e.target.value;
          if (raw === '') {
            onChange('');
            return;
          }
          const parsed = field.kind === 'int' ? parseInt(raw, 10) : parseFloat(raw);
          onChange(Number.isNaN(parsed) ? raw : parsed);
        }}
        style={{
          background: 'rgba(20,20,32,0.6)',
          border: `1px solid ${dirty ? STROKE_AMBER : 'rgba(240,176,96,0.18)'}`,
          color: '#c8c8d8',
          padding: '4px 8px',
          fontSize: 11,
          fontFamily: "'JetBrains Mono', monospace",
          borderRadius: 3,
          width: 180,
          opacity: disabled ? 0.4 : 1,
          cursor: disabled ? 'not-allowed' : 'text',
        }}
      />
    );
  } else {
    control = (
      <input
        type="text"
        value={value ?? ''}
        disabled={disabled}
        aria-disabled={disabled}
        title={disabled ? disabledReason : undefined}
        data-testid={`field-text-${field.field_id}`}
        onChange={e => onChange(e.target.value)}
        style={{
          background: 'rgba(20,20,32,0.6)',
          border: `1px solid ${dirty ? STROKE_AMBER : 'rgba(240,176,96,0.18)'}`,
          color: '#c8c8d8',
          padding: '4px 8px',
          fontSize: 11,
          fontFamily: "'JetBrains Mono', monospace",
          borderRadius: 3,
          width: 320,
          opacity: disabled ? 0.4 : 1,
          cursor: disabled ? 'not-allowed' : 'text',
        }}
      />
    );
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 16,
        padding: '8px 0',
        borderBottom: '1px solid rgba(240,176,96,0.06)',
      }}
    >
      <div style={{ width: 240, flex: '0 0 240px' }}>
        <div style={{ color: '#c8c8d8', fontSize: 11, fontWeight: 600 }}>{field.label}</div>
        <code style={{ color: STROKE_DIM, fontSize: 9 }}>{field.field_id}</code>
        {field.description && (
          <div style={{ color: '#888899', fontSize: 9, marginTop: 2, lineHeight: 1.4 }}>
            {field.description}
          </div>
        )}
      </div>
      <div style={{ flex: 1 }}>
        {control}
        {errors.length > 0 && (
          <div
            data-testid={`field-error-${field.field_id}`}
            style={{ color: '#e07060', fontSize: 9, marginTop: 4 }}
          >
            {errors.map(e => e.msg).join(', ')}
          </div>
        )}
      </div>
    </div>
  );
}

export default function SettingsMain() {
  const snapshot = useSettingsStore(s => s.snapshot);
  const selectedSectionId = useSettingsStore(s => s.selectedSectionId);
  const draft = useSettingsStore(s => s.draft);
  const setDraftField = useSettingsStore(s => s.setDraftField);
  const applyErrors = useSettingsStore(s => s.applyErrors);

  if (!snapshot) return <div style={{ padding: 24, color: STROKE_DIM }}>Loading…</div>;

  const section: SectionDescriptorDTO | undefined = snapshot.sections.find(
    s => s.section_id === selectedSectionId,
  );
  if (!section) {
    return (
      <div style={{ padding: 24, color: STROKE_DIM, flex: 1 }}>Select a section.</div>
    );
  }

  const errorsByField: Record<string, { msg: string }[]> = {};
  for (const err of applyErrors) {
    const path = err.loc.filter(p => typeof p === 'string').join('.');
    if (!errorsByField[path]) errorsByField[path] = [];
    errorsByField[path].push({ msg: err.msg });
  }

  return (
    <div style={{ flex: 1, padding: '20px 24px', overflowY: 'auto' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 4,
        }}
      >
        <SectionIcon sectionId={section.section_id} size={16} active />
        <h2
          style={{
            margin: 0,
            color: '#e0c090',
            fontSize: 14,
            fontWeight: 700,
            letterSpacing: 1,
          }}
        >
          {section.label}
        </h2>
        <code
          style={{
            color: STROKE_DIM,
            fontSize: 10,
            background: 'rgba(20,20,32,0.5)',
            padding: '1px 6px',
            borderRadius: 3,
          }}
        >
          [{section.section_id}]
        </code>
      </div>
      <div
        style={{
          color: '#888899',
          fontSize: 10,
          marginBottom: 18,
          lineHeight: 1.5,
        }}
      >
        {section.description}
      </div>

      {section.section_id === 'perception' && <PerceptionLivePanel />}
      {section.section_id === 'proactive' && <ProactiveStatusSection />}

      {section.fields.map(field => {
        const initial = getNested(snapshot.config, field.field_id);
        const draftValue = draft[field.field_id];
        const secretPresent = snapshot.secret_present?.[field.field_id];
        const fieldErrors = errorsByField[field.field_id] ?? [];
        // BF-298: parent/child gating — when a section's master toggle is OFF,
        // every other field in the section is functionally inert until APPLY.
        // The master toggle itself stays enabled so the operator can flip it on.
        let disabled = false;
        let disabledReason = '';
        if (section.section_id === 'perception') {
          const masterDraft = draft['perception.enabled'];
          const masterValue = masterDraft !== undefined
            ? masterDraft
            : getNested(snapshot.config, 'perception.enabled');
          const masterOn = Boolean(masterValue);
          if (!masterOn && field.field_id !== 'perception.enabled') {
            disabled = true;
            disabledReason = 'Enable the Perception subsystem first.';
          }
        }
        return (
          <FieldRow
            key={field.field_id}
            field={field}
            initialValue={initial}
            draftValue={draftValue}
            secretPresent={secretPresent}
            errors={fieldErrors}
            onChange={value => setDraftField(field.field_id, value)}
            disabled={disabled}
            disabledReason={disabledReason}
          />
        );
      })}
    </div>
  );
}
