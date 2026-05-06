# AD-473 v1 — Mobile PWA (HXI Installable Shell)

**Status:** Ready to build (Wave 85)
**Dependencies:** none (UI-only; HEAD `05989c3` is greenfield for `ui/public/`, `ui/src/pwa/`, `ui/src/components/InstallPrompt.tsx`)
**Estimated tests:** +14 vitest, ±0 pytest
**Closes:** GH #67

## Problem

The HXI is a Vite-built React + Three.js single-page app served at `/ui/`. It is not currently installable as a Progressive Web App. iOS Safari and Android Chrome users cannot add it to their home screen as a standalone app, and there is no offline app-shell — a transient WebSocket disconnect during boot leaves the user staring at an empty page until the network returns.

Roadmap line 1544 calls this out as the literal Phase 1 of AD-473: *"the existing HXI (`/ui/`) made installable as a PWA. Add `manifest.json`, service worker, responsive viewport. Zero new code for basic mobile access."*

This prompt ships exactly that — a hand-rolled, dependency-free PWA scaffold that turns the HXI into an installable, offline-tolerant app on iOS and Android with no UX guesses about the responsive layout (HXI principle #1 forbids guessing).

## Solution

Add three small surfaces to the existing UI:

1. A **Web App Manifest** (`ui/public/manifest.webmanifest`) declaring the app's identity, icons, and standalone display mode.
2. A **service worker** (`ui/public/sw.js`) that caches the app-shell on `install` and serves it from cache on `fetch` when the network is unavailable. Hand-rolled, ~50 LOC, no Workbox.
3. A **registration helper** (`ui/src/pwa/register.ts`) and **install-prompt component** (`ui/src/components/InstallPrompt.tsx`) that wire the SW into the app and surface a `beforeinstallprompt`-aware install button matching HXI design principles #2 (organic but digitally authentic) and #3 (no emoji — stroke-based SVG glyphs only).

Plus four `<head>` edits in `index.html` and one import + one call + one component render in `main.tsx`.

Out of scope: Web Push (AD-473d), responsive HXI mobile layout (AD-473e), mDNS auto-discovery (AD-473f), native-app wrappers (AD-473g). See WAVE-85-DISPATCH.md for the parked-items rationale and forcing functions.

---

### Section 1 — Web App Manifest (AD-473a)

Create `ui/public/manifest.webmanifest`:

```json
{
  "name": "ProbOS HXI",
  "short_name": "ProbOS",
  "description": "Probabilistic agent-native OS — Human Experience Interface",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "orientation": "any",
  "theme_color": "#0a0a12",
  "background_color": "#0a0a12",
  "icons": [
    {
      "src": "/icons/icon-192.svg",
      "sizes": "192x192",
      "type": "image/svg+xml",
      "purpose": "any"
    },
    {
      "src": "/icons/icon-512.svg",
      "sizes": "512x512",
      "type": "image/svg+xml",
      "purpose": "any"
    },
    {
      "src": "/icons/icon-512.svg",
      "sizes": "512x512",
      "type": "image/svg+xml",
      "purpose": "maskable"
    }
  ]
}
```

The `theme_color` and `background_color` match `ui/index.html:13` (`background: #0a0a12`) — verified.

`"display": "standalone"` and `"orientation": "any"` keep the door open for AD-473e (responsive HXI) without painting the team into a corner.

### Section 2 — App icons (AD-473a)

Create two stroke-based SVG icons matching HXI principle #3 (no emoji, no fills, geometric). Both use `strokeWidth="1.5"`, `strokeLinecap="round"` and the amber-on-dark palette (`#f0b060` glyph, `#0a0a12` background) from the existing HXI iconography (e.g., `ui/src/components/work/WorkBoard.tsx:374` `<Warning size={10} />` style — but inline rather than an icon library, since none is in `package.json`).

Create `ui/public/icons/icon-192.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192" width="192" height="192">
  <rect width="192" height="192" fill="#0a0a12"/>
  <circle cx="96" cy="96" r="56" fill="none" stroke="#f0b060" stroke-width="3" stroke-linecap="round"/>
  <circle cx="96" cy="96" r="28" fill="none" stroke="#f0b060" stroke-width="3" stroke-linecap="round"/>
  <line x1="96" y1="40" x2="96" y2="68" stroke="#f0b060" stroke-width="3" stroke-linecap="round"/>
  <line x1="96" y1="124" x2="96" y2="152" stroke="#f0b060" stroke-width="3" stroke-linecap="round"/>
  <line x1="40" y1="96" x2="68" y2="96" stroke="#f0b060" stroke-width="3" stroke-linecap="round"/>
  <line x1="124" y1="96" x2="152" y2="96" stroke="#f0b060" stroke-width="3" stroke-linecap="round"/>
</svg>
```

Create `ui/public/icons/icon-512.svg` (same glyph, scaled):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <rect width="512" height="512" fill="#0a0a12"/>
  <circle cx="256" cy="256" r="150" fill="none" stroke="#f0b060" stroke-width="8" stroke-linecap="round"/>
  <circle cx="256" cy="256" r="75" fill="none" stroke="#f0b060" stroke-width="8" stroke-linecap="round"/>
  <line x1="256" y1="106" x2="256" y2="181" stroke="#f0b060" stroke-width="8" stroke-linecap="round"/>
  <line x1="256" y1="331" x2="256" y2="406" stroke="#f0b060" stroke-width="8" stroke-linecap="round"/>
  <line x1="106" y1="256" x2="181" y2="256" stroke="#f0b060" stroke-width="8" stroke-linecap="round"/>
  <line x1="331" y1="256" x2="406" y2="256" stroke="#f0b060" stroke-width="8" stroke-linecap="round"/>
</svg>
```

Two concentric rings + four cardinal lines = a simple, alien-but-familiar mark consistent with HXI design principle #2 (bioluminescent / digital). Builder may polish, but the principles are non-negotiable: geometric, stroke-based, amber/blue/violet only.

### Section 3 — Service worker (AD-473b)

Create `ui/public/sw.js`. Hand-rolled, no Workbox, no `vite-plugin-pwa`. Versioned cache key for clean upgrades.

```javascript
// ProbOS HXI — Service Worker (AD-473b)
//
// App-shell caching strategy:
//   - install: pre-cache the app shell (HTML + manifest + icons).
//   - fetch:  cache-first for app-shell URLs, network-first for /api/* and /ws.
//   - activate: drop stale cache versions.
//
// AD-473d (future): Web Push event handler (`push`, `notificationclick`) lands here.

const CACHE_VERSION = 'probos-hxi-v1';
const APP_SHELL = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/icons/icon-192.svg',
  '/icons/icon-512.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never cache API or WebSocket traffic.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) {
    return;
  }

  // App-shell: cache-first, fall back to network, fall back to cached '/'.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).catch(() => caches.match('/'));
    })
  );
});
```

LOC: 38 (under the 50-LOC ceiling). Plain JS, no TypeScript — vitest does not run service workers; the SW is exercised at runtime in the browser only.

### Section 4 — Registration helper (AD-473c)

Create `ui/src/pwa/register.ts`:

```typescript
/**
 * ProbOS HXI — Service Worker registration helper (AD-473c).
 *
 * Returns `null` on unsupported browsers (no throw). Caller in `main.tsx`
 * does NOT await this — registration happens asynchronously after first paint.
 */
