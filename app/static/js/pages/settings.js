/* Settings: preferences, integration status and diagnostics. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, badge, toast, icons, dateFmt, devDetails } = BB;

  function integrationCard(title, state, detail, extra) {
    const tone = state === 'ready' || state === 'connected' || state === 'enabled' || state === 'ok' ? 'ok'
      : state === 'not_configured' || state === 'unavailable' || state === 'disabled' ? 'warning' : 'info';
    return `<div class="insight ${tone === 'ok' ? 'info' : tone}" style="align-items:flex-start">
      <i data-lucide="${tone === 'ok' ? 'check-circle' : 'alert-triangle'}" class="ico"></i>
      <div style="flex:1"><b>${esc(title)} ${badge(BB.humanize(state || 'unknown'), tone)}</b>
        <span>${esc(detail || '')}</span>
        ${extra ? `<div class="small muted" style="margin-top:3px">${extra}</div>` : ''}</div></div>`;
  }

  async function loadIntegrations() {
    const host = el('#integrations');
    host.innerHTML = '<div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row"></div>';
    try {
      const s = await api('/settings/integrations');
      const ai = s.ai || {};
      const mail = s.mail || {};
      const sched = s.scheduler || {};
      const rag = s.retrieval || {};
      host.innerHTML = [
        integrationCard('Language model', ai.available ? 'ready' : 'not_configured',
          ai.available ? `${ai.provider} · ${ai.model}` : (ai.reason || 'No provider key configured.'),
          ai.available ? 'Configured through server environment variables.' : 'Set GROQ_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY or OPENROUTER_API_KEY in .env.'),
        integrationCard('Email sending', mail.state || 'unknown', mail.message || '',
          `Provider: ${mail.provider || 'smtp'}${mail.from_address ? ' · from ' + mail.from_address : ''}. Gmail API mailbox sync is not implemented.`),
        integrationCard('Weather', s.weather && s.weather.configured ? 'ready' : 'unavailable',
          'Open-Meteo forecast, no key required.', s.weather ? s.weather.note : ''),
        integrationCard('Knowledge retrieval', 'ready', rag.note || 'Hybrid BM25 + vector retrieval.',
          `${rag.documents || 0} document(s) · ${rag.chunks || 0} passage(s) · ${rag.neural_embeddings ? 'neural embeddings available' : 'hashed TF-IDF vectors'}`),
        integrationCard('Scheduler', sched.enabled ? 'enabled' : 'disabled',
          sched.enabled ? `Checks every ${sched.interval_minutes} minutes${sched.in_app ? ' (in-app scheduler)' : ''}.` : 'Scheduler is disabled.',
          sched.note || ''),
        integrationCard('Database', 'ready', s.database ? s.database.url_scheme.toUpperCase() : 'SQLite',
          s.database ? s.database.backup_advice : ''),
      ].join('');
      el('#data-info').innerHTML = `<div>Environment: <strong>${esc(s.environment || '')}</strong> · Version <strong>${esc(s.version || '')}</strong>
        · Demo mode <strong>${s.demo_mode ? 'on' : 'off'}</strong></div>
        ${(sched.jobs || []).length ? `<div class="small muted" style="margin-top:4px">Scheduled jobs: ${sched.jobs.map((j) => esc(j.name || j.id || j)).join(', ')}</div>` : ''}`;
      icons(host);
    } catch (err) {
      host.innerHTML = `<div class="alert error">${esc(err.message)}</div>`;
    }
  }

  function fill() {
    const me = BB.me;
    if (!me) return;
    el('#set-theme').value = me.theme || localStorage.getItem('bb-theme') || 'system';
    el('#set-units').value = me.units || 'imperial';
    el('#set-currency').value = (me.currency || 'INR').toUpperCase();
    el('#set-timezone').value = me.timezone || 'Asia/Kolkata';
    el('#set-notify').checked = !!me.notify_email;
  }

  el('#settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {
      theme: el('#set-theme').value,
      units: el('#set-units').value,
      currency: el('#set-currency').value,
      timezone: el('#set-timezone').value.trim() || 'Asia/Kolkata',
      notify_email: el('#set-notify').checked,
    };
    try {
      const me = await api('/auth/profile', { method: 'PUT', body });
      BB.me = { ...BB.me, ...me };
      localStorage.setItem('bb-theme', body.theme);
      document.documentElement.setAttribute('data-theme', body.theme === 'system'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : body.theme);
      toast('Preferences saved.', 'success');
    } catch (err) { /* toasted */ }
  });

  el('#set-refresh').addEventListener('click', loadIntegrations);

  el('#test-llm').addEventListener('click', async () => {
    const box = el('#diagnostics');
    box.innerHTML = '<div class="small"><span class="spinner"></span> Calling the provider…</div>';
    try {
      const r = await api('/settings/test/llm', { method: 'POST' });
      box.innerHTML = integrationCard('Language model test', r.ok ? 'ok' : 'failed', r.message, r.sample ? `Sample reply: ${esc(r.sample)}` : '');
      icons(box);
    } catch (err) {
      box.innerHTML = integrationCard('Language model test', 'failed', err.message);
      icons(box);
    }
  });

  el('#test-mail').addEventListener('click', async () => {
    const box = el('#diagnostics');
    box.innerHTML = '<div class="small"><span class="spinner"></span> Checking SMTP…</div>';
    try {
      const r = await api('/mail/test-connection', { method: 'POST' });
      box.innerHTML = integrationCard('SMTP connection', r.ok ? 'ok' : 'failed', r.message);
      icons(box);
    } catch (err) {
      box.innerHTML = integrationCard('SMTP connection', 'failed', err.message);
      icons(box);
    }
  });

  BB.ready().then(() => { fill(); loadIntegrations(); });
})();
