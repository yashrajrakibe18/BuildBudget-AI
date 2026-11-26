/* My Projects: card/table views, filtering, creation and lifecycle actions. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, money, moneyShort, num, pct, table, statusBadge, progressBar,
          emptyState, modal, confirm: confirmDialog, toast, icons, dateFmt, field, formValues } = BB;

  let projects = [];
  let view = 'cards';

  const TYPES = () => (BB.labels.project_types || {});
  const STATUSES = () => (BB.labels.project_status || {});

  function filtered() {
    const q = (el('#p-q').value || '').toLowerCase().trim();
    const status = el('#p-status').value;
    const type = el('#p-type').value;
    const sort = el('#p-sort').value;
    let rows = projects.slice();
    if (q) rows = rows.filter((p) => (p.name + ' ' + (p.location || '')).toLowerCase().includes(q));
    if (status) rows = rows.filter((p) => p.status === status);
    if (type) rows = rows.filter((p) => p.project_type === type);
    const sorts = {
      recent: (a, b) => b.id - a.id,
      name: (a, b) => a.name.localeCompare(b.name),
      budget: (a, b) => (b.approved_budget || 0) - (a.approved_budget || 0),
      utilisation: (a, b) => (b.utilization_pct || -1) - (a.utilization_pct || -1),
      progress: (a, b) => (a.progress || 0) - (b.progress || 0),
    };
    return rows.sort(sorts[sort] || sorts.recent);
  }

  function card(p) {
    const util = p.utilization_pct;
    return `<article class="card" style="display:flex;flex-direction:column;gap:10px">
      <div style="display:flex;gap:8px;align-items:flex-start">
        <div style="min-width:0;flex:1">
          <h3 style="margin:0"><a href="/projects/${p.id}">${esc(p.name)}</a></h3>
          <div class="small muted">${esc(p.project_type_label || TYPES()[p.project_type] || 'Custom Project')}
            ${p.location ? ' · ' + esc(p.location) : ''}</div>
        </div>
        ${p.is_demo ? '<span class="badge demonstration">Demo</span>' : ''}
        ${p.archived ? '<span class="badge archived">Archived</span>' : statusBadge(p.status, p.status_label)}
      </div>
      <div>
        <div class="progress-label"><span>Budget used</span>
          <span>${util == null ? 'No budget' : pct(util)}</span></div>
        ${progressBar(util || 0, util >= 100 ? 'bad' : util >= 75 ? 'warn' : '')}
      </div>
      <div class="stat-inline">
        <div><div class="k">Budget</div><div class="v">${moneyShort(p.approved_budget)}</div></div>
        <div><div class="k">Spent</div><div class="v">${moneyShort(p.actual_expenses)}</div></div>
        <div><div class="k">Progress</div><div class="v">${num(p.progress || 0, 0)}%</div></div>
      </div>
      <div class="small muted" style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <span>${p.start_date ? 'Start ' + dateFmt(p.start_date) : 'No start date'}</span>
        <span>${p.end_date ? 'Target ' + dateFmt(p.end_date) : 'No target date'}</span>
      </div>
      <div class="btn-group" style="margin-top:auto">
        <a class="btn btn-sm" href="/projects/${p.id}">Open workspace</a>
        <button class="btn btn-ghost btn-sm" type="button" data-edit="${p.id}">Edit</button>
        ${p.archived
          ? `<button class="btn btn-ghost btn-sm" type="button" data-restore="${p.id}">Restore</button>`
          : `<button class="btn btn-ghost btn-sm" type="button" data-archive="${p.id}">Archive</button>`}
        <button class="btn btn-ghost btn-sm" type="button" data-delete="${p.id}" title="Delete permanently">Delete</button>
      </div>
    </article>`;
  }

  function render() {
    const rows = filtered();
    const host = el('#projects-host');
    if (!rows.length) {
      host.innerHTML = `<div class="card">${emptyState(
        projects.length ? 'No projects match these filters' : 'Create your first project',
        projects.length ? 'Try clearing the filters.' : 'A project holds rooms, estimates, BOQ, budget, stock and schedule together.',
        'folder-kanban')}
        <div style="text-align:center">${projects.length ? '' : '<button class="btn btn-accent" type="button" id="empty-new">New project</button>'}</div></div>`;
      const b = el('#empty-new'); if (b) b.addEventListener('click', () => openForm());
      icons(host);
      return;
    }
    if (view === 'table') {
      host.innerHTML = table(rows, [
        { key: 'name', label: 'Project', render: (v, r) => `<a href="/projects/${r.id}"><strong>${esc(v)}</strong></a>
          <div class="small muted">${esc(r.project_type_label || TYPES()[r.project_type] || '')}</div>` },
        { key: 'location', label: 'Location', render: (v) => esc(v || '—') },
        { key: 'status', label: 'Status', render: (v, r) => r.archived ? '<span class="badge archived">Archived</span>' : statusBadge(v, r.status_label) },
        { key: 'approved_budget', label: 'Budget', align: 'right', render: (v) => money(v) },
        { key: 'actual_expenses', label: 'Spent', align: 'right', render: (v) => money(v) },
        { key: 'utilization_pct', label: 'Used', align: 'right', render: (v) => v == null ? '—' : pct(v) },
        { key: 'progress', label: 'Progress', align: 'right', render: (v) => num(v || 0, 0) + '%' },
        { key: 'end_date', label: 'Target', render: (v) => dateFmt(v) },
        { key: 'id', label: '', render: (v, r) => `<a class="btn btn-ghost btn-sm" href="/projects/${v}">Open</a>` },
      ]);
      return;
    }
    host.innerHTML = `<div class="grid grid-3">${rows.map(card).join('')}</div>`;
    icons(host);
  }

  function formBody(p) {
    p = p || {};
    const types = Object.entries(TYPES()).filter(([k]) => k !== 'painting');
    return `<form id="project-form" novalidate>
      <fieldset><legend>Basics</legend>
        <div class="form-grid">
          ${field('name', 'Project name', { required: true, value: p.name, placeholder: 'e.g. 12×15 room renovation' })}
          ${field('project_type', 'Project type', { value: p.project_type || 'single_room', options: types.map(([k, v]) => ({ value: k, label: v })) })}
          ${field('location', 'Location', { value: p.location, placeholder: 'City or site name' })}
          ${field('status', 'Status', { value: p.status || 'planning', options: Object.entries(STATUSES()).filter(([k]) => k !== 'archived').map(([k, v]) => ({ value: k, label: v })) })}
        </div>
      </fieldset>
      <fieldset><legend>Budget and timeline</legend>
        <div class="form-grid">
          ${field('budget', 'Approved budget (₹)', { type: 'number', min: 0, step: '0.01', value: p.budget, hint: '0 means no budget has been approved yet.' })}
          ${field('start_date', 'Start date', { type: 'date', value: p.start_date })}
          ${field('end_date', 'Expected completion', { type: 'date', value: p.end_date })}
        </div>
        <p class="small muted" style="margin:8px 0 0">Estimates from the BOQ are not the same as a full construction cost.</p>
      </fieldset>
      <fieldset><legend>Contacts</legend>
        <div class="form-grid">
          ${field('manager_name', 'Project manager', { value: p.manager_name })}
          ${field('manager_email', 'Manager email', { type: 'email', value: p.manager_email, hint: 'Used only when you approve an email to this person.' })}
          ${field('contractor', 'Contractor', { value: p.contractor })}
        </div>
      </fieldset>
      <fieldset><legend>Notes and optional coordinates</legend>
        <div class="form-grid">
          ${field('description', 'Scope description', { textarea: true, value: p.description, rows: 3 })}
          ${field('assumptions', 'Assumptions', { textarea: true, value: p.assumptions, rows: 3 })}
          ${field('latitude', 'Latitude (optional)', { type: 'number', step: '0.000001', min: -90, max: 90, value: p.latitude, hint: 'Needed only for weather forecasts.' })}
          ${field('longitude', 'Longitude (optional)', { type: 'number', step: '0.000001', min: -180, max: 180, value: p.longitude })}
        </div>
      </fieldset>
    </form>`;
  }

  async function openForm(project) {
    const editing = !!project;
    const result = await modal({
      title: editing ? 'Edit project' : 'New project',
      wide: true,
      body: formBody(project),
      footer: `<button class="btn btn-ghost" data-close>Cancel</button>
        <button class="btn btn-accent" data-result="save">${editing ? 'Save changes' : 'Create project'}</button>`,
      onResult: (value, root) => {
        if (value !== 'save') return true;
        const data = formValues(el('#project-form', root));
        if (!data.name || !data.name.trim()) {
          toast('Give the project a name first.', 'error');
          el('#project-form input[name="name"]', root).focus();
          return false;
        }
        if (data.start_date && data.end_date && data.end_date < data.start_date) {
          toast('Expected completion cannot be before the start date.', 'error');
          return false;
        }
        data.budget = Number(data.budget || 0);
        ['latitude', 'longitude'].forEach((k) => { if (data[k] === null || data[k] === '') delete data[k]; });
        const call = editing
          ? api('/projects/' + project.id, { method: 'PUT', body: data })
          : api('/projects', { method: 'POST', body: data });
        call.then(() => {
          toast(editing ? 'Project updated.' : 'Project created.', 'success');
          load();
        }).catch(() => {});
        return true;
      },
    });
    return result;
  }

  async function act(kind, id) {
    const p = projects.find((x) => x.id === id);
    if (!p) return;
    if (kind === 'edit') return openForm(p);
    if (kind === 'archive') {
      if (!await confirmDialog({ title: 'Archive this project?', message: `${p.name} will be hidden from active lists but all records are kept.`, confirmText: 'Archive' })) return;
      await api(`/projects/${id}/archive`, { method: 'POST' });
    }
    if (kind === 'restore') {
      await api(`/projects/${id}/restore`, { method: 'POST' });
    }
    if (kind === 'delete') {
      if (!await confirmDialog({
        title: 'Delete this project permanently?',
        message: `${p.name} and its BOQ, expenses, stock, tasks and purchase orders will be removed. This cannot be undone.`,
        detail: 'Archive instead if you only want to hide it.',
        confirmText: 'Delete permanently', danger: true,
      })) return;
      await api(`/projects/${id}`, { method: 'DELETE' });
    }
    toast('Project updated.', 'success');
    load();
  }

  async function load() {
    try {
      const archived = el('#p-archived').checked;
      projects = await api('/projects?include_archived=' + archived);
      render();
    } catch (err) {
      el('#projects-host').innerHTML = `<div class="card">${emptyState('Projects could not load', err.message, 'alert-circle')}</div>`;
      icons(el('#projects-host'));
    }
  }

  el('#projects-host').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-edit],[data-archive],[data-restore],[data-delete]');
    if (!btn) return;
    const kind = btn.hasAttribute('data-edit') ? 'edit' : btn.hasAttribute('data-archive') ? 'archive'
      : btn.hasAttribute('data-restore') ? 'restore' : 'delete';
    act(kind, Number(btn.getAttribute('data-' + kind))).catch(() => {});
  });
  el('#new-project').addEventListener('click', () => openForm());
  ['#p-q', '#p-status', '#p-type', '#p-sort'].forEach((sel) => {
    el(sel).addEventListener('input', render);
  });
  el('#p-archived').addEventListener('change', load);
  el('#view-cards').addEventListener('click', () => {
    view = 'cards'; el('#view-cards').setAttribute('aria-pressed', 'true');
    el('#view-table').setAttribute('aria-pressed', 'false'); render();
  });
  el('#view-table').addEventListener('click', () => {
    view = 'table'; el('#view-table').setAttribute('aria-pressed', 'true');
    el('#view-cards').setAttribute('aria-pressed', 'false'); render();
  });

  BB.ready().then(() => {
    load();
    if (new URLSearchParams(location.search).get('new')) openForm();
  });
})();
