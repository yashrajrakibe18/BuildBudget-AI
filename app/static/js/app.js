/* Application shell: theme, sidebar, project switcher, global search,
   notification bell, profile menu and logout confirmation. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, toast, icons, modal, timeAgo } = BB;

  /* ---------------------------------------------------------------- theme */
  const THEME_LABELS = { light: 'Light', dark: 'Dark', system: 'System' };
  function applyTheme(pref) {
    const dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const resolved = pref === 'system' ? (dark ? 'dark' : 'light') : pref;
    document.documentElement.setAttribute('data-theme', resolved);
    document.documentElement.setAttribute('data-theme-pref', pref);
    document.documentElement.style.colorScheme = resolved;
    try { localStorage.setItem('bb-theme', pref); } catch (e) { /* private mode */ }
    els('[data-theme-choice]').forEach((b) => {
      b.classList.toggle('on', b.getAttribute('data-theme-choice') === pref);
    });
    if (window.BB.refreshCharts) window.BB.refreshCharts();
  }
  function currentThemePref() {
    try { return localStorage.getItem('bb-theme') || 'system'; } catch (e) { return 'system'; }
  }
  applyTheme(currentThemePref());
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (currentThemePref() === 'system') applyTheme('system');
    });
  }
  // Persist the choice to the user profile when signed in (best effort).
  function persistTheme(pref) {
    applyTheme(pref);
    const labels = { light: 'light', dark: 'dark', system: 'system' };
    if (BB.me) api('/auth/profile', { method: 'PUT', body: { theme: labels[pref] }, silent: true }).catch(() => {});
  }

  /* ---------------------------------------------------------------- sidebar */
  const shell = el('.shell');
  if (shell) {
    const stored = localStorage.getItem('bb-sidebar') === 'collapsed';
    if (stored && window.innerWidth > 900) shell.setAttribute('data-collapsed', 'true');
    const toggle = el('#sidebar-toggle');
    if (toggle) {
      toggle.addEventListener('click', () => {
        if (window.innerWidth <= 900) {
          const open = shell.getAttribute('data-mobile-open') !== 'true';
          shell.setAttribute('data-mobile-open', String(open));
          let scrim = el('.scrim');
          if (open && !scrim) {
            scrim = document.createElement('div');
            scrim.className = 'scrim';
            scrim.addEventListener('click', () => {
              shell.setAttribute('data-mobile-open', 'false');
              scrim.remove();
            });
            document.body.appendChild(scrim);
          } else if (!open && scrim) scrim.remove();
        } else {
          const collapsed = shell.getAttribute('data-collapsed') === 'true';
          shell.setAttribute('data-collapsed', String(!collapsed));
          localStorage.setItem('bb-sidebar', collapsed ? 'expanded' : 'collapsed');
        }
      });
    }
    els('.nav-link').forEach((a) => a.addEventListener('click', () => {
      if (window.innerWidth <= 900) {
        shell.setAttribute('data-mobile-open', 'false');
        const scrim = el('.scrim'); if (scrim) scrim.remove();
      }
    }));
  }

  /* ---------------------------------------------------------------- dropdown menus */
  function closeMenus(except) {
    els('.menu').forEach((menu) => {
      if (menu !== except) menu.remove();
    });
  }
  document.addEventListener('click', (e) => {
    if (!e.target.closest('[data-menu-trigger]') && !e.target.closest('.menu')) closeMenus();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenus(); });

  function toggleMenu(trigger, builder) {
    const existing = trigger.parentElement.querySelector('.menu');
    closeMenus(existing);
    if (existing) { existing.remove(); return; }
    const menu = document.createElement('div');
    menu.className = 'menu';
    menu.innerHTML = builder();
    trigger.parentElement.appendChild(menu);
    icons(menu);
    menu.addEventListener('click', async (e) => {
      const themeChoice = e.target.closest('[data-theme-choice]');
      if (themeChoice) { persistTheme(themeChoice.getAttribute('data-theme-choice')); closeMenus(); }
      const action = e.target.closest('[data-menu-action]');
      if (action) {
        const name = action.getAttribute('data-menu-action');
        closeMenus();
        if (name === 'logout') return confirmLogout();
      }
    });
  }

  const themeBtn = el('#theme-menu');
  if (themeBtn) {
    themeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const pref = currentThemePref();
      toggleMenu(themeBtn, () => `<div class="menu-head small muted">Appearance</div>
        ${Object.keys(THEME_LABELS).map((k) => `<button data-theme-choice="${k}" class="${pref === k ? 'on' : ''}">
          <i data-lucide="${k === 'light' ? 'sun' : k === 'dark' ? 'moon' : 'monitor'}" class="ico"></i>
          ${THEME_LABELS[k]}${pref === k ? ' <span style="margin-left:auto">✓</span>' : ''}</button>`).join('')}`);
    });
  }

  const profileBtn = el('#profile-menu');
  if (profileBtn) {
    profileBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const me = BB.me || {};
      toggleMenu(profileBtn, () => `<div class="menu-head">
          <div style="font-weight:600">${esc(me.name || 'Signed in')}</div>
          <div class="small muted">${esc(me.email || '')}</div>
          <div class="small muted">${esc(me.role_label || '')}</div>
        </div>
        <a class="menu-item" href="/profile"><i data-lucide="user" class="ico"></i> Profile</a>
        <a class="menu-item" href="/settings"><i data-lucide="settings" class="ico"></i> Settings</a>
        <a class="menu-item" href="/activity"><i data-lucide="history" class="ico"></i> Activity logs</a>
        <div class="sep"></div>
        <button data-menu-action="logout"><i data-lucide="log-out" class="ico"></i> Sign out</button>`);
    });
  }

  function confirmLogout() {
    modal({
      title: 'Sign out of BuildBudget AI?',
      body: '<p>Your session will end on this device. Saved work is not affected.</p>',
      footer: '<button class="btn btn-ghost" data-close>Stay signed in</button>' +
              '<button class="btn btn-danger" data-result="yes">Sign out</button>',
    }).then(async (result) => {
      if (result !== 'yes') return;
      try { await api('/auth/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
      location.href = '/login';
    });
  }

  /* ---------------------------------------------------------------- project switcher */
  const switcher = el('#project-switcher');
  if (switcher) {
    switcher.addEventListener('change', () => {
      const id = switcher.value;
      localStorage.setItem('bb-project', id || '');
      const page = document.body.getAttribute('data-page');
      if (page === 'assistant') {
        document.dispatchEvent(new CustomEvent('bb:project-change', { detail: id ? Number(id) : null }));
      } else if (id) {
        location.href = `/projects/${id}`;
      }
    });
  }

  /* ---------------------------------------------------------------- global search */
  const search = el('#global-search');
  if (search) {
    let timer = null, box = null;
    const close = () => { if (box) { box.remove(); box = null; } };
    search.addEventListener('input', () => {
      clearTimeout(timer);
      const q = search.value.trim();
      if (q.length < 2) { close(); return; }
      timer = setTimeout(async () => {
        try {
          const r = await api('/search?q=' + encodeURIComponent(q), { silent: true });
          close();
          box = document.createElement('div');
          box.className = 'search-results';
          const groups = [
            ['Projects', r.projects, (p) => `/projects/${p.id}`],
            ['Suppliers', r.suppliers, () => '/suppliers'],
            ['Documents', r.documents, () => '/knowledge'],
            ['Materials', r.materials, () => '/suppliers'],
          ];
          let html = '';
          groups.forEach(([title, rows, href]) => {
            if (!rows || !rows.length) return;
            html += `<div class="group-title">${title}</div>`;
            html += rows.map((row) => `<a href="${href(row)}">${esc(row.name || (row.name + ' · ' + row.category))}</a>`).join('');
          });
          box.innerHTML = html || '<div class="group-title">No matches</div>';
          search.parentElement.appendChild(box);
        } catch (e) { /* ignore */ }
      }, 220);
    });
    search.addEventListener('blur', () => setTimeout(close, 180));
    search.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { search.value = ''; close(); search.blur(); }
      if (e.key === 'Enter' && box) {
        const first = box.querySelector('a');
        if (first) first.click();
      }
    });
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); search.focus();
      }
    });
  }

  /* ---------------------------------------------------------------- notifications */
  const bell = el('#bell');
  if (bell) {
    const dot = el('#bell-count');
    async function refreshCount() {
      try {
        const r = await api('/notifications?unread_only=true', { silent: true });
        const count = r.unread || 0;
        if (dot) {
          dot.textContent = count > 99 ? '99+' : String(count);
          dot.classList.toggle('hidden', count === 0);
        }
        BB.unread = count;
        document.dispatchEvent(new CustomEvent('bb:unread', { detail: count }));
      } catch (e) { /* ignore */ }
    }
    refreshCount();
    setInterval(refreshCount, 60000);
    bell.addEventListener('click', async (e) => {
      e.stopPropagation();
      let items = [];
      try { items = (await api('/notifications?unread_only=true', { silent: true })).items.slice(0, 6); }
      catch (err) { /* ignore */ }
      const menu = document.createElement('div');
      menu.className = 'menu';
      menu.style.minWidth = '320px';
      menu.innerHTML = `<div class="menu-head small muted">Notifications</div>` + (items.length ? items.map((n) => `
        <a class="menu-item" href="${esc(n.link || '/notifications')}">
          <span class="status-dot ${n.status === 'failed' ? 'error' : 'ok'}"></span>
          <span style="min-width:0"><span style="display:block;font-weight:600;font-size:12.5px">${esc(n.subject)}</span>
          <span class="small muted">${esc(timeAgo(n.created_at))}</span></span>
        </a>`).join('') : '<div style="padding:10px" class="small muted">You are all caught up.</div>')
        + `<div class="sep"></div><a class="menu-item" href="/notifications"><i data-lucide="bell" class="ico"></i> Open notification centre</a>`;
      const existing = bell.parentElement.querySelector('.menu');
      closeMenus(existing);
      if (existing) return;
      bell.parentElement.appendChild(menu);
      icons(menu);
    });
  }

  /* ---------------------------------------------------------------- bootstrap */
  BB.ready().then(() => {
    if (BB.me) {
      const nameEl = el('#user-name');
      if (nameEl) nameEl.textContent = BB.me.name || BB.me.email;
      const roleEl = el('#user-role');
      if (roleEl) roleEl.textContent = BB.me.role_label || '';
      const initials = (BB.me.name || BB.me.email || '?').split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase();
      els('.avatar').forEach((a) => { if (!a.textContent.trim()) a.textContent = initials; });
    }
    icons(document);
  });
})();
