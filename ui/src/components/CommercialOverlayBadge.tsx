/**
 * AD-697-1: HXI badge surfacing commercial overlay status.
 *
 * Reads /api/system/extensions on mount + every 30s. When
 * commercial_loaded=true, renders a small chip in the TopNav showing
 * the loaded provider names. Pure UI — no commercial logic.
 */
import { useEffect, useState } from 'react';

interface ExtensionsResponse {
  commercial_loaded: boolean;
  providers: string[];
  hooks: string[];
  pre_intent_auth_hooks: string[];
}

const POLL_INTERVAL_MS = 30000;

export default function CommercialOverlayBadge() {
  const [data, setData] = useState<ExtensionsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    async function fetchOnce() {
      try {
        const r = await fetch('/api/system/extensions');
        if (!r.ok) return;
        const json = (await r.json()) as ExtensionsResponse;
        if (!cancelled) setData(json);
      } catch {
        // network errors are silent — badge just hides
      }
    }

    void fetchOnce();
    timer = window.setInterval(() => void fetchOnce(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearInterval(timer);
    };
  }, []);

  if (!data || !data.commercial_loaded || data.providers.length === 0) {
    return null;
  }

  const label = data.providers.join(', ');

  return (
    <div
      data-testid="commercial-overlay-badge"
      title={`Overlay providers: ${label}\nFinalize hooks: ${data.hooks.length}\nIntent-auth hooks: ${data.pre_intent_auth_hooks.length}`}
      style={{
        padding: '3px 8px',
        border: '1px solid rgba(86, 192, 134, 0.35)',
        borderRadius: 4,
        fontSize: 8,
        letterSpacing: 1.5,
        fontFamily: "'JetBrains Mono', monospace",
        color: '#56c086',
        background: 'rgba(86, 192, 134, 0.08)',
        boxShadow: '0 0 8px rgba(86, 192, 134, 0.20)',
        userSelect: 'none',
      }}
    >
      OVERLAY · {label.toUpperCase()}
    </div>
  );
}
