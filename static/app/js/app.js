// static/app/js/app.js — chrome interativo do base.html

(function () {
  'use strict';

  // --- Sidebar collapse ---
  const sbToggle = document.getElementById('sbToggle');
  const appRoot  = document.getElementById('app');
  if (sbToggle && appRoot) {
    sbToggle.addEventListener('click', () => appRoot.classList.toggle('sb-collapsed'));
  }

  // --- Toast legado: window.toast(msg) ---
  // A versão colorida (window.lprToast) é definida no inline script do base.html.
  // Este shim garante que código antigo que chame window.toast() continue funcionando
  // mesmo antes do inline script rodar (improvável, mas seguro).
  if (!window.toast) {
    const toastEl  = document.getElementById('toast');
    const toastMsg = document.getElementById('toastMsg');
    let toastTimer;
    window.toast = function (msg, duration) {
      duration = duration || 2200;
      if (!toastEl) return;
      toastMsg.textContent = msg;
      toastEl.classList.remove('opacity-0', 'translate-y-2');
      toastEl.classList.add('opacity-100', 'translate-y-0');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function () {
        toastEl.classList.add('opacity-0', 'translate-y-2');
        toastEl.classList.remove('opacity-100', 'translate-y-0');
      }, duration);
    };
  }

  // --- ⌘K / Ctrl+K → foco na busca de placa ---
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const search = document.getElementById('plateSearch');
      if (search) search.focus();
    }
  });

  // Nota: o ticker ao vivo agora é gerenciado pelo LPRLive (inline script em
  // base.html) que o atualiza via polling. startTickerAnim() é chamado lá.

})();
