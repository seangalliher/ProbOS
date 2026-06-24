/* AD-708f — "Connect a device" discovery card (#484)
 *
 * Surfaces the AD-708e `<hostname>.local` LAN address in the System view so the
 * Captain can read/copy it and point a phone at the HXI. PURE-UI: `/api/config`
 * already returns the full `SystemConfig.model_dump` (including the `discovery`
 * block) and `useSettingsStore.loadSnapshot()` already loads it; this card only
 * reads `discovery.{enabled,hostname}` from the store and builds the URL
 * client-side. It renders ONLY when `discovery.enabled` is true (progressive
 * disclosure, HXI #5) — invisible + byte-identical when off (the default).
 *
 * No backend change, no new endpoint, no new dependency. The QR-code affordance
 * is the deferred AD-708f-1. HXI #3: inline stroke-SVG glyphs only (no emoji),
 * amber/blue palette. The clipboard write is guarded (honest-degrade on an
 * insecure context / old browser — no throw).
 */

import { useState } from 'react';
import type { ReactElement } from 'react';
import { Check } from '../icons/Glyphs';
import { useSettingsStore } from '../../store/useSettingsStore';

const ACTIVE_AMBER = '#f0b060';
const DIM = '#666';

// ── Local stroke-SVG copy glyph (no shared Copy glyph exists; HXI #3) ──
function CopyGlyph(): ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="5" y="5" width="8" height="8" rx="1.5" />
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
    </svg>
  );
}

export default function ConnectPhoneCard(): ReactElement | null {
  // Mirror the App.tsx:96-97 selector idiom exactly.
  const enabled = useSettingsStore((s) => Boolean((s.snapshot?.config as any)?.discovery?.enabled));
  const hostname = useSettingsStore((s) => String((s.snapshot?.config as any)?.discovery?.hostname ?? 'probos'));
  const [copied, setCopied] = useState(false);

  // Progressive disclosure (HXI #5): invisible when discovery is off (the
  // default), keeping FullSystem byte-identical. All hooks run above this
  // early return.
  if (!enabled) return null;

  // http:// matches AD-708e's advertised scheme — a cert-less `.local` A record
  // is plain http. The port is read client-side from the live HXI origin.
  const port = window.location.port; // "" on 80/443
  const url = port ? `http://${hostname}.local:${port}` : `http://${hostname}.local`;

  const onCopy = async (): Promise<void> => {
    try {
      await navigator.clipboard?.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (insecure context / old browser) — log-and-degrade, no throw */
    }
  };

  return (
    <div data-testid="connect-phone-card" style={{ padding: '8px 0' }}>
      <div
        style={{
          fontSize: 10,
          textTransform: 'uppercase' as const,
          letterSpacing: 1,
          color: DIM,
          fontWeight: 600,
          marginBottom: 6,
          padding: '0 2px',
        }}
      >
        Connect a Device
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(80,144,208,0.2)',
          borderRadius: 6,
          padding: '10px 12px',
        }}
      >
        <span
          data-testid="connect-phone-url"
          style={{
            userSelect: 'text' as const,
            color: ACTIVE_AMBER,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 13,
            wordBreak: 'break-all' as const,
          }}
        >
          {url}
        </span>
        <button
          type="button"
          data-testid="connect-phone-copy"
          onClick={onCopy}
          aria-label="Copy address"
          style={{
            marginLeft: 'auto',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 26,
            height: 26,
            background: 'transparent',
            border: 'none',
            borderRadius: 4,
            color: ACTIVE_AMBER,
            cursor: 'pointer',
            padding: 0,
          }}
        >
          {copied ? <Check size={14} style={{ color: ACTIVE_AMBER }} /> : <CopyGlyph />}
        </button>
      </div>
      <div style={{ color: DIM, fontSize: 9, marginTop: 6, padding: '0 2px' }}>
        Requires the server bound to the LAN (--host 0.0.0.0).
      </div>
    </div>
  );
}