export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
    return null;
  }

  try {
    const registration = await navigator.serviceWorker.register('/sw.js');
    // AD-473d: Web Push integration point — `registration.pushManager.subscribe(...)` lands here.
    return registration;
  } catch (err) {
    // Tier 2: log-and-degrade. PWA install failure must not break the HXI.
    // eslint-disable-next-line no-console
    console.warn('Service worker registration failed; HXI will run online-only', err);
    return null;
  }
}
```

LOC: 18. Returns `Promise<ServiceWorkerRegistration | null>`. Three-tier exception handling: tier 2 (log-and-degrade) — PWA failure must never crash the HXI.

### Section 5 — InstallPrompt component (AD-473c)

Create `ui/src/components/InstallPrompt.tsx`:

```typescript
/**
 * ProbOS HXI — Install Prompt (AD-473c).
 *
 * Listens for `beforeinstallprompt`, surfaces a stroke-based SVG install
 * button matching HXI principle #3 (no emoji), and dismisses on
 * `appinstalled` or user dismissal. Does NOT auto-render — appears only
 * after `beforeinstallprompt` fires (HXI principle #5: progressive
 * disclosure driven by engagement).
 */
import { useEffect, useState } from 'react';

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

export function InstallPrompt() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setDeferred(null);
      setDismissed(true);
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  if (dismissed || deferred === null) return null;

  const handleInstall = async () => {
    await deferred.prompt();
    const choice = await deferred.userChoice;
    if (choice.outcome !== 'accepted') {
      setDismissed(true);
    }
    setDeferred(null);
  };

  const handleDismiss = () => {
    setDismissed(true);
    setDeferred(null);
  };

  return (
    <div
      data-testid="install-prompt"
      style={{
        position: 'fixed',
        bottom: 16,
        right: 16,
        zIndex: 30,
        display: 'flex',
        gap: 8,
        padding: '8px 12px',
        background: 'rgba(10, 10, 18, 0.85)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid #f0b060',
        borderRadius: 4,
        color: '#e0dcd4',
        fontFamily: 'Inter, sans-serif',
        fontSize: 12,
      }}
    >
      <button
        data-testid="install-prompt-install"
        onClick={handleInstall}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 10px',
          background: 'transparent',
          border: '1px solid #f0b060',
          borderRadius: 2,
          color: '#f0b060',
          cursor: 'pointer',
          font: 'inherit',
        }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path d="M6 1 V8 M3 5 L6 8 L9 5 M2 10 H10" stroke="#f0b060" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        Install ProbOS
      </button>
      <button
        data-testid="install-prompt-dismiss"
        onClick={handleDismiss}
        aria-label="Dismiss"
        style={{
          padding: '4px 8px',
          background: 'transparent',
          border: '1px solid #666680',
          borderRadius: 2,
          color: '#666680',
          cursor: 'pointer',
          font: 'inherit',
        }}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M2 2 L8 8 M8 2 L2 8" stroke="#666680" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </button>
    </div>
  );
}
```

LOC: ~95. HXI principle #3 honored: zero emoji, all glyphs are inline SVG with `strokeWidth="1.5"` and `strokeLinecap="round"`. HXI principle #5 honored: component renders nothing until `beforeinstallprompt` fires.

### Section 6 — Wire-up in `main.tsx`

Modify `ui/src/main.tsx`:

```
===SEARCH===
/* ProbOS HXI — Entry point (AD-255) */

