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
