/**
 * AD-797 (Wave 197): viewer panel — fetches content + renders by mime,
 * surfaces Copy / Save / Pin-to-project actions in the toolbar.
 *
 * Render branches:
 *   text/markdown                                 → react-markdown
 *   text/x-* / application/{json,sql,yaml}        → <pre><code> (no syntax highlight, AD-797d forward)
 *   image/*                                       → <img src="/api/artifacts/{id}/content">
 *   text/uri-list                                 → fetch body → parse → <img>
 *   text/plain / default                          → <pre> wrap
 *
 * NO Monaco / NO Prism in v1 — both are forward markers.
 */
import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import type { ArtifactView } from '../../store/useStore';
import { useStore } from '../../store/useStore';
import { fetchArtifactContent, pinArtifactToProject } from './artifactApi';

const AMBER = '#f0b060';
const DIM = '#888899';

interface ContentState {
  status: 'idle' | 'loading' | 'ready' | 'error';
  text: string;
  blob: Blob | null;
  imageUrl: string | null;
  mime: string;
  error: string | null;
}

const EMPTY_STATE: ContentState = {
  status: 'idle', text: '', blob: null, imageUrl: null, mime: '', error: null,
};

export interface ArtifactViewerProps {
  artifact: ArtifactView;
  versions: ArtifactView[];
  onSelectVersion: (id: string) => void;
  projectIdForPinning: string | null;
}

