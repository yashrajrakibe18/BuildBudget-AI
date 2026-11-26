/* Activity log: filter, inspect and export the audit trail. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, table, badge, emptyState, toast, icons, dateFmt, timeAgo } = BB;

  let rows = [];

  function params() {
    const p = new URLSearchParams({ limit: el('#act-limit').value });
    if (el('#act-project').value) p.set('project_id', el('#act-project').value);
    if (el('#act-action').value.trim()) p.set('action', el('#act-action').value.trim());
    return p;
  }

  function render() {
    el('#act-count').textContent = `${rows.length} event${rows.length === 1 ? '' : 's'}`;
    el('#act-host').innerHTML = rows.length ? table(rows, [
      { key: 'when', label: 'When', render: (v) => `<span class="nowrap">${dateFmt(v, true)}</span><div class="small muted">${timeAgo(v)}</div>` },
      { key: 'action', label: 'Action', render: (v) => badge(BB.humanize(v), 'info') },
      { key: 'summary', label: 'Summary', render: (v) => esc(v || '—') },
      { key: 'entity', label: 'Record', render: (v, r) => `${esc(BB.humanize(v || ''))}${r.entity_id ? ` <span class="muted">#${r.entity_id}</span>` : ''}` },
      { key: 'project', label: 'Project', render: (v) => esc(v || '<span class="muted">—</span>') },
      { key: 'user', label: 'User' },
    ], { compact: true }) : `<div class="card">${emptyState('No activity matches', 'Try clearing the filters.', 'history')}</div>`;
    icons(el('#act-host'));
  }

  async function load() {
    try { rows = await api('/activity?' + params().toString()); render(); }
    catch (err) {
      el('#act-host').innerHTML = `<div class="card">${emptyState('Activity could not load', err.message, 'alert-circle')}</div>`;
      icons(el('#act-host'));
    }
  }

  el('#act-apply').addEventListener('click', load);
  el('#act-project').addEventListener('change', load);
  el('#act-limit').addEventListener('change', load);
  el('#act-action').addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });

  el('#act-export').addEventListener('click', () => {
    if (!rows.length) return toast('Nothing to export.', 'warn');
    const head = ['When', 'Action', 'Summary', 'Record', 'Record ID', 'Project', 'User'];
    const lines = [head.join(',')].concat(rows.map((r) => [r.when, r.action, r.summary, r.entity, r.entity_id, r.project, r.user]
      .map((v) => {
        const s = v instanceof Date ? v.toISOString() : String(v == null ? '' : v);
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      }).join(',')));
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'buildbudget-activity.csv'; a.click();
  });

  BB.ready().then(load);
})();
