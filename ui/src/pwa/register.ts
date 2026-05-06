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
