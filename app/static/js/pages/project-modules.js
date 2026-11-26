/* Project workspace tab renderers: BOQ, budget, inventory, procurement,
   labour, schedule, documents, reports and activity. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, money, moneyShort, num, pct, qty, table, badge, statusBadge, progressBar,
          emptyState, modal, confirm: confirmDialog, toast, icons, dateFmt, timeAgo, field,
          formValues, chart, devDetails, download } = BB;
  BB.projectTabs = BB.projectTabs || {};

  const projectOf = (pid) => api('/projects/' + pid);

  function moneyCell(v) { return `<span class="nowrap">${money(v)}</span>`; }
  function reportLink(pid, name, fmt, label) {
    return `<button class="btn btn-ghost btn-sm" type="button" data-report="${name}" data-fmt="${fmt}">${esc(label || fmt.toUpperCase())}</button>`;
  }
  function bindReports(host, pid) {
    host.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-report]');
      if (!b) return;
      const name = b.getAttribute('data-report'), fmt = b.getAttribute('data-fmt');
      b.disabled = true;
      try { await download(`/projects/${pid}/reports/${name}.${fmt}`, `${name}_${pid}.${fmt}`); toast('Report downloaded.', 'success'); }
      catch (err) { /* toast already shown */ }
      finally { b.disabled = false; }
    });
  }

  /* ------------------------------------------------------------------ BOQ */
  BB.projectTabs.boq = async function (host, pid) {
    const data = await api(`/projects/${pid}/boq`);
    const cats = data.category_totals || [];
    host.innerHTML = `
      <div class="card">
        <div class="card-head">
          <h2>Bill of Quantities</h2>
          <span class="badge ${data.approved ? 'approved' : 'draft'}">${data.approved ? 'Approved' : 'Draft'}</span>
          <div class="spacer"></div>
          <span class="small muted">Revision ${data.revision}${data.revisions.length > 1 ? ` of ${data.revisions.join(', ')}` : ''}</span>
          <div class="btn-group">
            <button class="btn btn-sm" type="button" data-add>Add item</button>
            <button class="btn btn-ghost btn-sm" type="button" data-revision>New revision</button>
            <button class="btn btn-ghost btn-sm" type="button" data-approve ${data.items.length ? '' : 'disabled'}>Approve revision</button>
            <button class="btn btn-ghost btn-sm" type="button" data-estimate>From estimate</button>
          </div>
        </div>
        <div class="small muted" style="margin-bottom:10px">Prices come only from what you entered or from stored
          supplier quotations. Approved items revert to draft if edited.</div>
        ${data.items.length ? table(data.items, [
          { key: 'item_no', label: '#', render: (v) => `<span class="muted">${v}</span>` },
          { key: 'description', label: 'Description', render: (v, r) => `<strong>${esc(v)}</strong>
            <div class="small muted">${esc(r.category || 'Uncategorised')}${r.rate_source ? ' · source: ' + esc(BB.label('sources', r.rate_source)) : ''}</div>` },
          { key: 'quantity', label: 'Quantity', align: 'right', render: (v, r) => qty(v, r.unit) },
          { key: 'unit_rate', label: 'Rate', align: 'right', render: (v) => moneyCell(v) },
          { key: 'labour_cost', label: 'Labour', align: 'right', render: (v) => v ? moneyCell(v) : '—' },
          { key: 'tax_pct', label: 'Tax', align: 'right', render: (v) => num(v, 0) + '%' },
          { key: 'total', label: 'Total', align: 'right', render: (v) => `<strong>${moneyCell(v)}</strong>` },
          { key: 'approval_status', label: 'Status', render: (v) => badge(BB.label('approval_status', v), v) },
          { key: 'id', label: '', render: (v, r) => `<div class="btn-group">
              <button class="btn btn-ghost btn-sm" type="button" data-edit="${v}">Edit</button>
              <button class="btn btn-ghost btn-sm" type="button" data-dup="${v}">Copy</button>
              <button class="btn btn-ghost btn-sm" type="button" data-del="${v}">Delete</button></div>` },
        ], { compact: true }) : emptyState('No BOQ items yet', 'Add priced items manually, or calculate a quantity in the estimator and add it here.', 'list-checks')}
        <div style="display:flex;justify-content:flex-end;gap:20px;margin-top:12px;flex-wrap:wrap">
          <div class="small muted">Items: ${data.items.length}</div>
          <div><span class="muted small">Revision total</span> <strong style="font-size:16px">${money(data.total)}</strong></div>
        </div>
      </div>
      ${cats.length ? `<div class="card"><div class="card-head"><h3>Category totals</h3></div>
        ${table(cats, [{ key: 'category', label: 'Category' },
          { key: 'total', label: 'Value', align: 'right', render: (v) => money(v) }], { compact: true })}</div>` : ''}
      <div class="card"><div class="card-head"><h3>Exports</h3><div class="spacer"></div>
        <div class="btn-group">${reportLink(pid, 'boq', 'pdf', 'PDF')}${reportLink(pid, 'boq', 'xlsx', 'Excel')}${reportLink(pid, 'boq', 'csv', 'CSV')}${reportLink(pid, 'boq', 'docx', 'Word')}</div>
      </div><p class="small muted" style="margin:0">Exports contain the current revision with rate sources and assumptions.</p></div>`;
    bindReports(host, pid);

    host.addEventListener('click', async (e) => {
      const add = e.target.closest('[data-add]');
      const edit = e.target.closest('[data-edit]');
      const dup = e.target.closest('[data-dup]');
      const del = e.target.closest('[data-del]');
      const rev = e.target.closest('[data-revision]');
      const approve = e.target.closest('[data-approve]');
      if (add || edit) {
        const item = edit ? data.items.find((i) => i.id === Number(edit.getAttribute('data-edit'))) : null;
        const result = await modal({
          title: item ? 'Edit BOQ item' : 'Add BOQ item',
          body: `<form id="boq-form"><div class="form-grid">
            ${field('description', 'Description', { required: true, value: item ? item.description : '', placeholder: 'e.g. Vitrified floor tiles 600×600' })}
            ${field('category', 'Category', { value: item ? item.category : 'Finishing' })}
            ${field('unit', 'Unit', { required: true, value: item ? item.unit : 'sqft', placeholder: 'sqft, pcs, bag…' })}
            ${field('quantity', 'Quantity', { type: 'number', step: '0.001', min: 0, required: true, value: item ? item.quantity : '' })}
            ${field('unit_rate', 'Unit rate (₹)', { type: 'number', step: '0.01', min: 0, required: true, value: item ? item.unit_rate : '', hint: 'From your quotation or entered rate.' })}
            ${field('labour_cost', 'Labour cost (₹)', { type: 'number', step: '0.01', min: 0, value: item ? item.labour_cost : 0 })}
            ${field('transport_cost', 'Transport (₹)', { type: 'number', step: '0.01', min: 0, value: item ? item.transport_cost : 0 })}
            ${field('discount_pct', 'Discount %', { type: 'number', step: '0.01', min: 0, max: 100, value: item ? item.discount_pct : 0 })}
            ${field('tax_pct', 'Tax %', { type: 'number', step: '0.01', min: 0, max: 100, value: item ? item.tax_pct : 18 })}
            ${field('assumptions', 'Assumptions / source', { textarea: true, value: item ? item.assumptions : '', rows: 2 })}
          </div></form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">${item ? 'Save item' : 'Add item'}</button>`,
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const body = formValues(el('#boq-form', root));
            if (!body.description || !body.quantity || body.quantity <= 0) { toast('Description and a positive quantity are required.', 'error'); return false; }
            const call = item ? api(`/projects/${pid}/boq/${item.id}`, { method: 'PUT', body })
              : api(`/projects/${pid}/boq/items`, { method: 'POST', body });
            call.then(() => { toast(item ? 'Item updated.' : 'Item added.', 'success'); BB.project.go('boq'); }).catch(() => {});
            return true;
          },
        });
      }
      if (dup) {
        await api(`/projects/${pid}/boq/${dup.getAttribute('data-dup')}/duplicate`, { method: 'POST' });
        toast('Item duplicated.', 'success'); BB.project.go('boq');
      }
      if (del) {
        const item = data.items.find((i) => i.id === Number(del.getAttribute('data-del')));
        if (!await confirmDialog({ title: 'Delete this BOQ item?', message: item.description, confirmText: 'Delete', danger: true })) return;
        await api(`/projects/${pid}/boq/${item.id}`, { method: 'DELETE' });
        BB.project.go('boq');
      }
      if (rev) {
        if (!await confirmDialog({ title: 'Create a new revision?', message: 'The current items are copied into a new draft revision. The existing revision is kept.', confirmText: 'Create revision' })) return;
        const r = await api(`/projects/${pid}/boq/revisions`, { method: 'POST' });
        toast(`Revision ${r.revision} created.`, 'success'); BB.project.go('boq');
      }
      if (approve) {
        if (!await confirmDialog({ title: 'Approve this BOQ revision?', message: 'Approval records that you reviewed the quantities and rates. It is not an engineering certification.', confirmText: 'Approve' })) return;
        await api(`/projects/${pid}/boq/approve`, { method: 'POST' });
        toast('Revision approved.', 'success'); BB.project.go('boq');
      }
      if (e.target.closest('[data-estimate]')) {
        location.href = `/estimator?project=${pid}`;
      }
    });
  };

  /* --------------------------------------------------------------- budget */
  BB.projectTabs.budget = async function (host, pid) {
    const [b, expenses] = await Promise.all([api(`/projects/${pid}/budget`), api(`/projects/${pid}/expenses`)]);
    const proj = await projectOf(pid);
    const cats = Object.entries(b.expenses_by_category || {}).filter(([, v]) => v > 0);
    host.innerHTML = `
      <div class="grid grid-kpi">
        <div class="kpi"><div class="label">Approved budget</div><div class="value">${moneyShort(b.approved_budget)}</div></div>
        <div class="kpi"><div class="label">Estimated BOQ</div><div class="value">${moneyShort(b.estimated_cost)}</div></div>
        <div class="kpi"><div class="label">Actual expenses</div><div class="value">${moneyShort(b.actual_expenses)}</div></div>
        <div class="kpi ${b.remaining_budget < 0 ? 'is-danger' : b.utilization_pct >= 75 ? 'is-warning' : 'is-success'}">
          <div class="label">Remaining</div><div class="value">${moneyShort(b.remaining_budget)}</div>
          <div class="foot">${b.utilization_pct == null ? 'No approved budget' : pct(b.utilization_pct) + ' used'}</div></div>
        <div class="kpi"><div class="label">Labour recorded</div><div class="value">${moneyShort(b.labour_cost_recorded)}</div>
          <div class="foot">Separate from expenses below</div></div>
      </div>
      ${(b.alerts || []).map((a) => `<div class="insight ${a.level === 'critical' ? 'critical' : a.level === 'warning' ? 'warning' : 'info'}" style="margin-top:12px">
        <i data-lucide="alert-triangle" class="ico"></i><div>${esc(a.message)}</div></div>`).join('')}
      <div class="card" style="margin-top:16px">
        <div class="card-head"><h2>Expenses</h2><div class="spacer"></div>
          <div class="btn-group">
            <button class="btn btn-sm" type="button" data-add-expense>Record expense</button>
            ${reportLink(pid, 'expenses', 'xlsx', 'Excel')}${reportLink(pid, 'expenses', 'csv', 'CSV')}
            ${reportLink(pid, 'budget', 'pdf', 'Budget PDF')}
          </div>
        </div>
        ${expenses.length ? table(expenses, [
          { key: 'date', label: 'Date', render: (v) => dateFmt(v) },
          { key: 'category', label: 'Category' },
          { key: 'description', label: 'Description', render: (v, r) => `${esc(v || '—')}${r.vendor ? `<div class="small muted">${esc(r.vendor)}</div>` : ''}` },
          { key: 'invoice_no', label: 'Invoice', render: (v) => v ? esc(v) : '<span class="muted">—</span>' },
          { key: 'payment_status', label: 'Payment', render: (v) => badge(BB.humanize(v), v === 'paid' ? 'ok' : v === 'partial' ? 'warning' : 'pending') },
          { key: 'amount', label: 'Amount', align: 'right', render: (v) => moneyCell(v) },
          { key: 'id', label: '', render: (v) => `<button class="btn btn-ghost btn-sm" type="button" data-del-expense="${v}">Delete</button>` },
        ], { compact: true, footer: ['', '', '', '', '<strong>Total</strong>', `<strong>${money(b.actual_expenses)}</strong>`, ''] })
          : emptyState('No expenses recorded', 'Record invoices and payments here; duplicates with the same invoice number and vendor are rejected.', 'receipt')}
        <p class="small muted" style="margin:10px 0 0">Labour entries are tracked separately in the Labour tab and are not
        automatically added to expenses, so the same cost is never counted twice.</p>
      </div>
      ${cats.length ? `<div class="card"><div class="card-head"><h3>Spending by category</h3></div>
        <div class="chart-box" style="height:240px"><canvas id="budget-cats"></canvas></div></div>` : ''}`;
    bindReports(host, pid);
    if (cats.length) {
      chart(el('#budget-cats'), {
        type: 'doughnut',
        data: { labels: cats.map(([k]) => BB.humanize(k)), datasets: [{ data: cats.map(([, v]) => v), backgroundColor: BB.THEME_KEYS, borderWidth: 0 }] },
        options: { cutout: '58%', plugins: { legend: { position: 'bottom' } } },
      });
    }
    host.addEventListener('click', async (e) => {
      if (e.target.closest('[data-add-expense]')) {
        const catsList = BB.labels.expense_categories || ['Materials', 'Labour', 'Other'];
        await modal({
          title: 'Record an expense',
          body: `<form id="expense-form"><div class="form-grid">
            ${field('category', 'Category', { options: catsList })}
            ${field('amount', 'Amount (₹)', { type: 'number', step: '0.01', min: 0, required: true })}
            ${field('expense_date', 'Expense date', { type: 'date', value: new Date().toISOString().slice(0, 10) })}
            ${field('vendor', 'Vendor', { placeholder: 'Supplier or contractor' })}
            ${field('invoice_no', 'Invoice number', { hint: 'The same invoice for the same vendor is rejected as a duplicate.' })}
            ${field('payment_status', 'Payment status', { options: [{ value: 'paid', label: 'Paid' }, { value: 'pending', label: 'Pending' }, { value: 'partial', label: 'Partially paid' }] })}
            ${field('description', 'Description', { textarea: true, rows: 2 })}
          </div></form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Record expense</button>`,
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const body = formValues(el('#expense-form', root));
            if (!body.amount || body.amount <= 0) { toast('Enter an amount greater than zero.', 'error'); return false; }
            if (!body.invoice_no) delete body.invoice_no;
            api(`/projects/${pid}/expenses`, { method: 'POST', body })
              .then(() => { toast('Expense recorded.', 'success'); BB.project.go('budget'); }).catch(() => {});
            return true;
          },
        });
      }
      const del = e.target.closest('[data-del-expense]');
      if (del) {
        if (!await confirmDialog({ title: 'Delete this expense?', message: 'The budget figures will update immediately.', confirmText: 'Delete', danger: true })) return;
        await api(`/projects/${pid}/expenses/${del.getAttribute('data-del-expense')}`, { method: 'DELETE' });
        toast('Expense deleted.', 'success'); BB.project.go('budget');
      }
    });
  };

  /* ------------------------------------------------------------ inventory */
  BB.projectTabs.inventory = async function (host, pid) {
    const items = await api(`/projects/${pid}/inventory`);
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>Site inventory</h2><div class="spacer"></div>
        <button class="btn btn-sm" type="button" data-add>Add material</button></div>
      <p class="small muted" style="margin-top:-4px">Stock in, out, damage, wastage, returns and adjustments are recorded
      as transactions. Stock can never go negative.</p>
      ${items.length ? table(items, [
        { key: 'material_name', label: 'Material' },
        { key: 'available', label: 'Available', align: 'right', render: (v, r) => `${num(v, 2)} ${esc(r.unit)}` },
        { key: 'reserved', label: 'Reserved', align: 'right', render: (v, r) => `${num(v, 2)} ${esc(r.unit)}` },
        { key: 'usable', label: 'Usable', align: 'right', render: (v, r) => `${num(v, 2)} ${esc(r.unit)}` },
        { key: 'reorder_level', label: 'Reorder at', align: 'right', render: (v, r) => `${num(v, 2)} ${esc(r.unit)}` },
        { key: 'location', label: 'Store', render: (v) => esc(v || '—') },
        { key: 'low', label: 'Status', render: (v) => v ? badge('Below reorder level', 'critical') : badge('Sufficient', 'ok') },
        { key: 'id', label: '', render: (v) => `<div class="btn-group">
            <button class="btn btn-ghost btn-sm" type="button" data-txn="${v}">Transactions</button>
            <button class="btn btn-ghost btn-sm" type="button" data-move="${v}">Stock movement</button></div>` },
      ], { compact: true }) : emptyState('No materials tracked', 'Add the materials you keep on site to get low-stock alerts.', 'package')}
    </div>`;
    host.addEventListener('click', async (e) => {
      if (e.target.closest('[data-add]')) {
        await modal({
          title: 'Add a tracked material',
          body: `<form id="inv-form"><div class="form-grid">
            ${field('material_name', 'Material name', { required: true, placeholder: 'e.g. Cement OPC 53' })}
            ${field('unit', 'Unit', { required: true, value: 'bag' })}
            ${field('available', 'Opening stock', { type: 'number', step: '0.01', min: 0, value: 0 })}
            ${field('reserved', 'Reserved for tasks', { type: 'number', step: '0.01', min: 0, value: 0 })}
            ${field('reorder_level', 'Reorder level', { type: 'number', step: '0.01', min: 0, value: 0 })}
            ${field('location', 'Storage location', { placeholder: 'e.g. Site store A' })}
          </div></form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Add material</button>`,
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const body = formValues(el('#inv-form', root));
            if (!body.material_name) { toast('A material name is required.', 'error'); return false; }
            api(`/projects/${pid}/inventory`, { method: 'POST', body })
              .then(() => { toast('Material added.', 'success'); BB.project.go('inventory'); }).catch(() => {});
            return true;
          },
        });
      }
      const txn = e.target.closest('[data-txn]');
      if (txn) {
        const id = Number(txn.getAttribute('data-txn'));
        const rows = await api(`/projects/${pid}/inventory/${id}/transactions`);
        await modal({
          title: 'Stock transaction history',
          body: rows.length ? table(rows, [
            { key: 'kind', label: 'Type', render: (v) => badge(BB.label('inventory_txn_kinds', v), v) },
            { key: 'quantity', label: 'Quantity', align: 'right', render: (v) => num(v, 2) },
            { key: 'note', label: 'Note', render: (v) => esc(v || '—') },
            { key: 'when', label: 'When', render: (v) => dateFmt(v, true) },
          ], { compact: true }) : emptyState('No transactions yet', '', 'list'),
          footer: '<button class="btn btn-ghost" data-close>Close</button>',
        });
      }
      const move = e.target.closest('[data-move]');
      if (move) {
        const id = Number(move.getAttribute('data-move'));
        const item = items.find((i) => i.id === id);
        await modal({
          title: `Stock movement — ${item.material_name}`,
          body: `<form id="txn-form"><div class="form-grid">
            ${field('kind', 'Movement type', { options: Object.entries(BB.labels.inventory_txn_kinds || {}).map(([k, v]) => ({ value: k, label: v })) })}
            ${field('quantity', 'Quantity', { type: 'number', step: '0.01', min: 0, required: true })}
            ${field('note', 'Reference / note', { placeholder: 'Delivery note or reason' })}
          </div>
          <p class="small muted" style="margin:8px 0 0">Current available stock: ${num(item.available, 2)} ${esc(item.unit)}.
          Consuming more than available is rejected.</p></form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Record movement</button>`,
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const body = formValues(el('#txn-form', root));
            if (!body.quantity || body.quantity <= 0) { toast('Quantity must be greater than zero.', 'error'); return false; }
            api(`/projects/${pid}/inventory/${id}/transactions`, { method: 'POST', body })
              .then(() => { toast('Stock updated.', 'success'); BB.project.go('inventory'); }).catch(() => {});
            return true;
          },
        });
      }
    });
  };

  /* ----------------------------------------------------------- procurement */
  BB.projectTabs.procurement = async function (host, pid) {
    const pos = await api(`/projects/${pid}/purchase-orders`);
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>Purchase orders</h2><div class="spacer"></div>
        <button class="btn btn-sm" type="button" data-new-po>New purchase order</button></div>
      <p class="small muted" style="margin-top:-4px">Orders are drafts until you mark them received. Delivery dates are
      recorded by you — nothing is confirmed with a supplier automatically.</p>
      ${pos.length ? table(pos, [
        { key: 'number', label: 'Order', render: (v) => `<strong>${esc(v)}</strong>` },
        { key: 'supplier', label: 'Supplier' },
        { key: 'created_at', label: 'Created', render: (v) => dateFmt(v) },
        { key: 'expected_date', label: 'Expected', render: (v) => v ? dateFmt(v) : '<span class="muted">—</span>' },
        { key: 'status', label: 'Status', render: (v, r) => badge(BB.humanize(v), v === 'received' ? 'ok' : v === 'draft' ? 'draft' : 'pending')
            + (r.delivery_late ? ' ' + badge('Delayed', 'critical') : '') },
        { key: 'total', label: 'Value', align: 'right', render: (v) => moneyCell(v) },
        { key: 'id', label: '', render: (v, r) => `<div class="btn-group">
            <button class="btn btn-ghost btn-sm" type="button" data-po-pdf="${v}">PDF</button>
            ${r.status !== 'received' ? `<button class="btn btn-ghost btn-sm" type="button" data-receive="${v}">Mark received</button>` : ''}
          </div>` },
      ], { compact: true }) : emptyState('No purchase orders yet', 'Draft an order from your material requirements, then mark it received when it arrives.', 'clipboard-list')}
      <div class="btn-group" style="margin-top:12px">${reportLink(pid, 'summary', 'pdf', 'Project summary')}${reportLink(pid, 'inventory', 'xlsx', 'Inventory Excel')}</div>
    </div>`;
    bindReports(host, pid);
    host.addEventListener('click', async (e) => {
      if (e.target.closest('[data-new-po]')) {
        const suppliers = await api('/suppliers');
        let line = 0;
        const lineRow = () => `<div class="po-line form-grid" style="margin-bottom:8px;border-bottom:1px solid var(--border);padding-bottom:8px">
          ${field('material_' + (line), 'Material', { required: true })}
          ${field('unit_' + (line), 'Unit', { required: true, value: 'pcs' })}
          ${field('quantity_' + (line), 'Quantity', { type: 'number', step: '0.01', min: 0, required: true })}
          ${field('price_' + (line++), 'Unit price (₹)', { type: 'number', step: '0.01', min: 0, required: true })}
        </div>`;
        const first = lineRow();
        await modal({
          title: 'New purchase order',
          wide: true,
          body: `<form id="po-form">
            <div class="form-grid">
              ${field('supplier_id', 'Supplier', { options: [{ value: '', label: 'No supplier selected' }].concat(suppliers.map((s) => ({ value: String(s.id), label: s.name }))) })}
              ${field('expected_date', 'Expected delivery', { type: 'date' })}
              ${field('notes', 'Notes', { textarea: true, rows: 2 })}
            </div>
            <div style="display:flex;align-items:center;gap:8px;margin:12px 0 8px"><strong>Lines</strong>
              <div style="flex:1"></div><button class="btn btn-ghost btn-sm" type="button" id="po-add-line">Add line</button></div>
            <div id="po-lines">${first}</div>
          </form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Create draft order</button>`,
          onMount: (root) => {
            el('#po-add-line', root).addEventListener('click', () => {
              el('#po-lines', root).insertAdjacentHTML('beforeend', lineRow());
            });
          },
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const v = formValues(el('#po-form', root));
            const items = [];
            for (let i = 0; i < line; i++) {
              const material = v['material_' + i];
              if (!material) continue;
              items.push({ material_name: material, unit: v['unit_' + i] || 'pcs', quantity: Number(v['quantity_' + i] || 0), unit_price: Number(v['price_' + i] || 0) });
            }
            if (!items.length) { toast('Add at least one material line.', 'error'); return false; }
            const body = { items, notes: v.notes || '', supplier_id: v.supplier_id ? Number(v.supplier_id) : null };
            if (v.expected_date) body.expected_date = v.expected_date;
            api(`/projects/${pid}/purchase-orders`, { method: 'POST', body })
              .then(() => { toast('Draft purchase order created.', 'success'); BB.project.go('procurement'); }).catch(() => {});
            return true;
          },
        });
      }
      const pdf = e.target.closest('[data-po-pdf]');
      if (pdf) {
        await download(`/projects/${pid}/purchase-orders/${pdf.getAttribute('data-po-pdf')}/pdf`, 'purchase-order.pdf');
      }
      const rec = e.target.closest('[data-receive]');
      if (rec) {
        if (!await confirmDialog({ title: 'Mark this order as received?', message: 'Stock levels will be increased for each line and the delivery date recorded.', confirmText: 'Mark received' })) return;
        await api(`/projects/${pid}/purchase-orders/${rec.getAttribute('data-receive')}/receive`, { method: 'POST' });
        toast('Order received and stock updated.', 'success'); BB.project.go('procurement');
      }
    });
  };

  /* --------------------------------------------------------------- labour */
  BB.projectTabs.labour = async function (host, pid) {
    const data = await api(`/projects/${pid}/labour`);
    host.innerHTML = `<div class="grid grid-kpi">
        <div class="kpi"><div class="label">Labour cost recorded</div><div class="value">${moneyShort(data.total_cost)}</div></div>
        <div class="kpi"><div class="label">Worker-days</div><div class="value">${num(data.worker_days, 1)}</div></div>
        <div class="kpi"><div class="label">Entries</div><div class="value">${data.entries.length}</div></div>
        <div class="kpi"><div class="label">Categories</div><div class="value">${(data.by_category || []).length}</div></div>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-head"><h2>Labour entries</h2><div class="spacer"></div>
          <button class="btn btn-sm" type="button" data-add>Log attendance</button></div>
        <p class="small muted" style="margin-top:-4px">${esc(data.note || '')}</p>
        ${data.entries.length ? table(data.entries, [
          { key: 'work_date', label: 'Date', render: (v) => dateFmt(v) },
          { key: 'category', label: 'Category' },
          { key: 'contractor', label: 'Contractor', render: (v) => esc(v || '—') },
          { key: 'workers', label: 'Workers', align: 'right' },
          { key: 'days', label: 'Days', align: 'right' },
          { key: 'rate', label: 'Rate', align: 'right', render: (v, r) => `${money(v)} <span class="small muted">${esc(BB.humanize(r.rate_type))}</span>` },
          { key: 'total', label: 'Cost', align: 'right', render: (v) => moneyCell(v) },
          { key: 'id', label: '', render: (v) => `<button class="btn btn-ghost btn-sm" type="button" data-del="${v}">Delete</button>` },
        ], { compact: true }) : emptyState('No labour recorded', 'Log attendance with the rate you agreed with the contractor.', 'hard-hat')}
        ${(data.by_category || []).length ? `<div class="card" style="margin-top:14px;box-shadow:none">
          <div class="card-head"><h3>Cost by category</h3></div>
          ${table(data.by_category, [{ key: 'category', label: 'Category' },
            { key: 'worker_days', label: 'Worker-days', align: 'right', render: (v) => num(v, 1) },
            { key: 'cost', label: 'Cost', align: 'right', render: (v) => money(v) }], { compact: true })}</div>` : ''}
      </div>`;
    host.addEventListener('click', async (e) => {
      if (e.target.closest('[data-add]')) {
        await modal({
          title: 'Log labour attendance',
          body: `<form id="lab-form"><div class="form-grid">
            ${field('category', 'Worker category', { required: true, placeholder: 'e.g. Painter, Mason, Helper' })}
            ${field('contractor', 'Contractor', { placeholder: 'Optional' })}
            ${field('workers', 'Number of workers', { type: 'number', min: 1, value: 1, required: true })}
            ${field('days', 'Days worked', { type: 'number', min: 0.5, step: '0.5', value: 1, required: true })}
            ${field('rate', 'Agreed rate (₹)', { type: 'number', min: 0, step: '0.01', required: true, hint: 'Use the rate you agreed; nothing is inferred.' })}
            ${field('rate_type', 'Rate basis', { options: [{ value: 'per_day', label: 'Per day' }, { value: 'per_hour', label: 'Per hour' }, { value: 'per_sqft', label: 'Per sq ft' }] })}
            ${field('hours_per_day', 'Hours per day', { type: 'number', min: 1, max: 24, step: '0.5', value: 8 })}
            ${field('work_date', 'Work date', { type: 'date', value: new Date().toISOString().slice(0, 10) })}
            ${field('note', 'Note', { textarea: true, rows: 2 })}
          </div></form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Log entry</button>`,
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const body = formValues(el('#lab-form', root));
            if (!body.category) { toast('Choose or type a worker category.', 'error'); return false; }
            api(`/projects/${pid}/labour`, { method: 'POST', body })
              .then(() => { toast('Labour entry logged.', 'success'); BB.project.go('labour'); }).catch(() => {});
            return true;
          },
        });
      }
      const del = e.target.closest('[data-del]');
      if (del) {
        if (!await confirmDialog({ title: 'Delete this labour entry?', message: 'Only this attendance record is removed.', confirmText: 'Delete', danger: true })) return;
        await api(`/projects/${pid}/labour/${del.getAttribute('data-del')}`, { method: 'DELETE' });
        BB.project.go('labour');
      }
    });
  };

  /* ------------------------------------------------------------- schedule */
  BB.projectTabs.schedule = async function (host, pid) {
    const [data, proj] = await Promise.all([api(`/projects/${pid}/tasks`), projectOf(pid)]);
    const plan = data.plan || {};
    const rows = plan.rows || [];
    const all = rows.length ? rows : [];
    const min = all.length ? new Date(all[0].start) : null;
    const max = all.length ? new Date(all.reduce((a, r) => (r.end > a ? r.end : a), all[0].end)) : null;
    const span = min && max ? Math.max(1, (max - min) / 86400000 + 1) : 1;
    const gantt = rows.length ? `<div class="gantt">
      <div class="gantt-head"><div>Activity</div><div>${dateFmt(plan.project_start)} → ${dateFmt(plan.project_finish)} · ${plan.calendar_span_days} calendar days</div></div>
      ${rows.map((r) => {
        const offset = Math.max(0, (new Date(r.start) - min) / 86400000);
        const width = Math.max(1, ((new Date(r.end) - new Date(r.start)) / 86400000 + 1) / span * 100);
        return `<div class="gantt-row">
          <div><strong>${esc(r.name)}</strong>
            <div class="small muted">${esc(r.assignee || 'Unassigned')} · ${r.duration_days}d${r.critical ? ' · critical' : ''}${r.overdue ? ` · <span style="color:var(--danger)">${r.days_late}d late</span>` : ''}</div></div>
          <div class="gantt-track" title="${esc(r.name)}: ${dateFmt(r.start)} to ${dateFmt(r.end)}">
            <div class="gantt-bar ${r.critical ? 'critical' : ''} ${r.milestone ? 'milestone' : ''}"
                 style="left:${offset / span * 100}%;width:${width}%">
              <div class="gantt-fill" style="width:${Math.min(100, Number(r.progress) || 0)}%"></div>
            </div>
          </div></div>`;
      }).join('')}
    </div>
    <div class="gantt-legend"><span><i style="background:var(--navy-600)"></i>Planned</span>
      <span><i style="background:var(--danger)"></i>Critical path</span>
      <span><i style="background:var(--amber)"></i>Milestone</span>
      <span>Fill = recorded progress</span></div>` : emptyState('No tasks scheduled', 'Add tasks with durations and dependencies to build a Gantt plan.', 'calendar-range');

    const weather = proj.has_coordinates
      ? '<div class="insight info"><i data-lucide="cloud-sun" class="ico"></i><div><b>Weather advisory</b><span>Loading forecast…</span></div></div>'
      : '<div class="insight info"><i data-lucide="map-pin" class="ico"></i><div><b>Weather not available</b><span>Add latitude and longitude to this project for an advisory forecast.</span></div></div>';

    host.innerHTML = `
      <div class="grid grid-kpi">
        <div class="kpi"><div class="label">Tasks</div><div class="value">${data.tasks.length}</div></div>
        <div class="kpi"><div class="label">Planned finish</div><div class="value sm">${plan.project_finish ? dateFmt(plan.project_finish) : '—'}</div></div>
        <div class="kpi"><div class="label">Critical path</div><div class="value">${data.cpm.total_duration_days || 0}d</div>
          <div class="foot">Working duration</div></div>
        <div class="kpi ${(plan.overdue || []).length ? 'is-danger' : ''}"><div class="label">Overdue</div><div class="value">${(plan.overdue || []).length}</div></div>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-head"><h2>Schedule</h2><div class="spacer"></div>
          <div class="btn-group"><button class="btn btn-sm" type="button" data-add-task>Add task</button>
          ${reportLink(pid, 'progress', 'pdf', 'Progress report')}</div></div>
        ${gantt}
        <p class="small muted" style="margin:10px 0 0">${esc(plan.note || '')}</p>
      </div>
      <div class="grid grid-2" style="margin-top:16px">
        <div class="card"><div class="card-head"><h3>Critical path</h3></div>
          <p class="small">${(data.cpm.critical_path_names || []).length ? esc(data.cpm.critical_path_names.join(' → ')) : 'No critical path yet.'}</p>
          <p class="small muted" style="margin:0">${esc(data.cpm.note || '')}</p></div>
        <div class="card"><div class="card-head"><h3>Variance</h3></div>
          ${data.variance && Object.keys(data.variance).length ? `<dl class="dl">
            <dt>Planned effort</dt><dd>${num(data.variance.planned_days, 1)} days</dd>
            <dt>Completed equivalent</dt><dd>${num(data.variance.completed_equivalent_days, 1)} days</dd>
            <dt>Progress</dt><dd>${pct(data.variance.progress_pct)}</dd>
            <dt>Late tasks</dt><dd>${num(data.variance.late_tasks, 0)}</dd>
            <dt>Total late days</dt><dd>${num(data.variance.total_late_days, 0)}</dd>
            <dt>As of</dt><dd>${dateFmt(data.variance.as_of)}</dd></dl>` : '<p class="small muted">No variance yet.</p>'}
        </div>
      </div>
      <div class="card" style="margin-top:16px"><div class="card-head"><h3>Weather</h3></div>${weather}</div>
      <div class="card" style="margin-top:16px">
        <div class="card-head"><h2>Tasks</h2></div>
        ${data.tasks.length ? table(data.tasks.map((t) => {
          const row = rows.find((r) => r.id === t.id) || {};
          return { ...t, start: row.start, end: row.end, critical: row.critical, overdue: row.overdue, days_late: row.days_late };
        }), [
          { key: 'name', label: 'Task', render: (v, r) => `<strong>${esc(v)}</strong>${r.milestone ? ' ' + badge('Milestone', 'info') : ''}
            ${r.depends_on && r.depends_on.length ? `<div class="small muted">After ${r.depends_on.map((id) => (data.tasks.find((t) => t.id === id) || {}).name || ('#' + id)).map(esc).join(', ')}</div>` : ''}` },
          { key: 'duration_days', label: 'Days', align: 'right' },
          { key: 'start', label: 'Start', render: (v) => v ? dateFmt(v) : '—' },
          { key: 'end', label: 'Finish', render: (v) => v ? dateFmt(v) : '—' },
          { key: 'progress', label: 'Progress', render: (v) => `<div style="min-width:80px">${progressBar(v)}</div><span class="small muted">${num(v, 0)}%</span>` },
          { key: 'priority', label: 'Priority', render: (v) => badge(BB.label('task_priority', v), v) },
          { key: 'overdue', label: '', render: (v) => v ? badge('Overdue', 'critical') : '' },
          { key: 'id', label: '', render: (v, r) => `<div class="btn-group">
              <button class="btn btn-ghost btn-sm" type="button" data-progress="${v}" data-current="${r.progress}">Progress</button>
              <button class="btn btn-ghost btn-sm" type="button" data-del-task="${v}">Delete</button></div>` },
        ], { compact: true }) : emptyState('No tasks yet', 'Tasks drive the Gantt and progress figures.', 'list-todo')}
      </div>`;
    bindReports(host, pid);
    icons(host);

    if (proj.has_coordinates) {
      api(`/projects/${pid}/weather?days=3`, { silent: true }).then((w) => {
        const box = host.querySelector('.insight.info');
        if (!box) return;
        const days = (w.days || w.forecast || []).slice(0, 3);
        box.innerHTML = `<i data-lucide="cloud-sun" class="ico"></i><div><b>Weather advisory — ${esc(w.location || w.timezone || 'site')}</b>
          <span>${days.length ? days.map((d) => `${esc(d.date || '')}: ${esc(d.condition || d.summary || '')} ${d.temp_max != null ? Math.round(d.temp_max) + '° / ' + Math.round(d.temp_min) + '°' : ''}${d.precipitation_mm != null ? ' · ' + d.precipitation_mm + ' mm' : ''}`).join(' · ') : 'No forecast data returned.'}</span>
          <span class="small">Advisory only — not a site-safety determination.</span></div>`;
        icons(host);
      }).catch(() => {
        const box = host.querySelector('.insight.info');
        if (box) box.innerHTML = '<i data-lucide="cloud-off" class="ico"></i><div><b>Forecast unavailable</b><span>The weather provider could not be reached. Try again later.</span></div>';
        icons(host);
      });
    }

    host.addEventListener('click', async (e) => {
      if (e.target.closest('[data-add-task]')) {
        const options = data.tasks.map((t) => ({ value: String(t.id), label: t.name }));
        await modal({
          title: 'Add a task',
          body: `<form id="task-form"><div class="form-grid">
            ${field('name', 'Task name', { required: true })}
            ${field('duration_days', 'Duration (working days)', { type: 'number', min: 1, value: 1, required: true })}
            ${field('start_date', 'Earliest start', { type: 'date', value: proj.start_date || '' })}
            ${field('priority', 'Priority', { options: Object.entries(BB.labels.task_priority || {}).map(([k, v]) => ({ value: k, label: v })) })}
            ${field('assignee', 'Assigned to', { placeholder: 'Person or crew' })}
            ${field('progress', 'Progress %', { type: 'number', min: 0, max: 100, value: 0 })}
            <div class="field"><label for="dep-select">Depends on</label>
              <select id="dep-select" multiple size="${Math.min(6, Math.max(2, options.length))}" style="min-height:auto">
                ${options.map((o) => `<option value="${o.value}">${esc(o.label)}</option>`).join('')}
              </select><span class="hint">Select one or more earlier tasks. Circular chains are rejected.</span></div>
            <label class="check" style="align-self:end"><input type="checkbox" name="milestone"> Milestone</label>
            ${field('notes', 'Notes', { textarea: true, rows: 2 })}
          </div></form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Add task</button>`,
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const body = formValues(el('#task-form', root));
            const dep = el('#dep-select', root);
            body.depends_on = Array.from(dep.selectedOptions).map((o) => Number(o.value));
            if (!body.start_date) delete body.start_date;
            api(`/projects/${pid}/tasks`, { method: 'POST', body })
              .then(() => { toast('Task added.', 'success'); BB.project.go('schedule'); })
              .catch(() => {});
            return true;
          },
        });
      }
      const prog = e.target.closest('[data-progress]');
      if (prog) {
        const current = Number(prog.getAttribute('data-current'));
        await modal({
          title: 'Update progress',
          body: `<form id="prog-form">${field('progress', 'Completion %', { type: 'number', min: 0, max: 100, value: current })}</form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Save progress</button>`,
          onResult: (value, root) => {
            if (value !== 'save') return true;
            const v = formValues(el('#prog-form', root));
            api(`/projects/${pid}/tasks/${prog.getAttribute('data-progress')}/progress?progress=${Number(v.progress || 0)}`, { method: 'PUT' })
              .then(() => { toast('Progress updated.', 'success'); BB.project.go('schedule'); }).catch(() => {});
            return true;
          },
        });
      }
      const del = e.target.closest('[data-del-task]');
      if (del) {
        if (!await confirmDialog({ title: 'Delete this task?', message: 'Dependencies that point to it will also be removed.', confirmText: 'Delete', danger: true })) return;
        await api(`/projects/${pid}/tasks/${del.getAttribute('data-del-task')}`, { method: 'DELETE' });
        BB.project.go('schedule');
      }
    });
  };

  /* ------------------------------------------------------------ documents */
  BB.projectTabs.documents = async function (host, pid) {
    const docs = await api(`/documents?project_id=${pid}`);
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>Project documents</h2><div class="spacer"></div>
        <a class="btn btn-sm" href="/knowledge">Upload in Knowledge Base</a></div>
      ${docs.length ? `<div class="grid grid-3">${docs.map((d) => `<div class="card" style="box-shadow:none">
        <div style="display:flex;justify-content:space-between;gap:8px">
          <strong>${esc(d.name)}</strong><span class="badge">${esc(d.pages ? d.pages + ' pages' : 'No pages')}</span></div>
        <div class="small muted" style="margin:6px 0">${esc(BB.label('document_categories', d.category))} · v${esc(d.version)}</div>
        <div class="small">${num(d.chunks, 0)} indexed passages · ${num((d.size_bytes || 0) / 1024, 0)} KB</div>
        <div class="small muted" style="margin-top:4px">Uploaded ${dateFmt(d.uploaded_at)}</div>
      </div>`).join('')}</div>` : emptyState('No documents linked to this project', 'Upload specifications, quotations or approved quantities in the Knowledge Base and link them to this project.', 'files')}
      <p class="small muted" style="margin:10px 0 0">Documents are treated as untrusted reference text. They inform answers but never trigger actions.</p>
    </div>`;
  };

  /* -------------------------------------------------------------- reports */
  BB.projectTabs.reports = async function (host, pid) {
    const data = await api(`/reports/catalog?project_id=${pid}`);
    host.innerHTML = `<div class="card"><div class="card-head"><h2>Reports</h2></div>
      <div class="grid grid-2">
        ${data.reports.map((r) => `<div class="card" style="box-shadow:none">
          <h3>${esc(r.label)}</h3><p class="small muted">${esc(r.description)}</p>
          <div class="btn-group">${r.formats.map((f) => `<button class="btn btn-ghost btn-sm" type="button"
            data-report="${esc(r.key)}" data-fmt="${esc(f)}">${esc(f.toUpperCase())}</button>`).join('')}</div>
        </div>`).join('')}
      </div>
      <p class="small muted" style="margin:12px 0 0">Reports carry the project name, date, data sources and scope
      limitations. Preliminary planning documents, not audited statements.</p></div>`;
    bindReports(host, pid);
  };

  /* ------------------------------------------------------------- activity */
  BB.projectTabs.activity = async function (host, pid) {
    const rows = await api(`/projects/${pid}/activity`);
    host.innerHTML = `<div class="card"><div class="card-head"><h2>Project activity</h2><div class="spacer"></div>
        <span class="small muted">${rows.length} event(s)</span></div>
      ${rows.length ? `<ul class="timeline">${rows.map((r) => `<li>
        <div><strong>${esc(BB.humanize(r.action))}</strong> — ${esc(r.summary || '')}</div>
        <div class="when">${esc(r.user)} · ${dateFmt(r.when, true)}</div></li>`).join('')}</ul>`
        : emptyState('No activity yet', 'Project changes, estimates and approvals appear here.', 'history')}
    </div>`;
  };
})();
