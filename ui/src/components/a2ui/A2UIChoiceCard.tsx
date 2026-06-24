/**
 * AD-811a: interactive choice card rendered in place of an [A2UI] stub
 * inside ProfileChatTab message bodies.
 *
 * The agent's reply carried an ``[A2UI]{json}[/A2UI]`` block; the DM
 * pipeline stored the JSON as an ``application/json`` artifact and left an
 * inline stub:
 *
 *     [A2UI: a2ui-choice-1.json v1 - choice]
 *
 * This card resolves ``(threadId, name, version)`` against
 * ``useStore.artifactsByThread`` (mirroring ArtifactCard), fetches the
 * JSON via ``fetchArtifactContent``, parses it with ``parseChoiceSpec``,
 * and renders the prompt + one button per option. Clicking an option
 * calls ``onChoice(option)`` (ProfileChatTab posts it back through
 * ``sendText``) and locks the card (all buttons disabled, the pick
 * highlighted).
 */
import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../../store/useStore';
import { fetchArtifactContent } from '../artifacts/artifactApi';
import { parseChoiceSpec, type ParsedChoiceSpec } from './a2uiApi';

const AMBER = '#f0b060';
const DIM = '#888899';

export interface A2UIChoiceCardProps {
  /** The chat thread the message belongs to. */
  threadId: string;
  /** Parsed-from-stub artifact name. */
  name: string;
  /** Parsed-from-stub artifact version. */
  version: number;
  /** Called with the chosen option label when the Captain clicks. */
  onChoice: (option: string) => void;
}

export function A2UIChoiceCard(props: A2UIChoiceCardProps) {
  const { threadId, name, version, onChoice } = props;
  const artifactsByThread = useStore((s) => s.artifactsByThread);
  const [spec, setSpec] = useState<ParsedChoiceSpec | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);

  const resolved = useMemo(() => {
    const list = artifactsByThread.get(threadId) ?? [];
    return list.find((a) => a.name === name && a.version === version) ?? null;
  }, [artifactsByThread, threadId, name, version]);

  useEffect(() => {
    if (!resolved) return;
    let cancelled = false;
    fetchArtifactContent(resolved.id)
      .then(({ text }) => {
        if (!cancelled) setSpec(parseChoiceSpec(text));
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
        data-testid="a2ui-choice-card"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          margin: '4px 0', padding: '4px 8px',
          border: '1px solid rgba(255,255,255,0.1)', borderRadius: 4,
          background: 'rgba(240, 176, 96, 0.04)', color: DIM,
          fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
          cursor: 'wait', whiteSpace: 'nowrap',
        }}
      >
        Loading choice…
      </span>
    );
  }

  return (
    <div
      data-testid="a2ui-choice-card"
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
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {spec.options.map((opt, i) => {
          const isPick = chosen === opt;
          const disabled = chosen !== null;
          return (
            <button
              key={i}
              data-testid={'a2ui-option-' + i}
              disabled={disabled}
              onClick={() => {
                if (chosen !== null) return;
                setChosen(opt);
                onChoice(opt);
              }}
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
    </div>
  );
}
