/* BuildBudget AI — shared UI toolkit.
   Formatting, labels, safe Markdown, tables, modals, toasts, charts, API client.
   No raw JSON is ever shown to the user: anything technical lives inside a
   collapsed "Developer details" disclosure.                                   */
(function () {
  'use strict';

  const BB = window.BB = window.BB || {};
  BB.labels = {};
  BB.me = null;
  BB.csrf = (document.querySelector('meta[name="csrf"]') || {}).content || '';

  /* ------------------------------------------------------------- helpers */
  const el = (sel, root) => (root || document).querySelector(sel);
  const els = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const nf = (min, max) => new Intl.NumberFormat('en-IN',
    { minimumFractionDigits: min, maximumFractionDigits: max });

  function money(v, opts) {
    if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return '—';
    const n = Number(v);
    const abs = Math.abs(n);
    const digits = abs >= 1000 ? 0 : (abs >= 10 ? 0 : 2);
    return '₹' + nf(digits, 2).format(n);
  }
  function moneyShort(v) {
    if (v === null || v === undefined) return '—';
    const n = Number(v), abs = Math.abs(n);
    if (abs >= 1e7) return '₹' + nf(1, 2).format(n / 1e7) + ' Cr';
    if (abs >= 1e5) return '₹' + nf(1, 2).format(n / 1e5) + ' L';
    if (abs >= 1e3) return '₹' + nf(0, 1).format(n / 1e3) + 'k';
    return '₹' + nf(0, 2).format(n);
  }
  const num = (v, d) => (v === null || v === undefined || v === '' ? '—'
    : nf(0, d === undefined ? 2 : d).format(Number(v)));
  const pct = (v) => (v === null || v === undefined ? '—' : num(v, 1) + '%');
  const qty = (v, unit) => (v === null || v === undefined ? '—'
    : `${nf(0, 3).format(Number(v))}${unit ? ' ' + unit : ''}`);

  function dateFmt(v, withTime) {
    if (!v) return '—';
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
      + (withTime ? ', ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '');
  }
  function timeAgo(v) {
    if (!v) return '—';
    const d = new Date(v), diff = (Date.now() - d.getTime()) / 1000;
    if (Number.isNaN(diff)) return '—';
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
    if (diff < 86400) return Math.floor(diff / 3600) + ' h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + ' d ago';
    return dateFmt(d);
  }
  const humanize = (key) => String(key == null ? '' : key)
    .replace(/[_\-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()).trim() || '—';
  function label(map, key, fallback) {
    const table = (map && BB.labels[map]) || {};
    if (key == null) return fallback || '—';
    return table[key] || humanize(key);
  }
  const statusLabel = (v) => label('project_status', v, humanize(v));

  function badge(text, tone) {
    const key = String(tone || text || '').toLowerCase().replace(/\s+/g, '_');
    return `<span class="badge ${esc(key)}">${esc(text == null ? '—' : text)}</span>`;
  }
  const healthBadge = (v) => badge(label('health_status', v), v);
  const statusBadge = (v, text) => badge(text || statusLabel(v), v);
  const priorityBadge = (v) => badge(label('priority', v), v);
  const sourceBadge = (v) => badge(label('sources', v), v);

  function progressBar(value, tone) {
    const v = Math.max(0, Math.min(100, Number(value) || 0));
    const cls = tone || (v >= 100 ? 'bad' : v >= 90 ? 'bad' : v >= 75 ? 'warn' : '');
    return `<div class="progress ${cls}" role="progressbar" aria-valuenow="${v}" aria-valuemin="0" aria-valuemax="100"><span style="width:${v}%"></span></div>`;
  }

  /* ------------------------------------------------------------- tables */
  /* cols: [{key, label, render?, align?, class?}] */
  function table(rows, cols, opts) {
    opts = opts || {};
    if (!rows || !rows.length) return emptyState(opts.empty || 'Nothing here yet', opts.emptyHint || '', opts.emptyIcon || 'inbox');
    const head = cols.map((c) => `<th class="${c.align === 'right' ? 'num' : ''}">${esc(c.label)}</th>`).join('');
    const body = rows.map((row) => '<tr>' + cols.map((c) => {
      const raw = typeof c.key === 'function' ? c.key(row) : row[c.key];
      const content = c.render ? c.render(raw, row) : esc(raw == null || raw === '' ? '—' : raw);
      return `<td class="${c.align === 'right' ? 'num' : ''} ${c.class || ''}">${content}</td>`;
    }).join('') + '</tr>').join('');
    const foot = opts.footer ? `<tfoot><tr>${opts.footer.map((f, i) =>
      `<td class="${cols[i] && cols[i].align === 'right' ? 'num' : ''}">${f}</td>`).join('')}</tr></tfoot>` : '';
    return `<div class="table-wrap"><table class="data ${opts.compact ? 'compact' : ''}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody>${foot}</table></div>`;
  }

  function emptyState(title, hint, icon) {
    return `<div class="empty">
      <i data-lucide="${esc(icon || 'inbox')}" class="ico"></i>
      <h3>${esc(title)}</h3>
      ${hint ? `<p>${esc(hint)}</p>` : ''}
    </div>`;
  }
  const skeleton = (n, cls) => Array.from({ length: n || 3 },
    () => `<div class="skeleton ${cls || 'skeleton-line'}"></div>`).join('');
  const spinner = (text) => `<span class="spinner"></span>${text ? ' ' + esc(text) : ''}`;

  /* ------------------------------------------------------------- toasts */
  function toast(message, kind) {
    const host = el('#toasts') || (() => {
      const d = document.createElement('div');
      d.id = 'toasts'; d.className = 'toasts';
      document.body.appendChild(d); return d;
    })();
    const tone = kind === true ? 'error' : (kind || '');
    const iconName = tone === 'error' ? 'alert-circle' : tone === 'success' ? 'check-circle'
      : tone === 'warn' ? 'alert-triangle' : 'info';
    const node = document.createElement('div');
    node.className = 'toast ' + tone;
    node.setAttribute('role', 'status');
    node.innerHTML = `<i data-lucide="${iconName}" class="ico"></i><div>${esc(message)}</div>`;
    host.appendChild(node);
    icons(node);
    setTimeout(() => { node.style.opacity = '0'; node.style.transform = 'translateY(6px)'; }, 3800);
    setTimeout(() => node.remove(), 4200);
  }

  /* ------------------------------------------------------------- icons */
  function icons(root) {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      try { window.lucide.createIcons({ nameAttr: 'data-lucide', attrs: { 'stroke-width': 1.8 }, root: root || document }); } catch (e) { /* noop */ }
    }
  }

  /* ------------------------------------------------------------- http */
  function errorText(payload, fallback) {
    const d = payload && payload.detail;
    if (!d) return fallback || 'Something went wrong';
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map((x) => (x.msg || '') + (x.loc ? ` (${x.loc.slice(1).join('.')})` : '')).join('; ');
    return String(d);
  }

  async function api(path, opts) {
    opts = opts || {};
    const init = { credentials: 'same-origin', method: opts.method || 'GET', headers: {} };
    if (opts.body instanceof FormData) init.body = opts.body;
    else if (opts.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }
    if ((init.method || 'GET').toUpperCase() !== 'GET') {
      const token = BB.csrf || (document.querySelector('meta[name="csrf"]') || {}).content;
      if (token) init.headers['X-CSRF-Token'] = token;
    }
    if (opts.signal) init.signal = opts.signal;
    let res;
    try { res = await fetch('/api/v1' + path, init); }
    catch (err) {
      if (err.name === 'AbortError') throw err;
      toast('Network unavailable — live data could not be loaded.', 'error');
      throw err;
    }
    const type = res.headers.get('content-type') || '';
    let payload = null;
    if (type.includes('json')) payload = await res.json();
    else if (type.includes('text/')) payload = await res.text();
    else payload = await res.blob();
    if (res.status === 401) {
      const authPaths = ['/login', '/register', '/reset-password'];
      const onAuthPage = authPaths.some((p) => location.pathname.startsWith(p));
      if (!onAuthPage) location.href = '/login';
      throw new Error('Not authenticated');
    }
    if (!res.ok) {
      const msg = errorText(payload, res.statusText);
      if (!opts.silent) toast(msg, 'error');
      const err = new Error(msg); err.status = res.status; err.payload = payload; throw err;
    }
    return payload;
  }

  async function download(path, filename) {
    const blob = await api(path);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename || 'download'; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  /* ------------------------------------------------------------- labels/meta */
  BB.readyPromise = null;
  BB.ready = function () {
    if (BB.readyPromise) return BB.readyPromise;
    BB.readyPromise = api('/meta').then((meta) => {
      BB.labels = meta.labels || {};
      BB.me = meta.user || null;
      BB.meta = meta;
      return meta;
    }).catch(() => { BB.readyPromise = null; return null; });
    return BB.readyPromise;
  };

  /* ------------------------------------------------------------- markdown */
  function safeUrl(url) {
    const u = String(url || '').trim();
    if (/^(https?:|mailto:|#|\/)/i.test(u)) return u;
    return '#';
  }
  function markdownFallback(text) {
    const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
    let out = '', inList = false, inTable = false;
    const closeList = () => { if (inList) { out += '</ul>'; inList = false; } };
    const closeTable = () => { if (inTable) { out += '</tbody></table>'; inTable = false; } };
    const inline = (s) => esc(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[\s(])\*([^*]+)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t, u) => `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener">${t}</a>`);
    lines.forEach((line) => {
      const t = line.trim();
      const h = /^(#{1,4})\s+(.*)$/.exec(t);
      if (h) { closeList(); closeTable(); out += `<h${h[1].length + 1}>${inline(h[2])}</h${h[1].length + 1}>`; return; }
      if (/^[-*]\s+/.test(t)) { closeTable(); if (!inList) { out += '<ul>'; inList = true; } out += `<li>${inline(t.replace(/^[-*]\s+/, ''))}</li>`; return; }
      if (/^\|/.test(t) && /\|$/.test(t)) {
        const cells = t.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        if (/^[-: ]+$/.test(cells.join(''))) return;
        if (!inTable) { out += '<table><tbody>'; inTable = true; }
        out += '<tr>' + cells.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>';
        return;
      }
      closeList(); closeTable();
      if (!t) { out += '<p></p>'; return; }
      out += `<p>${inline(t)}</p>`;
    });
    closeList(); closeTable();
    return out;
  }
  function markdown(text) {
    const src = String(text || '');
    if (window.marked && window.DOMPurify) {
      try {
        const raw = window.marked.parse(src, { gfm: true, breaks: true });
        return window.DOMPurify.sanitize(raw, { USE_PROFILES: { html: true }, ADD_ATTR: ['target', 'rel'] });
      } catch (e) { /* fall through */ }
    }
    return markdownFallback(src);
  }

  /* ------------------------------------------------------------- modal */
  function modal(opts) {
    return new Promise((resolve) => {
      const backdrop = document.createElement('div');
      backdrop.className = 'modal-backdrop';
      backdrop.innerHTML = `<div class="modal ${opts.wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-head"><h2 id="modal-title">${esc(opts.title || '')}</h2>
          <div style="flex:1"></div><button class="icon-btn" data-close aria-label="Close"><i data-lucide="x" class="ico"></i></button></div>
        <div class="modal-body">${opts.body || ''}</div>
        <div class="modal-foot">${opts.footer || '<button class="btn btn-ghost" data-close>Cancel</button>'}</div>
      </div>`;
      document.body.appendChild(backdrop);
      icons(backdrop);
      const close = (value) => { backdrop.remove(); document.removeEventListener('keydown', onKey); resolve(value); };
      const onKey = (e) => { if (e.key === 'Escape') close(null); };
      document.addEventListener('keydown', onKey);
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) return close(null);
        const closer = e.target.closest('[data-close]');
        if (closer) close(null);
        const done = e.target.closest('[data-result]');
        if (done) {
          if (opts.onResult) {
            const value = opts.onResult(done.getAttribute('data-result'), backdrop);
            if (value !== false) close(done.getAttribute('data-result'));
          } else close(done.getAttribute('data-result'));
        }
      });
      if (opts.onMount) opts.onMount(backdrop, close);
      const first = backdrop.querySelector('input, select, textarea, button[data-result]');
      if (first) setTimeout(() => first.focus(), 30);
    });
  }

  function confirmDialog(opts) {
    return modal({
      title: opts.title || 'Are you sure?',
      body: `<p>${esc(opts.message || '')}</p>${opts.detail ? `<p class="muted small">${esc(opts.detail)}</p>` : ''}`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button>
        <button class="btn ${opts.danger ? 'btn-danger' : 'btn-accent'}" data-result="yes">${esc(opts.confirmText || 'Confirm')}</button>`,
    }).then((r) => r === 'yes');
  }

  /* ------------------------------------------------------------- charts */
  const THEME_KEYS = ['#142139', '#f59e0b', '#059669', '#2563eb', '#dc2626', '#7c3aed', '#0891b2', '#b45309'];
  function chartColors() {
    const css = getComputedStyle(document.documentElement);
    return {
      text: css.getPropertyValue('--text-2').trim() || '#334155',
      muted: css.getPropertyValue('--muted').trim() || '#5b6b82',
      grid: css.getPropertyValue('--border').trim() || '#e2e8f0',
      surface: css.getPropertyValue('--surface').trim() || '#fff',
      amber: '#f59e0b', navy: '#142139', success: '#059669', danger: '#dc2626',
    };
  }
  const charts = new Map();
  function chart(canvas, config) {
    if (!canvas) return null;
    if (!window.Chart) {
      const box = canvas.parentElement;
      if (box) box.innerHTML = emptyState('Charts unavailable', 'The chart library could not load. Check your connection.', 'bar-chart-3');
      icons(box);
      return null;
    }
    const c = chartColors();
    window.Chart.defaults.color = c.text;
    window.Chart.defaults.font.family = 'Inter, Segoe UI, system-ui, sans-serif';
    window.Chart.defaults.font.size = 11;
    const base = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: c.text, boxWidth: 10, boxHeight: 10, usePointStyle: true, padding: 12 } },
        tooltip: { backgroundColor: c.navy, titleColor: '#fff', bodyColor: '#e2e8f0', padding: 9, cornerRadius: 6 },
      },
      scales: config.type === 'doughnut' || config.type === 'pie' ? undefined : {
        x: { grid: { color: c.grid, drawBorder: false }, ticks: { color: c.muted, maxRotation: 0, autoSkipPadding: 12 } },
        y: { grid: { color: c.grid, drawBorder: false }, ticks: { color: c.muted }, beginAtZero: true },
      },
      animation: { duration: 320 },
    };
    const merged = Object.assign({}, base, config);
    merged.options = Object.assign({}, base, config.options || {});
    merged.options.plugins = Object.assign({}, base.plugins, (config.options || {}).plugins || {});
    merged.data = config.data;
    const prev = charts.get(canvas.id);
    if (prev) { try { prev.destroy(); } catch (e) { /* noop */ } }
    const instance = new window.Chart(canvas, merged);
    if (canvas.id) charts.set(canvas.id, instance);
    return instance;
  }
  function refreshCharts() {
    charts.forEach((instance) => {
      const c = chartColors();
      try {
        instance.options.plugins.legend.labels.color = c.text;
        instance.update('none');
      } catch (e) { /* noop */ }
    });
  }

  /* ------------------------------------------------------------- disclosures */
  function devDetails(title, payload) {
    let text;
    try { text = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2); }
    catch (e) { text = String(payload); }
    if (text && text.length > 4000) text = text.slice(0, 4000) + '\n… (truncated)';
    return `<details class="disclosure"><summary>${esc(title || 'Developer details')}</summary>
      <div class="body"><pre>${esc(text)}</pre></div></details>`;
  }

  function copy(text) {
    const value = String(text || '');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(() => toast('Copied to clipboard', 'success'),
        () => toast('Could not copy', 'error'));
    } else {
      const ta = document.createElement('textarea');
      ta.value = value; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast('Copied to clipboard', 'success'); } catch (e) { toast('Could not copy', 'error'); }
      ta.remove();
    }
  }

  function formValues(root) {
    const out = {};
    els('input, select, textarea', root).forEach((input) => {
      if (!input.name) return;
      if (input.type === 'checkbox') out[input.name] = input.checked;
      else if (input.type === 'number') out[input.name] = input.value === '' ? null : Number(input.value);
      else out[input.name] = input.value;
    });
    return out;
  }

  function field(name, labelText, opts) {
    opts = opts || {};
    const id = 'f-' + name + '-' + Math.random().toString(36).slice(2, 7);
    const attrs = [
      `id="${id}"`, `name="${name}"`,
      opts.required ? 'required' : '',
      opts.type ? `type="${opts.type}"` : '',
      opts.min !== undefined ? `min="${opts.min}"` : '',
      opts.max !== undefined ? `max="${opts.max}"` : '',
      opts.step !== undefined ? `step="${opts.step}"` : '',
      opts.value !== undefined && opts.value !== null ? `value="${esc(opts.value)}"` : '',
      opts.placeholder ? `placeholder="${esc(opts.placeholder)}"` : '',
    ].filter(Boolean).join(' ');
    let control;
    if (opts.options) {
      control = `<select ${attrs}>${opts.options.map((o) => {
        const value = typeof o === 'string' ? o : o.value;
        const text = typeof o === 'string' ? humanize(o) : o.label;
        const sel = String(opts.value) === String(value) ? ' selected' : '';
        return `<option value="${esc(value)}"${sel}>${esc(text)}</option>`;
      }).join('')}</select>`;
    } else if (opts.textarea) {
      control = `<textarea ${attrs} rows="${opts.rows || 4}">${esc(opts.value || '')}</textarea>`;
    } else {
      control = `<input ${attrs}>`;
    }
    return `<div class="field"><label for="${id}">${esc(labelText)}${opts.required ? ' *' : ''}</label>
      ${control}${opts.hint ? `<span class="hint">${esc(opts.hint)}</span>` : ''}</div>`;
  }

  /* ------------------------------------------------------------- expose */
  Object.assign(BB, {
    el, els, esc, money, moneyShort, num, pct, qty, dateFmt, timeAgo, humanize, label,
    statusLabel, badge, healthBadge, statusBadge, priorityBadge, sourceBadge, progressBar,
    table, emptyState, skeleton, spinner, toast, icons, api, download, markdown, modal,
    confirm: confirmDialog, chart, refreshCharts, chartColors, devDetails, copy, formValues,
    field, THEME_KEYS,
  });

  // Backwards-compatible globals used by older snippets
  window.$ = el;
  window.api = api;
  window.inr = money;
  window.esc = esc;
  window.table = (rows, cols) => table(rows, (cols || []).map((c) => ({ key: c[0], label: c[1], render: c[2] })));
  window.tag = (v) => badge(humanize(v), v);
  window.toast = toast;
  window.download = download;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => icons(document));
  } else { icons(document); }
})();
