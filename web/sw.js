/* Service worker : l'interface s'ouvre instantanément et fonctionne même avec un réseau faible.
   Les données (API) ne sont jamais mises en cache : elles viennent toujours du serveur. */
const VERSION = 'tmp-2.2.0';
const SHELL = ['/', '/app.css', '/app.js', '/vendor/leaflet.js', '/vendor/leaflet.css',
  '/geo/france.json', '/geo/regions.json', '/icon.svg', '/manifest.webmanifest',
  '/fonts/atkinson-400.woff2', '/fonts/atkinson-700.woff2', '/fonts/barlow-500.woff2',
  '/fonts/barlow-600.woff2', '/fonts/barlow-700.woff2'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).catch(() => {}));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz') return;
  // réseau d'abord (versions à jour), cache en secours hors ligne
  e.respondWith(fetch(e.request).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(VERSION).then(c => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match(e.request, { ignoreSearch: url.pathname === '/' })));
});
