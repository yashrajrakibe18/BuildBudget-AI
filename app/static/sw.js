/* BuildBudget AI service worker: caches static assets only.
   Never caches API responses, HTML pages or documents, so project data is always fresh
   and one user's data can never be served from a shared cache. */
const CACHE = 'bb-static-v4';
const ASSETS = [
  '/static/css/app.css',
  '/static/js/theme.js',
  '/static/js/ui.js',
  '/static/js/app.js',
  '/static/img/icon.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  const isStatic = event.request.method === 'GET' && url.origin === self.location.origin
    && url.pathname.startsWith('/static/');
  if (!isStatic) return;                       // network handles pages, APIs and streams
  // Network-first so updated JS/CSS is never served stale while online;
  // the cache is an offline fallback, not the primary source.
  event.respondWith(
    fetch(event.request).then((res) => {
      if (res.ok) caches.open(CACHE).then((c) => c.put(event.request, res.clone()));
      return res;
    }).catch(() => caches.match(event.request))
  );
});
