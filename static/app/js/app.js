// static/app/js/app.js — chrome interativo do base.html

(function () {
  'use strict';

  // --- Sidebar collapse ---
  const sbToggle = document.getElementById('sbToggle');
  const appRoot  = document.getElementById('app');
  if (sbToggle && appRoot) {
    sbToggle.addEventListener('click', () => appRoot.classList.toggle('sb-collapsed'));
  }

  // --- Toast utilitário: window.toast(msg, duration?) ---
  const toastEl  = document.getElementById('toast');
  const toastMsg = document.getElementById('toastMsg');
  let toastTimer;
  window.toast = function (msg, duration = 2200) {
    if (!toastEl) return;
    toastMsg.textContent = msg;
    toastEl.classList.remove('opacity-0', 'translate-y-2');
    toastEl.classList.add('opacity-100', 'translate-y-0');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toastEl.classList.add('opacity-0', 'translate-y-2');
      toastEl.classList.remove('opacity-100', 'translate-y-0');
    }, duration);
  };

  // --- ⌘K / Ctrl+K → foco na busca de placa ---
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const search = document.getElementById('plateSearch');
      if (search) search.focus();
    }
  });

  // --- Live ticker (loop contínuo) ---
  const ticker = document.getElementById('ticker');
  if (ticker && ticker.children.length > 0) {
    ticker.innerHTML += ticker.innerHTML; // duplica para loop suave
    let offsetX = 0;
    function animateTicker() {
      offsetX -= 0.35;
      const half = ticker.scrollWidth / 2;
      if (Math.abs(offsetX) >= half) offsetX = 0;
      ticker.style.transform = `translateX(${offsetX}px)`;
      requestAnimationFrame(animateTicker);
    }
    requestAnimationFrame(animateTicker);
  }
})();
