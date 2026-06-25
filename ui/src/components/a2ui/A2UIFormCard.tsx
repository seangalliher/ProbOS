/**
 * AD-811b-1: interactive form card rendered in place of an [A2UI] stub
 * whose kind is ``form`` inside ProfileChatTab message bodies.
 *
 * Mirrors ``A2UIMultiSelectCard`` for artifact resolution + fetch, but the
 * Captain fills a free-text input per field. The DM pipeline stored the
 * JSON as an ``application/json`` artifact and left an inline stub:
 *
 *     [A2UI: a2ui-form-1.json v1 - form]
 *
 * Resolves ``(threadId, name, version)`` against
 * ``useStore.artifactsByThread``, fetches the JSON via
 * ``fetchArtifactContent``, parses it with ``parseFormSpec``, and renders
 * the prompt + one labeled text input per field + a Submit button. Submit
 * is enabled once every ``required`` field has a non-empty value. On submit
 * the card locks (all controls disabled) and calls ``onChoice`` with the
 * fields encoded as ``label: value`` lines (e.g. "Name: Ada\nRole: Eng");
 * ProfileChatTab posts that back through ``sendText`` (same callback the
 * choice + multiselect cards use).
 */
import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../../store/useStore';
import { fetchArtifactContent } from '../artifacts/artifactApi';
import { parseFormSpec, type ParsedFormSpec } from './a2uiApi';

const AMBER = '#f0b060';
const DIM = '#888899';

export interface A2UIFormCardProps {
  /** The chat thread the message belongs to. */
  threadId: string;
  /** Parsed-from-stub artifact name. */
  name: string;
  /** Parsed-from-stub artifact version. */
  version: number;
  /** Called with the filled fields ("label: value" lines) on submit. */
  onChoice: (response: string) => void;
}

export function A2UIFormCard(props: A2UIFormCardProps) {
  const { threadId, name, version, onChoice } = props;
  const artifactsByThread = useStore((s) => s.artifactsByThread);
  const [spec, setSpec] = useState<ParsedFormSpec | null>(null);
  const [values, setValues] = useState<string[]>([]);
  const [submitted, setSubmitted] = useState(false);

  const resolved = useMemo(() => {
    const list = artifactsByThread.get(threadId) ?? [];
    return list.find((a) => a.name === name && a.version === version) ?? null;
  }, [artifactsByThread, threadId, name, version]);

  useEffect(() => {
    if (!resolved) return;
    let cancelled = false;
    fetchArtifactContent(resolved.id)
      .then(({ text }) => {
        if (cancelled) return;
        const parsed = parseFormSpec(text);
        setSpec(parsed);
        setValues(parsed ? parsed.fields.map(() => '') : []);
      })
      .catch(() => {
        if (!cancelled) setSpec(null);
      });
    return () => {
      cancelled = true;
    };
  }, [resolved]);

  if (!resolved || !spec) {
    return (
      <span
        data-testid="a2ui-form-card"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          margin: '4px 0', padding: '4px 8px',
          border: '1px solid rgba(255,255,255,0.1)', borderRadius: 4,
          background: 'rgba(240, 176, 96, 0.04)', color: DIM,
          fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
          cursor: 'wait', whiteSpace: 'nowrap',
        }}
      >
        Loading form…
      </span>
    );
  }

  const canSubmit =
    !submitted &&
    spec.fields.every((f, i) => !f.required || (values[i] ?? '').trim() !== '');

  const setField = (i: number, v: string): void => {
    if (submitted) return;
    setValues((prev) => {
      const next = prev.slice();
      next[i] = v;
      return next;
    });
  };

  const submit = (): void => {
    if (!canSubmit) return;
    setSubmitted(true);
    onChoice(
      spec.fields
        .map((f, i) => `${f.label}: ${(values[i] ?? '').trim()}`)
        .join('\n'),
    );
  };

  return (
    <div
      data-testid="a2ui-form-card"
      style={{
        display: 'block', margin: '6px 0', padding: '10px 12px',
        border: `1px solid ${AMBER}`, borderRadius: 6,
        background: 'rgba(240, 176, 96, 0.06)',
        backdropFilter: 'blur(6px)',
        color: '#e0dcd4',
        fontFamily: "'Inter', system-ui, sans-serif",
      }}
    >
      <div style={{ fontSize: 13, marginBottom: 8 }}>{spec.prompt}</div>
      <div
        style={{
          display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 8,
        }}
      >
        {spec.fields.map((f, i) => (
          <label
            key={i}
            style={{
              display: 'flex', flexDirection: 'column', gap: 3,
              fontSize: 12, color: '#e0dcd4',
            }}
          >
            <span>
              {f.label}
              {f.required ? ' *' : ''}
            </span>
            <input
              data-testid={'a2ui-form-input-' + i}
              type="text"
              value={values[i] ?? ''}
              disabled={submitted}
              onChange={(e) => setField(i, e.target.value)}
              style={{
                padding: '5px 8px', borderRadius: 4,
                border: `1px solid rgba(240, 176, 96, 0.3)`,
                background: submitted ? 'transparent' : 'rgba(0,0,0,0.2)',
                color: submitted ? DIM : '#e0dcd4',
                fontFamily: "'Inter', system-ui, sans-serif",
                fontSize: 12,
              }}
            />
          </label>
        ))}
      </div>
      <button
        data-testid="a2ui-form-submit"
        disabled={!canSubmit}
        onClick={submit}
        style={{
          padding: '5px 14px', borderRadius: 4,
          border: `1px solid ${canSubmit ? AMBER : 'rgba(240, 176, 96, 0.3)'}`,
          background: canSubmit ? 'rgba(240, 176, 96, 0.18)' : 'transparent',
          color: canSubmit ? AMBER : DIM,
          fontFamily: "'Inter', system-ui, sans-serif",
          fontSize: 12,
          cursor: canSubmit ? 'pointer' : 'default',
        }}
      >
        Submit
      </button>
    </div>
  );
}
