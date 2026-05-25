// static/js/app.js — chrome interativo do _base.html

(function () {
  // Sidebar collapse
  const sbToggle = document.getElementById('sbToggle');
  const app = document.getElementById('app');
  if (sbToggle && app) {
    sbToggle.addEventListener('click', () => app.classList.toggle('sb-collapsed'));
  }

  // Toast utilitário, exposto em window.toast(msg)
  const toastEl = document.getElementById('toast');
  const toastMsg = document.getElementById('toastMsg');
  let toastT;
  window.toast = function (msg) {
    if (!toastEl) return;
    toastMsg.textContent = msg;
    toastEl.classList.remove('opacity-0','translate-y-2');
    toastEl.classList.add('opacity-100','translate-y-0');
    clearTimeout(toastT);
    toastT = setTimeout(() => {
      toastEl.classList.add('opacity-0','translate-y-2');
      toastEl.classList.remove('opacity-100','translate-y-0');
    }, 2200);
  };

  // ⌘K / Ctrl+K — foco no busca de placa
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const s = document.getElementById('plateSearch');
      if (s) s.focus();
    }
  });

  // Live ticker (loop suave)
  const ticker = document.getElementById('ticker');
  if (ticker) {
    ticker.innerHTML += ticker.innerHTML; // duplica para loop
    let x = 0;
    function tick() {
      x -= 0.35;
      if (Math.abs(x) > ticker.scrollWidth / 2) x = 0;
      ticker.style.transform = `translateX(${x}px)`;
      requestAnimationFrame(tick);
    }
    tick();
  }
})();
