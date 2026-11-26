/* Knowledge base: upload with progress, hybrid search, preview, reindex and delete. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, esc, api, num, badge, table, emptyState, modal, confirm: confirmDialog, toast,
          icons, dateFmt, markdown, devDetails } = BB;

  let docs = [];
  let stats = null;

  function renderStats() {
    const s = stats || {};
    el('#kb-stats').innerHTML = [
      { label: 'Documents', value: s.documents || 0 },
      { label: 'Indexed passages', value: s.chunks || 0 },
      { label: 'Storage', value: `${num((s.bytes || 0) / 1024 / 1024, 1)} MB` },
      { label: 'Embeddings', value: s.neural_embeddings ? 'Neural (MiniLM)' : 'Hashed TF-IDF' },
      { label: 'Backend', value: s.backend || 'SQLite + BM25' },
    ].map((k) => `<div class="kpi"><div class="label">${esc(k.label)}</div>
      <div class="value sm">${typeof k.value === 'number' ? num(k.value, 0) : esc(k.value)}</div></div>`).join('');
    icons(el('#kb-stats'));
  }

  function renderDocs() {
    el('#kb-doc-count').textContent = `${docs.length} document${docs.length === 1 ? '' : 's'}`;
    el('#kb-docs').innerHTML = docs.length ? `<div class="grid grid-3">${docs.map((d) => `<article class="card">
      <div style="display:flex;gap:8px;align-items:flex-start">
        <div style="min-width:0;flex:1"><h3 style="margin:0;overflow-wrap:anywhere">${esc(d.name)}</h3>
          <div class="small muted">${esc(BB.label('document_categories', d.category))} · v${esc(d.version)}</div></div>
        ${d.index_status === 'indexed' ? badge('Indexed', 'ok') : badge(BB.humanize(d.index_status), 'warning')}
      </div>
      <div class="small" style="margin-top:8px">${num(d.chunks, 0)} passages · ${d.pages ? d.pages + ' pages' : 'no page numbers'} · ${num((d.size_bytes || 0) / 1024, 0)} KB</div>
      <div class="small muted">Uploaded ${dateFmt(d.uploaded_at)}${d.project_id ? ' · project #' + d.project_id : ' · shared'}</div>
      <div class="btn-group" style="margin-top:10px">
        <button class="btn btn-ghost btn-sm" type="button" data-preview="${d.id}">Preview</button>
        <button class="btn btn-ghost btn-sm" type="button" data-reindex="${d.id}">Reindex</button>
        <button class="btn btn-ghost btn-sm" type="button" data-del="${d.id}">Delete</button>
      </div>
    </article>`).join('')}</div>`
      : `<div class="card">${emptyState('No documents indexed', 'Upload a specification, quotation or guideline to ground the assistant in your references.', 'library')}</div>`;
    icons(el('#kb-docs'));
  }

  async function load() {
    try {
      [stats, docs] = await Promise.all([api('/documents/stats'), api('/documents')]);
      renderStats(); renderDocs();
    } catch (err) {
      el('#kb-docs').innerHTML = `<div class="card">${emptyState('Knowledge base could not load', err.message, 'alert-circle')}</div>`;
      icons(el('#kb-docs'));
    }
  }

  el('#kb-upload-toggle').addEventListener('click', () => {
    const card = el('#kb-upload-card');
    card.style.display = card.style.display === 'none' ? '' : 'none';
  });
  el('#kb-upload-close').addEventListener('click', () => { el('#kb-upload-card').style.display = 'none'; });

  const drop = el('#kb-drop');
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault(); drop.style.borderColor = 'var(--amber)'; drop.style.background = 'var(--surface-2)';
  }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault(); drop.style.borderColor = ''; drop.style.background = '';
  }));
  drop.addEventListener('drop', (e) => {
    if (e.dataTransfer.files && e.dataTransfer.files[0]) el('#kb-file').files = e.dataTransfer.files;
  });

  el('#kb-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const file = el('#kb-file').files && el('#kb-file').files[0];
    if (!file) return toast('Choose a file to upload.', 'error');
    if (file.size > 20 * 1024 * 1024) return toast('Files must be 20 MB or smaller.', 'error');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('category', el('#kb-category').value);
    fd.append('version', el('#kb-version').value || '1');
    if (el('#kb-project').value) fd.append('project_id', el('#kb-project').value);
    if (el('#kb-source').value) fd.append('source_url', el('#kb-source').value);
    if (el('#kb-published').value) fd.append('published_on', el('#kb-published').value);
    if (el('#kb-scope').value) fd.append('location_scope', el('#kb-scope').value);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/v1/documents');
    xhr.withCredentials = true;
    xhr.setRequestHeader('X-CSRF-Token', BB.csrf);
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) el('#kb-progress').style.width = Math.round(ev.loaded / ev.total * 100) + '%';
    };
    xhr.onload = () => {
      let payload = {};
      try { payload = JSON.parse(xhr.responseText); } catch (err) { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        toast(payload.message || 'Document indexed.', 'success');
        el('#kb-form').reset(); el('#kb-progress').style.width = '0';
        el('#kb-upload-card').style.display = 'none';
        load();
      } else {
        toast((payload && payload.detail) || 'Upload failed.', 'error');
        el('#kb-progress').style.width = '0';
      }
    };
    xhr.onerror = () => { toast('Upload failed — check the connection.', 'error'); el('#kb-progress').style.width = '0'; };
    el('#kb-submit').disabled = true;
    xhr.onloadend = () => { el('#kb-submit').disabled = false; };
    xhr.send(fd);
  });

  el('#kb-search-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = el('#kb-q').value.trim();
    if (!q) return;
    const host = el('#kb-results');
    host.innerHTML = '<div class="skeleton skeleton-row"></div><div class="skeleton skeleton-row"></div>';
    const pid = el('#kb-search-project').value;
    try {
      const hits = await api(`/documents/search?q=${encodeURIComponent(q)}&k=6${pid ? '&project_id=' + pid : ''}`);
      if (!hits.length) {
        host.innerHTML = emptyState('No relevant passages', 'Try different words, or upload a document that covers this topic. The assistant will say when it has no source.', 'search');
        icons(host);
        return;
      }
      host.innerHTML = `<div class="small muted" style="margin-bottom:8px">${hits.length} passage(s), ranked by fused keyword and vector relevance.</div>`
        + hits.map((h, i) => `<div class="card" style="box-shadow:none;margin-bottom:10px">
          <div style="display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap">
            <span class="badge info">Source ${i + 1}</span>
            <strong style="flex:1;min-width:180px">${esc(h.document)}</strong>
            <span class="small muted">${h.page ? 'page ' + h.page : 'no page' }${h.section ? ' · ' + esc(h.section) : ''} · relevance ${num(h.confidence * 100, 0)}%</span>
          </div>
          <p class="small" style="margin:8px 0">${esc(h.excerpt)}</p>
          <div class="small muted">${esc(BB.label('document_categories', h.category))} · v${esc(h.version)} · ${esc(h.retrieval)}</div>
          <div class="btn-group" style="margin-top:8px">
            <button class="btn btn-ghost btn-sm" type="button" data-ask="${esc(q)}">Ask AI with this</button>
            ${h.source_url ? `<a class="btn btn-ghost btn-sm" href="${esc(h.source_url)}" target="_blank" rel="noopener">Source link</a>` : ''}
            ${devDetails('Technical details', { score: h.score, chunk_id: h.chunk_id })}
          </div>
        </div>`).join('');
      icons(host);
    } catch (err) {
      host.innerHTML = emptyState('Search failed', err.message, 'alert-circle');
      icons(host);
    }
  });

  el('#kb-results').addEventListener('click', (e) => {
    const ask = e.target.closest('[data-ask]');
    if (ask) location.href = '/assistant?q=' + encodeURIComponent(ask.getAttribute('data-ask'));
  });

  el('#kb-docs').addEventListener('click', async (e) => {
    const preview = e.target.closest('[data-preview]');
    if (preview) {
      try {
        const d = await api('/documents/' + preview.getAttribute('data-preview'));
        await modal({
          title: d.name,
          wide: true,
          body: `<div class="stat-inline" style="margin-bottom:12px">
            <div><div class="k">Category</div><div class="v sm">${esc(d.category_label || BB.label('document_categories', d.category))}</div></div>
            <div><div class="k">Version</div><div class="v sm">${esc(d.version)}</div></div>
            <div><div class="k">Passages</div><div class="v sm">${num(d.chunks, 0)}</div></div>
            <div><div class="k">Pages</div><div class="v sm">${d.pages || '—'}</div></div></div>
            ${(d.passages || []).map((p) => `<div class="card" style="box-shadow:none;margin-bottom:8px">
              <div class="small muted">${p.page ? 'Page ' + p.page : 'No page number'}${p.section ? ' · ' + esc(p.section) : ''}</div>
              <p class="small" style="margin:4px 0 0">${esc(p.text)}</p></div>`).join('')}`,
          footer: '<button class="btn btn-ghost" data-close>Close</button>',
        });
      } catch (err) { /* toasted */ }
      return;
    }
    const reindex = e.target.closest('[data-reindex]');
    if (reindex) {
      try {
        const r = await api(`/documents/${reindex.getAttribute('data-reindex')}/reindex`, { method: 'POST' });
        toast(`Reindexed ${r.chunks} passage(s).`, 'success'); load();
      } catch (err) { /* toasted */ }
      return;
    }
    const del = e.target.closest('[data-del]');
    if (del) {
      if (!await confirmDialog({ title: 'Delete this document?', message: 'The document and all of its indexed passages are removed. This cannot be undone.', confirmText: 'Delete', danger: true })) return;
      try {
        await api(`/documents/${del.getAttribute('data-del')}`, { method: 'DELETE' });
        toast('Document and its passages were deleted.', 'success'); load();
      } catch (err) { /* toasted */ }
    }
  });

  el('#kb-refresh').addEventListener('click', load);
  BB.ready().then(load);
})();
