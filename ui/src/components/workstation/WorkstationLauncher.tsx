/**
 * AD-1022: WorkstationLauncher — lists the available workstation types from
 * GET /api/workstations/types and opens one.
 *
 * Tiered render seam (DD-3): a `native` type renders an OSS-shipped React
 * component keyed by id (monaco/browser/chat land in their own ADs — until then
 * the launcher honest-degrades to a "not yet available" placeholder). An
 * `iframe` type renders through the already-built sandboxed McpAppFrame
 * (AD-597a, external=true) — the OSS bundle never imports commercial React.
 *
 * Deps-injectable (HXI convention, mirrors ShipsLockerPanel) so tests need no
 * global fetch mock. HXI-compliant: stroke-SVG glyphs, no emoji.
 */
import { useEffect, useState, type ComponentType } from 'react';
import { McpAppFrame } from '../McpAppFrame';
import type { WorkstationDoc } from '../../store/types';

export interface WorkstationTypeView {
  id: string;
  label: string;
  tier: string;
  available: boolean;
  render_kind: string;
}

interface WorkstationTypesResponse {
  types: WorkstationTypeView[];
}

export interface NativeWorkstationProps {
  typeId: string;
  doc?: WorkstationDoc | null;  // AD-1023: per-workstation doc (container host); store fallback when undefined
}

export interface WorkstationLauncherDeps {
  /** Fetch the available workstation types. Defaults to the real endpoint. */
  fetchTypes: () => Promise<WorkstationTypeView[]>;
  /** Sandboxed iframe renderer for `kind:"iframe"` types. Defaults to McpAppFrame. */
  IframeFrame: typeof McpAppFrame;
  /** Map of native id -> OSS React component. Empty until monaco/browser/chat land. */
  nativeComponents: Record<string, ComponentType<NativeWorkstationProps>>;
}

export const DEFAULT_FETCH_TYPES = async (): Promise<WorkstationTypeView[]> => {
  const r = await fetch('/api/workstations/types');
  if (!r.ok) return [];
  const json = (await r.json()) as WorkstationTypesResponse;
  return json.types ?? [];
};

const glyphStyle = {
  width: 14,
  height: 14,
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  fill: 'none',
};

function WorkstationGlyph({ kind }: { kind: string }) {
  // Stroke-only SVG glyph (HXI #3: no emoji). A framed window for native, a
  // nested frame for iframe.
  return (
    <svg viewBox="0 0 16 16" style={glyphStyle} stroke="currentColor" aria-hidden="true">
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      {kind === 'iframe' ? <rect x="5" y="6" width="6" height="4" rx="0.5" /> : <path d="M2 6h12" />}
    </svg>
  );
}

export function WorkstationRender({
  type,
  deps,
  doc,
}: {
  type: WorkstationTypeView;
  deps: WorkstationLauncherDeps;
  doc?: WorkstationDoc | null;
}) {
  if (type.render_kind === 'native') {
    const Native = deps.nativeComponents[type.id];
    if (Native) {
      return (
        <div data-testid="workstation-native">
          <Native typeId={type.id} doc={doc} />
        </div>
      );
    }
    return (
      <div
        data-testid="workstation-unavailable"
        style={{ padding: 16, color: '#666680', fontSize: 12 }}
      >
        {type.label} workstation is not yet available.
      </div>
    );
  }
  if (type.render_kind === 'iframe') {
    const Frame = deps.IframeFrame;
    return (
      <div data-testid="workstation-iframe" style={{ width: '100%', height: '100%' }}>
        <Frame resourceUri={type.id} toolName={type.id} external />
      </div>
    );
  }
  return (
    <div data-testid="workstation-unsupported" style={{ padding: 16, color: '#666680' }}>
      Unsupported workstation type.
    </div>
  );
}

export function WorkstationLauncher({
  deps,
}: {
  deps?: Partial<WorkstationLauncherDeps>;
}) {
  const merged: WorkstationLauncherDeps = {
    fetchTypes: deps?.fetchTypes ?? DEFAULT_FETCH_TYPES,
    IframeFrame: deps?.IframeFrame ?? McpAppFrame,
    nativeComponents: deps?.nativeComponents ?? {},
  };

  const [types, setTypes] = useState<WorkstationTypeView[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await merged.fetchTypes();
        if (!cancelled) setTypes(list);
      } catch {
        // Network errors honest-degrade to an empty catalog.
        if (!cancelled) setTypes([]);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (types === null) {
    return (
      <div data-testid="workstation-launcher-loading" style={{ padding: 16, color: '#666680' }}>
        Loading workstations…
      </div>
    );
  }

  const available = types.filter((t) => t.available);
  const opened = available.find((t) => t.id === openId) ?? null;

  return (
    <div data-testid="workstation-launcher" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        data-testid="workstation-list"
        style={{ display: 'flex', gap: 6, padding: 8, flexWrap: 'wrap' }}
      >
        {available.length === 0 ? (
          <div data-testid="workstation-empty" style={{ color: '#666680', fontSize: 12 }}>
            No workstations available.
          </div>
        ) : (
          available.map((t) => {
            const active = t.id === openId;
            return (
              <button
                key={t.id}
                type="button"
                data-testid={`workstation-type-${t.id}`}
                onClick={() => setOpenId(t.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '4px 10px',
                  border: `1px solid ${active ? '#f0b060' : '#33334a'}`,
                  borderRadius: 4,
                  background: 'transparent',
                  color: active ? '#f0b060' : '#aaaac0',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                <WorkstationGlyph kind={t.render_kind} />
                <span>{t.label}</span>
                <span
                  data-testid={`workstation-tier-${t.id}`}
                  style={{ fontSize: 8, letterSpacing: 1, color: '#666680' }}
                >
                  {t.tier.toUpperCase()}
                </span>
              </button>
            );
          })
        )}
      </div>
      {opened && (
        <div data-testid="workstation-open" style={{ flex: 1, minHeight: 0 }}>
          <WorkstationRender type={opened} deps={merged} />
        </div>
      )}
    </div>
  );
}

export default WorkstationLauncher;
