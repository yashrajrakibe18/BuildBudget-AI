/* Report catalogue and downloads for the selected project. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, download, toast, icons, emptyState } = BB;

  const host = el('#report-host');
  let catalog = null;

  function render() {
    if (!catalog) { host.innerHTML = '<div class="skeleton skeleton-row"></div>'; return; }
    host.innerHTML = `<div class="grid grid-2">${catalog.reports.map((r) => `<div class="card" style="box-shadow:none">
      <h3>${esc(r.label)}</h3>
      <p class="small muted">${esc(r.description)}</p>
      <div class="btn-group">${r.formats.map((f) => `<button class="btn btn-ghost btn-sm" type="button"
        data-report="${esc(r.key)}" data-fmt="${esc(f)}" ${el('#rep-project').value ? '' : 'disabled'}>${esc(f.toUpperCase())}</button>`).join('')}</div>
    </div>`).join('')}</div>
    ${el('#rep-project').value ? '' : '<p class="small muted" style="margin-top:10px">Choose a project to enable downloads.</p>'}`;
    icons(host);
  }

  async function loadCatalog() {
    const pid = el('#rep-project').value;
    try {
      catalog = await api('/reports/catalog' + (pid ? '?project_id=' + pid : ''));
      render();
    } catch (err) {
      host.innerHTML = emptyState('Catalogue unavailable', err.message, 'alert-circle');
      icons(host);
    }
  }

  host.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-report]');
    if (!b) return;
    const pid = el('#rep-project').value;
    if (!pid) return toast('Choose a project first.', 'warn');
    const name = b.getAttribute('data-report'), fmt = b.getAttribute('data-fmt');
    b.disabled = true;
    const original = b.textContent;
    b.textContent = 'Generating…';
    try {
      await download(`/projects/${pid}/reports/${name}.${fmt}`, `${name}_${pid}.${fmt}`);
      toast('Report downloaded.', 'success');
    } catch (err) { /* toasted */ }
    finally { b.disabled = false; b.textContent = original; }
  });

  el('#rep-project').addEventListener('change', () => {
    localStorage.setItem('bb-project', el('#rep-project').value || '');
    render();
    loadCatalog();
  });

  BB.ready().then(() => {
    const stored = localStorage.getItem('bb-project');
    if (stored) el('#rep-project').value = stored;
    loadCatalog();
  });
})();
