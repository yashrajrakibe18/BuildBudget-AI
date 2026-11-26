/* Dashboard: filters, KPI cards, charts, insights and attention lists. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, money, moneyShort, num, pct, table, statusBadge, healthBadge,
          progressBar, emptyState, chart, dateFmt, icons } = BB;

  const insightCard = (i) => `<div class="insight ${esc(i.tone || 'info')}">
      <i data-lucide="${i.tone === 'critical' ? 'alert-octagon' : i.tone === 'warning' ? 'alert-triangle' : 'info'}" class="ico"></i>
      <div><b>${esc(i.title)}</b><span>${esc(i.detail || '')}</span></div></div>`;

  let data = null;

  function filters() {
    const form = el('#dash-filters');
    const v = BB.formValues(form);
    const params = new URLSearchParams();
    if (v.project_id) params.set('project_id', v.project_id);
    if (v.status) params.set('status', v.status);
    if (v.location) params.set('location', v.location);
    params.set('months', v.months || 12);
    return params;
  }

  function renderKpis(k) {
    const cards = [
      { label: 'Projects', value: k.total_projects, foot: `${k.active_projects} active · ${k.completed_projects} completed` },
      { label: 'Approved budget', value: moneyShort(k.approved_budget), foot: `Estimated BOQ ${moneyShort(k.estimated_cost)}`, cls: '' },
      { label: 'Actual expenses', value: moneyShort(k.actual_expenses), foot: `${k.boq_items_estimated ? 'BOQ entered' : 'No BOQ yet'}` },
      { label: 'Remaining', value: moneyShort(k.remaining_budget), foot: k.remaining_budget < 0 ? 'Over approved budget' : 'Against approved budget', cls: k.remaining_budget < 0 ? 'is-danger' : '' },
      { label: 'Budget used', value: k.budget_utilization_pct == null ? '—' : pct(k.budget_utilization_pct),
        foot: k.budget_utilization_pct == null ? 'No approved budget' : (k.budget_utilization_pct >= 90 ? 'Over 90% — review commitments' : 'Within plan'),
        cls: k.budget_utilization_pct == null ? '' : k.budget_utilization_pct >= 100 ? 'is-danger' : k.budget_utilization_pct >= 75 ? 'is-warning' : 'is-success' },
      { label: 'Over budget', value: k.over_budget_projects, foot: 'Projects', cls: k.over_budget_projects ? 'is-danger' : '' },
      { label: 'Low stock', value: k.low_stock_items, foot: 'At or below reorder level', cls: k.low_stock_items ? 'is-warning' : '' },
      { label: 'Overdue tasks', value: k.overdue_tasks, foot: 'Past planned finish', cls: k.overdue_tasks ? 'is-danger' : '' },
      { label: 'Pending approvals', value: k.pending_approvals, foot: 'Nothing runs until approved', cls: k.pending_approvals ? 'is-warning' : '' },
      { label: 'Unread notifications', value: k.unread_notifications, foot: 'In-app alerts', cls: '' },
    ];
    el('#kpis').innerHTML = cards.map((c) => `<div class="kpi ${c.cls || ''}">
      <div class="label">${esc(c.label)}</div>
      <div class="value">${typeof c.value === 'string' ? esc(c.value) : num(c.value, 0)}</div>
      <div class="foot">${esc(c.foot)}</div></div>`).join('');
  }

  function drawExpenses(series) {
    const labels = series.map((r) => {
      const [y, m] = r.month.split('-');
      return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' });
    });
    if (!series.some((r) => r.total > 0)) {
      el('#chart-expenses').parentElement.innerHTML = emptyState('No expenses recorded yet', 'Record expenses in a project to see a trend.', 'line-chart');
      icons(el('#chart-expenses').parentElement);
      return;
    }
    chart(el('#chart-expenses'), {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Expenses', data: series.map((r) => r.total),
          borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,.14)',
          fill: true, tension: .32, borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#f59e0b',
        }],
      },
      options: { plugins: { legend: { display: false } } },
    });
  }

  function drawBudget(rows) {
    const valid = rows.filter((r) => r.approved_budget > 0).slice(0, 8);
    if (!valid.length) {
      el('#chart-budget').parentElement.innerHTML = emptyState('No approved budgets yet', 'Set a budget on a project to compare plan and actual spend.', 'bar-chart-3');
      icons(el('#chart-budget').parentElement);
      return;
    }
    chart(el('#chart-budget'), {
      type: 'bar',
      data: {
        labels: valid.map((r) => r.name.length > 22 ? r.name.slice(0, 21) + '…' : r.name),
        datasets: [
          { label: 'Approved budget', data: valid.map((r) => r.approved_budget), backgroundColor: '#142139', borderRadius: 4, maxBarThickness: 18 },
          { label: 'Actual expenses', data: valid.map((r) => r.actual_expenses), backgroundColor: '#f59e0b', borderRadius: 4, maxBarThickness: 18 },
        ],
      },
      options: { indexAxis: 'y', scales: { x: { beginAtZero: true, ticks: { callback: (v) => moneyShort(v) } }, y: { grid: { display: false } } } },
    });
  }

  function drawCategories(cats) {
    const entries = Object.entries(cats || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 7);
    if (!entries.length) {
      el('#chart-categories').parentElement.innerHTML = emptyState('No expense categories yet', '', 'pie-chart');
      icons(el('#chart-categories').parentElement);
      return;
    }
    chart(el('#chart-categories'), {
      type: 'doughnut',
      data: {
        labels: entries.map(([k]) => BB.humanize(k)),
        datasets: [{ data: entries.map(([, v]) => v), backgroundColor: BB.THEME_KEYS, borderWidth: 0, hoverOffset: 4 }],
      },
      options: {
        cutout: '58%',
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 9, boxHeight: 9, padding: 10 } },
          tooltip: { callbacks: { label: (c) => ` ${c.label}: ${money(c.raw)}` } } },
      },
    });
  }

  function drawHealth(bands) {
    const entries = Object.entries(bands || {}).filter(([, v]) => v > 0);
    if (!entries.length) {
      el('#chart-health').parentElement.innerHTML = emptyState('No projects to assess', '', 'activity');
      icons(el('#chart-health').parentElement);
      return;
    }
    const colors = { healthy: '#059669', watch: '#f59e0b', at_risk: '#dc2626' };
    chart(el('#chart-health'), {
      type: 'doughnut',
      data: {
        labels: entries.map(([k]) => BB.label('health_status', k === 'healthy' ? 'ok' : k === 'watch' ? 'warning' : 'critical')),
        datasets: [{ data: entries.map(([, v]) => v), backgroundColor: entries.map(([k]) => colors[k] || '#94a3b8'), borderWidth: 0 }],
      },
      options: { cutout: '62%', plugins: { legend: { position: 'bottom', labels: { boxWidth: 9, boxHeight: 9, padding: 10 } } } },
    });
  }

  function renderProjects(rows) {
    if (!rows.length) {
      el('#dash-projects').innerHTML = emptyState('No projects match these filters', 'Adjust the filters or create a project.', 'folder-kanban')
        + '<div style="text-align:center"><a class="btn btn-sm" href="/projects?new=1">Create project</a></div>';
      icons(el('#dash-projects'));
      return;
    }
    el('#dash-projects').innerHTML = table(rows, [
      { key: 'name', label: 'Project', render: (v, r) => `<a href="/projects/${r.id}"><strong>${esc(v)}</strong></a>
        <div class="small muted">${esc(r.project_type_label || BB.label('project_types', r.project_type))}${r.location ? ' · ' + esc(r.location) : ''}</div>` },
      { key: 'status', label: 'Status', render: (v) => statusBadge(v, v === 'archived' ? 'Archived' : BB.label('project_status', v)) },
      { key: 'progress', label: 'Progress', render: (v) => `<div style="min-width:90px">${progressBar(v)}<div class="small muted" style="margin-top:3px">${num(v, 0)}%</div></div>` },
      { key: 'utilization_pct', label: 'Budget used', align: 'right', render: (v) => v == null ? '<span class="muted">—</span>' : pct(v) },
      { key: 'actual_expenses', label: 'Spent', align: 'right', render: (v) => money(v) },
      { key: 'health', label: 'Health', render: (v) => healthBadge(v) },
    ], { compact: true });
  }

  function renderAttention(d) {
    const items = [];
    (d.overdue_task_list || []).slice(0, 3).forEach((t) => items.push({
      tone: 'critical', title: `${t.name} is ${t.days_late} day(s) late`,
      detail: `${t.project} · planned finish ${dateFmt(t.planned_end)} · ${num(t.progress, 0)}% complete`, link: `/projects/${t.project_id}?tab=schedule`,
    }));
    (d.insights || []).forEach((i) => { if (i.tone !== 'info') items.push(i); });
    if ((d.kpis.low_stock_items || 0) > 0) items.push({ tone: 'warning', title: `${d.kpis.low_stock_items} material(s) low`, detail: 'Raise a purchase requirement.', link: '/inventory' });
    const seen = new Set();
    const unique = items.filter((i) => { const k = i.title; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 5);
    el('#dash-attention').innerHTML = unique.length
      ? unique.map((i) => `<div class="insight ${esc(i.tone)}">
          <i data-lucide="${i.tone === 'critical' ? 'alert-octagon' : i.tone === 'warning' ? 'alert-triangle' : 'info'}" class="ico"></i>
          <div><b>${esc(i.title)}</b><span>${esc(i.detail || '')}</span>
          ${i.link ? ` <a href="${esc(i.link)}" class="small">Open</a>` : i.project_id ? ` <a href="/projects/${i.project_id}" class="small">Open</a>` : ''}</div>
        </div>`).join('')
      : emptyState('Nothing needs attention', 'You are up to date.', 'check-circle');
    icons(el('#dash-attention'));
  }

  function render(d) {
    data = d;
    renderKpis(d.kpis);
    drawExpenses(d.expense_series || []);
    drawBudget(d.projects || []);
    drawCategories(d.expenses_by_category);
    drawHealth(d.health_distribution);
    renderProjects(d.projects || []);
    renderAttention(d);
    el('#dash-insights').innerHTML = (d.insights || []).length
      ? d.insights.map((i) => insightCard(i)).join('')
      : emptyState('No observations yet', 'Add a project and record activity to generate insights.', 'lightbulb');

    el('#dash-upcoming').innerHTML = (d.upcoming_deadlines || []).length
      ? table(d.upcoming_deadlines, [
        { key: 'task', label: 'Task', render: (v, r) => `<a href="/projects/${r.project_id}?tab=schedule">${esc(v)}</a><div class="small muted">${esc(r.project)}</div>` },
        { key: 'due', label: 'Due', render: (v) => dateFmt(v) },
        { key: 'progress', label: 'Progress', align: 'right', render: (v) => num(v, 0) + '%' },
      ], { compact: true, empty: 'Nothing due in the next three weeks' })
      : emptyState('Nothing due soon', 'Tasks with dates in the next 21 days appear here.', 'calendar-check');

    el('#dash-overdue').innerHTML = (d.overdue_task_list || []).length
      ? table(d.overdue_task_list, [
        { key: 'name', label: 'Task', render: (v, r) => `<a href="/projects/${r.project_id}?tab=schedule">${esc(v)}</a><div class="small muted">${esc(r.project)}</div>` },
        { key: 'days_late', label: 'Days late', align: 'right', render: (v) => `<span style="color:var(--danger);font-weight:600">${num(v, 0)}</span>` },
        { key: 'progress', label: 'Progress', align: 'right', render: (v) => num(v, 0) + '%' },
      ], { compact: true })
      : emptyState('No overdue tasks', 'Every scheduled task is within its planned finish.', 'check-circle');

    el('#dash-notes').textContent = d.notes
      ? `${d.notes.estimate_scope}${d.notes.demo_data ? ' Some projects contain labelled demonstration data.' : ''}`
      : '';
    icons(document);
  }

  async function load() {
    try {
      render(await api('/dashboard?' + filters().toString()));
    } catch (err) {
      el('#kpis').innerHTML = `<div class="card" style="grid-column:1/-1">${emptyState('Dashboard could not load', err.message, 'alert-circle')}</div>`;
      icons(document);
    }
  }

  el('#dash-filters').addEventListener('submit', (e) => { e.preventDefault(); load(); });
  el('#dash-reset').addEventListener('click', () => {
    el('#dash-filters').reset();
    load();
  });
  el('#dash-export').addEventListener('click', () => {
    if (!data || !(data.projects || []).length) return BB.toast('Nothing to export for these filters.', 'warn');
    const cols = ['name', 'status', 'approved_budget', 'estimated_cost', 'actual_expenses', 'remaining_budget', 'utilization_pct', 'progress', 'health'];
    const head = ['Project', 'Status', 'Approved budget', 'Estimated BOQ', 'Actual expenses', 'Remaining', 'Utilisation %', 'Progress %', 'Health'];
    const lines = [head.join(',')].concat(data.projects.map((r) => cols.map((c) => {
      const v = r[c];
      return typeof v === 'string' && v.includes(',') ? `"${v.replace(/"/g, '""')}"` : (v == null ? '' : v);
    }).join(',')));
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'buildbudget-dashboard.csv'; a.click();
  });

  BB.ready().then(load);
  document.addEventListener('bb:theme', () => { if (data) render(data); });
})();
