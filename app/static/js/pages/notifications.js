/* Notification centre: filters, mark read, archive and live unread updates. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, badge, emptyState, confirm: confirmDialog, toast, icons, dateFmt, timeAgo } = BB;

  const host = el('#notif-list');
  let source = null;

  function params() {
    const p = new URLSearchParams();
    if (el('#notif-unread').checked) p.set('unread_only', 'true');
    if (el('#notif-kind').value) p.set('kind', el('#notif-kind').value);
    if (el('#notif-project').value) p.set('project_id', el('#notif-project').value);
    if (el('#notif-archived').checked) p.set('include_archived', 'true');
    return p;
  }

  function tone(n) {
    if (n.status === 'failed' || n.kind === 'email_failed') return 'critical';
    if (n.kind === 'budget' || n.kind === 'inventory' || n.kind === 'deadline') return 'warning';
    return 'info';
  }
  function icon(n) {
    return { budget: 'wallet', inventory: 'package', deadline: 'alarm-clock', approval: 'shield-check',
      email: 'mail', email_failed: 'mail-x', automation: 'zap', weather: 'cloud-sun',
      quotation: 'file-check', report: 'file-text', system: 'info' }[n.kind] || 'bell';
  }

  function render(data) {
    el('#notif-count').textContent = `${data.unread} unread`;
    host.innerHTML = (data.items || []).length ? data.items.map((n) => `<article class="notif ${n.read ? '' : 'unread'}">
      <div class="n-ico"><i data-lucide="${icon(n)}" class="ico" style="width:17px;height:17px"></i></div>
      <div class="n-main">
        <div class="n-title">${esc(n.subject)}</div>
        <div class="n-meta">
          ${badge(n.kind_label || BB.label('notification_kinds', n.kind), tone(n))}
          ${n.priority && n.priority !== 'normal' ? badge(BB.humanize(n.priority), n.priority) : ''}
          ${n.project ? `<span>${esc(n.project)}</span>` : ''}
          <span>${timeAgo(n.created_at)}</span>
          ${n.status === 'failed' ? badge('Delivery failed', 'critical') : ''}
          ${n.read ? '' : '<span class="dot-status" style="color:var(--amber)"></span><span>Unread</span>'}
        </div>
        ${n.body ? `<div class="n-body">${esc(n.body)}</div>` : ''}
        ${n.error ? `<div class="alert error" style="margin-top:8px">${esc(n.error)}</div>` : ''}
        <div class="btn-group" style="margin-top:8px">
          ${n.link ? `<a class="btn btn-ghost btn-sm" href="${esc(n.link)}">Open</a>` : ''}
          ${n.read ? '' : `<button class="btn btn-ghost btn-sm" type="button" data-read="${n.id}">Mark read</button>`}
          <button class="btn btn-ghost btn-sm" type="button" data-archive="${n.id}">Archive</button>
        </div>
      </div>
    </article>`).join('') : emptyState('No notifications', 'Alerts are created from real budget, stock, task and approval events.', 'bell');
    icons(host);
    el('#notif-live').textContent = source ? 'Live updates enabled' : 'Live updates unavailable — refresh to check again';
  }

  async function load() {
    try {
      render(await api('/notifications?' + params().toString()));
    } catch (err) {
      host.innerHTML = `<div class="card">${emptyState('Notifications could not load', err.message, 'alert-circle')}</div>`;
      icons(host);
    }
  }

  async function markRead(ids) {
    const r = await api('/notifications/mark-read', { method: 'POST', body: { ids: ids || [] } });
    el('#bell-count').textContent = r.unread > 99 ? '99+' : String(r.unread);
    el('#bell-count').classList.toggle('hidden', !r.unread);
    load();
  }

  host.addEventListener('click', async (e) => {
    const read = e.target.closest('[data-read]');
    if (read) { markRead([Number(read.getAttribute('data-read'))]); return; }
    const archive = e.target.closest('[data-archive]');
    if (archive) {
      await api(`/notifications/${archive.getAttribute('data-archive')}/archive`, { method: 'POST' });
      toast('Notification archived.', 'success'); load();
    }
  });

  el('#notif-read').addEventListener('click', () => markRead([]));
  el('#notif-checks').addEventListener('click', async () => {
    try {
      const r = await api('/notifications/run-checks', { method: 'POST' });
      toast(r.processed ? `${r.processed} alert(s) created.` : 'All checks ran; nothing new to report.', 'success');
      load();
    } catch (err) { /* toasted */ }
  });
  ['#notif-unread', '#notif-kind', '#notif-project', '#notif-archived'].forEach((sel) => {
    el(sel).addEventListener('change', load);
  });

  function connect() {
    try {
      source = new EventSource('/api/v1/notifications/stream');
      source.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'unread') {
            el('#bell-count').textContent = data.count > 99 ? '99+' : String(data.count);
            el('#bell-count').classList.toggle('hidden', !data.count);
            load();
          }
        } catch (err) { /* ignore */ }
      };
      source.onerror = () => {
        if (source) { source.close(); source = null; }
        el('#notif-live').textContent = 'Live updates paused — reconnect by refreshing';
        setTimeout(connect, 45000);
      };
    } catch (err) { source = null; }
  }

  BB.ready().then(() => { load(); connect(); });
})();
