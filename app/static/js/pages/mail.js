/* Mail Centre: folders, drafts, approval-gated sending and scheduling. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, badge, emptyState, modal, confirm: confirmDialog, toast, icons,
          dateFmt, timeAgo, field, formValues, money } = BB;

  const FOLDERS = ['drafts', 'pending_approval', 'scheduled', 'sent', 'failed'];
  const TONES = ['professional', 'friendly', 'firm', 'concise', 'follow_up'];
  const state = { folder: 'drafts', counts: {}, messages: [], current: null, provider: null,
                  projects: null };

  async function projectChoices() {
    if (state.projects) return state.projects;
    try {
      const rows = await api('/projects');
      state.projects = (rows || []).map((p) => ({ value: String(p.id), label: p.name }));
    } catch (err) {
      state.projects = [];
    }
    return state.projects;
  }

  function can(cap) { return !BB.me || !BB.me.capabilities || BB.me.capabilities.includes(cap); }

  function renderStatus() {
    const box = el('#mail-status');
    const p = state.provider || {};
    const gmail = p.gmail || {};
    let tone = 'warning';
    let text = p.message || 'Mail provider status unknown.';
    if (p.state === 'ready') {
      tone = 'ok';
      text = p.provider === 'local'
        ? 'Sending through LOCAL capture — messages are written to .run/mailbox and are NOT delivered to the recipient.'
        : `Sending through ${(p.provider || 'SMTP').toUpperCase()}${p.from_address ? ' as ' + p.from_address : ''}.`;
    }
    if (p.state === 'disabled') { tone = 'warning'; text = p.message || 'Email sending is disabled in the server configuration.'; }
    if (p.state === 'not_configured') { tone = 'warning'; text = p.message || 'SMTP credentials are not configured.'; }
    box.innerHTML = `<div style="display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap">
      <span class="badge ${esc(tone)}">${esc(p.state === 'ready' ? 'Ready' : p.state === 'disabled' ? 'Disabled' : 'Not configured')}</span>
      <div style="flex:1;min-width:200px"><div>${esc(text)}</div>
        <div class="small muted" style="margin-top:4px">Configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME and SMTP_PASSWORD
        (a Gmail App Password, never your normal password) in the server environment.</div></div>
      <div class="small" style="text-align:right">
        <div><strong>Gmail API</strong>: ${gmail.implemented ? 'available' : 'not implemented'}</div>
        <div class="muted">${esc(gmail.message || 'Mailbox sync is unavailable.')}</div>
      </div></div>`;
    icons(box);
  }

  function renderFolders() {
    el('#mail-folders').innerHTML = FOLDERS.map((f) => `<button class="mail-folder ${state.folder === f ? 'on' : ''}"
      type="button" data-folder="${f}">
      <i data-lucide="${f === 'drafts' ? 'file' : f === 'sent' ? 'send' : f === 'failed' ? 'alert-circle' : f === 'scheduled' ? 'clock' : 'shield-check'}" class="ico" style="width:15px;height:15px"></i>
      <span>${esc(BB.label('mail_folders', f))}</span>
      <span class="count">${state.counts[f] || 0}</span></button>`).join('');
    icons(el('#mail-folders'));
  }

  function renderList() {
    if (!state.messages.length) {
      el('#mail-list').innerHTML = `<div style="padding:12px">${emptyState(`No mail in ${BB.label('mail_folders', state.folder).toLowerCase()}`,
        state.folder === 'drafts' ? 'Compose a message or ask the assistant to prepare one.' : '', 'mail')}</div>`;
      icons(el('#mail-list'));
      return;
    }
    el('#mail-list').innerHTML = state.messages.map((m) => `<div class="mail-list-item ${state.current === m.id ? 'on' : ''}" data-mid="${m.id}">
      <div style="display:flex;gap:6px;align-items:center">
        <div class="m-to" style="flex:1">${esc(m.to || '(no recipient)')}</div>
        <div class="small muted nowrap">${m.sent_at ? dateFmt(m.sent_at) : timeAgo(m.updated_at)}</div>
      </div>
      <div class="m-sub">${esc(m.subject)}</div>
      <div class="m-prev">${esc((m.body || '').slice(0, 120))}</div>
      <div style="margin-top:4px">${badge(BB.label('email_status', m.status), m.status)}
        ${(m.attachments || []).length ? `<span class="badge info">${m.attachments.length} attachment(s)</span>` : ''}</div>
    </div>`).join('');
    icons(el('#mail-list'));
  }

  function renderView(d) {
    const canSend = can('mail.send');
    el('#mail-view').innerHTML = `<div class="mv-head">
      <div style="display:flex;gap:8px;align-items:flex-start">
        <h2 style="margin:0;font-size:17px;flex:1">${esc(d.subject || '(no subject)')}</h2>
        ${badge(BB.label('email_status', d.status), d.status)}
      </div>
      <div class="small muted" style="margin-top:6px">To: ${esc(d.to || '—')}${d.cc ? ' · Cc: ' + esc(d.cc) : ''}${d.bcc ? ' · Bcc: ' + esc(d.bcc) : ''}</div>
      <div class="small muted">Updated ${dateFmt(d.updated_at, true)}${d.sent_at ? ' · sent ' + dateFmt(d.sent_at, true) : ''}${d.scheduled_at ? ' · scheduled ' + dateFmt(d.scheduled_at, true) : ''}</div>
      ${d.error ? `<div class="alert error" style="margin-top:8px">${esc(d.error)}</div>` : ''}
    </div>
    <div class="mv-body">${esc(d.body || '')}</div>
    ${(d.attachments || []).length ? `<div style="margin-top:14px"><div class="label">Attachments</div>
      <ul class="small" style="margin:6px 0 0 16px">${d.attachments.map((a) => `<li>${esc(a.name || 'file')}</li>`).join('')}</ul></div>` : ''}
    <div class="btn-group" style="margin-top:18px">
      ${canSend && d.status !== 'sent' ? `
        <button class="btn btn-accent btn-sm" type="button" data-send="${d.id}">${d.approval_id ? 'Approve & send' : 'Request approval & send'}</button>
        <button class="btn btn-ghost btn-sm" type="button" data-edit="${d.id}">Edit</button>
        <button class="btn btn-ghost btn-sm" type="button" data-schedule="${d.id}">Schedule</button>
        ${d.status === 'pending_approval' && d.approval_id ? `<a class="btn btn-ghost btn-sm" href="/approvals">View approval</a>` : ''}
        <button class="btn btn-danger btn-sm" type="button" data-delete="${d.id}">Delete</button>` : ''}
      ${d.status === 'sent' ? `<button class="btn btn-ghost btn-sm" type="button" data-followup="${d.id}">Follow up</button>` : ''}
    </div>
    <p class="small muted" style="margin-top:12px">Sending is an explicit action. Provider acceptance means the message
    left this server, not that the recipient read it.</p>`;
    icons(el('#mail-view'));
  }

  async function loadStatus() {
    try {
      const s = await api('/mail/status', { silent: true });
      state.provider = s.provider;
      state.counts = s.counts || {};
      renderStatus();
      renderFolders();
    } catch (err) {
      el('#mail-status').innerHTML = `<div class="alert error">Mail status could not be loaded.</div>`;
    }
  }

  async function loadFolder(folder) {
    state.folder = folder; state.current = null;
    renderFolders();
    el('#mail-view').innerHTML = '<p class="small muted">Select a message.</p>';
    try {
      const r = await api(`/mail?folder=${folder}`);
      state.messages = r.messages || [];
      state.counts = r.counts || state.counts;
      renderFolders();
      renderList();
    } catch (err) {
      el('#mail-list').innerHTML = `<div style="padding:12px">${emptyState('Mail could not load', err.message, 'alert-circle')}</div>`;
      icons(el('#mail-list'));
    }
  }

  async function openMessage(id) {
    try {
      const d = await api('/mail/' + id);
      state.current = id;
      renderList();
      renderView(d);
    } catch (err) { /* toasted */ }
  }

  async function compose(prefill) {
    prefill = prefill || {};
    const projects = await projectChoices();
    const aiPanel = `<div class="ai-mail">
      <div class="ai-mail-head">
        <i data-lucide="sparkles" class="ico"></i>
        <div><strong>Write with AI</strong>
          <div class="small muted">Describe the email and the assistant writes the subject and message
          from your saved records. It never invents a recipient — you add the address — and nothing
          is sent without approval.</div></div>
      </div>
      <div class="form-grid">
        ${field('ai_project', 'Project context (optional)', { options: [{ value: '', label: 'No project context' }].concat(projects) })}
        ${field('ai_tone', 'Tone', { options: TONES, value: 'professional' })}
      </div>
      ${field('ai_purpose', 'What should the email say?', { textarea: true, rows: 3,
        placeholder: 'e.g. Ask the tiler for a delivery date this week because cement stock is below the reorder level.' })}
      <div class="ai-mail-actions">
        <button class="btn btn-ghost btn-sm" type="button" id="ai-write">
          <i data-lucide="wand-2" class="ico"></i> Write draft</button>
        <span class="small muted" id="ai-write-status" role="status" aria-live="polite"></span>
      </div>
    </div>`;
    await modal({
      title: prefill.id ? 'Edit email' : 'Compose email',
      wide: true,
      body: `<form id="compose-form">${aiPanel}<div class="form-grid">
        ${field('to', 'To', { value: prefill.to || '', required: true, placeholder: 'recipient@example.com', hint: 'Recipients are never invented — type the address your contact gave you.' })}
        ${field('cc', 'Cc', { value: prefill.cc || '' })}
        ${field('bcc', 'Bcc', { value: prefill.bcc || '' })}
        ${field('subject', 'Subject', { value: prefill.subject || '' })}
        ${field('body', 'Message', { textarea: true, rows: 10, value: prefill.body || '' })}
      </div>
      <p class="small muted" style="margin:8px 0 0">Plain-text email. Attachments generated by the assistant are kept with
      the draft and sent with it after approval.</p></form>`,
      footer: `<button class="btn btn-ghost" data-close>Cancel</button>
        ${prefill.sentAsDraft ? '' : '<button class="btn btn-ghost" data-result="save">Save draft</button>'}
        <button class="btn btn-accent" data-result="approval">Save & request approval</button>`,
      onMount: (root) => {
        const btn = el('#ai-write', root);
        if (!btn) return;
        btn.addEventListener('click', async () => {
          const form = el('#compose-form', root);
          const status = el('#ai-write-status', root);
          const purposeEl = el('[name="ai_purpose"]', root);
          const purpose = (purposeEl.value || '').trim();
          if (!purpose) { purposeEl.focus(); toast('Say what the email should be about first.', 'error'); return; }
          const current = formValues(form);
          if ((current.body || '').trim() && !await confirmDialog({
            title: 'Replace the current message?',
            message: 'The AI draft replaces the Subject and Message fields.',
            detail: 'Your To, Cc and Bcc fields are kept as they are.',
            confirmText: 'Replace text',
          })) return;
          const pid = el('[name="ai_project"]', root).value;
          btn.disabled = true;
          status.textContent = 'Writing the draft…';
          try {
            const r = await api('/mail/ai-draft', { method: 'POST', body: {
              purpose,
              tone: el('[name="ai_tone"]', root).value,
              project_id: pid ? Number(pid) : null,
              recipient: (current.to || '').trim(),
              subject_hint: (current.subject || '').trim(),
            } });
            form.elements.subject.value = r.subject;
            form.elements.body.value = r.body;
            status.textContent = r.note || 'Draft written. Check it before saving.';
            toast(r.project ? `Draft written from ${r.project}.` : 'Draft written.', 'success');
          } catch (err) {
            status.textContent = 'The AI writer did not answer. You can still write the email yourself.';
          } finally {
            btn.disabled = false;
          }
        });
      },
      onResult: (value, root) => {
        if (value === 'save' || value === 'approval') {
          const form = el('#compose-form', root);
          const body = formValues(form);
          const to = (body.to || '').trim();
          const isAddr = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
          const badAddrs = (v) => (v || '').split(/[,;]/).map((s) => s.trim()).filter(Boolean).filter((s) => !isAddr(s));
          const reject = (name, msg) => {
            const input = el(`[name="${name}"]`, form);
            if (input) {
              input.setAttribute('aria-invalid', 'true');
              input.focus();
              input.select();
              input.addEventListener('input', () => input.removeAttribute('aria-invalid'), { once: true });
            }
            toast(msg, 'error');
            return false;
          };
          if (value === 'approval' && !to) return reject('to', 'Add the recipient\u2019s email in the To field, then request approval.');
          if (to && !isAddr(to)) return reject('to', 'The To field must be a single valid email address (for example name@example.com).');
          const ccBad = badAddrs(body.cc);
          if (ccBad.length) return reject('cc', `Cc has to contain email addresses only — remove: ${ccBad.join(', ')}. Leave it empty to send without a copy.`);
          const bccBad = badAddrs(body.bcc);
          if (bccBad.length) return reject('bcc', `Bcc has to contain email addresses only — remove: ${bccBad.join(', ')}. Leave it empty to send without a blind copy.`);
          if (to !== (body.to || '')) body.to = to;
          body.cc = (body.cc || '').trim();
          body.bcc = (body.bcc || '').trim();
          const call = prefill.id
            ? api(`/mail/${prefill.id}`, { method: 'PUT', body: { to_addr: body.to, cc_addr: body.cc, bcc_addr: body.bcc, subject: body.subject, body_text: body.body } })
            : api('/mail/drafts', { method: 'POST', body });
          call.then(async (r) => {
            const id = prefill.id || r.id;
            toast('Draft saved.', 'success');
            if (value === 'approval') {
              try {
                const a = await api(`/mail/${id}/request-approval`, { method: 'POST' });
                toast(a.message || 'Approval requested.', 'success');
              } catch (err) { /* toasted */ }
            }
            loadStatus(); loadFolder(state.folder === 'sent' ? 'drafts' : state.folder);
            openMessage(id);
          }).catch(() => {});
          return true;
        }
        return true;
      },
    });
  }

  el('#mail-compose').addEventListener('click', () => compose());
  el('#mail-folders').addEventListener('click', (e) => {
    const b = e.target.closest('[data-folder]');
    if (b) loadFolder(b.getAttribute('data-folder'));
  });
  el('#mail-list').addEventListener('click', (e) => {
    const item = e.target.closest('[data-mid]');
    if (item) openMessage(Number(item.getAttribute('data-mid')));
  });

  el('#mail-view').addEventListener('click', async (e) => {
    const send = e.target.closest('[data-send]');
    if (send) {
      if (!await confirmDialog({
        title: 'Approve and send this email?',
        message: 'The message will be sent through the configured provider immediately. This action is recorded.',
        detail: 'If an approval is already pending, it is approved now. Otherwise one is created and approved by this click.',
        confirmText: 'Approve & send',
      })) return;
      try {
        const r = await api(`/mail/${send.getAttribute('data-send')}/send?confirm=true`, { method: 'POST' });
        toast(r.message || 'Email sent.', r.status === 'failed' ? 'error' : 'success');
        loadStatus(); loadFolder(state.folder);
        if (r.status === 'sent') openMessage(Number(send.getAttribute('data-send')));
      } catch (err) { /* toasted */ }
      return;
    }
    const edit = e.target.closest('[data-edit]');
    if (edit) { const d = await api('/mail/' + edit.getAttribute('data-edit')); compose({ ...d, id: d.id }); return; }
    const del = e.target.closest('[data-delete]');
    if (del) {
      if (!await confirmDialog({ title: 'Delete this draft?', message: 'The draft is removed. Sent mail cannot be deleted here.', confirmText: 'Delete', danger: true })) return;
      await api(`/mail/${del.getAttribute('data-delete')}`, { method: 'DELETE' });
      toast('Draft deleted.', 'success'); loadStatus(); loadFolder(state.folder);
      return;
    }
    const schedule = e.target.closest('[data-schedule]');
    if (schedule) {
      await modal({
        title: 'Schedule this email',
        body: `<form id="sched-form">${field('when', 'Send at', { type: 'datetime-local', required: true })}
          <p class="small muted" style="margin:8px 0 0">A running scheduler process sends it when due. Configure
          scripts/run_scheduler.py or the in-app scheduler.</p></form>`,
        footer: `<button class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-accent" data-result="save">Schedule</button>`,
        onResult: (v, root) => {
          if (v !== 'save') return true;
          const when = formValues(el('#sched-form', root)).when;
          if (!when) { toast('Choose a date and time.', 'error'); return false; }
          api(`/mail/${schedule.getAttribute('data-schedule')}/schedule`, { method: 'POST', body: { when: new Date(when).toISOString() } })
            .then((r) => { toast(r.message || 'Scheduled.', 'success'); loadStatus(); loadFolder('scheduled'); }).catch(() => {});
          return true;
        },
      });
      return;
    }
    const follow = e.target.closest('[data-followup]');
    if (follow) {
      const d = state.messages.find((m) => m.id === Number(follow.getAttribute('data-followup'))) || await api('/mail/' + follow.getAttribute('data-followup'));
      compose({ to: d.to, subject: d.subject.startsWith('Re:') ? d.subject : 'Re: ' + d.subject, body: `\n\n---\n${d.body || ''}` });
    }
  });

  el('#mail-test').addEventListener('click', async () => {
    try {
      const r = await api('/mail/test-connection', { method: 'POST' });
      toast(r.message, r.ok ? 'success' : 'warn');
    } catch (err) { /* toasted */ }
  });

  BB.ready().then(() => {
    if (!can('mail.send')) toast('Your role can read mail but not send it.', 'warn');
    loadStatus().then(() => loadFolder('drafts'));
  });
})();
