/* Cross-project module views: budget, BOQ, inventory, procurement, labour, schedule. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, money, moneyShort, num, pct, table, badge, statusBadge, progressBar,
          emptyState, icons, dateFmt, humanize } = BB;

  const host = el('#module-host');
  if (!host) return;
  const name = el('#module-tabs').getAttribute('data-current');
  let rows = [];

  const CONFIG = {
    budgets: {
      title: 'Budget position',
      cols: [
        { key: 'project', label: 'Project', render: (v, r) => `<a href="/projects/${r.project_id}?tab=budget"><strong>${esc(v)}</strong></a>` },
        { key: 'status', label: 'Status', render: (v) => badge(BB.label('health_status', v), v) },
        { key: 'approved_budget', label: 'Approved', align: 'right', render: (v) => money(v) },
        { key: 'estimated_cost', label: 'BOQ estimate', align: 'right', render: (v) => money(v) },
        { key: 'actual_expenses', label: 'Actual', align: 'right', render: (v) => money(v) },
        { key: 'remaining_budget', label: 'Remaining', align: 'right', render: (v) => `<span style="${v < 0 ? 'color:var(--danger)' : ''}">${money(v)}</span>` },
        { key: 'utilization_pct', label: 'Used', align: 'right', render: (v) => v == null ? '—' : pct(v) },
      ],
    },
    boq: {
      title: 'Bill of Quantities across projects',
      cols: [
        { key: 'project', label: 'Project', render: (v, r) => `<a href="/projects/${r.project_id}?tab=boq"><strong>${esc(v)}</strong></a>` },
        { key: 'revision', label: 'Revision', align: 'right' },
        { key: 'items', label: 'Items', align: 'right' },
        { key: 'approved', label: 'Approval', render: (v) => v ? badge('Approved', 'approved') : badge('Draft', 'draft') },
        { key: 'total', label: 'Value', align: 'right', render: (v) => money(v) },
      ],
      empty: 'No project has BOQ items yet',
    },
    inventory: {
      title: 'Stock across projects',
      search: true,
      cols: [
        { key: 'material_name', label: 'Material', render: (v, r) => `<strong>${esc(v)}</strong><div class="small muted">${esc(r.project)}</div>` },
        { key: 'available', label: 'Available', align: 'right', render: (v, r) => `${num(v, 2)} ${esc(r.unit)}` },
        { key: 'reserved', label: 'Reserved', align: 'right', render: (v, r) => `${num(v, 2)} ${esc(r.unit)}` },
        { key: 'reorder_level', label: 'Reorder at', align: 'right', render: (v, r) => `${num(v, 2)} ${esc(r.unit)}` },
        { key: 'location', label: 'Store', render: (v) => esc(v || '—') },
        { key: 'low', label: 'Status', render: (v) => v ? badge('Low stock', 'critical') : badge('Sufficient', 'ok') },
      ],
      empty: 'No materials tracked yet',
    },
    procurement: {
      title: 'Purchase orders',
      cols: [
        { key: 'number', label: 'Order', render: (v, r) => `<strong>${esc(v)}</strong><div class="small muted">${esc(r.project || '')}</div>` },
        { key: 'supplier', label: 'Supplier' },
        { key: 'status', label: 'Status', render: (v, r) => badge(humanize(v), v === 'received' ? 'ok' : v === 'draft' ? 'draft' : 'pending')
            + (r.delivery_late ? ' ' + badge('Delayed', 'critical') : '') },
        { key: 'expected_date', label: 'Expected', render: (v) => v ? dateFmt(v) : '—' },
        { key: 'total', label: 'Value', align: 'right', render: (v) => money(v) },
        { key: 'id', label: '', render: (v, r) => `<a class="btn btn-ghost btn-sm" href="/projects/${r.project_id}?tab=procurement">Open</a>` },
      ],
      empty: 'No purchase orders yet',
    },
    labour: {
      title: 'Labour cost across projects',
      cols: [
        { key: 'project', label: 'Project', render: (v, r) => `<a href="/projects/${r.project_id}?tab=labour"><strong>${esc(v)}</strong></a>` },
        { key: 'entries', label: 'Entries', align: 'right' },
        { key: 'worker_days', label: 'Worker-days', align: 'right', render: (v) => num(v, 1) },
        { key: 'categories', label: 'Categories', align: 'right' },
        { key: 'total_cost', label: 'Cost', align: 'right', render: (v) => money(v) },
      ],
      empty: 'No labour recorded yet',
    },
    schedule: {
      title: 'Schedule across projects',
      cols: [
        { key: 'project', label: 'Project', render: (v, r) => `<a href="/projects/${r.project_id}?tab=schedule"><strong>${esc(v)}</strong></a>` },
        { key: 'tasks', label: 'Tasks', align: 'right' },
        { key: 'planned_finish', label: 'Planned finish', render: (v) => v ? dateFmt(v) : '—' },
        { key: 'working_days', label: 'Working days', align: 'right' },
        { key: 'overdue', label: 'Overdue', align: 'right', render: (v) => v ? `<span style="color:var(--danger);font-weight:600">${v}</span>` : '0' },
        { key: 'progress', label: 'Progress', render: (v) => `<div style="min-width:80px">${progressBar(v)}</div><span class="small muted">${num(v, 0)}%</span>` },
      ],
      empty: 'No project has tasks yet',
    },
  };

  const cfg = CONFIG[name] || CONFIG.budgets;
  document.querySelectorAll('#module-tabs [data-mod]').forEach((a) => {
    if (a.getAttribute('data-mod') === name) { a.classList.remove('btn-ghost'); a.classList.add('btn'); a.setAttribute('aria-current', 'page'); }
  });
  el('#module-title').textContent = cfg.title;
  if (cfg.search) el('#module-q').classList.remove('hidden');

  function q() { return el('#module-q') ? el('#module-q').value.trim().toLowerCase() : ''; }

  function render(data) {
    rows = data.rows || [];
    el('#module-kpis').innerHTML = (data.kpis || []).map((k) => `<div class="kpi">
      <div class="label">${esc(k.label)}</div>
      <div class="value">${k.money ? moneyShort(k.value) : num(k.value, k.value % 1 ? 1 : 0)}</div></div>`).join('');
    let shown = rows;
    if (q()) shown = rows.filter((r) => Object.values(r).some((v) => String(v || '').toLowerCase().includes(q())));
    host.innerHTML = shown.length ? table(shown, cfg.cols, { compact: true })
      : emptyState(cfg.empty || 'Nothing to show', 'Change the project filter or add data in a project workspace.', 'inbox');
    const pid = el('#module-project').value;
    const link = el('#module-open-project');
    link.href = pid ? `/projects/${pid}?tab=${name}` : '/projects';
    link.textContent = pid ? 'Open project reports' : 'Choose a project';
    icons(host);
  }

  async function load() {
    const params = new URLSearchParams();
    const pid = el('#module-project').value;
    if (pid) params.set('project_id', pid);
    try {
      render(await api(`/modules/${name}?` + params.toString()));
    } catch (err) {
      host.innerHTML = emptyState('Could not load this view', err.message, 'alert-circle');
      icons(host);
    }
  }

  el('#module-project').addEventListener('change', load);
  if (el('#module-q')) el('#module-q').addEventListener('input', () => load());
  BB.ready().then(load);
})();
