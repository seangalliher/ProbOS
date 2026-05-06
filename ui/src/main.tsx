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
