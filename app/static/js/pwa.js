/* Register the PWA service worker without blocking the app or caching user data. */
(function () {
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {
      /* Registration is optional: the app works normally without it. */
    });
  });
})();
