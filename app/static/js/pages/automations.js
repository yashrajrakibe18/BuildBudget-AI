/* Automation rules: trigger, recipients, schedule, approval requirement and run history. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, badge, emptyState, modal, confirm: confirmDialog, toast, icons,
          dateFmt, timeAgo, field, formValues } = BB;

  let rules = [];

  const TEMPLATES = [
    { value: 'project_summary', label: 'Project summary' },
    { value: 'budget_warning', label: 'Budget warning' },
    { value: 'rfq', label: 'Request for quotation' },
  ];

  function card(r) {
    return `<article class="card" style="margin-bottom:12px">
      <div style="display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap">
        <div style="flex:1;min-width:220px">
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            <h3 style="margin:0">${esc(r.name)}</h3>
            ${badge(r.enabled ? 'Enabled' : 'Disabled', r.enabled ? 'ok' : 'archived')}
            ${r.require_approval ? badge('Approval required', 'warning') : badge('Sends without approval', 'critical')}
          </div>
          <div class="small muted" style="margin-top:4px">${esc(r.trigger_label || BB.label('automation_triggers', r.trigger))}
            ${r.threshold != null ? ` · threshold ${r.threshold}` : ''}</div>
          <div class="small">${esc(r.recipients || 'No recipients configured')}</div>
          <div class="small muted">Template: ${esc(BB.humanize(r.template))}${r.schedule ? ' · ' + esc(r.schedule) : ''} · ${esc(r.timezone || '')}</div>
        </div>
        <div class="small muted" style="text-align:right;min-width:150px">
          <div>Last run: ${r.last_run_at ? timeAgo(r.last_run_at) : 'Never'}</div>
          <div>Next run: ${r.next_run_at ? dateFmt(r.next_run_at, true) : 'Not scheduled'}</div>
          ${r.last_result ? `<div>${esc(r.last_result)}</div>` : ''}
        </div>
      </div>
      <div class="btn-group" style="margin-top:10px">
        <button class="btn btn-ghost btn-sm" type="button" data-run="${r.id}">Run now</button>
        <button class="btn btn-ghost btn-sm" type="button" data-edit="${r.id}">Edit</button>
        <button class="btn btn-ghost btn-sm" type="button" data-toggle="${r.id}">${r.enabled ? 'Disable' : 'Enable'}</button>
        <button class="btn btn-ghost btn-sm" type="button" data-del="${r.id}">Delete</button>
      </div>
      ${(r.history || []).length ? `<details class="disclosure" style="margin-top:10px"><summary>Execution history</summary>
        <div class="body"><ul class="timeline" style="margin-top:8px">${r.history.map((h) => `<li>
          <div>${esc(BB.humanize(h.status))} — ${esc(h.detail || '')}</div>
          <div class="when">${dateFmt(h.created_at, true)}</div></li>`).join('')}</ul></div></details>` : ''}
    </article>`;
  }

  function render() {
    el('#auto-host').innerHTML = rules.length ? rules.map(card).join('')
      : `<div class="card">${emptyState('No automation rules yet', 'Create a rule to draft budget warnings, project summaries or RFQs on a schedule.', 'zap')}
        <div style="text-align:center"><button class="btn btn-accent btn-sm" type="button" id="empty-new">New rule</button></div></div>`;
    const empty = el('#empty-new');
    if (empty) empty.addEventListener('click', () => openRule());
    icons(el('#auto-host'));
  }

  async function load() {
    try { rules = await api('/automations'); render(); }
    catch (err) {
      el('#auto-host').innerHTML = `<div class="card">${emptyState('Automations could not load', err.message, 'alert-circle')}</div>`;
      icons(el('#auto-host'));
    }
  }

  async function openRule(rule) {
    const editing = !!rule;
    const r = rule || { require_approval: true, enabled: true, timezone: 'Asia/Kolkata', template: 'project_summary' };
    const triggers = Object.entries(BB.labels.automation_triggers || {});
    await modal({
      title: editing ? 'Edit automation rule' : 'New automation rule',
      wide: true,
      body: `<form id="auto-form">
        <div class="form-grid">
          ${field('name', 'Rule name', { required: true, value: r.name, placeholder: 'e.g. Weekly budget warning' })}
          ${field('trigger', 'Trigger', { value: r.trigger || (triggers[0] && triggers[0][0]), options: triggers.map(([k, v]) => ({ value: k, label: v })) })}
          ${field('project_id', 'Project scope', { value: r.project_id ? String(r.project_id) : '', options: [{ value: '', label: 'All projects' }].concat(
            Array.from(el('#chat-project') ? [] : [])) })}
          ${field('threshold', 'Threshold (if applicable)', { type: 'number', step: '0.01', value: r.threshold, hint: 'For budget utilisation, use a percentage such as 90.' })}
          ${field('recipients', 'Recipients', { value: r.recipients, placeholder: 'manager@example.com', hint: 'Separate multiple addresses with commas. Never assume an address — enter the ones your contact gave you.' })}
          ${field('template', 'Email template', { value: r.template, options: TEMPLATES })}
          ${field('schedule', 'Schedule', { value: r.schedule, placeholder: 'e.g. weekly Monday 08:00', hint: 'Free-form description evaluated by the scheduler; leave blank for event-driven rules.' })}
          ${field('timezone', 'Time zone', { value: r.timezone || 'Asia/Kolkata' })}
        </div>
        <label class="check" style="margin-top:10px"><input type="checkbox" name="require_approval" ${r.require_approval ? 'checked' : ''}>
          Require human approval before sending</label>
        <label class="check" style="margin-top:6px"><input type="checkbox" name="enabled" ${r.enabled ? 'checked' : ''}>
          Rule enabled</label>
        <p class="small muted" style="margin-top:10px">Turning approval off means the scheduler may send email automatically
        under this rule. Only do that for recipients who explicitly asked for it.</p>
      </form>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">${editing ? 'Save rule' : 'Create rule'}</button>`,
      onMount: (root) => {
        const projectField = el('#auto-form select[name="project_id"]', root);
        if (projectField) {
          projectField.innerHTML = '<option value="">All projects</option>' +
            Array.from((el('#project-switcher') || { options: [] }).options || []).filter((o) => o.value)
              .map((o) => `<option value="${o.value}" ${String(r.project_id) === o.value ? 'selected' : ''}>${esc(o.textContent)}</option>`).join('');
        }
      },
      onResult: (value, root) => {
        if (value !== 'save') return true;
        const v = formValues(el('#auto-form', root));
        const body = {
          name: v.name, trigger: v.trigger, recipients: v.recipients || '', template: v.template,
          schedule: v.schedule || '', timezone: v.timezone || 'Asia/Kolkata',
          require_approval: !!v.require_approval, enabled: !!v.enabled,
          project_id: v.project_id ? Number(v.project_id) : null,
          threshold: v.threshold === null || v.threshold === '' ? null : Number(v.threshold),
        };
        if (!body.name) { toast('Give the rule a name.', 'error'); return false; }
        const call = editing ? api(`/automations/${r.id}`, { method: 'PUT', body }) : api('/automations', { method: 'POST', body });
        call.then(() => { toast(editing ? 'Rule saved.' : 'Rule created.', 'success'); load(); }).catch(() => {});
        return true;
      },
    });
  }

  el('#auto-new').addEventListener('click', () => openRule());
  el('#auto-host').addEventListener('click', async (e) => {
    const run = e.target.closest('[data-run]');
    if (run) {
      try {
        const r = await api(`/automations/${run.getAttribute('data-run')}/run`, { method: 'POST' });
        toast(r.detail || (r.ran ? 'Rule ran.' : 'Nothing to do.'), r.ran ? 'success' : 'warn');
        load();
      } catch (err) { /* toasted */ }
      return;
    }
    const edit = e.target.closest('[data-edit]');
    if (edit) { openRule(rules.find((x) => x.id === Number(edit.getAttribute('data-edit')))); return; }
    const toggle = e.target.closest('[data-toggle]');
    if (toggle) {
      const r = rules.find((x) => x.id === Number(toggle.getAttribute('data-toggle')));
      const body = {
        name: r.name, trigger: r.trigger, project_id: r.project_id, threshold: r.threshold,
        recipients: r.recipients, template: r.template, schedule: r.schedule, timezone: r.timezone,
        require_approval: r.require_approval, enabled: !r.enabled,
      };
      try { await api(`/automations/${r.id}`, { method: 'PUT', body }); toast(r.enabled ? 'Rule disabled.' : 'Rule enabled.', 'success'); load(); }
      catch (err) { /* toasted */ }
      return;
    }
    const del = e.target.closest('[data-del]');
    if (del) {
      if (!await confirmDialog({ title: 'Delete this automation?', message: 'The rule and its execution history are removed. Scheduled mail already created is kept.', confirmText: 'Delete', danger: true })) return;
      await api(`/automations/${del.getAttribute('data-del')}`, { method: 'DELETE' });
      toast('Automation deleted.', 'success'); load();
    }
  });

  BB.ready().then(load);
})();
