/* Approval centre: review proposed changes, approve once, reject, retry failed execution. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, money, num, badge, emptyState, confirm: confirmDialog, toast, icons,
          dateFmt, timeAgo, devDetails, modal } = BB;

  let filter = 'pending';
  let rows = [];

  const ACTIONS_WITH_AMOUNT = ['record_expense'];

  function payloadRows(a) {
    const p = a.payload || {};
    const out = [];
    if (a.action === 'record_expense') {
      out.push(['Category', BB.humanize(p.category)], ['Amount', money(p.amount)], ['Vendor', p.vendor || '—'],
        ['Invoice', p.invoice_no || '—'], ['Date', p.expense_date ? dateFmt(p.expense_date) : 'Today']);
    } else if (a.action === 'create_project' || a.action === 'update_project') {
      ['name', 'project_type', 'location', 'budget', 'start_date', 'end_date', 'manager_name', 'manager_email', 'status']
        .forEach((k) => { if (p[k] !== undefined && p[k] !== null && p[k] !== '') out.push([BB.humanize(k), k === 'budget' ? money(p[k]) : String(p[k])]); });
    } else if (a.action === 'approve_boq') {
      out.push(['Revision', p.revision || 'Latest']);
    } else if (a.action === 'create_purchase_order') {
      out.push(['Supplier', p.supplier || p.supplier_id || 'Not selected'], ['Lines', (p.items || []).length],
        ['Expected', p.expected_date ? dateFmt(p.expected_date) : '—']);
    } else if (a.action === 'add_boq_items') {
      out.push(['Lines', (p.lines || []).length]);
    } else if (a.action === 'create_task') {
      out.push(['Task', p.name || '—'], ['Duration', (p.duration || '—') + ' days'],
        ['Start', p.start_date ? dateFmt(p.start_date) : '—'], ['Priority', BB.humanize(p.priority || 'normal')]);
    } else if (a.action === 'stock_adjustment') {
      out.push(['Movement', BB.label('inventory_txn_kinds', p.kind)], ['Quantity', num(p.quantity, 2)], ['Note', p.note || '—']);
    } else if (a.action === 'send_email') {
      out.push(['Recipient', p.to || 'See draft'], ['Draft', p.draft_id ? '#' + p.draft_id : '—']);
    } else if (a.action === 'create_automation') {
      out.push(['Rule', p.name || '—'], ['Trigger', BB.label('automation_triggers', p.trigger)],
        ['Recipients', p.recipients || '—'], ['Schedule', p.schedule || '—']);
    }
    return out;
  }

  function card(a) {
    const details = payloadRows(a);
    return `<article class="card" style="margin-bottom:12px">
      <div style="display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap">
        <div style="flex:1;min-width:220px">
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <span class="badge info">${esc(BB.label('approval_actions', a.action))}</span>
            <span class="badge ${esc(a.status)}">${esc(BB.label('approval_status', a.status))}</span>
            ${a.project ? `<span class="small muted">${esc(a.project)}</span>` : ''}
          </div>
          <h3 style="margin:6px 0 2px">${esc(a.title)}</h3>
          ${a.summary ? `<div class="small muted">${esc(a.summary)}</div>` : ''}
        </div>
        <div class="small muted" style="text-align:right">
          <div>Requested ${timeAgo(a.created_at)}</div>
          <div>Expires ${dateFmt(a.expires_at, true)}</div>
          ${a.executed_at ? `<div style="color:var(--success)">Executed ${dateFmt(a.executed_at, true)}</div>` : ''}
        </div>
      </div>
      ${details.length ? `<dl class="dl" style="margin-top:12px">${details.map(([k, v]) =>
        `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>` : ''}
      ${a.execution_error ? `<div class="alert error" style="margin-top:10px">Execution failed: ${esc(a.execution_error)}</div>` : ''}
      ${devDetails('Technical details', { action: a.action, payload: a.payload, before: a.before })}
      <div class="btn-group" style="margin-top:12px">
        ${a.status === 'pending' ? `
          <button class="btn btn-accent btn-sm" type="button" data-approve="${a.id}">Approve & execute</button>
          <button class="btn btn-ghost btn-sm" type="button" data-reject="${a.id}">Reject</button>` : ''}
        ${a.status === 'approved' && !a.executed_at ? `
          <button class="btn btn-accent btn-sm" type="button" data-execute="${a.id}">Retry execution</button>` : ''}
        ${a.action === 'send_email' && a.payload && a.payload.draft_id ? `<a class="btn btn-ghost btn-sm" href="/mail">Review in Mail Centre</a>` : ''}
      </div>
    </article>`;
  }

  async function load() {
    try {
      const [summary, list] = await Promise.all([
        api('/approvals/summary', { silent: true }),
        api('/approvals' + (filter ? '?status=' + filter : '')),
      ]);
      rows = list;
      el('#approval-summary').innerHTML = [
        { label: 'Pending', value: summary.pending, cls: summary.pending ? 'is-warning' : '' },
        { label: 'Approved', value: summary.approved },
        { label: 'Rejected', value: summary.rejected },
        { label: 'Expired', value: summary.expired, cls: summary.expired ? 'is-danger' : '' },
        { label: 'Total', value: summary.total },
      ].map((k) => `<div class="kpi ${k.cls || ''}"><div class="label">${k.label}</div>
        <div class="value">${num(k.value, 0)}</div></div>`).join('');
      el('#approval-count').textContent = `${rows.length} shown`;
      el('#approval-host').innerHTML = rows.length ? rows.map(card).join('')
        : `<div class="card">${emptyState(filter === 'pending' ? 'No approvals waiting' : 'Nothing in this view',
          filter === 'pending' ? 'Requests created by the assistant or email workflow appear here.' : 'Try another filter.', 'shield-check')}</div>`;
      icons(el('#approval-host'));
      els('[data-filter]').forEach((b) => {
        b.className = b.getAttribute('data-filter') === filter ? 'btn btn-sm' : 'btn btn-ghost btn-sm';
      });
    } catch (err) {
      el('#approval-host').innerHTML = `<div class="card">${emptyState('Approvals could not load', err.message, 'alert-circle')}</div>`;
      icons(el('#approval-host'));
    }
  }

  el('#approval-host').addEventListener('click', async (e) => {
    const approve = e.target.closest('[data-approve]');
    if (approve) {
      if (!await confirmDialog({ title: 'Approve and execute now?', message: 'The action runs exactly once. This can record project data or send an email.', confirmText: 'Approve & execute' })) return;
      try {
        const r = await api(`/approvals/${approve.getAttribute('data-approve')}/decide`, { method: 'POST', body: { approve: true } });
        toast(r.message || 'Approved.', r.executed === false ? 'warn' : 'success');
        load();
      } catch (err) { /* toasted */ }
      return;
    }
    const reject = e.target.closest('[data-reject]');
    if (reject) {
      if (!await confirmDialog({ title: 'Reject this request?', message: 'Nothing is executed and the requester can create a new request later.', confirmText: 'Reject', danger: true })) return;
      try {
        await api(`/approvals/${reject.getAttribute('data-reject')}/decide`, { method: 'POST', body: { approve: false } });
        toast('Rejected — nothing was executed.', 'success'); load();
      } catch (err) { /* toasted */ }
      return;
    }
    const retry = e.target.closest('[data-execute]');
    if (retry) {
      try {
        const r = await api(`/approvals/${retry.getAttribute('data-execute')}/execute`, { method: 'POST' });
        toast(r.message || 'Executed.', 'success'); load();
      } catch (err) { /* toasted */ }
    }
  });

  document.querySelectorAll('[data-filter]').forEach((b) => b.addEventListener('click', () => {
    filter = b.getAttribute('data-filter');
    load();
  }));

  BB.ready().then(load);
})();
