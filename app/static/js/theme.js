/* Resolve light/dark/system before first paint (loaded synchronously in <head>). */
(function () {
  var pref = 'system';
  try { pref = localStorage.getItem('bb-theme') || 'system'; } catch (e) { /* private mode */ }
  var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var resolved = pref === 'system' ? (dark ? 'dark' : 'light') : pref;
  document.documentElement.setAttribute('data-theme', resolved);
  document.documentElement.setAttribute('data-theme-pref', pref);
  document.documentElement.style.colorScheme = resolved;
})();
