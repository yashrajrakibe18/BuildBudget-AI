/* ChatGPT-style assistant: conversations, SSE progress, tool cards, approvals and email previews. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, money, num, badge, statusBadge, emptyState, modal, confirm: confirmDialog,
          toast, icons, dateFmt, timeAgo, markdown, field, formValues, devDetails, spinner } = BB;

  const streamHost = el('#chat-stream');
  const messagesHost = el('#chat-messages');
  const liveHost = el('#chat-live');
  const input = el('#composer-input');
  const projectSelect = el('#chat-project');
  const state = { conversations: [], current: null, messages: [], busy: false, controller: null, pinned: false,
                  lastDocumentId: null, lastDocumentName: null };

  const AGENT_LABELS = {
    general: 'General', planning: 'Project Planning', estimation: 'Measurement & Estimation',
    finance: 'Budget & Finance', procurement: 'Procurement', supplier: 'Supplier Research',
    inventory: 'Inventory', scheduling: 'Scheduling', knowledge: 'Construction Knowledge',
    analytics: 'Analytics', risk: 'Risk Analysis', reporting: 'Report Generation',
    communication: 'Email', notification: 'Notifications', verification: 'Verification',
  };

  /* ------------------------------------------------------------- helpers */
  function scrollDown() { streamHost.scrollTop = streamHost.scrollHeight; }

  function setBusy(on) {
    state.busy = on;
    el('#composer-send').disabled = on;
    el('#composer-stop').classList.toggle('hidden', !on);
    if (!on) state.controller = null;
  }

  function projectName(id) {
    const opt = Array.from(projectSelect.options).find((o) => o.value === String(id || ''));
    return opt && opt.value ? opt.textContent : '';
  }

  function updateContext() {
    const name = projectName(projectSelect.value);
    el('#context-chip').innerHTML = `<i data-lucide="folder" class="ico" style="width:12px;height:12px"></i> ${name ? esc(name) : 'General'}`;
    el('#chat-context').textContent = name ? `Project context: ${name}` : 'No project selected — general questions work too';
    icons(el('#context-chip'));
  }

  /* --------------------------------------------------------- conversations */
  function groupLabel(c) {
    const d = new Date(c.updated_at || c.created_at);
    const days = (Date.now() - d.getTime()) / 86400000;
    if (days < 1) return 'Today';
    if (days < 7) return 'Previous 7 days';
    if (days < 30) return 'Previous 30 days';
    return 'Older';
  }

  async function loadConversations(q) {
    try {
      const rows = await api('/assistant/conversations' + (q ? '?q=' + encodeURIComponent(q) : ''), { silent: true });
      state.conversations = rows;
      const pinned = rows.filter((c) => c.pinned);
      const normal = rows.filter((c) => !c.pinned);
      let html = '';
      if (pinned.length) {
        html += '<div class="chat-list-group">Pinned</div>' + pinned.map(item).join('');
      }
      let lastGroup = '';
      normal.forEach((c) => {
        const g = groupLabel(c);
        if (g !== lastGroup) { html += `<div class="chat-list-group">${g}</div>`; lastGroup = g; }
        html += item(c);
      });
      el('#chat-list').innerHTML = html || '<p class="small muted" style="padding:10px">No conversations yet. Start with New chat.</p>';
      el('#chat-count').textContent = `${rows.length} conversation${rows.length === 1 ? '' : 's'}`;
    } catch (err) { /* silent */ }
  }

  function item(c) {
    return `<div class="chat-item ${state.current === c.id ? 'on' : ''}" data-cid="${c.id}">
      <a href="#" data-open="${c.id}" title="${esc(c.title)}">${esc(c.title)}</a>
      <button class="icon-btn more" type="button" data-menu="${c.id}" aria-label="Conversation actions"
        style="width:26px;height:26px"><i data-lucide="more-horizontal" class="ico" style="width:15px;height:15px"></i></button>
    </div>`;
  }

  async function openConversation(id) {
    try {
      const conv = await api(`/assistant/conversations/${id}`);
      state.current = conv.id;
      state.pinned = !!conv.pinned;
      state.messages = conv.messages || [];
      state.lastDocumentId = null; state.lastDocumentName = null;
      projectSelect.value = conv.project_id || '';
      el('#chat-title').textContent = conv.title;
      el('#chat-pin').style.color = conv.pinned ? 'var(--amber)' : '';
      el('#chat-welcome').classList.add('hidden');
      renderMessages();
      updateContext();
      loadConversations(el('#chat-search').value.trim());
      new URLSearchParams(location.search).get('cid');
      const url = new URL(location.href); url.searchParams.set('cid', id); history.replaceState({}, '', url);
    } catch (err) { toast('Conversation could not be opened.', 'error'); }
  }

  function newChat() {
    state.current = null; state.messages = []; state.pinned = false;
    state.lastDocumentId = null; state.lastDocumentName = null;
    el('#chat-title').textContent = 'New chat';
    el('#chat-pin').style.color = '';
    el('#chat-welcome').classList.remove('hidden');
    messagesHost.innerHTML = ''; liveHost.innerHTML = ''; liveHost.classList.add('hidden');
    const url = new URL(location.href); url.searchParams.delete('cid'); history.replaceState({}, '', url);
    loadConversations(el('#chat-search').value.trim());
    input.focus();
  }

  /* --------------------------------------------------------------- render */
  function approvalCard(a) {
    return `<div class="approval-card" data-approval="${a.id}">
      <div class="ac-head"><i data-lucide="shield-check" class="ico" style="width:15px;height:15px;vertical-align:-2px"></i>
        Approval required: ${esc(BB.label('approval_actions', a.action))}</div>
      <div class="ac-body">
        <div><strong>${esc(a.title)}</strong></div>
        ${a.summary ? `<div class="small muted" style="margin-top:3px">${esc(a.summary)}</div>` : ''}
        <div class="small muted" style="margin-top:6px">Requested ${dateFmt(a.created_at, true)} · expires ${dateFmt(a.expires_at, true)}</div>
        ${a.execution_error ? `<div class="alert error" style="margin-top:8px">${esc(a.execution_error)}</div>` : ''}
        ${devDetails('Technical details', a.payload)}
      </div>
      <div class="ac-foot">
        ${a.status === 'pending' ? `
          <button class="btn btn-accent btn-sm" type="button" data-approve="${a.id}">Approve & execute</button>
          <button class="btn btn-ghost btn-sm" type="button" data-reject="${a.id}">Reject</button>` :
          `<span class="badge ${esc(a.status)}">${esc(BB.label('approval_status', a.status))}</span>
           ${a.executed_at ? `<span class="small muted">Executed ${dateFmt(a.executed_at, true)}</span>` : ''}`}
        <a class="small" href="/approvals" style="align-self:center">Approval Centre</a>
      </div>
    </div>`;
  }

  async function emailCard(draftId, approval) {
    const card = document.createElement('div');
    card.className = 'email-card';
    card.innerHTML = '<div class="ec-head small muted">Loading email preview…</div>';
    try {
      const d = await api('/mail/' + draftId, { silent: true });
      card.innerHTML = `<div class="ec-head">
          <div class="small muted">Email draft ${d.status === 'sent' ? '· sent' : '· awaiting approval'}</div>
          <div><strong>${esc(d.subject || '(no subject)')}</strong></div>
          <div class="small">To: ${esc(d.to || '—')}${d.cc ? ' · Cc: ' + esc(d.cc) : ''}${d.bcc ? ' · Bcc: ' + esc(d.bcc) : ''}</div>
        </div>
        <div class="ec-body">${esc(d.body || '')}</div>
        ${(d.attachments || []).length ? `<div class="small muted" style="padding:0 13px 8px">Attachments: ${d.attachments.map((a) => esc(a.name || 'file')).join(', ')}</div>` : ''}
        <div class="ec-foot">
          ${d.status !== 'sent' ? `<button class="btn btn-accent btn-sm" type="button" data-send-draft="${d.id}">Approve & send</button>
            <button class="btn btn-ghost btn-sm" type="button" data-edit-draft="${d.id}">Edit draft</button>
            <button class="btn btn-ghost btn-sm" type="button" data-schedule-draft="${d.id}">Schedule instead</button>` :
            `<span class="badge sent">Sent ${d.sent_at ? dateFmt(d.sent_at, true) : ''}</span>`}
          ${approval && approval.status === 'pending' ? `<button class="btn btn-ghost btn-sm" type="button" data-reject="${approval.id}">Reject</button>` : ''}
          <a class="small" href="/mail" style="align-self:center">Mail Centre</a>
        </div>`;
    } catch (err) {
      card.innerHTML = `<div class="ec-head small muted">This email draft is no longer available.</div>`;
    }
    return card;
  }

  function toolCard(t) {
    const label = BB.label('tools', t.tool, BB.humanize(t.tool));
    return `<details class="tool-card">
      <summary><span class="status-dot ${esc(t.status)}"></span>
        <strong>${esc(label)}</strong>
        <span class="small muted" style="margin-left:auto">${t.status === 'ok' ? 'completed' : t.status}${t.duration_ms != null ? ' · ' + num(t.duration_ms, 0) + ' ms' : ''}</span>
      </summary>
      <div class="tool-body"><div class="small">${esc(t.summary || 'No summary returned.')}</div></div>
    </details>`;
  }

  function messageRow(role, content, meta, when, id) {
    const isUser = role === 'user';
    const initials = isUser ? 'You' : 'AI';
    const rows = [];
    rows.push(`<div class="msg-row ${isUser ? 'user' : 'assistant'}" data-mid="${id || ''}">
      <div class="msg-avatar">${initials}</div>
      <div class="msg-body">
        <div class="msg-meta">${isUser ? 'You' : 'BuildBudget AI'} · ${when ? timeAgo(when) : 'just now'}</div>
        <div class="msg-bubble md">${isUser ? `<p>${esc(content).replace(/\n/g, '<br>')}</p>` : markdown(content)}</div>`);
    if (!isUser) {
      const m = meta || {};
      rows.push(`<div class="msg-tools">${(m.tools || []).map(toolCard).join('')}</div>`);
      if ((m.agents || []).length) {
        rows.push(`<div class="small muted" style="margin-top:6px">Specialists: ${m.agents.map((a) => esc(AGENT_LABELS[a] || BB.humanize(a))).join(', ')}</div>`);
      }
      if ((m.missing_info || []).length) {
        rows.push(`<div class="insight warning" style="margin-top:8px"><i data-lucide="help-circle" class="ico"></i>
          <div><b>Information needed</b><span>${m.missing_info.map(esc).join('<br>')}</span></div></div>`);
      }
      rows.push(`<div class="msg-actions">
        <button type="button" data-copy>Copy</button>
        <button type="button" data-regen>Regenerate</button>
      </div>`);
    }
    rows.push('</div></div>');
    return rows.join('');
  }

  function renderMessages() {
    messagesHost.innerHTML = state.messages.map((msg) => messageRow(msg.role, msg.content, msg.meta, msg.created_at, msg.id)).join('');
    icons(messagesHost);
    const last = [...state.messages].reverse().find((x) => x.role === 'assistant');
    if (last && (last.meta || {}).approval_ids) {
      (last.meta.approval_ids || []).forEach(async (aid) => {
        try {
          const a = await api('/approvals', { silent: true });
          const row = a.find((x) => x.id === aid);
          if (!row) return;
          const node = document.createElement('div');
          node.innerHTML = approvalCard(row);
          messagesHost.appendChild(node.firstElementChild);
          icons(messagesHost);
          if (row.action === 'send_email' && row.payload && row.payload.draft_id) {
            const card = await emailCard(row.payload.draft_id, row);
            messagesHost.appendChild(card);
            icons(messagesHost);
          }
        } catch (e) { /* ignore */ }
      });
    }
    scrollDown();
  }

  /* -------------------------------------------------------------- streaming */
  function liveLine(text, tone) {
    liveHost.classList.remove('hidden');
    const line = document.createElement('div');
    line.className = 'small' + (tone ? ' ' + tone : '');
    line.style.cssText = 'display:flex;gap:8px;align-items:center;margin:4px 0;color:var(--muted)';
    line.innerHTML = `${tone === 'error' ? '<span class="status-dot error"></span>' : '<span class="spinner"></span>'}<span>${esc(text)}</span>`;
    liveHost.appendChild(line);
    scrollDown();
    return line;
  }

  function handleEvent(ev, ctx) {
    if (ev.type === 'status') liveLine(ev.message);
    if (ev.type === 'routing') {
      const names = (ev.agents || []).map((a) => AGENT_LABELS[a] || BB.humanize(a)).join(', ');
      liveLine(`Routing to ${names || 'general assistant'}`, 'ok');
    }
    if (ev.type === 'tool') {
      liveLine(`${BB.label('tools', ev.tool, BB.humanize(ev.tool))} — ${ev.status}${ev.duration_ms != null ? ` (${ev.duration_ms} ms)` : ''}`,
        ev.status === 'ok' ? 'ok' : 'error');
    }
    if (ev.type === 'answer') {
      ctx.answer = ev;
      state.pendingApprovals = ev.approvals || [];
    }
    if (ev.type === 'error') { ctx.error = ev.message; liveLine(ev.message, 'error'); }
  }

  async function send(message) {
    if (state.busy) return;
    if (!message.trim()) return;
    const usedDocument = state.lastDocumentId;
    state.lastDocumentId = null;
    el('#chat-welcome').classList.add('hidden');
    messagesHost.insertAdjacentHTML('beforeend', messageRow('user', message, null, null));
    input.value = '';
    autosize();
    scrollDown();
    liveHost.innerHTML = '';
    liveHost.classList.remove('hidden');
    const thinking = liveLine('Understanding your request…');
    setBusy(true);
    state.controller = new AbortController();
    const ctx = {};
    try {
      const res = await fetch('/api/v1/assistant/stream', {
        method: 'POST', credentials: 'same-origin', signal: state.controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': BB.csrf },
        body: JSON.stringify({
          message,
          project_id: projectSelect.value ? Number(projectSelect.value) : null,
          conversation_id: state.current,
          document_id: usedDocument,
        }),
      });
      if (!res.ok) {
        let detail = 'The assistant is unavailable.';
        try { const j = await res.json(); detail = j.detail || detail; } catch (e) { /* ignore */ }
        throw new Error(detail);
      }
      if (!res.body) throw new Error('Streaming is not supported by this browser.');
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop();
        parts.forEach((part) => {
          const line = part.split('\n').find((l) => l.startsWith('data: '));
          if (!line) return;
          try { handleEvent(JSON.parse(line.slice(6)), ctx); } catch (e) { /* ignore malformed */ }
        });
      }
      liveHost.classList.add('hidden');
      if (ctx.error) {
        messagesHost.insertAdjacentHTML('beforeend', `<div class="insight critical" style="margin-bottom:12px">
          <i data-lucide="alert-octagon" class="ico"></i><div><b>The assistant could not complete this request</b>
          <span>${esc(ctx.error)}</span>
          <div class="btn-group" style="margin-top:6px"><button class="btn btn-ghost btn-sm" type="button" data-retry-message="${esc(message)}">Retry</button></div></div></div>`);
        icons(messagesHost);
      } else if (ctx.answer) {
        const a = ctx.answer;
        state.current = a.conversation_id;
        state.messages.push({ role: 'user', content: message, created_at: new Date().toISOString() });
        const meta = { agents: a.agents, tools: a.tool_events || [],
          approval_ids: (a.approvals || []).map((x) => x.id), missing_info: [] };
        state.messages.push({ role: 'assistant', content: a.answer, meta, created_at: new Date().toISOString(), id: a.message_id });
        messagesHost.insertAdjacentHTML('beforeend', messageRow('assistant', a.answer, meta, null, a.message_id));
        icons(messagesHost);
        (a.approvals || []).forEach(async (approval) => {
          const node = document.createElement('div');
          node.innerHTML = approvalCard(approval);
          messagesHost.appendChild(node.firstElementChild);
          if (approval.action === 'send_email' && approval.payload && approval.payload.draft_id) {
            messagesHost.appendChild(await emailCard(approval.payload.draft_id, approval));
          }
          icons(messagesHost);
        });
        if (state.current) {
          const conv = await api(`/assistant/conversations/${state.current}`, { silent: true });
          el('#chat-title').textContent = conv.title;
          el('#chat-pin').style.color = conv.pinned ? 'var(--amber)' : '';
          state.pinned = !!conv.pinned;
        }
        loadConversations(el('#chat-search').value.trim());
      } else {
        messagesHost.insertAdjacentHTML('beforeend', `<div class="insight warning">The stream ended without an answer. Try again.</div>`);
      }
    } catch (err) {
      liveHost.classList.add('hidden');
      if (err.name === 'AbortError') {
        messagesHost.insertAdjacentHTML('beforeend', `<div class="small muted" style="margin-bottom:12px">Generation stopped. The partial run was discarded.</div>`);
      } else {
        messagesHost.insertAdjacentHTML('beforeend', `<div class="insight critical" style="margin-bottom:12px">
          <i data-lucide="alert-octagon" class="ico"></i><div><b>Request failed</b><span>${esc(err.message)}</span>
          <div class="btn-group" style="margin-top:6px"><button class="btn btn-ghost btn-sm" type="button" data-retry-message="${esc(message)}">Retry</button></div></div></div>`);
        icons(messagesHost);
        if (/unavailable|not configured/i.test(err.message)) showSetup(err.message);
      }
    } finally {
      setBusy(false);
      liveHost.innerHTML = '';
      scrollDown();
    }
  }

  function showSetup(message) {
    const box = el('#assistant-setup');
    box.classList.remove('hidden');
    box.innerHTML = `<div class="card" style="border-color:var(--amber)">
      <h3>Assistant not configured</h3>
      <p class="small">${esc(message)}</p>
      <p class="small muted">Add an API key in <code>.env</code> (for example <code>GROQ_API_KEY</code> or
      <code>OPENAI_API_KEY</code>) and restart the server. Everything else in BuildBudget AI keeps working without a model.</p>
      <a class="btn btn-ghost btn-sm" href="/settings">Open settings</a>
    </div>`;
    icons(box);
  }

  /* --------------------------------------------------------------- composer */
  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(220, input.scrollHeight) + 'px';
  }
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); el('#composer-form').requestSubmit(); }
  });
  el('#composer-form').addEventListener('submit', (e) => {
    e.preventDefault();
    send(input.value);
  });
  el('#composer-stop').addEventListener('click', () => {
    if (state.controller) state.controller.abort();
    setBusy(false);
  });
  const fileInput = el('#composer-file');
  const attachBox = el('#composer-attachment');
  const attachBtn = el('#composer-attach');
  el('#composer-attach').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    if (file.size > 15 * 1024 * 1024) {
      toast('That file is larger than 15 MB. Upload a smaller document.', 'error');
      fileInput.value = '';
      return;
    }
    const body = new FormData();
    body.append('file', file);
    body.append('category', projectSelect.value ? 'project_document' : 'general');
    if (projectSelect.value) body.append('project_id', projectSelect.value);
    attachBtn.disabled = true;
    attachBox.classList.remove('hidden');
    attachBox.innerHTML = `<i data-lucide="loader" class="ico"></i> Indexing ${esc(file.name)}…`;
    icons(attachBox);
    try {
      const res = await fetch('/api/v1/documents', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'X-CSRF-Token': BB.csrf }, body,
      });
      let data = {};
      try { data = await res.json(); } catch (e) { /* non-JSON error */ }
      if (!res.ok) throw new Error(data.detail || 'The document could not be indexed.');
      state.lastDocumentId = data.id;
      state.lastDocumentName = data.name || file.name;
      attachBox.innerHTML = `<i data-lucide="file-check" class="ico" style="color:var(--success)"></i>
        Indexed <b>${esc(data.name || file.name)}</b> — ${num(data.chunks || 0, 0)} searchable passage(s).
        It will be read with your next message.`;
      icons(attachBox);
      toast('Document indexed. Ask the assistant about it.', 'ok');
      fileInput.value = '';
    } catch (err) {
      attachBox.classList.add('hidden');
      attachBox.innerHTML = '';
      toast(err.message || 'The document could not be indexed.', 'error');
      fileInput.value = '';
    } finally {
      attachBtn.disabled = false;
    }
  });

  projectSelect.addEventListener('change', () => {
    updateContext();
    if (state.current) {
      api(`/assistant/conversations/${state.current}`, { method: 'PATCH', body: { title: undefined }, silent: true }).catch(() => {});
    }
  });

  el('#new-chat').addEventListener('click', newChat);
  el('#chat-search').addEventListener('input', () => loadConversations(el('#chat-search').value.trim()));
  el('#prompt-grid').addEventListener('click', (e) => {
    const card = e.target.closest('[data-prompt]');
    if (card) { input.value = card.getAttribute('data-prompt'); autosize(); input.focus(); }
  });

  el('#chat-list').addEventListener('click', async (e) => {
    const open = e.target.closest('[data-open]');
    if (open) { e.preventDefault(); openConversation(Number(open.getAttribute('data-open'))); return; }
    const menu = e.target.closest('[data-menu]');
    if (menu) {
      e.stopPropagation();
      const id = Number(menu.getAttribute('data-menu'));
      const conv = state.conversations.find((c) => c.id === id);
      const action = await modal({
        title: conv ? conv.title : 'Conversation',
        body: '<p class="small muted">Choose an action for this conversation.</p>',
        footer: `<button class="btn btn-ghost" data-close>Cancel</button>
          <button class="btn btn-ghost" data-result="rename">Rename</button>
          <button class="btn btn-ghost" data-result="pin">${conv && conv.pinned ? 'Unpin' : 'Pin'}</button>
          <button class="btn btn-danger" data-result="delete">Delete</button>`,
      });
      if (action === 'rename') {
        const title = await modal({
          title: 'Rename conversation',
          body: `<form id="rename-form">${field('title', 'Title', { value: conv ? conv.title : '', required: true })}</form>`,
          footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Save</button>`,
          onResult: (v, root) => {
            if (v !== 'save') return true;
            const t = formValues(el('#rename-form', root)).title;
            if (!t) { toast('Title cannot be empty.', 'error'); return false; }
            api(`/assistant/conversations/${id}`, { method: 'PATCH', body: { title: t } })
              .then(() => { if (state.current === id) el('#chat-title').textContent = t; loadConversations(); }).catch(() => {});
            return true;
          },
        });
      } else if (action === 'pin') {
        await api(`/assistant/conversations/${id}`, { method: 'PATCH', body: { pinned: !(conv && conv.pinned) } });
        loadConversations();
      } else if (action === 'delete') {
        if (!await confirmDialog({ title: 'Delete this conversation?', message: 'Messages and tool history for this chat are removed. Approval records are kept.', confirmText: 'Delete', danger: true })) return;
        await api(`/assistant/conversations/${id}`, { method: 'DELETE' });
        if (state.current === id) newChat();
        loadConversations();
      }
    }
  });

  el('#chat-pin').addEventListener('click', async () => {
    if (!state.current) return;
    state.pinned = !state.pinned;
    await api(`/assistant/conversations/${state.current}`, { method: 'PATCH', body: { pinned: state.pinned } });
    el('#chat-pin').style.color = state.pinned ? 'var(--amber)' : '';
    loadConversations();
  });
  el('#chat-delete').addEventListener('click', async () => {
    if (!state.current) return;
    if (!await confirmDialog({ title: 'Delete this conversation?', message: 'This removes its messages from your history.', confirmText: 'Delete', danger: true })) return;
    await api(`/assistant/conversations/${state.current}`, { method: 'DELETE' });
    newChat();
  });

  /* --------------------------------------------------- in-message actions */
  messagesHost.addEventListener('click', async (e) => {
    const copy = e.target.closest('[data-copy]');
    if (copy) { BB.copy(copy.closest('.msg-row').querySelector('.msg-bubble').innerText); return; }
    const regen = e.target.closest('[data-regen]');
    if (regen) {
      const rows = [...messagesHost.querySelectorAll('.msg-row')];
      const idx = rows.indexOf(regen.closest('.msg-row'));
      const prevUser = rows.slice(0, idx).reverse().find((r) => r.classList.contains('user'));
      if (prevUser) send(prevUser.querySelector('.msg-bubble').innerText);
      return;
    }
    const retry = e.target.closest('[data-retry-message]');
    if (retry) { send(retry.getAttribute('data-retry-message')); return; }
    const approve = e.target.closest('[data-approve]');
    if (approve) {
      if (!await confirmDialog({ title: 'Approve and execute?', message: 'The approved action runs now, exactly once. This may record data or send an external email.', confirmText: 'Approve & execute' })) return;
      try {
        const r = await api(`/approvals/${approve.getAttribute('data-approve')}/decide`, { method: 'POST', body: { approve: true } });
        toast(r.message || 'Approved.', r.executed === false ? 'warn' : 'success');
        if (r.executed === false && r.approval_id) {
          const retryBtn = document.createElement('button');
          retryBtn.className = 'btn btn-ghost btn-sm';
          retryBtn.textContent = 'Retry execution';
          retryBtn.addEventListener('click', async () => {
            try { await api(`/approvals/${r.approval_id}/execute`, { method: 'POST' }); toast('Execution retried.', 'success'); }
            catch (err) { /* toasted */ }
          });
          approve.replaceWith(retryBtn);
        } else {
          approve.closest('.ac-foot').innerHTML = `<span class="badge approved">Approved${r.executed ? ' & executed' : ''}</span>`;
        }
      } catch (err) { /* toasted */ }
      return;
    }
    const reject = e.target.closest('[data-reject]');
    if (reject) {
      if (!await confirmDialog({ title: 'Reject this request?', message: 'Nothing will be executed.', confirmText: 'Reject', danger: true })) return;
      try {
        await api(`/approvals/${reject.getAttribute('data-reject')}/decide`, { method: 'POST', body: { approve: false } });
        toast('Rejected — nothing was executed.', 'success');
        reject.closest('.ac-foot').innerHTML = '<span class="badge rejected">Rejected</span>';
      } catch (err) { /* toasted */ }
      return;
    }
    const sendDraft = e.target.closest('[data-send-draft]');
    if (sendDraft) {
      if (!await confirmDialog({ title: 'Approve and send this email?', message: 'The message is sent through the configured provider now. Provider acceptance is not proof of inbox delivery.', confirmText: 'Approve & send' })) return;
      try {
        const r = await api(`/mail/${sendDraft.getAttribute('data-send-draft')}/send?confirm=true`, { method: 'POST' });
        toast(r.message || 'Email sent.', r.status === 'failed' ? 'error' : 'success');
        sendDraft.closest('.ec-foot').innerHTML = `<span class="badge ${esc(r.status)}">${esc(BB.label('email_status', r.status))}</span>
          <span class="small muted">${esc(r.delivery_note || '')}</span>`;
      } catch (err) { /* toasted */ }
      return;
    }
    const editDraft = e.target.closest('[data-edit-draft]');
    if (editDraft) {
      const id = editDraft.getAttribute('data-edit-draft');
      const d = await api('/mail/' + id);
      await modal({
        title: 'Edit email draft',
        wide: true,
        body: `<p class="small muted">Editing a draft that was awaiting approval cancels that approval — a new approval is
          required before it can be sent.</p>
          <form id="draft-edit"><div class="form-grid">
            ${field('to_addr', 'To', { value: d.to, required: true })}
            ${field('cc_addr', 'Cc', { value: d.cc })}
            ${field('bcc_addr', 'Bcc', { value: d.bcc })}
            ${field('subject', 'Subject', { value: d.subject })}
            ${field('body_text', 'Message', { textarea: true, rows: 8, value: d.body })}
          </div></form>`,
        footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Save draft</button>`,
        onResult: (v, root) => {
          if (v !== 'save') return true;
          api(`/mail/${id}`, { method: 'PUT', body: formValues(el('#draft-edit', root)) })
            .then(() => { toast('Draft updated. Request approval again to send.', 'success'); })
            .catch(() => {});
          return true;
        },
      });
      return;
    }
    const schedule = e.target.closest('[data-schedule-draft]');
    if (schedule) {
      await modal({
        title: 'Schedule this email',
        body: `<form id="sched-form">${field('when', 'Send at', { type: 'datetime-local', required: true })}
          <p class="small muted" style="margin:8px 0 0">The scheduler process sends it when due. It is not sent from this browser tab.</p></form>`,
        footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Schedule</button>`,
        onResult: (v, root) => {
          if (v !== 'save') return true;
          const when = formValues(el('#sched-form', root)).when;
          if (!when) { toast('Choose a date and time.', 'error'); return false; }
          api(`/mail/${schedule.getAttribute('data-schedule-draft')}/schedule`, { method: 'POST', body: { when: new Date(when).toISOString() } })
            .then((r) => toast(r.message || 'Scheduled.', 'success')).catch(() => {});
          return true;
        },
      });
    }
  });

  /* ---------------------------------------------------------------- startup */
  async function status() {
    try {
      const s = await api('/assistant/status', { silent: true });
      const badgeEl = el('#assistant-status');
      if (s.llm && s.llm.available) {
        badgeEl.className = 'badge ok';
        badgeEl.textContent = `${s.llm.provider} · ${s.llm.model}`;
      } else {
        badgeEl.className = 'badge warning';
        badgeEl.textContent = 'Model not configured';
        showSetup((s.llm && s.llm.reason) || 'No language-model provider is configured.');
      }
    } catch (err) { /* ignore */ }
  }

  BB.ready().then(() => {
    status();
    loadConversations();
    updateContext();
    const params = new URLSearchParams(location.search);
    if (params.get('project')) { projectSelect.value = params.get('project'); updateContext(); }
    if (params.get('q')) { input.value = params.get('q'); autosize(); input.focus(); }
    if (params.get('cid')) openConversation(Number(params.get('cid')));
    document.addEventListener('bb:project-change', (e) => {
      projectSelect.value = e.detail ? String(e.detail) : '';
      updateContext();
    });
    if (window.innerWidth <= 900) el('#assistant-side-toggle').style.display = '';
    el('#assistant-side-toggle').addEventListener('click', () => {
      const shell = el('#chat-shell');
      shell.setAttribute('data-side', shell.getAttribute('data-side') === 'open' ? 'closed' : 'open');
    });
  });
})();