import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(<App />);
===REPLACE===
/* ProbOS HXI — Entry point (AD-255, AD-473c) */

import { createRoot } from 'react-dom/client';
import App from './App';
import { InstallPrompt } from './components/InstallPrompt';
import { registerServiceWorker } from './pwa/register';

createRoot(document.getElementById('root')!).render(
  <>
    <App />
    <InstallPrompt />
  </>
);

// AD-473c: register PWA service worker after first paint. Tier-2 log-and-degrade
// inside `registerServiceWorker` — failure does not block the HXI.
void registerServiceWorker();
===END REPLACE===
```

Three new imports + one fragment wrapper + one fire-and-forget call. `void` operator marks the unhandled promise as intentional (TypeScript `no-floating-promises` clean).

### Section 7 — Wire-up in `index.html`

Modify `ui/index.html`. Insert the four PWA `<head>` entries immediately after the existing `<link rel="icon">`:

```
===SEARCH===
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ProbOS HXI</title>
    <link rel="icon" href="data:," />
    <style>
===REPLACE===
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ProbOS HXI</title>
    <link rel="icon" href="data:," />
    <link rel="manifest" href="/manifest.webmanifest" />
    <meta name="theme-color" content="#0a0a12" />
    <meta name="apple-mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
    <link rel="apple-touch-icon" href="/icons/icon-192.svg" />
    <style>
