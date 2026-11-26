/* Suppliers and prices: directory CRUD, quotations, delivered-cost comparison,
   CSV import, purchase requirements, orders and deliveries. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, money, moneyShort, num, qty, table, badge, emptyState, modal,
          confirm: confirmDialog, toast, icons, dateFmt, field, formValues } = BB;

  const host = el('#sup-host');
  let tab = 'directory';
  let suppliers = [];
  let prices = [];

  const SOURCE_OPTIONS = () => Object.entries(BB.labels.sources || {})
    .filter(([k]) => ['user_entered', 'supplier_quotation', 'historical', 'demonstration'].includes(k))
    .map(([k, v]) => ({ value: k, label: v }));

  function supplierOptions(includeBlank) {
    const opts = suppliers.filter((s) => (s.name || '').trim()).map((s) => ({ value: String(s.id), label: s.name }));
    return includeBlank ? [{ value: '', label: 'No supplier selected' }].concat(opts) : opts;
  }

  /* ------------------------------------------------------------- directory */
  function directory() {
    const blanks = suppliers.filter((s) => !(s.name || '').trim());
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>Supplier directory</h2><div class="spacer"></div>
        <input id="sup-q" type="search" placeholder="Search name, category, location" style="max-width:240px"></div>
      ${blanks.length ? `<div class="insight warning" style="margin-bottom:12px">
        <i data-lucide="alert-triangle" class="ico"></i>
        <div><b>${blanks.length} legacy supplier record has no name</b>
        <span>It was created before name validation existed. Edit it to add a name or delete it. New suppliers cannot be saved without a name.</span>
        <div class="btn-group" style="margin-top:6px"><button class="btn btn-ghost btn-sm" type="button" data-fix-blank>Review record</button></div></div>
      </div>` : ''}
      <div id="sup-table"></div>
      <p class="small muted" style="margin:10px 0 0">Reliability is only shown when you have recorded purchase orders and
      deliveries for that supplier. Demonstration suppliers are labelled and never presented as market data.</p>
    </div>`;
    drawDirectory();
    el('#sup-q').addEventListener('input', drawDirectory);
    const fix = host.querySelector('[data-fix-blank]');
    if (fix) fix.addEventListener('click', () => { const b = blanks[0]; if (b) openSupplier(b); });
    icons(host);
  }

  function drawDirectory() {
    const q = (el('#sup-q') ? el('#sup-q').value : '').toLowerCase().trim();
    const rows = suppliers.filter((s) => !q || [s.name, s.category, s.location, s.email].join(' ').toLowerCase().includes(q));
    el('#sup-table').innerHTML = rows.length ? table(rows, [
      { key: 'name', label: 'Supplier', render: (v, r) => `<strong>${esc(v || 'Unnamed supplier')}</strong>
        ${r.is_demo ? ' ' + badge('Demo', 'demonstration') : ''}
        <div class="small muted">${esc(r.category || 'Uncategorised')}</div>` },
      { key: 'email', label: 'Contact', render: (v, r) => `${v ? esc(v) : '<span class="muted">No email</span>'}
        ${r.phone ? `<div class="small muted">${esc(r.phone)}</div>` : ''}` },
      { key: 'location', label: 'Location', render: (v) => esc(v || '—') },
      { key: 'lead_time_days', label: 'Lead time', align: 'right', render: (v) => `${num(v, 0)} d` },
      { key: 'reliability', label: 'Reliability', align: 'right', render: (v) => v ? `${num(v, 1)} / 5` : '<span class="muted">Not scored</span>' },
      { key: 'tax_id', label: 'Tax ID', render: (v) => v ? esc(v) : '<span class="muted">—</span>' },
      { key: 'id', label: '', render: (v, r) => `<div class="btn-group">
          <button class="btn btn-ghost btn-sm" type="button" data-edit="${v}">Edit</button>
          <button class="btn btn-ghost btn-sm" type="button" data-del="${v}">Delete</button></div>` },
    ], { compact: true }) : emptyState('No suppliers match your search', 'Try a different name, category or location.', 'users');
  }

  async function openSupplier(s) {
    const editing = !!s;
    s = s || {};
    await modal({
      title: editing ? 'Edit supplier' : 'Add supplier',
      wide: true,
      body: `<form id="sup-form"><div class="form-grid">
        ${field('name', 'Supplier name', { required: true, value: s.name, hint: 'Required. This is what appears in comparisons and purchase orders.' })}
        ${field('category', 'Material category', { value: s.category, placeholder: 'e.g. Cement, Tiles, Paint' })}
        ${field('email', 'Email', { type: 'email', value: s.email })}
        ${field('phone', 'Phone', { value: s.phone })}
        ${field('location', 'Location', { value: s.location })}
        ${field('tax_id', 'GSTIN / tax ID', { value: s.tax_id })}
        ${field('lead_time_days', 'Typical lead time (days)', { type: 'number', min: 0, max: 365, value: s.lead_time_days != null ? s.lead_time_days : 3 })}
        ${field('payment_terms', 'Payment terms', { value: s.payment_terms, placeholder: 'e.g. 30 days' })}
        ${field('notes', 'Notes', { textarea: true, rows: 2, value: s.notes })}
      </div></form>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button>
        <button class="btn btn-accent" data-result="save">${editing ? 'Save supplier' : 'Add supplier'}</button>`,
      onResult: (value, root) => {
        if (value !== 'save') return true;
        const body = formValues(el('#sup-form', root));
        body.lead_time_days = Number(body.lead_time_days || 0);
        if (!body.name || !body.name.trim()) { toast('A supplier name is required.', 'error'); return false; }
        const call = editing ? api(`/suppliers/${s.id}`, { method: 'PUT', body }) : api('/suppliers', { method: 'POST', body });
        call.then(() => { toast(editing ? 'Supplier updated.' : 'Supplier added.', 'success'); loadAll(); }).catch(() => {});
        return true;
      },
    });
  }

  /* ---------------------------------------------------------------- prices */
  function priceRows(list) {
    return table(list, [
      { key: 'material', label: 'Material', render: (v, r) => `<strong>${esc(v)}</strong>
        <div class="small muted">${esc(r.category || '')}${r.brand ? ' · ' + esc(r.brand) : ''}</div>` },
      { key: 'supplier', label: 'Supplier', render: (v) => v ? esc(v) : '<span class="muted">No supplier</span>' },
      { key: 'unit', label: 'Unit' },
      { key: 'unit_price', label: 'Unit price', align: 'right', render: (v) => money(v) },
      { key: 'tax_pct', label: 'Tax', align: 'right', render: (v) => num(v, 0) + '%' },
      { key: 'delivery_charge', label: 'Delivery', align: 'right', render: (v) => money(v) },
      { key: 'moq', label: 'MOQ', align: 'right', render: (v) => num(v, 0) },
      { key: 'valid_until', label: 'Valid until', render: (v, r) => {
          if (!v) return '<span class="muted">Not stated</span>';
          const expired = new Date(v) < new Date();
          return `${dateFmt(v)} ${expired ? badge('Expired', 'critical') : ''}`;
        } },
      { key: 'source_type', label: 'Source', render: (v) => badge(BB.label('sources', v), v) },
      { key: 'id', label: '', render: (v) => `<button class="btn btn-ghost btn-sm" type="button" data-del-price="${v}">Delete</button>` },
    ], { compact: true });
  }

  function pricesTab() {
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>Price database</h2><div class="spacer"></div>
        <div class="btn-group">
          <button class="btn btn-sm" type="button" id="add-price">Add price</button>
          <button class="btn btn-ghost btn-sm" type="button" id="import-csv">Import CSV</button>
        </div></div>
      <p class="small muted" style="margin-top:-6px">Every price carries its source and validity. Nothing here is inferred,
      and demonstration rows are labelled.</p>
      ${prices.length ? priceRows(prices) : emptyState('No prices stored', 'Add a supplier quotation or import a CSV to price materials.', 'tag')}
      <div class="small muted" style="margin-top:10px">Common CSV columns: material_name, category, unit, unit_price,
        tax_pct, delivery_charge, moq, valid_until, supplier, brand, source_type.</div>
    </div>`;
    el('#add-price').addEventListener('click', openPrice);
    el('#import-csv').addEventListener('click', openImport);
    bindPriceDelete();
  }

  function bindPriceDelete() {
    host.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-del-price]');
      if (!b) return;
      if (!await confirmDialog({ title: 'Delete this price?', message: 'The quotation will no longer be available for comparisons or BOQ pricing.', confirmText: 'Delete', danger: true })) return;
      await api(`/material-prices/${b.getAttribute('data-del-price')}`, { method: 'DELETE' });
      toast('Price deleted.', 'success'); loadAll();
    });
  }

  async function openPrice() {
    await modal({
      title: 'Add a material price',
      wide: true,
      body: `<form id="price-form"><div class="form-grid">
        ${field('material_name', 'Material name', { required: true, placeholder: 'e.g. Cement OPC 53 grade' })}
        ${field('category', 'Category', { value: 'Other' })}
        ${field('unit', 'Unit', { required: true, value: 'bag' })}
        ${field('unit_price', 'Unit price (₹)', { type: 'number', step: '0.01', min: 0, required: true })}
        ${field('tax_pct', 'Tax %', { type: 'number', step: '0.01', min: 0, max: 100, value: 18 })}
        ${field('delivery_charge', 'Delivery charge (₹)', { type: 'number', step: '0.01', min: 0, value: 0 })}
        ${field('moq', 'Minimum order quantity', { type: 'number', step: '0.01', min: 0, value: 1 })}
        ${field('supplier_id', 'Supplier', { options: supplierOptions(true) })}
        ${field('valid_until', 'Quotation valid until', { type: 'date' })}
        ${field('brand', 'Brand / specification', { value: '' })}
        ${field('source_type', 'Source', { options: SOURCE_OPTIONS() })}
      </div></form>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Save price</button>`,
      onResult: (value, root) => {
        if (value !== 'save') return true;
        const body = formValues(el('#price-form', root));
        body.supplier_id = body.supplier_id ? Number(body.supplier_id) : null;
        ['unit_price', 'tax_pct', 'delivery_charge', 'moq'].forEach((k) => { body[k] = Number(body[k] || 0); });
        if (!body.valid_until) delete body.valid_until;
        api('/material-prices', { method: 'POST', body })
          .then(() => { toast('Price saved.', 'success'); loadAll(); }).catch(() => {});
        return true;
      },
    });
  }

  async function openImport() {
    const modalResult = await modal({
      title: 'Import supplier prices from CSV',
      wide: true,
      body: `<p class="small muted">Upload a CSV, review the parsed rows and any duplicates, then confirm.
        Nothing is saved until you confirm.</p>
        <div class="field"><label for="csv-file">CSV file</label><input id="csv-file" type="file" accept=".csv,text/csv"></div>
        <div id="import-preview" style="margin-top:12px"></div>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button>
        <button class="btn btn-ghost" type="button" id="preview-csv">Preview</button>
        <button class="btn btn-accent" type="button" id="confirm-csv" disabled>Import rows</button>`,
      onMount: (root, close) => {
        const fileInput = el('#csv-file', root);
        const preview = el('#import-preview', root);
        const confirmBtn = el('#confirm-csv', root);
        let file = null;
        el('#preview-csv', root).addEventListener('click', async () => {
          file = fileInput.files && fileInput.files[0];
          if (!file) return toast('Choose a CSV file first.', 'error');
          const fd = new FormData(); fd.append('file', file);
          try {
            const r = await api('/material-prices/import/preview', { method: 'POST', body: fd });
            preview.innerHTML = `<div class="stat-inline" style="margin-bottom:8px">
              <div><div class="k">Rows parsed</div><div class="v">${r.valid}</div></div>
              <div><div class="k">Possible duplicates</div><div class="v">${(r.duplicates || []).length}</div></div>
              <div><div class="k">Errors</div><div class="v">${(r.errors || []).length}</div></div></div>
              ${(r.errors || []).length ? `<div class="alert error">${r.errors.map(esc).join('<br>')}</div>` : ''}
              ${(r.rows || []).length ? table(r.rows, [
                { key: 'material_name', label: 'Material', render: (v, row) => esc(v) + (row.possible_duplicate ? ' ' + badge('Duplicate?', 'warning') : '') },
                { key: 'unit', label: 'Unit' }, { key: 'unit_price', label: 'Price', align: 'right', render: (v) => money(v) },
                { key: 'tax_pct', label: 'Tax', align: 'right' }, { key: 'supplier', label: 'Supplier', render: (v) => esc(v || '—') },
              ], { compact: true }) : '<p class="small muted">No valid rows found.</p>'}
              <p class="small muted" style="margin-top:6px">${esc(r.note || '')}</p>`;
            confirmBtn.disabled = !(r.rows || []).length;
          } catch (err) { /* toasted */ }
        });
        confirmBtn.addEventListener('click', async () => {
          if (!file) return;
          const fd = new FormData(); fd.append('file', file);
          confirmBtn.disabled = true;
          try {
            const r = await api('/material-prices/import-csv', { method: 'POST', body: fd });
            const parts = Object.entries(r).filter(([, v]) => typeof v === 'number')
              .map(([k, v]) => `${v} ${BB.humanize(k).toLowerCase()}`);
            toast(`Import complete — ${parts.join(', ')}.`, 'success');
            close('done');
            loadAll();
          } catch (err) { confirmBtn.disabled = false; }
        });
      },
    });
  }

  /* ------------------------------------------------------------ quotations */
  function quotations() {
    const rows = prices.filter((p) => p.source_type === 'supplier_quotation' || p.valid_until);
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>Quotations</h2><div class="spacer"></div><span class="small muted">${rows.length} stored</span></div>
      <p class="small muted" style="margin-top:-6px">Quotations with a stated validity are flagged once they expire. Expired
      prices remain visible but sort below valid offers in comparisons.</p>
      ${rows.length ? priceRows(rows) : emptyState('No quotations stored', 'Add a price with the source "Supplier quotation" and a validity date.', 'file-check')}
    </div>`;
    bindPriceDelete();
  }

  /* -------------------------------------------------------------- compare */
  function compareTab() {
    const materials = Array.from(new Set(prices.map((p) => p.material))).sort();
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>Supplier comparison</h2></div>
      <p class="small muted" style="margin-top:-6px">Comparison uses total delivered cost: quantity (respecting the minimum
      order), tax and delivery. Expired or unavailable offers are ranked after valid ones.</p>
      <form id="compare-form" class="form-row">
        <div class="field" style="flex:2 1 240px"><label for="cmp-material">Material</label>
          <select id="cmp-material" name="material">${materials.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join('')}</select></div>
        <div class="field" style="flex:1 1 140px"><label for="cmp-qty">Quantity</label>
          <input id="cmp-qty" name="quantity" type="number" min="1" step="0.01" value="10"></div>
        <button class="btn" type="submit" ${materials.length ? '' : 'disabled'}>Compare</button>
      </form>
      <div id="compare-results" style="margin-top:14px">
        ${materials.length ? '' : emptyState('No prices to compare', 'Add at least one quotation for a material first.', 'scale')}
      </div>
    </div>`;
    const form = el('#compare-form');
    if (!materials.length) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const v = formValues(form);
      const box = el('#compare-results');
      box.innerHTML = '<div class="skeleton skeleton-row"></div>';
      try {
        const rows = await api(`/suppliers/compare?material=${encodeURIComponent(v.material)}&quantity=${Number(v.quantity)}`);
        box.innerHTML = `<div class="grid grid-3">${rows.map((r) => `<div class="card" style="box-shadow:none;border-color:${r.rank === 1 ? 'var(--success)' : 'var(--border)'}">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
            <div><strong>${esc(r.supplier || 'No supplier')}</strong>
              <div class="small muted">Rank ${r.rank}${r.is_demo ? ' · demonstration' : ''}</div></div>
            ${r.rank === 1 ? badge('Best delivered cost', 'ok') : ''}
          </div>
          <div class="value" style="font-size:20px;font-weight:650;margin:8px 0 2px">${money(r.total)}</div>
          <div class="small muted">for ${num(r.buy_quantity, 2)} units · ${money(r.effective_unit_cost)} each delivered</div>
          <dl class="dl" style="margin-top:10px;font-size:12px">
            <dt>Base</dt><dd>${money(r.base)}</dd>
            <dt>Tax</dt><dd>${money(r.tax)}</dd>
            <dt>Delivery</dt><dd>${money(r.delivery)}</dd>
            <dt>MOQ</dt><dd>${num(r.moq, 2)}</dd>
            <dt>Valid until</dt><dd>${r.valid_until ? dateFmt(r.valid_until) : 'Not stated'}</dd>
          </dl>
          <div style="margin-top:8px">${r.expired ? badge('Expired', 'critical') : badge('Valid', 'ok')}
            ${r.available ? '' : badge('Unavailable', 'warning')}</div>
          <p class="small muted" style="margin:8px 0 0">${esc(r.recommendation)}</p>
        </div>`).join('')}</div>
        <p class="small muted" style="margin-top:10px">Delivered cost = unit price × max(quantity, MOQ) + tax + delivery.
        It excludes unloading, storage and any rate not present in the stored quotation.</p>`;
        icons(box);
      } catch (err) {
        box.innerHTML = emptyState('Comparison unavailable', err.message, 'alert-circle');
        icons(box);
      }
    });
  }

  /* ------------------------------------------------------------- catalogue */
  function catalogue() {
    const map = new Map();
    prices.forEach((p) => {
      const key = p.material + '|' + p.unit;
      const row = map.get(key) || { material: p.material, unit: p.unit, category: p.category, suppliers: new Set(), prices: [] };
      if (p.supplier) row.suppliers.add(p.supplier);
      row.prices.push(p.unit_price);
      map.set(key, row);
    });
    const rows = Array.from(map.values()).map((r) => ({
      material: r.material, unit: r.unit, category: r.category,
      suppliers: r.suppliers.size, quotes: r.prices.length,
      low: Math.min(...r.prices), high: Math.max(...r.prices),
    })).sort((a, b) => a.material.localeCompare(b.material));
    host.innerHTML = `<div class="card"><div class="card-head"><h2>Material catalogue</h2><div class="spacer"></div>
        <span class="small muted">Built from stored prices</span></div>
      ${rows.length ? table(rows, [
        { key: 'material', label: 'Material', render: (v, r) => `<strong>${esc(v)}</strong><div class="small muted">${esc(r.category || '')}</div>` },
        { key: 'unit', label: 'Unit' },
        { key: 'suppliers', label: 'Suppliers', align: 'right' },
        { key: 'quotes', label: 'Prices', align: 'right' },
        { key: 'low', label: 'Lowest', align: 'right', render: (v) => money(v) },
        { key: 'high', label: 'Highest', align: 'right', render: (v) => money(v) },
      ], { compact: true }) : emptyState('No materials yet', 'Materials appear here once a price is stored.', 'library')}
    </div>`;
  }

  /* -------------------------------------------------------------- requests */
  function requests() {
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>Purchase requirement</h2></div>
      <p class="small muted" style="margin-top:-6px">Work out how much to buy after allowing for a buffer, usable stock and
      confirmed incoming deliveries.</p>
      <form id="req-form" class="form-grid">
        <div class="field"><label for="req-required">Required quantity</label><input id="req-required" name="required" type="number" min="0" step="0.01" required></div>
        <div class="field"><label for="req-buffer">Buffer / wastage</label><input id="req-buffer" name="buffer" type="number" min="0" step="0.01" value="0"></div>
        <div class="field"><label for="req-available">Usable stock available</label><input id="req-available" name="available" type="number" min="0" step="0.01" value="0"></div>
        <div class="field"><label for="req-incoming">Confirmed incoming</label><input id="req-incoming" name="incoming" type="number" min="0" step="0.01" value="0"></div>
        <div style="display:flex;align-items:flex-end"><button class="btn" type="submit">Calculate</button></div>
      </form>
      <div id="req-result" style="margin-top:14px"></div>
      <p class="small muted" style="margin-top:12px">This is arithmetic, not a supplier commitment. Create a draft purchase
      order in the project workspace when you are ready.</p>
    </div>`;
    el('#req-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const v = formValues(el('#req-form'));
      try {
        const r = await api(`/procurement/requirement?required=${Number(v.required || 0)}&buffer=${Number(v.buffer || 0)}&available=${Number(v.available || 0)}&incoming=${Number(v.incoming || 0)}`);
        el('#req-result').innerHTML = `<div class="insight info"><i data-lucide="shopping-cart" class="ico"></i>
          <div><b>Purchase ${num(r.purchase_quantity, 2)} units</b><span>Formula: ${esc(r.formula)}</span></div></div>`;
        icons(el('#req-result'));
      } catch (err) { /* toasted */ }
    });
  }

  /* ---------------------------------------------------------------- orders */
  async function orders(deliveriesOnly) {
    const pid = el('#sup-project').value;
    if (!pid) {
      host.innerHTML = `<div class="card">${emptyState('Choose a project', 'Purchase orders and deliveries belong to a project. Select one in the header.', 'clipboard-list')}</div>`;
      icons(host);
      return;
    }
    const rows = await api(`/projects/${pid}/purchase-orders`);
    const shown = deliveriesOnly ? rows.filter((r) => r.received_date || r.status === 'received') : rows;
    host.innerHTML = `<div class="card">
      <div class="card-head"><h2>${deliveriesOnly ? 'Deliveries' : 'Purchase orders'}</h2><div class="spacer"></div>
        <a class="btn btn-ghost btn-sm" href="/projects/${pid}?tab=procurement">Manage in project</a></div>
      ${shown.length ? table(shown, [
        { key: 'number', label: 'Order', render: (v) => `<strong>${esc(v)}</strong>` },
        { key: 'supplier', label: 'Supplier' },
        { key: 'status', label: 'Status', render: (v, r) => badge(BB.humanize(v), v === 'received' ? 'ok' : 'pending')
            + (r.delivery_late ? ' ' + badge('Delayed', 'critical') : '') },
        { key: 'expected_date', label: 'Expected', render: (v) => v ? dateFmt(v) : '—' },
        { key: 'received_date', label: 'Received', render: (v) => v ? dateFmt(v) : '<span class="muted">Not yet</span>' },
        { key: 'total', label: 'Value', align: 'right', render: (v) => money(v) },
      ], { compact: true }) : emptyState(deliveriesOnly ? 'No deliveries recorded' : 'No purchase orders yet',
        deliveriesOnly ? 'Mark an order received in the project workspace when the material arrives.' : 'Create a draft order from the project workspace.', 'truck')}
      <p class="small muted" style="margin:10px 0 0">Provider delivery confirmation is not available; received dates are
      the ones you record.</p>
    </div>`;
    icons(host);
  }

  /* ------------------------------------------------------------------ tabs */
  function select(next) {
    tab = next;
    els('#sup-tabs button').forEach((b) => b.classList.toggle('on', b.getAttribute('data-tab') === next));
    if (next === 'directory') directory();
    else if (next === 'prices') pricesTab();
    else if (next === 'quotations') quotations();
    else if (next === 'compare') compareTab();
    else if (next === 'catalogue') catalogue();
    else if (next === 'requests') requests();
    else if (next === 'orders') orders(false).catch(() => {});
    else if (next === 'deliveries') orders(true).catch(() => {});
    icons(host);
  }

  async function loadAll() {
    try {
      [suppliers, prices] = await Promise.all([api('/suppliers'), api('/material-prices')]);
      select(tab);
    } catch (err) {
      host.innerHTML = `<div class="card">${emptyState('Suppliers could not load', err.message, 'alert-circle')}</div>`;
      icons(host);
    }
  }

  els('#sup-tabs button').forEach((b) => b.addEventListener('click', () => select(b.getAttribute('data-tab'))));
  el('#sup-add').addEventListener('click', () => openSupplier(null));
  el('#sup-project').addEventListener('change', () => {
    localStorage.setItem('bb-project', el('#sup-project').value || '');
    if (tab === 'orders' || tab === 'deliveries') select(tab);
  });

  host.addEventListener('click', (e) => {
    const edit = e.target.closest('[data-edit]');
    if (edit) { const s = suppliers.find((x) => x.id === Number(edit.getAttribute('data-edit'))); if (s) openSupplier(s); }
    const del = e.target.closest('[data-del]');
    if (del && del.closest('#sup-table')) {
      const s = suppliers.find((x) => x.id === Number(del.getAttribute('data-del')));
      confirmDialog({
        title: 'Delete this supplier?', message: `${s.name || 'Unnamed supplier'} will be removed from the directory. Stored prices that reference it may become unattached.`, confirmText: 'Delete', danger: true,
      }).then(async (ok) => {
        if (!ok) return;
        await api(`/suppliers/${s.id}`, { method: 'DELETE' });
        toast('Supplier deleted.', 'success'); loadAll();
      });
    }
  });

  BB.ready().then(() => {
    const stored = localStorage.getItem('bb-project');
    if (stored) el('#sup-project').value = stored;
    loadAll();
  });
})();
