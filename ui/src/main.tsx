/* ProbOS HXI — Entry point (AD-255, AD-473c) */

import { createRoot } from 'react-dom/client';
import App from './App';
import CompactApp from './CompactApp';
import { InstallPrompt } from './components/InstallPrompt';
import { registerServiceWorker } from './pwa/register';

// Compact mode: chat-only Yeo surface for the desktop tray app. Selected
// when the URL hash contains `compact` (Electron host loads `/#compact`).
const compactMode =
  typeof window !== 'undefined' &&
  window.location.hash.toLowerCase().includes('compact');

createRoot(document.getElementById('root')!).render(
  compactMode ? (
    <CompactApp />
  ) : (
    <>
      <App />
      <InstallPrompt />
    </>
  ),
);

// AD-473c: register PWA service worker after first paint. Tier-2 log-and-degrade
// inside `registerServiceWorker` — failure does not block the HXI.
void registerServiceWorker();