export function ArtifactViewer(props: ArtifactViewerProps) {
  const { artifact, versions, onSelectVersion, projectIdForPinning } = props;
  const [content, setContent] = useState<ContentState>(EMPTY_STATE);
  const [toast, setToast] = useState<string>('');

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    setContent({ ...EMPTY_STATE, status: 'loading' });

    (async () => {
      try {
        const { blob, text, mime } = await fetchArtifactContent(artifact.id);
        if (cancelled) return;
        if (mime.startsWith('image/')) {
          const url = URL.createObjectURL(blob);
          revoked = url;
          setContent({
            status: 'ready', text: '', blob, imageUrl: url, mime, error: null,
          });
          return;
        }
        if (mime.startsWith('text/uri-list')) {
          // Body is the URL — parse, render <img>.
          const urlText = text.split('\n').find((l) => l.trim() && !l.startsWith('#')) || '';
          setContent({
            status: 'ready', text: urlText, blob, imageUrl: urlText, mime,
            error: null,
          });
          return;
        }
        setContent({
          status: 'ready', text, blob, imageUrl: null, mime, error: null,
        });
      } catch (e) {
        if (cancelled) return;
        setContent({
          status: 'error', text: '', blob: null, imageUrl: null, mime: '',
          error: String(e),
        });
      }
    })();

    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [artifact.id]);

  const isImage = content.mime.startsWith('image/') ||
    content.mime.startsWith('text/uri-list');

  const onCopy = async () => {
    if (isImage) return;
    try {
      await navigator.clipboard.writeText(content.text);
      setToast(`Copied ${artifact.name}`);
      window.setTimeout(() => setToast(''), 1500);
    } catch {
      setToast('Copy failed');
      window.setTimeout(() => setToast(''), 1500);
    }
  };

  const onSave = () => {
    if (!content.blob) return;
    const url = URL.createObjectURL(content.blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = artifact.name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const onPin = async () => {
    if (!projectIdForPinning) return;
    try {
      await pinArtifactToProject(projectIdForPinning, artifact.content_hash);
      setToast(`Pinned ${artifact.name}`);
      window.setTimeout(() => setToast(''), 1500);
      // Re-fetch so the row picks up _pinned_from_project flag in this thread.
      const { hydrateArtifacts } = useStore.getState();
      try {
        const { fetchThreadArtifacts } = await import('./artifactApi');
        const list = await fetchThreadArtifacts(artifact.thread_id);
        hydrateArtifacts(artifact.thread_id, list);
      } catch {/* ignore */}
    } catch {
      setToast('Pin failed');
      window.setTimeout(() => setToast(''), 1500);
    }
  };

  const renderBody = useMemo(() => {
    if (content.status === 'loading') {
      return <div style={{ color: DIM, fontSize: 11 }}>Loading…</div>;
    }
    if (content.status === 'error') {
      return (
        <div style={{ color: '#cc6677', fontSize: 11 }}>
          Failed to load: {content.error}
        </div>
      );
    }
    if (content.status !== 'ready') return null;
    const m = content.mime;
    if (m.startsWith('image/')) {
      return (
        <img
          src={content.imageUrl ?? ''}
          alt={artifact.name}
          data-testid="artifact-image"
          style={{ maxWidth: '100%', maxHeight: '100%' }}
        />
      );
    }
    if (m.startsWith('text/uri-list')) {
      return (
        <img
          src={content.imageUrl ?? ''}
          alt={artifact.name}
          data-testid="artifact-image"
          style={{ maxWidth: '100%', maxHeight: '100%' }}
        />
      );
    }
    if (m === 'text/markdown') {
      return (
        <div data-testid="artifact-markdown" style={{ fontSize: 12 }}>
          <ReactMarkdown>{content.text}</ReactMarkdown>
        </div>
      );
    }
    if (
      m.startsWith('text/x-') ||
      m === 'application/json' ||
      m === 'application/yaml' ||
      m === 'application/sql'
    ) {
      return (
        <pre data-testid="artifact-code" style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11, lineHeight: 1.4, margin: 0,
          whiteSpace: 'pre', overflow: 'auto',
        }}>
          <code>{content.text}</code>
        </pre>
      );
    }
    return (
      <pre data-testid="artifact-plain" style={{
        fontFamily: 'inherit', fontSize: 12,
        whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
      }}>
        {content.text}
      </pre>
    );
  }, [content, artifact.name]);

  return (
    <div
      data-testid="artifact-viewer"
      style={{
        display: 'flex', flexDirection: 'column',
        flex: '1 1 auto', minHeight: 0,
        borderTop: '1px solid rgba(240, 176, 96, 0.15)',
      }}
    >
      <div
        style={{
          flex: '0 0 auto', display: 'flex', alignItems: 'center',
          gap: 6, padding: '6px 8px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
        }}
      >
        <span style={{
          flex: '1 1 auto', minWidth: 0, overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontSize: 12, color: '#e0dcd4', fontWeight: 600,
        }}>{artifact.name}</span>
        {versions.length > 1 ? (
          <select
            value={artifact.id}
            onChange={(e) => onSelectVersion(e.target.value)}
            data-testid="artifact-version-selector"
            style={{
              background: 'transparent', color: AMBER, fontSize: 10,
              border: '1px solid rgba(240, 176, 96, 0.3)', borderRadius: 3,
              padding: '0 4px',
            }}
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>v{v.version}</option>
            ))}
          </select>
        ) : (
          <span style={{
            fontSize: 10, color: AMBER,
            border: '1px solid rgba(240, 176, 96, 0.3)',
            borderRadius: 3, padding: '0 4px',
          }}>v{artifact.version}</span>
        )}
        <button
          type="button" onClick={onCopy}
          disabled={isImage}
          data-testid="artifact-copy"
          title={isImage ? 'Copy not supported for images' : 'Copy to clipboard'}
          style={toolbarBtnStyle(isImage)}
        >COPY</button>
        <button
          type="button" onClick={onSave}
          data-testid="artifact-save"
          title="Save to file"
          style={toolbarBtnStyle(false)}
        >SAVE</button>
        {projectIdForPinning && (
          <button
            type="button" onClick={onPin}
            data-testid="artifact-pin"
            title="Pin to project"
            style={toolbarBtnStyle(false)}
          >PIN</button>
        )}
      </div>
      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'auto', padding: 8 }}>
        {renderBody}
      </div>
      {toast && (
        <div
          data-testid="artifact-toast"
          style={{
            position: 'absolute', bottom: 12, right: 12,
            background: 'rgba(0, 0, 0, 0.85)', color: AMBER,
            padding: '4px 8px', borderRadius: 4, fontSize: 10,
            border: '1px solid rgba(240, 176, 96, 0.3)',
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}

function toolbarBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    background: 'transparent',
    border: '1px solid rgba(240, 176, 96, 0.3)',
    color: disabled ? DIM : AMBER,
    fontFamily: 'inherit', fontSize: 9, letterSpacing: 1,
    padding: '2px 6px', borderRadius: 3,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
  };
}