===END REPLACE===
```

Five lines added. Viewport meta untouched (already correct). The `apple-touch-icon` link uses the 192 SVG — iOS auto-rasterizes; no PNG needed for v1.

### Section 8 — Tests (`ui/src/__tests__/Pwa.test.tsx`)

Create the vitest file. **14 tests across 4 `describe` blocks.**

```typescript
/**
 * AD-473 v1 — Mobile PWA test coverage.
 *
 * Coverage:
 *   - Manifest JSON shape (4 tests)
 *   - registerServiceWorker helper (4 tests)
 *   - InstallPrompt component (5 tests)
 *   - Viewport meta verification (1 test) — verifies index.html line 5 unchanged
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { readFileSync } from 'fs';
import { resolve } from 'path';

import { InstallPrompt } from '../components/InstallPrompt';
import { registerServiceWorker } from '../pwa/register';

// ---------- Manifest ----------

describe('manifest.webmanifest', () => {
  const manifestPath = resolve(__dirname, '../../public/manifest.webmanifest');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));

  it('declares all 7 required PWA fields', () => {
    expect(manifest.name).toBe('ProbOS HXI');
    expect(manifest.short_name).toBe('ProbOS');
    expect(manifest.start_url).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.theme_color).toBe('#0a0a12');
    expect(manifest.background_color).toBe('#0a0a12');
    expect(Array.isArray(manifest.icons)).toBe(true);
  });

  it('declares at least one 192x192 icon', () => {
    const icon192 = manifest.icons.find((i: any) => i.sizes === '192x192');
    expect(icon192).toBeDefined();
    expect(icon192.src).toMatch(/icon-192\.svg$/);
  });

  it('declares at least one 512x512 icon', () => {
    const icon512 = manifest.icons.find((i: any) => i.sizes === '512x512');
    expect(icon512).toBeDefined();
    expect(icon512.src).toMatch(/icon-512\.svg$/);
  });

  it('declares a maskable icon for Android adaptive icons', () => {
    const maskable = manifest.icons.find((i: any) => i.purpose === 'maskable');
    expect(maskable).toBeDefined();
  });
});

// ---------- registerServiceWorker ----------

describe('registerServiceWorker', () => {
  let originalSW: any;

  beforeEach(() => {
    originalSW = (navigator as any).serviceWorker;
  });

  afterEach(() => {
    if (originalSW === undefined) {
      delete (navigator as any).serviceWorker;
    } else {
      Object.defineProperty(navigator, 'serviceWorker', {
        value: originalSW,
        configurable: true,
      });
    }
  });

  it('returns null when serviceWorker API is unavailable', async () => {
    delete (navigator as any).serviceWorker;
    const result = await registerServiceWorker();
    expect(result).toBeNull();
  });

  it('returns the registration when API is available', async () => {
    const fakeRegistration = { scope: '/' };
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { register: vi.fn().mockResolvedValue(fakeRegistration) },
      configurable: true,
    });
    const result = await registerServiceWorker();
    expect(result).toBe(fakeRegistration);
  });

  it('calls register with /sw.js path', async () => {
    const register = vi.fn().mockResolvedValue({ scope: '/' });
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { register },
      configurable: true,
    });
    await registerServiceWorker();
    expect(register).toHaveBeenCalledWith('/sw.js');
  });

  it('returns null and logs on registration failure (tier-2 log-and-degrade)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { register: vi.fn().mockRejectedValue(new Error('boom')) },
      configurable: true,
    });
    const result = await registerServiceWorker();
    expect(result).toBeNull();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

// ---------- InstallPrompt ----------

describe('InstallPrompt', () => {
  it('renders nothing before beforeinstallprompt fires', () => {
    const { container } = render(<InstallPrompt />);
    expect(container.firstChild).toBeNull();
  });

  it('renders install button after beforeinstallprompt fires', () => {
    render(<InstallPrompt />);
    const event: any = new Event('beforeinstallprompt');
    event.prompt = vi.fn().mockResolvedValue(undefined);
    event.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(screen.getByTestId('install-prompt')).toBeInTheDocument();
    expect(screen.getByTestId('install-prompt-install')).toBeInTheDocument();
  });

  it('calls prompt() when install button clicked', async () => {
    render(<InstallPrompt />);
    const promptFn = vi.fn().mockResolvedValue(undefined);
    const event: any = new Event('beforeinstallprompt');
    event.prompt = promptFn;
    event.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
    act(() => {
      window.dispatchEvent(event);
    });
    fireEvent.click(screen.getByTestId('install-prompt-install'));
    await waitFor(() => expect(promptFn).toHaveBeenCalled());
  });

  it('dismisses when user clicks dismiss button', () => {
    render(<InstallPrompt />);
    const event: any = new Event('beforeinstallprompt');
    event.prompt = vi.fn().mockResolvedValue(undefined);
    event.userChoice = Promise.resolve({ outcome: 'dismissed', platform: 'web' });
    act(() => {
      window.dispatchEvent(event);
    });
    fireEvent.click(screen.getByTestId('install-prompt-dismiss'));
    expect(screen.queryByTestId('install-prompt')).not.toBeInTheDocument();
  });

  it('dismisses on appinstalled event', () => {
    render(<InstallPrompt />);
    const event: any = new Event('beforeinstallprompt');
    event.prompt = vi.fn().mockResolvedValue(undefined);
    event.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(screen.getByTestId('install-prompt')).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event('appinstalled'));
    });
    expect(screen.queryByTestId('install-prompt')).not.toBeInTheDocument();
  });
});

// ---------- Viewport meta (regression guard) ----------

describe('index.html viewport meta', () => {
  it('declares mobile-friendly viewport (responsive viewport already shipped per roadmap line 1544)', () => {
    const indexHtml = readFileSync(resolve(__dirname, '../../index.html'), 'utf8');
    expect(indexHtml).toMatch(/<meta\s+name="viewport"\s+content="width=device-width,\s*initial-scale=1\.0"\s*\/?>/);
  });
});
```

14 tests. Uses `readFileSync` to validate the manifest and `index.html` as static assets — vitest runs in `jsdom` so file-system access works (matches the `ComponentRendering.test.tsx` pattern style of importing real components, here extended to real files).

---

## What this prompt does NOT change

- **No Python source touched.** Pytest delta = 0 (gate must remain 11705).
- **No new Python or UI dependency.** `pyproject.toml`, `ui/package.json` unchanged. SW is hand-rolled — no `vite-plugin-pwa`, no `workbox-*`.
- **No edits to** `App.tsx`, `CognitiveCanvas.tsx`, `animations.tsx`, `GlassLayer.tsx`, `WelcomeOverlay.tsx`, or any HXI canvas surface.
- **No edits to** `index.html` `<style>` block, `<title>`, or viewport meta.
- **No edits to** `vite.config.ts`, `vitest.config.ts`, `tsconfig.json`.
- **No new EventType, agent, pool, Intent, router edit, consensus change, trust scorer touch, episodic store touch.**
- **No federation, no MCP bridge, no naval-org artifact.**
- **No edits to** `data/`, `config/`, or Python `tests/`.
- **No Web Push, no responsive HXI mobile layout, no mDNS, no native-app wrapper** — those are AD-473d/e/f/g (parked with explicit forcing functions in WAVE-85-DISPATCH.md).

## Tracking

- `PROGRESS.md` — Wave 85 close line + updated baselines (`pytest 11705 unchanged; vitest 305+ from 291 baseline + 14 new`).
- `docs/development/roadmap.md:4205` — `(planned)` → `(v1 shipped — Wave 85)`. Append a one-paragraph sub-AD letter map: 473a/b/c shipped; 473d Web Push parked (Python VAPID + endpoints); 473e Responsive HXI parked (Captain UX decisions); 473f mDNS parked (Python `zeroconf` + cross-platform startup); 473g native apps remain `(future stretch)`.
- `prompts/wave-plan.yaml` — append `id: "85"` entry (see appendix).
- `DECISIONS.md` — no new architectural decision (AD-473 pre-allocated; v1 is roadmap Phase 1 shipment).

## Acceptance criteria

1. `ui/public/manifest.webmanifest` parses as JSON, contains the 7 required fields and three icons (192, 512, 512-maskable).
2. `ui/public/sw.js` exists, ≤ 50 LOC, defines `install` / `activate` / `fetch` listeners, skips `/api/` and `/ws` URLs, uses versioned `CACHE_VERSION` cache key.
3. `ui/public/icons/icon-192.svg` and `ui/public/icons/icon-512.svg` exist, are stroke-based, fillless except background, amber-on-dark palette per HXI principle #2.
4. `ui/src/pwa/register.ts` exports `registerServiceWorker(): Promise<ServiceWorkerRegistration | null>` with the AD-473d integration-point comment.
5. `ui/src/components/InstallPrompt.tsx` renders nothing before `beforeinstallprompt` fires, surfaces a stroke-based SVG install button with a stroke-based SVG dismiss button (zero emoji), responds correctly to `appinstalled` and to user dismissal.
6. `ui/src/main.tsx` imports both `InstallPrompt` and `registerServiceWorker`, renders `<InstallPrompt />` as a sibling of `<App />`, and fires `void registerServiceWorker()` after `render(...)`.
7. `ui/index.html` `<head>` carries the four new lines (`<link rel="manifest">`, `<meta name="theme-color">`, two `apple-mobile-web-app-*` metas, plus `apple-touch-icon` link).
8. **Vitest gate:** `cd ui && npx vitest run` passes ≥ 305 tests (291 baseline + 14 new). The pre-existing `WardRoomDmSync.test.tsx` failure remains 1 — Wave 85 does not fix it; Wave 85 does not regress it.
9. **Pytest gate:** `pytest tests/ -q -n 4 --dist=loadfile` reports 11705 unchanged.
10. `PROGRESS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml` updated per the Tracking section.
11. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** — specifically HXI principles #1 (no UX guessing), #2 (geometric SVG, amber/blue/violet), #3 (no emoji), #5 (progressive disclosure — InstallPrompt does not auto-render), and the Three-Tier Exception Handling rule (registerServiceWorker uses tier 2 log-and-degrade).

## Wave-plan appendix

Append to `prompts/wave-plan.yaml`:

```yaml
  - id: "85"
    title: "AD-473 v1 — Mobile PWA (HXI installable shell)"
    kind: main
    depends_on: ["84"]
    dispatch_prompt: "prompts/WAVE-85-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-473-mobile-pwa-v1.md"
    builder_required: true
    issues_to_close: [67]
    status: pending
```

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  05989c3

# Greenfield — no collisions:
Test-Path ui/public                         → False
Test-Path ui/public/manifest.webmanifest    → False
Test-Path ui/public/sw.js                   → False
Test-Path ui/src/pwa                        → False
Test-Path ui/src/components/InstallPrompt.tsx → False

# Pattern sources (verified):
ui/index.html:5    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
ui/index.html:13   background: #0a0a12;                                  # theme_color match
ui/index.html:7    <link rel="icon" href="data:," />                     # insertion anchor for new <link>/<meta>
ui/src/main.tsx:1-5    createRoot(...).render(<App />);                  # SEARCH/REPLACE anchor

ui/vite.config.ts:1-21    default Vite 6 config — public/* served at root
ui/package.json:6         "build": "tsc -b && vite build"
ui/package.json:11        "test": "vitest run"
ui/vitest.config.ts:7     environment: 'jsdom', globals: true
ui/src/test/setup.ts:1    @testing-library/jest-dom

# Test pattern source (verified):
ui/src/__tests__/ComponentRendering.test.tsx:6
  import { render, screen, fireEvent } from '@testing-library/react';
ui/src/__tests__/ComponentRendering.test.tsx:7
  import { describe, it, expect, vi, beforeEach } from 'vitest';

# HXI principles (verified — file paths exist):
.github/copilot-instructions.md (HXI Design Principles section, principles #1, #2, #3, #5, #11)

# Pre-commit hook banned-pattern check (verified):
.git/hooks/pre-commit:5-16    11 banned patterns enumerated.
# Sweep across this prompt + WAVE-85-DISPATCH.md → 0 literal hits across all 11.
# Audit text in both files uses placeholder forms (the e-word + tier;
# the private-repo path token; the GTM-pattern phrase; the recurring-revenue
# acronym; the price/month and price/mo regexes) per Captain's explicit
# warning that the hook would otherwise trip on the audit's own quoted text.

# Roadmap entries (verified):
docs/development/roadmap.md:1544    Phase 1 — manifest, service worker, responsive viewport. "Zero new code for basic mobile access."
docs/development/roadmap.md:4205    AD-473 umbrella — five components (1)–(5).

# Vitest baseline (verified):
cd ui && npx vitest run
  Tests  1 failed | 291 passed (292)
  # WardRoomDmSync.test.tsx pre-existing failure — pre-Wave-85, not introduced.

# Pytest baseline (verified):
# Wave 84 close note: pytest 11705 post-build (HEAD 05989c3, "Wave 84 archive: AD-512 discovery learning (#94)").
```
