/* Profile: account details, password change and session information. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, badge, toast, icons, modal, dateFmt, confirm: confirmDialog } = BB;

  function fill() {
    const me = BB.me || {};
    el('#prof-name').value = me.name || '';
    el('#prof-email').value = me.email || '';
    el('#prof-notify').checked = !!me.notify_email;
    el('#profile-role').innerHTML = `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <span class="badge info">${esc(me.role_label || me.role || '')}</span>
        <span class="small muted">${esc(me.email || '')}</span></div>
      <div class="label" style="margin-top:12px">Capabilities</div>
      <div class="pill-row" style="margin-top:4px">${(me.capabilities || []).map((c) =>
        `<span class="badge">${esc(BB.humanize(c))}</span>`).join('') || '<span class="small muted">None</span>'}</div>
      <p class="small muted" style="margin:10px 0 0">Permissions are enforced on the server for every request, not only in the interface.</p>`;
    icons(el('#profile-role'));
  }

  async function loadSession() {
    try {
      const s = await api('/auth/session', { silent: true });
      el('#profile-session').innerHTML = `Signed in as <strong>${esc(BB.me ? BB.me.email : '')}</strong>
        (${esc(s.role_label || '')}). ${s.expires_at ? 'Session expires ' + dateFmt(s.expires_at, true) + '.' : 'Session expires when the browser closes.'}
        ${s.remember ? 'Remember-me is enabled.' : ''}`;
    } catch (err) { /* ignore */ }
  }

  el('#profile-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {
      name: el('#prof-name').value.trim(),
      email: el('#prof-email').value.trim(),
      notify_email: el('#prof-notify').checked,
    };
    try {
      const me = await api('/auth/profile', { method: 'PUT', body });
      BB.me = { ...BB.me, ...me };
      const nameEl = el('#user-name'); if (nameEl) nameEl.textContent = me.name;
      toast('Profile updated.', 'success');
    } catch (err) { /* toasted */ }
  });

  els('[data-toggle-pw]').forEach((b) => b.addEventListener('click', () => {
    const input = document.getElementById(b.getAttribute('data-toggle-pw'));
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    b.textContent = show ? 'Hide' : 'Show';
  }));

  function score(v) {
    let s = 0;
    if (v.length >= 8) s++;
    if (v.length >= 12) s++;
    if (/[A-Z]/.test(v) && /[a-z]/.test(v)) s++;
    if (/\d/.test(v)) s++;
    if (/[^A-Za-z0-9]/.test(v)) s++;
    return Math.min(4, s);
  }
  el('#pw-new').addEventListener('input', () => {
    const s = score(el('#pw-new').value);
    els('#pw-meter i').forEach((bar, i) => {
      bar.className = i < s ? 'on' + (s <= 2 ? ' bad' : s === 3 ? ' warn' : '') : '';
    });
  });

  el('#password-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const current = el('#pw-current').value, next = el('#pw-new').value, confirm = el('#pw-confirm').value;
    if (next !== confirm) return toast('The new passwords do not match.', 'error');
    if (next.length < 8) return toast('Use at least 8 characters.', 'error');
    try {
      await api('/auth/password', { method: 'POST', body: { current_password: current, new_password: next } });
      el('#password-form').reset();
      els('#pw-meter i').forEach((b) => { b.className = ''; });
      toast('Password updated.', 'success');
    } catch (err) { /* toasted */ }
  });

  el('#profile-logout').addEventListener('click', async () => {
    if (!await confirmDialog({ title: 'Sign out?', message: 'Your session ends on this device. Saved work is not affected.', confirmText: 'Sign out', danger: true })) return;
    await api('/auth/logout', { method: 'POST' });
    location.href = '/login';
  });

  BB.ready().then(() => { fill(); loadSession(); });
})();
