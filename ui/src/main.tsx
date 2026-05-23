/* ProbOS HXI — Entry point (AD-255, AD-473c) */

import { createRoot } from 'react-dom/client';
import { lazy, Suspense } from 'react';
import CompactApp from './CompactApp';
import { InstallPrompt } from './components/InstallPrompt';
import { registerServiceWorker } from './pwa/register';

// Issue #770: lazy-load the full HXI so Compact mode does not eagerly
// pull the three.js / VRM stack. Vite/Rollup treats this dynamic import
// as a code-split boundary, which is what lets `manualChunks` actually
// carve `avatar-vendor` / `avatar-app` out of the entry graph.
const App = lazy(() => import('./App'));

// Compact mode: chat-only Yeo surface for the desktop tray app. Selected
// when the URL hash contains `compact` (Electron host loads `/#compact`).
const compactMode =
  typeof window !== 'undefined' &&
  window.location.hash.toLowerCase().includes('compact');

createRoot(document.getElementById('root')!).render(
  compactMode ? (
    <CompactApp />
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
