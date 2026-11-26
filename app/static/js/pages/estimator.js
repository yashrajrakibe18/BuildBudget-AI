/* Cost estimator: room geometry, deterministic material quantities, save and BOQ hand-off. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, money, num, qty, table, emptyState, modal, toast, icons,
          field, formValues, devDetails, dateFmt } = BB;

  let kind = 'tiles';
  let geometry = null;
  let result = null;
  let params = null;
  let openingCount = 0;

  const KINDS = {
    tiles: {
      label: 'Tiles', item: 'Tiles', area: 'floor',
      fields: [
        ['tile_length', 'Tile length', 'number', 24, { step: '0.01', min: 0, value: 24 }],
        ['tile_width', 'Tile width', 'number', 24, { step: '0.01', min: 0, value: 24 }],
        ['tile_unit', 'Tile unit', 'select', 'in', { options: [['in', 'Inches'], ['ft', 'Feet'], ['cm', 'Centimetres'], ['m', 'Metres']] }],
        ['wastage_pct', 'Wastage %', 'number', 10, { step: '0.5', min: 0, max: 50, hint: 'Cuts and breakage allowance.' }],
        ['tiles_per_box', 'Tiles per box (optional)', 'number', '', { step: '1', min: 1, hint: 'Adds a box count when supplied.' }],
      ],
    },
    paint: {
      label: 'Paint', item: 'Paint', area: 'wall',
      fields: [
        ['coats', 'Coats', 'number', 2, { min: 1, max: 6, step: '1' }],
        ['coverage_sqft_per_litre', 'Coverage (sq ft per litre)', 'number', '', { step: '0.01', min: 0, required: true, hint: 'Required — take it from the product datasheet.' }],
        ['wastage_pct', 'Wastage %', 'number', 5, { step: '0.5', min: 0, max: 50 }],
      ],
    },
    primer: {
      label: 'Primer', item: 'Primer', area: 'wall',
      fields: [
        ['coats', 'Coats', 'number', 1, { min: 1, max: 4, step: '1' }],
        ['coverage_sqft_per_litre', 'Coverage (sq ft per litre)', 'number', '', { step: '0.01', min: 0, required: true, hint: 'Required — datasheet coverage.' }],
        ['wastage_pct', 'Wastage %', 'number', 5, { step: '0.5', min: 0, max: 50 }],
      ],
    },
    plaster: {
      label: 'Plaster', item: 'Plaster', area: 'wall',
      fields: [
        ['thickness_mm', 'Thickness (mm)', 'number', 12, { step: '1', min: 1 }],
        ['sand_ratio', 'Sand ratio (1 : n)', 'number', 4, { step: '1', min: 1 }],
        ['wastage_pct', 'Wastage %', 'number', 5, { step: '0.5', min: 0, max: 50 }],
      ],
    },
    bricks: {
      label: 'Brickwork', item: 'Bricks', area: 'wall',
      fields: [
        ['wall_thickness_mm', 'Wall thickness (mm)', 'number', 90, { step: '1', min: 50 }],
        ['brick_l_mm', 'Brick length (mm)', 'number', 190, { step: '1', min: 1 }],
        ['brick_w_mm', 'Brick width (mm)', 'number', 90, { step: '1', min: 1 }],
        ['brick_h_mm', 'Brick height (mm)', 'number', 90, { step: '1', min: 1 }],
        ['mortar_mm', 'Mortar joint (mm)', 'number', 10, { step: '1', min: 1 }],
        ['mortar_ratio_sand', 'Mortar sand ratio (1 : n)', 'number', 6, { step: '1', min: 1 }],
        ['wastage_pct', 'Wastage %', 'number', 5, { step: '0.5', min: 0, max: 50 }],
      ],
    },
    tile_adhesive: {
      label: 'Tile adhesive', item: 'Tile adhesive', area: 'floor',
      fields: [
        ['coverage_sqft_per_bag', 'Coverage (sq ft per bag)', 'number', '', { step: '0.01', min: 0, required: true, hint: 'Required — datasheet coverage.' }],
        ['wastage_pct', 'Wastage %', 'number', 5, { step: '0.5', min: 0, max: 50 }],
      ],
    },
  };

  const initialProject = new URLSearchParams(location.search).get('project');
  if (initialProject) el('#est-project').value = initialProject;

  function openingRow() {
    openingCount += 1;
    const n = openingCount;
    return `<div class="opening-row form-grid" style="margin-bottom:8px">
      <div class="field"><label for="ow-${n}">Width</label><input id="ow-${n}" type="number" step="0.01" min="0"></div>
      <div class="field"><label for="oh-${n}">Height</label><input id="oh-${n}" type="number" step="0.01" min="0"></div>
      <div class="field"><label for="oc-${n}">Count</label><input id="oc-${n}" type="number" min="1" step="1" value="1"></div>
      <div style="display:flex;align-items:flex-end"><button class="btn btn-ghost btn-sm" type="button" data-remove-opening>Remove</button></div>
    </div>`;
  }
  el('#est-add-opening').addEventListener('click', () => el('#est-openings').insertAdjacentHTML('beforeend', openingRow()));
  el('#est-openings').addEventListener('click', (e) => {
    const b = e.target.closest('[data-remove-opening]');
    if (b) b.closest('.opening-row').remove();
  });

  function collectOpenings() {
    const out = [];
    els('#est-openings .opening-row').forEach((row) => {
      const inputs = row.querySelectorAll('input');
      const width = Number(inputs[0].value), height = Number(inputs[1].value), count = Number(inputs[2].value || 1);
      if (width > 0 && height > 0) out.push({ width, height, count: Math.max(1, count) });
    });
    return out;
  }

  async function calculateRoom() {
    const body = {
      length: Number(el('#room-length').value), width: Number(el('#room-width').value),
      height: Number(el('#room-height').value), unit: el('#room-unit').value, openings: collectOpenings(),
    };
    if (!body.length || !body.width || !body.height) return toast('Enter length, width and height greater than zero.', 'error');
    try {
      geometry = await api('/estimates/room-geometry', { method: 'POST', body });
      el('#room-source').textContent = 'Calculated just now';
      el('#room-areas').innerHTML = table([
        { m: 'Floor area', v: `${num(geometry.floor_area_sqft, 2)} sq. ft.` },
        { m: 'Ceiling area', v: `${num(geometry.ceiling_area_sqft, 2)} sq. ft.` },
        { m: 'Gross wall area', v: `${num(geometry.gross_wall_area_sqft, 2)} sq. ft.` },
        { m: 'Openings area', v: `${num(geometry.openings_area_sqft, 2)} sq. ft.` },
        { m: 'Net wall area', v: `${num(geometry.net_wall_area_sqft, 2)} sq. ft.` },
        { m: 'Floor area (metric)', v: `${num(geometry.floor_area_sqm, 2)} m²` },
        { m: 'Net wall area (metric)', v: `${num(geometry.net_wall_area_sqm, 2)} m²` },
      ], [{ key: 'm', label: 'Measurement' }, { key: 'v', label: 'Result', align: 'right' }], { compact: true })
        + `<details class="disclosure" style="margin-top:10px"><summary>Formula and assumptions</summary>
          <div class="body">${esc(geometry.formula)}<div class="small muted" style="margin-top:6px">
          All dimensions converted to feet first: ${num(geometry.inputs.length_ft, 2)} × ${num(geometry.inputs.width_ft, 2)} × ${num(geometry.inputs.height_ft, 2)} ft.</div></div></details>`;
      renderForm();
      toast('Room areas calculated.', 'success');
    } catch (err) { /* toast shown */ }
  }
  el('#calc-room').addEventListener('click', calculateRoom);

  function areaValue() {
    if (!geometry) return '';
    return kind === 'tiles' || kind === 'tile_adhesive' ? geometry.floor_area_sqft
      : kind === 'paint' || kind === 'primer' || kind === 'plaster' || kind === 'bricks' ? geometry.net_wall_area_sqft : '';
  }

  function renderForm() {
    const spec = KINDS[kind];
    let html = `<div class="form-grid">
      <div class="field"><label for="est-area">Area (sq. ft.)</label>
        <input id="est-area" name="area_sqft" type="number" step="0.01" min="0" value="${areaValue()}">
        <span class="hint">Use the room areas, or type a measured area.
          ${geometry ? `<button class="btn btn-ghost btn-sm" type="button" id="fill-floor" style="margin-top:4px">Floor ${num(geometry.floor_area_sqft, 1)}</button>
          <button class="btn btn-ghost btn-sm" type="button" id="fill-wall">Net wall ${num(geometry.net_wall_area_sqft, 1)}</button>` : ''}
        </span></div>`;
    spec.fields.forEach(([name, label, type, value, opts]) => {
      opts = opts || {};
      if (type === 'select') {
        const options = (opts && opts.options) || (value && value.options) || [];
        const defaultVal = (opts && opts.value) || (typeof value === 'string' ? value : '');
        html += `<div class="field"><label for="est-${name}">${label}</label><select id="est-${name}" name="${name}">
          ${options.map(([v, t]) => `<option value="${v}" ${String(v) === String(defaultVal) ? 'selected' : ''}>${t}</option>`).join('')}</select></div>`;
      } else {
        html += `<div class="field"><label for="est-${name}">${label}</label>
          <input id="est-${name}" name="${name}" type="number" ${opts.step ? `step="${opts.step}"` : ''}
            ${opts.min != null ? `min="${opts.min}"` : ''} ${opts.max != null ? `max="${opts.max}"` : ''}
            value="${value === '' ? '' : value}">
          ${opts.hint ? `<span class="hint">${opts.hint}</span>` : ''}</div>`;
      }
    });
    html += '</div>';
    el('#est-form').innerHTML = html;
    const ff = el('#fill-floor');
    if (ff) ff.addEventListener('click', () => { el('#est-area').value = geometry.floor_area_sqft; });
    const fw = el('#fill-wall');
    if (fw) fw.addEventListener('click', () => { el('#est-area').value = geometry.net_wall_area_sqft; });
  }

  els('#est-kinds button').forEach((b) => b.addEventListener('click', () => {
    kind = b.getAttribute('data-kind');
    els('#est-kinds button').forEach((x) => x.classList.toggle('on', x === b));
    result = null; params = null;
    el('#est-result-card').style.display = 'none';
    el('#est-save').disabled = true; el('#est-to-boq').disabled = true;
    renderForm();
  }));

  function buildParams() {
    const v = formValues(el('#est-form'));
    const out = { area_sqft: Number(v.area_sqft) };
    KINDS[kind].fields.forEach(([name, , type]) => {
      const raw = v[name];
      if (raw === '' || raw === null || raw === undefined) return;
      out[name] = type === 'select' ? raw : Number(raw);
    });
    if (!out.area_sqft || out.area_sqft <= 0) throw new Error('Enter an area greater than zero.');
    KINDS[kind].fields.forEach(([name, label, , , opts]) => {
      if (opts && opts.required && !out[name]) throw new Error(`${label} is required and must come from the datasheet.`);
    });
    return out;
  }

  el('#est-calculate').addEventListener('click', async () => {
    try {
      params = buildParams();
      result = await api('/estimates/calculate', { method: 'POST', body: { kind, params } });
      renderResult();
      el('#est-save').disabled = false;
      el('#est-to-boq').disabled = !el('#est-project').value;
    } catch (err) {
      if (err.status) return; /* API error already toasted */
      toast(err.message, 'error');
    }
  });

  function renderResult() {
    const r = result;
    el('#est-result-card').style.display = '';
    el('#est-item').textContent = r.item;
    const secondary = Object.entries(r.secondary || {});
    el('#est-result').innerHTML = `
      <div class="stat-inline" style="margin-bottom:12px">
        <div><div class="k">Final quantity</div><div class="v">${num(r.final_quantity, 2)} ${esc(r.unit)}</div></div>
        <div><div class="k">Before wastage</div><div class="v">${num(r.base_quantity, 2)} ${esc(r.unit)}</div></div>
        <div><div class="k">Wastage</div><div class="v">${num(r.wastage_pct, 1)}%</div></div>
      </div>
      ${table([
        { k: 'Calculated item', v: r.item },
        { k: 'Quantity', v: `${num(r.final_quantity, 2)} ${r.unit}` },
        { k: 'Formula', v: r.formula },
        ...secondary.map(([key, value]) => ({ k: BB.humanize(key), v: String(value) })),
      ], [{ key: 'k', label: 'Measurement' }, { key: 'v', label: 'Result', align: 'right' }], { compact: true })}
      <details class="disclosure" style="margin-top:10px"><summary>Assumptions and source</summary>
        <div class="body"><ul style="margin:6px 0 0 16px;padding:0">${(r.assumptions || []).map((a) => `<li>${esc(a)}</li>`).join('')}</ul>
        <p class="small muted" style="margin:8px 0 0">${esc(r.source_reference || '')}</p></div></details>
      <p class="small" style="margin:10px 0 0;color:var(--amber-ink)">${esc(r.notice || '')}</p>`;
    icons(el('#est-result'));
  }

  async function saveScenario() {
    const pid = el('#est-project').value;
    if (!pid) return toast('Select a project before saving a scenario.', 'warn');
    const name = await modal({
      title: 'Save estimation scenario',
      body: `<form id="scenario-form"><div class="form-grid">
        ${field('name', 'Scenario name', { required: true, value: `${KINDS[kind].label} — ${num(result.final_quantity, 0)} ${result.unit}` })}
        ${field('unit_rate', 'Unit rate (₹, optional)', { type: 'number', step: '0.01', min: 0, hint: 'Recorded with the scenario; no price is assumed.' })}
      </div></form>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Save scenario</button>`,
      onResult: (value, root) => {
        if (value !== 'save') return true;
        const v = formValues(el('#scenario-form', root));
        const body = { name: v.name, kind, params };
        if (v.unit_rate !== null && v.unit_rate !== '') body.unit_rate = Number(v.unit_rate);
        api(`/projects/${pid}/estimations`, { method: 'POST', body })
          .then((r) => { toast(`Scenario saved${r.total ? ' · ' + money(r.total) : ''}.`, 'success'); });
        return true;
      },
    });
  }
  el('#est-save').addEventListener('click', saveScenario);

  async function addToBoq() {
    const pid = el('#est-project').value;
    if (!pid) return toast('Select a project first.', 'warn');
    const catOptions = ['Finishing', 'Materials', 'Labour', 'Flooring', 'Painting', 'Plumbing', 'Electrical', 'Other'];
    modal({
      title: 'Add to Bill of Quantities',
      body: `<form id="boq-add-form">
        <p class="small muted">Quantity <strong>${num(result.final_quantity, 2)} ${esc(result.unit)}</strong> will be added as a line.
        A unit rate is required: either enter one from your quotation, or a stored supplier price is used when available.</p>
        <div class="form-grid">
          ${field('material_name', 'Material name (for price lookup)', { required: true, value: result.item })}
          ${field('category', 'Category', { options: catOptions })}
          ${field('unit_rate', 'Unit rate (₹)', { type: 'number', step: '0.01', min: 0, hint: 'Blank = latest stored supplier price. If none exists the line is rejected.' })}
          ${field('tax_pct', 'Tax %', { type: 'number', step: '0.01', min: 0, max: 100, hint: 'Blank = quotation tax rate, else 0.' })}
          ${field('labour_cost', 'Labour cost (₹)', { type: 'number', step: '0.01', min: 0, value: 0 })}
          ${field('transport_cost', 'Transport (₹)', { type: 'number', step: '0.01', min: 0, value: 0 })}
          ${field('discount_pct', 'Discount %', { type: 'number', step: '0.01', min: 0, max: 100, value: 0 })}
        </div></form>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Add to BOQ</button>`,
      onResult: (value, root) => {
        if (value !== 'save') return true;
        const v = formValues(el('#boq-add-form', root));
        const body = { kind, params, material_name: v.material_name, category: v.category || 'Finishing' };
        ['unit_rate', 'tax_pct'].forEach((k) => { if (v[k] !== null && v[k] !== '') body[k] = Number(v[k]); });
        ['labour_cost', 'transport_cost', 'discount_pct'].forEach((k) => { body[k] = Number(v[k] || 0); });
        api(`/projects/${pid}/boq/from-estimate`, { method: 'POST', body })
          .then((r) => {
            toast(`Added to BOQ · line total ${money(r.item.total)}.`, 'success');
            loadProjectCard();
          }).catch(() => {});
        return true;
      },
    });
  }
  el('#est-to-boq').addEventListener('click', addToBoq);

  el('#conv-run').addEventListener('click', async () => {
    try {
      const r = await api(`/measurements/convert?value=${Number(el('#conv-value').value)}&from_unit=${el('#conv-from').value}&to_unit=${el('#conv-to').value}`);
      el('#conv-result').innerHTML = `<strong>${num(Number(el('#conv-value').value), 4)} ${esc(el('#conv-from').value)} =
        ${num(r.result, 4)} ${esc(r.unit)}</strong>`;
    } catch (err) { /* toasted */ }
  });

  async function loadProjectCard() {
    const pid = el('#est-project').value;
    const host = el('#est-project-card');
    if (!pid) {
      host.innerHTML = '<p class="small muted">Select a project above to save scenarios or add items to its BOQ.</p>';
      el('#est-to-boq').disabled = true;
      return;
    }
    try {
      const [p, scenarios] = await Promise.all([api('/projects/' + pid), api(`/projects/${pid}/estimations`)]);
      host.innerHTML = `<div><strong>${esc(p.name)}</strong></div>
        <div class="small muted">${esc(p.project_type_label)}${p.location ? ' · ' + esc(p.location) : ''}</div>
        <div class="small" style="margin-top:6px">Budget ${money(p.budget)} · ${scenarios.length} saved scenario(s)</div>
        <a class="small" href="/projects/${pid}?tab=estimator">Open project scenarios</a>`;
      el('#est-to-boq').disabled = !result;
    } catch (err) { /* toasted */ }
  }
  el('#est-project').addEventListener('change', loadProjectCard);

  function prefillFromRoom() {
    const raw = sessionStorage.getItem('bb-room');
    if (!raw) return;
    sessionStorage.removeItem('bb-room');
    try {
      const room = JSON.parse(raw);
      el('#room-length').value = room.length;
      el('#room-width').value = room.width;
      el('#room-height').value = room.height;
      el('#room-unit').value = room.unit;
      (room.openings || []).forEach((o) => {
        el('#est-openings').insertAdjacentHTML('beforeend', openingRow());
        const row = el('#est-openings').lastElementChild;
        const inputs = row.querySelectorAll('input');
        inputs[0].value = o.width; inputs[1].value = o.height; inputs[2].value = o.count || 1;
      });
      if (room.project_id) el('#est-project').value = room.project_id;
      calculateRoom();
    } catch (e) { /* ignore malformed prefill */ }
  }

  BB.ready().then(() => {
    renderForm();
    loadProjectCard();
    prefillFromRoom();
    if (new URLSearchParams(location.search).get('fromRoom')) { /* prefill handled above */ }
  });
})();
