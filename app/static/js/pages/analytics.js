/* Analytics workspace: trend, OLS forecast with holdout metrics, anomalies, risk, health. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, money, moneyShort, num, pct, table, badge, emptyState, chart, icons, dateFmt, humanize } = BB;

  function monthLabel(key) {
    if (!key) return '';
    const [y, m] = key.split('-');
    return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' });
  }

  function insufficient(title, message) {
    return `<div class="insight info"><i data-lucide="info" class="ico"></i><div><b>${esc(title)}</b><span>${esc(message)}</span></div></div>`;
  }

  function render(data) {
    const series = data.expense_series || [];
    const total = series.reduce((a, r) => a + r.total, 0);
    const positive = series.filter((r) => r.total > 0);
    const latest = positive.length ? positive[positive.length - 1].total : 0;
    const avg = positive.length ? total / positive.length : 0;
    const fc = data.forecast || {};
    el('#an-kpis').innerHTML = [
      { label: 'Recorded spend', value: moneyShort(total), foot: `${positive.length} month(s) with expenses` },
      { label: 'Monthly average', value: moneyShort(avg) },
      { label: 'Latest month', value: moneyShort(latest) },
      { label: 'Forecast next total', value: fc.sufficient ? moneyShort(fc.expected_total || 0) : '—',
        foot: fc.sufficient ? `${(fc.forecast || []).length} month horizon` : 'Insufficient history' },
      { label: 'Anomalies flagged', value: (data.anomalies && data.anomalies.anomalies || []).length,
        cls: (data.anomalies && data.anomalies.anomalies || []).length ? 'is-warning' : '' },
      { label: 'High budget risk', value: (data.budget_risk || []).filter((r) => r.risk === 'high').length,
        cls: (data.budget_risk || []).some((r) => r.risk === 'high') ? 'is-danger' : '' },
    ].map((k) => `<div class="kpi ${k.cls || ''}"><div class="label">${esc(k.label)}</div>
      <div class="value">${typeof k.value === 'string' ? esc(k.value) : num(k.value, 0)}</div>
      ${k.foot ? `<div class="foot">${esc(k.foot)}</div>` : ''}</div>`).join('');

    const labels = series.map((r) => monthLabel(r.month));
    const actual = series.map((r) => r.total);
    const forecastVals = series.map(() => null);
    if (fc.sufficient && (fc.forecast || []).length) {
      const last = series.length ? series[series.length - 1].month : null;
      let y = 2024, m = 1;
      if (last) { y = Number(last.split('-')[0]); m = Number(last.split('-')[1]); }
      (fc.forecast || []).forEach((v, i) => {
        const d = new Date(y, m + i, 1);
        labels.push(d.toLocaleDateString('en-IN', { month: 'short', year: '2-digit' }));
        actual.push(null);
        forecastVals.push(v);
      });
      forecastVals[series.length - 1] = actual[series.length - 1];
    }
    if (series.some((r) => r.total > 0)) {
      const sets = [{ label: 'Recorded expenses', data: actual, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,.12)', fill: true, tension: .3, borderWidth: 2, pointRadius: 3 }];
      if (fc.sufficient) sets.push({ label: 'Forecast', data: forecastVals, borderColor: '#142139', borderDash: [6, 4], fill: false, tension: .25, borderWidth: 2, pointRadius: 3 });
      chart(el('#an-series'), {
        type: 'line',
        data: { labels, datasets: sets },
        options: { plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${money(c.raw)}` } } } },
      });
    } else {
      el('#an-series').parentElement.innerHTML = emptyState('No expenses recorded yet', 'Analytics begins as soon as expenses exist.', 'chart-line');
      icons(el('#an-series').parentElement);
    }

    const trend = data.trend || {};
    el('#an-trend').innerHTML = trend.sufficient
      ? `<div class="insight ${trend.direction === 'rising' ? 'warning' : 'info'}"><i data-lucide="trending-up" class="ico"></i>
          <div><b>${esc(trend.message)}</b><span>${esc(trend.limitation || '')}</span></div></div>`
      : insufficient('Trend not available', trend.message || 'Not enough history.');

    el('#an-forecast').innerHTML = fc.sufficient ? `
      <dl class="dl">
        <dt>Method</dt><dd>${esc(fc.method || 'Ordinary least squares')}</dd>
        <dt>Horizon</dt><dd>${(fc.forecast || []).length} months</dd>
        <dt>Forecast total</dt><dd>${money(fc.expected_total || 0)}</dd>
        <dt>Holdout MAE</dt><dd>${fc.mae != null ? money(fc.mae) : '—'}</dd>
        <dt>Holdout MAPE</dt><dd>${fc.mape != null ? pct(fc.mape) : '—'}</dd>
      </dl>
      ${table((fc.forecast || []).map((v, i) => ({ n: i + 1, v })), [
        { key: 'n', label: 'Month ahead' }, { key: 'v', label: 'Forecast', align: 'right', render: (x) => money(x) }], { compact: true })}
      <p class="small muted" style="margin-top:8px">${esc(fc.limitation || 'A statistical baseline, not a guarantee.')}</p>`
      : insufficient('Insufficient data for reliable forecasting', fc.message || 'Record more months of expenses.');

    const an = data.anomalies || {};
    el('#an-anomalies').innerHTML = (an.anomalies || []).length ? table(an.anomalies, [
      { key: 'date', label: 'Date', render: (v) => dateFmt(v) },
      { key: 'category', label: 'Category' },
      { key: 'amount', label: 'Amount', align: 'right', render: (v) => money(v) },
      { key: 'score', label: 'Deviation', align: 'right', render: (v) => num(v, 1) + 'σ' },
      { key: 'reason', label: 'Why flagged', render: (v, r) => esc(v) + `<div class="small muted">${esc(r.project || '')}${r.vendor ? ' · ' + esc(r.vendor) : ''}</div>` },
    ], { compact: true }) : insufficient('No anomalies detected', an.message || 'The robust z-score test found nothing unusual.');

    el('#an-risk').innerHTML = (data.budget_risk || []).length ? table(data.budget_risk, [
      { key: 'project', label: 'Project' },
      { key: 'risk', label: 'Risk', render: (v) => badge(BB.humanize(v), v === 'high' ? 'critical' : v === 'medium' ? 'warning' : v === 'low' ? 'ok' : 'info') },
      { key: 'projected_total', label: 'Projected', align: 'right', render: (v) => v == null ? '—' : money(v) },
      { key: 'budget', label: 'Budget', align: 'right', render: (v) => v == null ? '—' : money(v) },
      { key: 'message', label: 'Assessment', render: (v) => `<span class="small">${esc(v)}</span>` },
    ], { compact: true }) : emptyState('No projects to assess', '', 'shield');

    el('#an-health').innerHTML = (data.health || []).length ? table(data.health, [
      { key: 'project', label: 'Project' },
      { key: 'score', label: 'Score', align: 'right', render: (v) => `${num(v, 0)}/100` },
      { key: 'band', label: 'Band', render: (v) => badge(BB.label('health_status', v === 'healthy' ? 'ok' : v === 'watch' ? 'warning' : 'critical'), v === 'healthy' ? 'ok' : v === 'watch' ? 'warning' : 'critical') },
      { key: 'factors', label: 'Factors', render: (v) => `<span class="small">${(v || []).map((f) => Array.isArray(f) ? f[0] : f).map(esc).join('; ')}</span>` },
    ], { compact: true }) : emptyState('No health scores yet', '', 'activity');

    el('#an-consumption').innerHTML = (data.consumption || []).length ? table(data.consumption, [
      { key: 'material', label: 'Material' }, { key: 'unit', label: 'Unit' },
      { key: 'consumed', label: 'Consumed', align: 'right', render: (v) => num(v, 2) },
    ], { compact: true }) : insufficient('No consumption recorded', 'Stock-out transactions build this view.');

    const sup = data.suppliers || {};
    el('#an-suppliers').innerHTML = (sup.rows || []).length ? table(sup.rows, [
      { key: 'supplier', label: 'Supplier' },
      { key: 'orders', label: 'Orders', align: 'right' },
      { key: 'delivered', label: 'Delivered', align: 'right' },
      { key: 'on_time_pct', label: 'On time', align: 'right', render: (v) => v == null ? '<span class="muted">Not scored</span>' : pct(v) },
      { key: 'note', label: 'Note', render: (v) => `<span class="small muted">${esc(v || '')}</span>` },
    ], { compact: true }) + (sup.sufficient ? '' : `<p class="small muted" style="margin-top:8px">${esc(sup.message || '')}</p>`)
      : emptyState('No supplier history', 'Record purchase orders and deliveries to score performance.', 'truck');

    el('#an-methods').innerHTML = (data.method_notes || []).map((m) => `<li>${esc(m)}</li>`).join('')
      + '<li>All figures come from your recorded data. Insufficient history is reported instead of guessed.</li>';
    icons(document);
    const note = el('#an-trend-note');
    if (note) note.textContent = trend.sufficient ? `R² ${num(trend.r_squared, 2)} · ${trend.months_used} months` : 'Awaiting history';
  }

  async function load() {
    const p = new URLSearchParams({ months: el('#an-months').value });
    if (el('#an-project').value) p.set('project_id', el('#an-project').value);
    try { render(await api('/analytics?' + p.toString())); }
    catch (err) {
      el('#an-kpis').innerHTML = `<div class="card" style="grid-column:1/-1">${emptyState('Analytics could not load', err.message, 'alert-circle')}</div>`;
      icons(el('#an-kpis'));
    }
  }

  el('#an-project').addEventListener('change', load);
  el('#an-months').addEventListener('change', load);
  BB.ready().then(load);
})();
