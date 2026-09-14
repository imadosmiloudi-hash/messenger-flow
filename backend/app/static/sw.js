const CACHE = 'messenger-flow-static-v12';
const PRECACHE = ['/', '/manifest.json', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png', '/favicon.ico', '/favicon-32.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/webhook') || url.pathname.startsWith('/media/')) {
    return;
  }

  // Always network-first for JS/CSS so phone gets new flow upload UI
  const isAppAsset =
    url.pathname === '/assets/app.js' ||
    url.pathname === '/assets/app.css' ||
    url.pathname === '/sw.js' ||
    url.pathname === '/' ||
    url.pathname === '/index.html';

  if (isAppAsset) {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(event.request, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(event.request).then((cached) => cached || caches.match('/')))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request).catch(() => caches.match('/')))
  );
});
