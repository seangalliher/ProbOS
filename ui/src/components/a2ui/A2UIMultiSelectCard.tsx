/**
 * AD-811b: interactive multi-select card rendered in place of an [A2UI]
 * stub whose kind is ``multiselect`` inside ProfileChatTab message bodies.
 *
 * Mirrors ``A2UIChoiceCard`` for artifact resolution + fetch, but the
 * Captain may toggle several options before submitting. The DM pipeline
 * stored the JSON as an ``application/json`` artifact and left an inline
 * stub:
 *
 *     [A2UI: a2ui-multiselect-1.json v1 - multiselect]
 *
 * This card resolves ``(threadId, name, version)`` against
 * ``useStore.artifactsByThread`` (mirroring ArtifactCard), fetches the
 * JSON via ``fetchArtifactContent``, parses it with
 * ``parseMultiSelectSpec``, and renders the prompt + a toggle button per
 * option + a Submit button. Submit is enabled once at least ``minSelect``
 * options are picked; when ``maxSelect`` is set the unselected options
 * disable at the cap. On submit the card locks (all controls disabled)
 * and calls ``onChoice`` with the picked options in OPTION order joined
 * by ", " (e.g. "Alpha, Gamma"); ProfileChatTab posts that back through
 * ``sendText`` (same callback the choice card uses).
 */
import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../../store/useStore';
import { fetchArtifactContent } from '../artifacts/artifactApi';
import { parseMultiSelectSpec, type ParsedMultiSelectSpec } from './a2uiApi';

const AMBER = '#f0b060';
const DIM = '#888899';

export interface A2UIMultiSelectCardProps {
  /** The chat thread the message belongs to. */
  threadId: string;
  /** Parsed-from-stub artifact name. */
  name: string;
  /** Parsed-from-stub artifact version. */
  version: number;
  /** Called with the picked options (option order, ", "-joined) on submit. */
  onChoice: (response: string) => void;
}

export function A2UIMultiSelectCard(props: A2UIMultiSelectCardProps) {
  const { threadId, name, version, onChoice } = props;
  const artifactsByThread = useStore((s) => s.artifactsByThread);
  const [spec, setSpec] = useState<ParsedMultiSelectSpec | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
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
        if (!cancelled) setSpec(parseMultiSelectSpec(text));
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
        data-testid="a2ui-multiselect-card"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          margin: '4px 0', padding: '4px 8px',
          border: '1px solid rgba(255,255,255,0.1)', borderRadius: 4,
          background: 'rgba(240, 176, 96, 0.04)', color: DIM,
          fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
          cursor: 'wait', whiteSpace: 'nowrap',
        }}
      >
        Loading options…
      </span>
    );
  }

  const atMax = spec.maxSelect !== null && selected.size >= spec.maxSelect;
  const canSubmit = !submitted && selected.size >= spec.minSelect;

  const toggle = (opt: string): void => {
    if (submitted) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(opt)) {
        next.delete(opt);
      } else {
        if (spec.maxSelect !== null && next.size >= spec.maxSelect) return prev;
        next.add(opt);
      }
      return next;
    });
  };

  const submit = (): void => {
    if (submitted || selected.size < spec.minSelect) return;
    setSubmitted(true);
    onChoice(spec.options.filter((o) => selected.has(o)).join(', '));
  };

  return (
    <div
      data-testid="a2ui-multiselect-card"
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
          display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8,
        }}
      >
        {spec.options.map((opt, i) => {
          const isPick = selected.has(opt);
          const disabled = submitted || (!isPick && atMax);
          return (
            <button
              key={i}
              data-testid={'a2ui-ms-option-' + i}
              disabled={disabled}
              aria-pressed={isPick}
              onClick={() => toggle(opt)}
              style={{
                padding: '5px 12px', borderRadius: 4,
                border: `1px solid ${isPick ? AMBER : 'rgba(240, 176, 96, 0.3)'}`,
                background: isPick ? 'rgba(240, 176, 96, 0.18)' : 'transparent',
                color: isPick ? AMBER : (disabled ? DIM : '#e0dcd4'),
                fontFamily: "'Inter', system-ui, sans-serif",
                fontSize: 12,
                cursor: disabled ? 'default' : 'pointer',
                opacity: disabled && !isPick ? 0.55 : 1,
              }}
            >
              {opt}
            </button>
          );
        })}
      </div>
      <button
        data-testid="a2ui-ms-submit"
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
