/* Authentication pages: login, registration, password reset. */
(function () {
  'use strict';
  const BB = window.BB;
  const { el, els, esc, api, toast, icons } = BB;

  function alertBox(message, kind) {
    const box = el('#auth-alert');
    if (!box) return;
    box.className = 'alert ' + (kind || 'error') + (message ? '' : ' hidden');
    box.textContent = message || '';
  }
  function busy(button, on, text) {
    if (!button) return;
    button.disabled = on;
    if (on) { button.dataset.label = button.textContent; button.textContent = text || 'Please wait…'; }
    else if (button.dataset.label) button.textContent = button.dataset.label;
  }

  els('[data-pw-toggle]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.getAttribute('data-pw-toggle'));
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Hide' : 'Show';
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    });
  });

  function scorePassword(value) {
    let score = 0;
    if (value.length >= 8) score++;
    if (value.length >= 12) score++;
    if (/[A-Z]/.test(value) && /[a-z]/.test(value)) score++;
    if (/\d/.test(value)) score++;
    if (/[^A-Za-z0-9]/.test(value)) score++;
    return Math.min(4, score);
  }
  const pw = el('#password');
  if (pw && el('#pw-meter')) {
    const bars = els('#pw-meter i');
    const hint = el('#pw-hint');
    pw.addEventListener('input', () => {
      const s = scorePassword(pw.value);
      bars.forEach((bar, i) => {
        bar.className = i < s ? 'on' + (s <= 2 ? ' bad' : s === 3 ? ' warn' : '') : '';
      });
      if (hint) {
        hint.textContent = !pw.value ? 'Use a mix of letters, numbers and a symbol.'
          : s <= 2 ? 'Weak — add length and a symbol.' : s === 3 ? 'Good, but longer is better.' : 'Strong password.';
      }
    });
  }

  const login = el('#login-form');
  if (login) {
    login.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = BB.formValues(login);
      if (!data.email || !data.password) return alertBox('Enter your email and password.');
      busy(el('#login-submit'), true, 'Signing in…');
      alertBox('');
      try {
        await api('/auth/login', { method: 'POST', body: data });
        location.href = '/dashboard';
      } catch (err) {
        alertBox(err.message || 'Sign-in failed.');
        busy(el('#login-submit'), false);
      }
    });
  }

  const register = el('#register-form');
  if (register) {
    register.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = BB.formValues(register);
      if (data.password !== data.confirm) return alertBox('The two passwords do not match.');
      if (data.password.length < 8) return alertBox('Use at least 8 characters for the password.');
      busy(el('#register-submit'), true, 'Creating account…');
      alertBox('');
      try {
        await api('/auth/register', {
          method: 'POST',
          body: { name: data.name, email: data.email, role: data.role, password: data.password, remember: !!data.remember },
        });
        location.href = '/dashboard';
      } catch (err) {
        alertBox(err.message || 'Could not create the account.');
        busy(el('#register-submit'), false);
      }
    });
  }

  const requestForm = el('#reset-request-form');
  if (requestForm) {
    requestForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = BB.formValues(requestForm);
      alertBox('');
      try {
        const r = await api('/auth/password-reset/request', { method: 'POST', body: { email: data.email } });
        alertBox(r.message || 'Request received.', 'ok');
        const box = el('#reset-link-box');
        if (r.dev_link && box) {
          box.classList.remove('hidden');
          box.innerHTML = `<strong>Development link</strong><br>` +
            `<a href="${esc(r.dev_link)}">${esc(r.dev_link)}</a>`;
        }
      } catch (err) { alertBox(err.message); }
    });
  }

  const confirmForm = el('#reset-confirm-form');
  if (confirmForm) {
    confirmForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = BB.formValues(confirmForm);
      if (data.password !== data.confirm) return alertBox('The two passwords do not match.');
      try {
        const r = await api('/auth/password-reset/confirm', {
          method: 'POST', body: { token: data.token, password: data.password },
        });
        alertBox(r.message || 'Password updated.', 'ok');
        setTimeout(() => { location.href = '/login'; }, 1400);
      } catch (err) { alertBox(err.message); }
    });
  }

  BB.ready().then(() => icons(document));
})();
