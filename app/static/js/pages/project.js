/* Project workspace shell: tab routing, overview, planning and saved estimates. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, money, moneyShort, num, pct, qty, table, badge, statusBadge, healthBadge,
          progressBar, emptyState, modal, confirm: confirmDialog, toast, icons, dateFmt, timeAgo,
          field, formValues, chart, devDetails } = BB;

  const host = el('#project-host');
  if (!host) return;
  const pid = Number(host.getAttribute('data-pid'));
  const state = { tab: host.getAttribute('data-tab') || 'overview', project: null };

  const TABS = ['overview', 'planning', 'estimator', 'boq', 'budget', 'inventory', 'procurement',
    'labour', 'schedule', 'documents', 'reports', 'activity'];

  function setActive(tab) {
    els('#project-tabs .tab').forEach((b) => {
      const on = b.getAttribute('data-tab') === tab;
      b.classList.toggle('on', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }

  async function go(tab) {
    if (!TABS.includes(tab)) tab = 'overview';
    state.tab = tab;
    setActive(tab);
    const url = new URL(location.href);
    url.searchParams.set('tab', tab);
    history.replaceState({}, '', url);
    const body = document.createElement('div');
    host.replaceChildren(body);
    body.innerHTML = `<div class="card">${BB.skeleton(2, 'skeleton-card')}</div>`;
    // Re-bind the header actions that live inside tab bodies on each render.
    const renderer = ['overview', 'planning', 'estimator'].includes(tab) ? localRenderers[tab] : BB.projectTabs[tab];
    if (!renderer) {
      body.innerHTML = emptyState('Section unavailable', 'This section is not registered.', 'alert-circle');
      return;
    }
    try {
      await renderer(body, pid, state.project);
    } catch (err) {
      body.innerHTML = `<div class="card">${emptyState('Could not load this section', err.message || 'Please retry.', 'alert-circle')}
        <div style="text-align:center"><button class="btn btn-sm" type="button" id="retry-tab">Retry</button></div></div>`;
      const retry = el('#retry-tab', body);
      if (retry) retry.addEventListener('click', () => go(tab));
      icons(body);
    }
  }

  /* -------------------------------------------------------------- overview */
  const localRenderers = {};

  localRenderers.overview = async function (body, pid, project) {
    const d = await api(`/projects/${pid}/overview`);
    const p = d.project;
    document.title = `${p.name} · BuildBudget AI`;
    const sub = el('#project-sub');
    if (sub) sub.textContent = `${p.project_type_label}${p.location ? ' · ' + p.location : ''} · ${p.status_label}`;
    state.project = p;

    const b = d.budget || {};
    const kpis = [
      { label: 'Approved budget', value: moneyShort(b.approved_budget) },
      { label: 'BOQ estimate', value: moneyShort(d.boq.total), foot: `${d.boq.items} item(s) · rev ${d.boq.revision}` },
      { label: 'Actual expenses', value: moneyShort(b.actual_expenses), foot: `${d.expenses.count} recorded` },
      { label: 'Remaining', value: moneyShort(b.remaining_budget), cls: b.remaining_budget < 0 ? 'is-danger' : '' },
      { label: 'Budget used', value: b.utilization_pct == null ? '—' : pct(b.utilization_pct),
        cls: b.utilization_pct == null ? '' : b.utilization_pct >= 90 ? 'is-danger' : b.utilization_pct >= 75 ? 'is-warning' : 'is-success' },
      { label: 'Progress', value: num(d.schedule.progress, 0) + '%', foot: `${d.schedule.tasks} task(s)` },
      { label: 'Health', value: `${d.health.score}/100`, foot: BB.label('health_status', d.health.band) },
      { label: 'Pending approvals', value: d.pending_approvals, cls: d.pending_approvals ? 'is-warning' : '' },
    ];
    body.innerHTML = `
      <div class="grid grid-kpi">${kpis.map((k) => `<div class="kpi ${k.cls || ''}">
        <div class="label">${esc(k.label)}</div><div class="value">${typeof k.value === 'number' ? num(k.value, 0) : esc(k.value)}</div>
        ${k.foot ? `<div class="foot">${esc(k.foot)}</div>` : ''}</div>`).join('')}</div>

      <div class="grid grid-side" style="margin-top:16px">
        <div class="stack">
          <div class="card">
            <div class="card-head"><h2>Project position</h2><div class="spacer"></div>
              ${p.is_demo ? '<span class="badge demonstration">Demonstration data</span>' : ''}</div>
            <dl class="dl">
              <dt>Status</dt><dd>${statusBadge(p.status, p.status_label)}</dd>
              <dt>Project type</dt><dd>${esc(p.project_type_label)}</dd>
              <dt>Location</dt><dd>${esc(p.location || '—')}</dd>
              <dt>Manager</dt><dd>${esc(p.manager_name || '—')}${p.manager_email ? `<div class="small muted">${esc(p.manager_email)}</div>` : ''}</dd>
              <dt>Contractor</dt><dd>${esc(p.contractor || '—')}</dd>
              <dt>Start</dt><dd>${dateFmt(p.start_date)}</dd>
              <dt>Expected completion</dt><dd>${dateFmt(p.end_date)}</dd>
              <dt>Planned schedule finish</dt><dd>${dateFmt(d.schedule.planned_finish)}</dd>
              <dt>Documents</dt><dd>${num(d.documents, 0)}</dd>
            </dl>
            ${p.description ? `<p class="small" style="margin-top:12px">${esc(p.description)}</p>` : ''}
            ${p.assumptions ? `<details class="disclosure" style="margin-top:8px"><summary>Assumptions</summary><div class="body">${esc(p.assumptions)}</div></details>` : ''}
          </div>
          <div class="card">
            <div class="card-head"><h2>Budget by category</h2><div class="spacer"></div>
              <a class="small" href="?tab=budget">Open budget</a></div>
            ${Object.keys(b.expenses_by_category || {}).length ? '<div class="chart-box"><canvas id="proj-cats"></canvas></div>'
              : emptyState('No expenses yet', 'Record expenses to see the category split.', 'pie-chart')}
          </div>
          <div class="card">
            <div class="card-head"><h2>Recent expenses</h2><div class="spacer"></div><a class="small" href="?tab=budget">All expenses</a></div>
            ${(d.expenses.recent || []).length ? table(d.expenses.recent, [
              { key: 'date', label: 'Date', render: (v) => dateFmt(v) },
              { key: 'category', label: 'Category' },
              { key: 'description', label: 'Description', render: (v) => esc(v || '—') },
              { key: 'amount', label: 'Amount', align: 'right', render: (v) => money(v) },
            ], { compact: true }) : emptyState('No expenses recorded', '', 'receipt')}
          </div>
        </div>
        <div class="stack">
          <div class="card"><div class="card-head"><h3>Insights</h3></div>
            ${(d.insights || []).map((i) => `<div class="insight ${esc(i.tone)}">
              <i data-lucide="${i.tone === 'critical' ? 'alert-octagon' : i.tone === 'warning' ? 'alert-triangle' : 'info'}" class="ico"></i>
              <div><b>${esc(i.title)}</b><span>${esc(i.detail || '')}</span></div></div>`).join('') || '<p class="small muted">No observations.</p>'}
          </div>
          <div class="card"><div class="card-head"><h3>Stock</h3><div class="spacer"></div>
              <a class="small" href="?tab=inventory">Inventory</a></div>
            <div class="stat-inline"><div><div class="k">Tracked</div><div class="v">${d.inventory.items}</div></div>
              <div><div class="k">Low stock</div><div class="v" style="${d.inventory.low_stock ? 'color:var(--danger)' : ''}">${d.inventory.low_stock}</div></div></div>
            ${(d.inventory.low || []).length ? `<ul class="small" style="margin:10px 0 0 16px">${d.inventory.low.map((i) =>
              `<li>${esc(i.material_name)} — ${num(i.available, 2)} ${esc(i.unit)} left</li>`).join('')}</ul>` : '<p class="small muted" style="margin:8px 0 0">Nothing below its reorder level.</p>'}
          </div>
          <div class="card"><div class="card-head"><h3>Labour</h3><div class="spacer"></div>
              <a class="small" href="?tab=labour">Labour</a></div>
            <div class="stat-inline"><div><div class="k">Recorded cost</div><div class="v">${moneyShort(d.labour.total_cost)}</div></div>
              <div><div class="k">Worker-days</div><div class="v">${num(d.labour.worker_days, 1)}</div></div></div>
          </div>
          <div class="card"><div class="card-head"><h3>Recent activity</h3><div class="spacer"></div>
              <a class="small" href="?tab=activity">All</a></div>
            ${(d.recent_activity || []).length ? `<ul class="timeline">${d.recent_activity.map((r) =>
              `<li><div>${esc(BB.humanize(r.action))}${r.summary ? ' — ' + esc(r.summary) : ''}</div>
              <div class="when">${timeAgo(r.when)}</div></li>`).join('')}</ul>` : '<p class="small muted">No activity yet.</p>'}
          </div>
        </div>
      </div>`;

    if (Object.keys(b.expenses_by_category || {}).length) {
      const entries = Object.entries(b.expenses_by_category).filter(([, v]) => v > 0);
      chart(el('#proj-cats'), {
        type: 'doughnut',
        data: { labels: entries.map(([k]) => BB.humanize(k)), datasets: [{ data: entries.map(([, v]) => v), backgroundColor: BB.THEME_KEYS, borderWidth: 0 }] },
        options: { cutout: '58%', plugins: { legend: { position: 'bottom' } } },
      });
    }
    icons(body);
  };

  /* -------------------------------------------------------------- planning */
  localRenderers.planning = async function (body, pid) {
    const rooms = await api(`/projects/${pid}/rooms`);
    body.innerHTML = `
      <div class="card">
        <div class="card-head"><h2>Rooms and measurements</h2><div class="spacer"></div>
          <button class="btn btn-sm" type="button" id="add-room">Add room</button></div>
        <p class="small muted" style="margin-top:-6px">Every area is calculated in Python from the dimensions you enter.
        Openings are subtracted from the gross wall area.</p>
        ${rooms.length ? rooms.map((r) => `<div class="card" style="box-shadow:none;margin-top:12px">
          <div class="card-head"><h3>${esc(r.name)}</h3>
            <span class="badge">${num(r.length, 2)} × ${num(r.width, 2)} × ${num(r.height, 2)} ${esc(r.unit)}</span>
            <div class="spacer"></div>
            <div class="btn-group">
              <button class="btn btn-ghost btn-sm" type="button" data-estimate-room="${r.id}">Estimate this room</button>
              <button class="btn btn-ghost btn-sm" type="button" data-del-room="${r.id}">Remove</button>
            </div></div>
          <div class="grid grid-2">
            <div>${table([
              { m: 'Floor area', v: `${num(r.geometry.floor_area_sqft, 2)} sq. ft.` },
              { m: 'Ceiling area', v: `${num(r.geometry.ceiling_area_sqft, 2)} sq. ft.` },
              { m: 'Gross wall area', v: `${num(r.geometry.gross_wall_area_sqft, 2)} sq. ft.` },
              { m: 'Openings area', v: `${num(r.geometry.openings_area_sqft, 2)} sq. ft.` },
              { m: 'Net wall area', v: `${num(r.geometry.net_wall_area_sqft, 2)} sq. ft.` },
              { m: 'Floor area (metric)', v: `${num(r.geometry.floor_area_sqm, 2)} m²` },
            ], [{ key: 'm', label: 'Measurement' }, { key: 'v', label: 'Result', align: 'right' }], { compact: true })}</div>
            <div>
              ${(r.openings || []).length ? `<div class="label" style="margin-bottom:4px">Openings</div>
                ${table(r.openings.map((o, i) => ({ ...o, n: i + 1 })), [
                  { key: 'n', label: '#' }, { key: 'width', label: 'Width' }, { key: 'height', label: 'Height' },
                  { key: 'count', label: 'Count', align: 'right' }], { compact: true })}` : '<p class="small muted">No door or window openings recorded.</p>'}
              ${r.notes ? `<p class="small" style="margin-top:8px">${esc(r.notes)}</p>` : ''}
              <details class="disclosure" style="margin-top:10px"><summary>Calculation method</summary>
                <div class="body">${esc(r.geometry.formula)}
                <div class="small muted" style="margin-top:6px">Dimensions converted to feet first: ${num(r.geometry.inputs.length_ft, 2)} × ${num(r.geometry.inputs.width_ft, 2)} × ${num(r.geometry.inputs.height_ft, 2)} ft.</div></div></details>
            </div>
          </div>
        </div>`).join('') : emptyState('No rooms yet', 'Add the room dimensions once and reuse them for tiles, paint, plaster and brickwork.', 'ruler')}
      </div>`;

    el('#add-room', body).addEventListener('click', () => openRoomForm(body, pid));

    body.addEventListener('click', async (e) => {
      const del = e.target.closest('[data-del-room]');
      if (del) {
        if (!await confirmDialog({ title: 'Remove this room?', message: 'Only the saved measurement is removed; estimates already added to the BOQ are unaffected.', confirmText: 'Remove', danger: true })) return;
        await api(`/projects/${pid}/rooms/${del.getAttribute('data-del-room')}`, { method: 'DELETE' });
        go('planning');
      }
      const est = e.target.closest('[data-estimate-room]');
      if (est) {
        const room = rooms.find((r) => r.id === Number(est.getAttribute('data-estimate-room')));
        sessionStorage.setItem('bb-room', JSON.stringify({
          name: room.name, length: room.length, width: room.width, height: room.height,
          unit: room.unit, openings: room.openings, project_id: pid,
        }));
        location.href = `/estimator?project=${pid}&fromRoom=1`;
      }
    });
  };

  function openRoomForm(body, pid) {
    let openingCount = 0;
    const openingRow = () => `<div class="opening-row form-grid" data-opening="${openingCount++}" style="margin-bottom:8px">
      ${field('o_width_' + openingCount, 'Width', { type: 'number', step: '0.01', min: 0 })}
      ${field('o_height_' + openingCount, 'Height', { type: 'number', step: '0.01', min: 0 })}
      ${field('o_count_' + openingCount, 'Count', { type: 'number', min: 1, value: 1 })}
      <div style="display:flex;align-items:flex-end"><button class="btn btn-ghost btn-sm" type="button" data-remove-opening>Remove</button></div>
    </div>`;
    modal({
      title: 'Add a room',
      wide: true,
      body: `<form id="room-form">
        <div class="form-grid">
          ${field('name', 'Room name', { value: 'Room', required: true })}
          ${field('length', 'Length', { type: 'number', step: '0.01', min: 0, required: true, value: 12 })}
          ${field('width', 'Width', { type: 'number', step: '0.01', min: 0, required: true, value: 15 })}
          ${field('height', 'Height', { type: 'number', step: '0.01', min: 0, required: true, value: 10 })}
          ${field('unit', 'Unit', { options: [{ value: 'ft', label: 'Feet' }, { value: 'm', label: 'Metres' }, { value: 'in', label: 'Inches' }, { value: 'cm', label: 'Centimetres' }] })}
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin:14px 0 6px"><strong>Door and window openings</strong>
          <div style="flex:1"></div><button class="btn btn-ghost btn-sm" type="button" id="add-opening">Add opening</button></div>
        <div id="openings"></div>
        ${field('notes', 'Notes', { textarea: true, rows: 2 })}
        <div class="card" id="room-preview" style="box-shadow:none;margin-top:12px;background:var(--surface-2)">
          <p class="small muted" style="margin:0">Adjust the dimensions to preview the calculated areas.</p></div>
      </form>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Save room</button>`,
      onMount: (root) => {
        const form = el('#room-form', root);
        el('#add-opening', root).addEventListener('click', () => el('#openings', root).insertAdjacentHTML('beforeend', openingRow()));
        el('#openings', root).addEventListener('click', (e) => {
          const b = e.target.closest('[data-remove-opening]');
          if (b) b.closest('.opening-row').remove();
        });
        let timer = null;
        const preview = () => {
          const v = formValues(form);
          const openings = collectOpenings(root);
          const values = [v.length, v.width, v.height].map(Number);
          if (values.some((x) => !x || x <= 0)) {
            el('#room-preview', root).innerHTML = '<p class="small muted" style="margin:0">Enter length, width and height greater than zero.</p>';
            return;
          }
          api('/estimates/room-geometry', {
            method: 'POST', silent: true,
            body: { length: values[0], width: values[1], height: values[2], unit: v.unit, openings },
          }).then((g) => {
            el('#room-preview', root).innerHTML = `<div class="small"><strong>Floor area</strong> ${num(g.floor_area_sqft, 2)} sq. ft.
              (${num(g.floor_area_sqm, 2)} m²) · <strong>Net wall area</strong> ${num(g.net_wall_area_sqft, 2)} sq. ft.
              · <strong>Gross wall</strong> ${num(g.gross_wall_area_sqft, 2)} sq. ft. · <strong>Openings</strong> ${num(g.openings_area_sqft, 2)} sq. ft.</div>`;
          }).catch((err) => {
            el('#room-preview', root).innerHTML = `<div class="small" style="color:var(--danger)">${esc(err.message)}</div>`;
          });
        };
        form.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(preview, 300); });
        preview();
      },
      onResult: (value, root) => {
        if (value !== 'save') return true;
        const v = formValues(el('#room-form', root));
        const body = {
          name: v.name || 'Room', length: Number(v.length), width: Number(v.width), height: Number(v.height),
          unit: v.unit, openings: collectOpenings(root), notes: v.notes || '',
        };
        if (!body.length || !body.width || !body.height) { toast('Length, width and height are required.', 'error'); return false; }
        api(`/projects/${pid}/rooms`, { method: 'POST', body })
          .then(() => { toast('Room saved.', 'success'); go('planning'); }).catch(() => {});
        return true;
      },
    });
  }

  function collectOpenings(root) {
    const out = [];
    els('.opening-row', root).forEach((row) => {
      const inputs = Array.from(row.querySelectorAll('input'));
      const width = Number(inputs[0].value), height = Number(inputs[1].value), count = Number(inputs[2].value || 1);
      if (width > 0 && height > 0) out.push({ width, height, count: Math.max(1, count) });
    });
    return out;
  }

  /* ------------------------------------------------------------- estimator */
  localRenderers.estimator = async function (body, pid) {
    const rows = await api(`/projects/${pid}/estimations`);
    body.innerHTML = `<div class="card">
      <div class="card-head"><h2>Saved estimation scenarios</h2><div class="spacer"></div>
        <a class="btn btn-sm" href="/estimator?project=${pid}">Open cost estimator</a></div>
      <p class="small muted" style="margin-top:-6px">Scenarios store the exact inputs and deterministic result, so you can
      compare options later. Nothing here is a quotation.</p>
      ${rows.length ? table(rows, [
        { key: 'name', label: 'Scenario', render: (v, r) => `<strong>${esc(v)}</strong><div class="small muted">${esc(BB.humanize(r.kind))}</div>` },
        { key: 'result', label: 'Quantity', align: 'right', render: (v) => v && v.final_quantity != null ? `${num(v.final_quantity, 2)} ${esc(v.unit || '')}` : '—' },
        { key: 'total', label: 'Estimate', align: 'right', render: (v) => v > 0 ? money(v) : '<span class="muted">No rate</span>' },
        { key: 'created_at', label: 'Saved', render: (v) => dateFmt(v, true) },
        { key: 'id', label: '', render: (v, r) => `<div class="btn-group">
            <button class="btn btn-ghost btn-sm" type="button" data-to-boq="${v}">Add to BOQ</button>
            <button class="btn btn-ghost btn-sm" type="button" data-del-est="${v}">Delete</button></div>` },
      ], { compact: true }) : emptyState('No saved scenarios', 'Calculate a quantity in the estimator and save it to compare alternatives here.', 'calculator')}
    </div>`;
    body.addEventListener('click', async (e) => {
      const add = e.target.closest('[data-to-boq]');
      if (add) {
        const row = rows.find((r) => r.id === Number(add.getAttribute('data-to-boq')));
        await modal({
          title: 'Add estimated quantity to the BOQ',
          body: `<form id="to-boq-form">
            <div class="small muted" style="margin-bottom:10px">Quantity: <strong>${num(row.result.final_quantity, 2)} ${esc(row.result.unit || '')}</strong>
              — ${esc(row.result.item || '')}. Formula: ${esc(row.result.formula || '')}</div>
            <div class="form-grid">
              ${field('material_name', 'Material name for price lookup', { required: true, value: row.result.item || '' })}
              ${field('category', 'BOQ category', { value: 'Finishing' })}
              ${field('unit_rate', 'Unit rate (₹)', { type: 'number', step: '0.01', min: 0, hint: 'Leave blank to use the latest stored supplier price; if none exists the item is rejected rather than invented.' })}
              ${field('labour_cost', 'Labour cost (₹)', { type: 'number', step: '0.01', min: 0, value: 0 })}
              ${field('transport_cost', 'Transport (₹)', { type: 'number', step: '0.01', min: 0, value: 0 })}
              ${field('discount_pct', 'Discount %', { type: 'number', step: '0.01', min: 0, max: 100, value: 0 })}
              ${field('tax_pct', 'Tax %', { type: 'number', step: '0.01', min: 0, max: 100, hint: 'Leave blank to inherit the quotation tax rate.' })}
            </div></form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Add to BOQ</button>`,
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const v = formValues(el('#to-boq-form', root));
            const body = { kind: row.kind, params: row.params, material_name: v.material_name, category: v.category || 'Finishing' };
            ['unit_rate', 'tax_pct'].forEach((k) => { if (v[k] !== null && v[k] !== '') body[k] = Number(v[k]); });
            ['labour_cost', 'transport_cost', 'discount_pct'].forEach((k) => { body[k] = Number(v[k] || 0); });
            api(`/projects/${pid}/boq/from-estimate`, { method: 'POST', body })
              .then((r) => { toast(`Added ${r.item.description} to the BOQ.`, 'success'); go('boq'); }).catch(() => {});
            return true;
          },
        });
      }
      const del = e.target.closest('[data-del-est]');
      if (del) {
        if (!await confirmDialog({ title: 'Delete this scenario?', message: 'Saved inputs and results will be removed.', confirmText: 'Delete', danger: true })) return;
        await api(`/projects/${pid}/estimations/${del.getAttribute('data-del-est')}`, { method: 'DELETE' });
        go('estimator');
      }
    });
  };

  /* ---------------------------------------------------------------- header */
  els('#project-tabs .tab').forEach((b) => {
    b.addEventListener('click', () => go(b.getAttribute('data-tab')));
  });

  el('#project-archive').addEventListener('click', async () => {
    if (!state.project) return;
    if (!await confirmDialog({ title: 'Archive this project?', message: `${state.project.name} will be hidden from active lists. All records are kept and it can be restored.`, confirmText: 'Archive' })) return;
    await api(`/projects/${pid}/archive`, { method: 'POST' });
    toast('Project archived.', 'success');
    location.href = '/projects';
  });

  el('#project-edit').addEventListener('click', async () => {
    const p = state.project || await api(`/projects/${pid}`);
    const types = Object.entries(BB.labels.project_types || {}).filter(([k]) => k !== 'painting');
    await modal({
      title: 'Edit project',
      wide: true,
      body: `<form id="pedit-form"><div class="form-grid">
        ${field('name', 'Project name', { required: true, value: p.name })}
        ${field('project_type', 'Project type', { value: p.project_type, options: types.map(([k, v]) => ({ value: k, label: v })) })}
        ${field('status', 'Status', { value: p.status, options: Object.entries(BB.labels.project_status || {}).filter(([k]) => k !== 'archived').map(([k, v]) => ({ value: k, label: v })) })}
        ${field('location', 'Location', { value: p.location })}
        ${field('budget', 'Approved budget (₹)', { type: 'number', min: 0, step: '0.01', value: p.budget })}
        ${field('start_date', 'Start date', { type: 'date', value: p.start_date })}
        ${field('end_date', 'Expected completion', { type: 'date', value: p.end_date })}
        ${field('manager_name', 'Project manager', { value: p.manager_name })}
        ${field('manager_email', 'Manager email', { type: 'email', value: p.manager_email })}
        ${field('contractor', 'Contractor', { value: p.contractor })}
        ${field('latitude', 'Latitude', { type: 'number', step: '0.000001', value: p.latitude })}
        ${field('longitude', 'Longitude', { type: 'number', step: '0.000001', value: p.longitude })}
        ${field('description', 'Scope description', { textarea: true, rows: 2, value: p.description })}
        ${field('assumptions', 'Assumptions', { textarea: true, rows: 2, value: p.assumptions })}
      </div></form>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Save changes</button>`,
      onResult: (value, root) => {
        if (value !== 'save') return true;
        const body = formValues(el('#pedit-form', root));
        body.budget = Number(body.budget || 0);
        ['latitude', 'longitude'].forEach((k) => { if (body[k] === null || body[k] === '') delete body[k]; });
        api(`/projects/${pid}`, { method: 'PUT', body })
          .then((updated) => {
            state.project = updated;
            toast('Project updated.', 'success');
            const h = el('.page-head h1');
            if (h) h.textContent = updated.name;
            go(state.tab);
          }).catch(() => {});
        return true;
      },
    });
  });

  BB.project = { pid, go, state };
  BB.ready().then(() => {
    go(state.tab);
    document.addEventListener('bb:project-change', (e) => {
      if (e.detail && e.detail !== pid) location.href = `/projects/${e.detail}`;
    });
  });
})();
