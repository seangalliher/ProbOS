// ProbOS HXI — Service Worker (AD-473b)
//
// App-shell caching strategy:
//   - install: pre-cache the app shell (HTML + manifest + icons).
//   - fetch:
//       * /api/*, /ws*  → bypass entirely (live data).
//       * /, /index.html, /assets/* (hashed bundles) → network-first;
//         the cached copy is only a fallback when offline. This avoids
//         pinning a stale `index.html` to a deleted hashed JS bundle.
//       * everything else → cache-first.
//   - activate: drop stale cache versions.
//
// AD-473d (future): Web Push event handler (`push`, `notificationclick`) lands here.

// Bump CACHE_VERSION whenever the cache contract changes.
const CACHE_VERSION = 'probos-hxi-v2';
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

function isLiveTraffic(url) {
  return url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws');
}

function isAppShellNetworkFirst(url) {
  // HTML root + hashed Vite bundles must always prefer the network so a
  // new build's index.html doesn't keep pointing at a deleted JS hash.
  if (url.pathname === '/' || url.pathname === '/index.html') return true;
  if (url.pathname.startsWith('/assets/')) return true;
  return false;
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);

  if (isLiveTraffic(url)) return;

  if (isAppShellNetworkFirst(url)) {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(event.request, copy));
          }
          return resp;
        })
        .catch(() => caches.match(event.request).then((c) => c || caches.match('/')))
    );
    return;
  }

  // Static assets (icons, manifest, future bundles): cache-first.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).catch(() => caches.match('/'));
    })
  );
});
