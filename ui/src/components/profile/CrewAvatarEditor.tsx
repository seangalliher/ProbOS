/** AD-721a: Captain's Avatar Editor UI.
 *
 *  Mounted as an inline overlay from CrewAvatarPopout. Surfaces the
 *  AvatarDSL fields as form controls and routes edits through the
 *  AD-721d-3 preview endpoint -> SHA-256 ref -> popout VRM viewer. On
 *  Approve, PUT /api/agent/{id}/appearance persists the DSL.
 *
 *  Invariants:
 *  - Preview path is AD-721d-3 and does NOT consume AD-721d-1 Counselor
 *    revision iteration slots (the iteration counter lives on the
 *    /appearance/propose path; the /appearance/preview path is iteration-
 *    free by design).
 *  - DSL bytes flow through AttachmentStore SHA-256 refs (AD-731). The
 *    editor never inlines VRM bytes; it sets ``previewVrmUrl`` to
 *    ``/api/chat/attachments/{sha}`` which CrewVRM resolves via the
 *    attachment fetch path.
 *  - Honest-degrade: a 503 from /preview surfaces a banner; commit remains
 *    enabled so a hand-edited DSL can ship without a preview render.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AvatarDSLDict } from '../../store/types';

const BODY_TYPES = ['slim', 'average', 'stocky'] as const;
const HAIR_STYLES = ['short', 'medium', 'long', 'ponytail', 'bun', 'shaved'] as const;
const JAW_SHAPES = ['soft', 'neutral', 'strong'] as const;
const EYE_SHAPES = ['round', 'almond', 'narrow'] as const;
const OUTFIT_STYLES = ['uniform', 'casual', 'formal', 'robe', 'tactical'] as const;
const RESTING_EXPRESSIONS = ['neutral', 'gentle_smile', 'focused', 'alert'] as const;

const PREVIEW_DEBOUNCE_MS = 500;

/** Build a default DSL when the parent has none persisted yet. Mirrors
 *  ``AvatarDSL()`` defaults in src/probos/avatars/dsl.py. */
export function _defaultDsl(): AvatarDSLDict {
  return {
    body: { type: 'average', height_cm: 170 },
    hair: { style: 'medium', color_hsl: [30, 40, 30] },
    face: { warmth: 0.5, jaw: 'neutral', eyes: 'almond' },
    outfit: { style: 'uniform', primary_color: '#2a4a6a', accents: [] },
    expression_resting: 'neutral',
    notes: '',
  };
}

/** Convert an HSL triple to a CSS color string (used for hair preview swatch). */
function hslToCss(hsl: [number, number, number]): string {
  return `hsl(${hsl[0]}, ${hsl[1]}%, ${hsl[2]}%)`;
}

/** Convert a #rrggbb hex into [h, s, l] (0-360, 0-100, 0-100). */
export function _hexToHsl(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return [0, 0, 0];
  const v = parseInt(m[1], 16);
  const r = ((v >> 16) & 0xff) / 255;
  const g = ((v >> 8) & 0xff) / 255;
  const b = (v & 0xff) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
    else if (max === g) h = ((b - r) / d + 2) * 60;
    else h = ((r - g) / d + 4) * 60;
  }
  return [Math.round(h), Math.round(s * 100), Math.round(l * 100)];
}

