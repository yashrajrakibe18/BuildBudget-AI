// Caches ONLY static assets (app shell). API/financial data is never cached.
const C = 'bb-shell-v1', SHELL = ['/static/css/app.css', '/static/js/app.js'];
self.addEventListener('install', e => e.waitUntil(caches.open(C).then(c => c.addAll(SHELL))));
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (u.pathname.startsWith('/static/')) e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
