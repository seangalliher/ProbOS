/* ProbOS HXI — Entry point (AD-255, AD-473c) */

import { createRoot } from 'react-dom/client';
import { lazy, Suspense } from 'react';
import CompactApp from './CompactApp';
import { InstallPrompt } from './components/InstallPrompt';
import { registerServiceWorker } from './pwa/register';
import { resolveEntryTarget } from './entryRoute';
import { isPadDevice } from './hooks/usePadDevice';

// Issue #770: lazy-load the full HXI so Compact mode does not eagerly
// pull the three.js / VRM stack. Vite/Rollup treats this dynamic import
// as a code-split boundary, which is what lets `manualChunks` actually
// carve `avatar-vendor` / `avatar-app` out of the entry graph.
const App = lazy(() => import('./App'));
// AD-708b: lazy MobileShell — its own chunk, and the desktop App stays lazy so a
// PADD never pulls the three.js/VRM stack.
const MobileShell = lazy(() => import('./MobileShell'));

// AD-708b: module-load device routing (mirrors the #compact idiom). isPadDevice()
// honest-degrades to false (jsdom/SSR/no-matchMedia) -> 'desktop', so the desktop
// render path is provably byte-identical.
const entryTarget = resolveEntryTarget(window.location.hash, isPadDevice());

createRoot(document.getElementById('root')!).render(
  entryTarget === 'compact' ? (
    <CompactApp />
  ) : entryTarget === 'mobile' ? (
    <Suspense fallback={null}>
      <MobileShell />
      <InstallPrompt />
    </Suspense>
  ) : (
    // Suspense fallback is intentionally null — the existing
    // WelcomeOverlay / boot sequence handles first-paint UX once App
    // resolves. A spinner here would flash for one frame and feel
    // worse than the current behavior.
    <Suspense fallback={null}>
      <App />
      <InstallPrompt />
    </Suspense>
  ),
);

// AD-473c: register PWA service worker after first paint. Tier-2 log-and-degrade
// inside `registerServiceWorker` — failure does not block the HXI.
void registerServiceWorker();