/** Convert [h, s, l] back to a #rrggbb hex. */
export function _hslToHex(hsl: [number, number, number]): string {
  const [h, s, l] = [hsl[0] / 360, hsl[1] / 100, hsl[2] / 100];
  const hue2rgb = (p: number, q: number, t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  let r: number;
  let g: number;
  let b: number;
  if (s === 0) {
    r = g = b = l;
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }
  const toHex = (x: number) => Math.round(x * 255).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

export interface CrewAvatarEditorProps {
  agentId: string;
  /** Current DSL prop-passed from CrewAvatarPopout (AD-721a does NOT add a
   *  new GET /appearance endpoint; the popout already holds this). */
  currentDsl: AvatarDSLDict | null;
  /** Notify parent when the preview URL changes so it can swap CrewVRM. */
  onPreviewUrlChange: (url: string | null) => void;
  /** Called on successful PUT /appearance. */
  onApproved: () => void;
  /** Called when the editor is dismissed without a commit. */
  onCancelled: () => void;
}

interface PreviewState {
  status: 'idle' | 'in_flight' | 'ok' | 'unavailable' | 'invalid' | 'error';
  message: string | null;
  fieldErrors: Record<string, string>;
}

export function CrewAvatarEditor({
  agentId,
  currentDsl,
  onPreviewUrlChange,
  onApproved,
  onCancelled,
}: CrewAvatarEditorProps) {
  const initial = useMemo<AvatarDSLDict>(
    () => currentDsl ?? _defaultDsl(),
    [currentDsl],
  );
  const [dsl, setDsl] = useState<AvatarDSLDict>(initial);
  const [preview, setPreview] = useState<PreviewState>({
    status: 'idle',
    message: null,
    fieldErrors: {},
  });
  const [committing, setCommitting] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Debounced preview fetch. Cancellable via the in-flight token check
   *  so a faster edit invalidates a slower preview response. */
  const fetchPreview = useCallback(
    async (next: AvatarDSLDict, token: number) => {
      setPreview((prev) => ({ ...prev, status: 'in_flight', message: null }));
      try {
        const r = await fetch(`/api/agent/${agentId}/appearance/preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dsl: next }),
        });
        if (tokenRef.current !== token) return;
        if (r.status === 503) {
          setPreview({
            status: 'unavailable',
            message: 'Preview unavailable; commit will apply without preview.',
            fieldErrors: {},
          });
          onPreviewUrlChange(null);
          return;
        }
        if (r.status === 422) {
          let fieldErrors: Record<string, string> = {};
          let msg = 'Validation error';
          try {
            const body = await r.json();
            if (body?.detail?.reason) msg = String(body.detail.reason);
            if (body?.detail?.field_errors && typeof body.detail.field_errors === 'object') {
              fieldErrors = body.detail.field_errors;
            }
          } catch { /* swallow -- best-effort */ }
          setPreview({ status: 'invalid', message: msg, fieldErrors });
          onPreviewUrlChange(null);
          return;
        }
        if (!r.ok) {
          setPreview({
            status: 'error',
            message: `Preview failed (HTTP ${r.status})`,
            fieldErrors: {},
          });
          onPreviewUrlChange(null);
          return;
        }
        const data = await r.json();
        if (data && typeof data.attachment_id === 'string') {
          // AD-731 invariant: the editor consumes a SHA-256 ref; bytes
          // flow through AttachmentStore, not inlined in this message.
          onPreviewUrlChange(`/api/chat/attachments/${data.attachment_id}`);
          setPreview({ status: 'ok', message: null, fieldErrors: {} });
        } else {
          setPreview({
            status: 'error',
            message: 'Preview returned no attachment_id',
            fieldErrors: {},
          });
          onPreviewUrlChange(null);
        }
      } catch (e: any) {
        if (tokenRef.current !== token) return;
        setPreview({
          status: 'error',
          message: String(e?.message || e),
          fieldErrors: {},
        });
        onPreviewUrlChange(null);
      }
    },
    [agentId, onPreviewUrlChange],
  );

  // Token-based cancellation: every dispatch increments tokenRef; only the
  // latest dispatch's response is allowed to write to preview state.
  const tokenRef = useRef(0);

  const scheduleDebouncedPreview = useCallback(
    (next: AvatarDSLDict) => {
      tokenRef.current += 1;
      const token = tokenRef.current;
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
      }
      debounceRef.current = setTimeout(() => {
        debounceRef.current = null;
        void fetchPreview(next, token);
      }, PREVIEW_DEBOUNCE_MS);
    },
    [fetchPreview],
  );

  // Cleanup on unmount: cancel any pending debounce and clear preview URL.
  useEffect(() => {
    return () => {
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
      tokenRef.current += 1;
    };
  }, []);

  const updateDsl = useCallback(
    (mutator: (prev: AvatarDSLDict) => AvatarDSLDict) => {
      setDsl((prev) => {
        const next = mutator(prev);
        scheduleDebouncedPreview(next);
        return next;
      });
    },
    [scheduleDebouncedPreview],
  );

  const handleApprove = useCallback(async () => {
    if (committing) return;
    setCommitting(true);
    try {
      const r = await fetch(`/api/agent/${agentId}/appearance`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dsl }),
      });
      if (!r.ok) {
        setPreview({
          status: 'error',
          message: `Commit failed (HTTP ${r.status})`,
          fieldErrors: {},
        });
        return;
      }
      onPreviewUrlChange(null);
      onApproved();
    } catch (e: any) {
      setPreview({
        status: 'error',
        message: String(e?.message || e),
        fieldErrors: {},
      });
    } finally {
      setCommitting(false);
    }
  }, [agentId, dsl, committing, onApproved, onPreviewUrlChange]);

  const handleCancel = useCallback(() => {
    onPreviewUrlChange(null);
    onCancelled();
  }, [onCancelled, onPreviewUrlChange]);

  const fieldError = (path: string): string | undefined => preview.fieldErrors[path];
  const hairHexValue = _hslToHex(dsl.hair.color_hsl);

  return (
    <div
      data-testid="crew-avatar-editor"
      role="form"
      aria-label={`Edit appearance for ${agentId}`}
      style={{
        flex: '1 1 auto',
        padding: '8px 10px',
        background: 'rgba(10, 12, 24, 0.92)',
        borderTop: '1px solid rgba(96, 144, 240, 0.25)',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        fontSize: 11,
        fontFamily: "'JetBrains Mono', monospace",
        color: '#ccccd8',
        overflowY: 'auto',
      }}
    >
      <div style={{ color: '#6090f0', fontSize: 10, letterSpacing: 0.5 }}>
        EDIT APPEARANCE - {agentId}
      </div>

      {preview.status === 'unavailable' && (
        <div
          data-testid="preview-banner"
          data-status="unavailable"
          style={{ color: '#f0b060', fontSize: 10 }}
        >
          {preview.message}
        </div>
      )}
      {preview.status === 'error' && preview.message && (
        <div
          data-testid="preview-banner"
          data-status="error"
          style={{ color: '#f06070', fontSize: 10 }}
        >
          {preview.message}
        </div>
      )}

      {/* Body */}
      <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: '#8888a0', width: 70 }}>body type</span>
        <select
          data-testid="field-body-type"
          value={dsl.body.type}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              body: { ...prev.body, type: e.target.value as AvatarDSLDict['body']['type'] },
            }))
          }
        >
          {BODY_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        {fieldError('body.type') && (
          <span data-testid="field-error-body-type" style={{ color: '#f06070' }}>
            {fieldError('body.type')}
          </span>
        )}
      </label>

      <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: '#8888a0', width: 70 }}>height cm</span>
        <input
          data-testid="field-body-height"
          type="number"
          min={140}
          max={210}
          value={dsl.body.height_cm}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              body: { ...prev.body, height_cm: parseInt(e.target.value, 10) || prev.body.height_cm },
            }))
          }
          style={{ width: 64 }}
        />
      </label>

      {/* Hair */}
      <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: '#8888a0', width: 70 }}>hair</span>
        <select
          data-testid="field-hair-style"
          value={dsl.hair.style}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              hair: { ...prev.hair, style: e.target.value as AvatarDSLDict['hair']['style'] },
            }))
          }
        >
          {HAIR_STYLES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <input
          data-testid="field-hair-color"
          type="color"
          value={hairHexValue}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              hair: { ...prev.hair, color_hsl: _hexToHsl(e.target.value) },
            }))
          }
          aria-label="hair color"
        />
        <svg width="12" height="12" aria-label="hair color preview">
          <rect width="12" height="12" rx="2" fill={hslToCss(dsl.hair.color_hsl)} />
        </svg>
      </label>

      {/* Face */}
      <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: '#8888a0', width: 70 }}>warmth</span>
        <input
          data-testid="field-face-warmth"
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={dsl.face.warmth}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              face: { ...prev.face, warmth: parseFloat(e.target.value) },
            }))
          }
        />
        <span style={{ color: '#666680', width: 28 }}>{dsl.face.warmth.toFixed(2)}</span>
      </label>

      <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: '#8888a0', width: 70 }}>jaw</span>
        <select
          data-testid="field-face-jaw"
          value={dsl.face.jaw}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              face: { ...prev.face, jaw: e.target.value as AvatarDSLDict['face']['jaw'] },
            }))
          }
        >
          {JAW_SHAPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <span style={{ color: '#8888a0', width: 36, marginLeft: 6 }}>eyes</span>
        <select
          data-testid="field-face-eyes"
          value={dsl.face.eyes}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              face: { ...prev.face, eyes: e.target.value as AvatarDSLDict['face']['eyes'] },
            }))
          }
        >
          {EYE_SHAPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </label>

      {/* Outfit */}
      <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: '#8888a0', width: 70 }}>outfit</span>
        <select
          data-testid="field-outfit-style"
          value={dsl.outfit.style}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              outfit: { ...prev.outfit, style: e.target.value as AvatarDSLDict['outfit']['style'] },
            }))
          }
        >
          {OUTFIT_STYLES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <input
          data-testid="field-outfit-color"
          type="color"
          value={dsl.outfit.primary_color}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              outfit: { ...prev.outfit, primary_color: e.target.value },
            }))
          }
          aria-label="outfit color"
        />
      </label>

      {/* Expression */}
      <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: '#8888a0', width: 70 }}>resting</span>
        <select
          data-testid="field-expression-resting"
          value={dsl.expression_resting}
          onChange={(e) =>
            updateDsl((prev) => ({
              ...prev,
              expression_resting: e.target.value as AvatarDSLDict['expression_resting'],
            }))
          }
        >
          {RESTING_EXPRESSIONS.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </label>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
        <button
          data-testid="editor-approve"
          type="button"
          disabled={committing}
          onClick={handleApprove}
          style={{
            background: 'rgba(96, 240, 144, 0.18)',
            color: '#90f0b0',
            border: '1px solid rgba(96, 240, 144, 0.4)',
            padding: '4px 10px',
            cursor: committing ? 'wait' : 'pointer',
          }}
        >
          Approve
        </button>
        <button
          data-testid="editor-cancel"
          type="button"
          onClick={handleCancel}
          style={{
            background: 'rgba(240, 96, 96, 0.12)',
            color: '#f06070',
            border: '1px solid rgba(240, 96, 96, 0.3)',
            padding: '4px 10px',
            cursor: 'pointer',
          }}
        >
          Cancel
        </button>
        {preview.status === 'in_flight' && (
          <span data-testid="preview-spinner" style={{ color: '#6090f0', fontSize: 10 }}>
            previewing...
          </span>
        )}
      </div>
    </div>
  );
}
