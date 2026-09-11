(() => {
  'use strict';

  document.addEventListener('DOMContentLoaded', () => {
    const drawer = document.getElementById('msbSidebar');
    const backdrop = document.querySelector('[data-sidebar-backdrop]');
    const openButtons = Array.from(document.querySelectorAll('[data-sidebar-open]'));
    const closeButtons = Array.from(document.querySelectorAll('[data-sidebar-close]'));

    if (!drawer || !backdrop || !openButtons.length) return;

    let lastFocused = null;
    let backdropTimer = null;

    const setExpanded = (value) => {
      openButtons.forEach((button) => button.setAttribute('aria-expanded', value ? 'true' : 'false'));
    };

    const openSidebar = () => {
      if (drawer.classList.contains('is-open')) return;
      if (backdropTimer) window.clearTimeout(backdropTimer);

      lastFocused = document.activeElement;
      backdrop.hidden = false;
      requestAnimationFrame(() => backdrop.classList.add('is-visible'));
      drawer.classList.add('is-open');
      drawer.setAttribute('aria-hidden', 'false');
      document.body.classList.add('sidebar-open');
      setExpanded(true);

      const firstTarget = drawer.querySelector('[data-sidebar-close]');
      if (firstTarget) firstTarget.focus({ preventScroll: true });
    };

    const closeSidebar = ({ restoreFocus = true } = {}) => {
      if (!drawer.classList.contains('is-open')) return;

      drawer.classList.remove('is-open');
      drawer.setAttribute('aria-hidden', 'true');
      backdrop.classList.remove('is-visible');
      document.body.classList.remove('sidebar-open');
      setExpanded(false);

      backdropTimer = window.setTimeout(() => {
        backdrop.hidden = true;
      }, 230);

      if (restoreFocus && lastFocused && typeof lastFocused.focus === 'function') {
        lastFocused.focus({ preventScroll: true });
      }
    };

    openButtons.forEach((button) => button.addEventListener('click', openSidebar));
    closeButtons.forEach((button) => button.addEventListener('click', () => closeSidebar()));
    backdrop.addEventListener('click', () => closeSidebar());

    drawer.querySelectorAll('[data-nav-link]').forEach((link) => {
      link.addEventListener('click', () => closeSidebar({ restoreFocus: false }));
    });

    const projectInfo = document.querySelector('[data-project-info]');
    const projectInfoOpenButtons = Array.from(document.querySelectorAll('[data-project-info-open]'));
    const projectInfoCloseButtons = Array.from(document.querySelectorAll('[data-project-info-close]'));
    let projectInfoTimer = null;

    const setProjectInfoExpanded = (value) => {
      projectInfoOpenButtons.forEach((button) => button.setAttribute('aria-expanded', value ? 'true' : 'false'));
    };

    const openProjectInfo = () => {
      if (!projectInfo) return;
      if (projectInfoTimer) window.clearTimeout(projectInfoTimer);
      projectInfo.hidden = false;
      projectInfo.setAttribute('aria-hidden', 'false');
      requestAnimationFrame(() => projectInfo.classList.add('is-visible'));
      setProjectInfoExpanded(true);
    };

    const closeProjectInfo = () => {
      if (!projectInfo || projectInfo.hidden) return;
      projectInfo.classList.remove('is-visible');
      projectInfo.setAttribute('aria-hidden', 'true');
      setProjectInfoExpanded(false);
      projectInfoTimer = window.setTimeout(() => {
        projectInfo.hidden = true;
      }, 170);
    };

    projectInfoOpenButtons.forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        const shouldOpen = !projectInfo || projectInfo.hidden || !projectInfo.classList.contains('is-visible');
        if (shouldOpen) openProjectInfo();
        else closeProjectInfo();
      });
    });
    projectInfoCloseButtons.forEach((button) => button.addEventListener('click', closeProjectInfo));
    if (projectInfo) projectInfo.addEventListener('click', (event) => event.stopPropagation());
    document.addEventListener('click', closeProjectInfo);

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeProjectInfo();
        closeSidebar();
      }
    });

    // ---------- Кнопка-пояснение «?» у заголовков колонок таблиц ----------
    // Аналог components/ColumnHint.tsx из эталона: клик по «?» показывает
    // поповер с объяснением колонки. Поповер позиционируется через
    // position:fixed, чтобы не обрезался внутри .table-wrap (overflow-x-auto).
    const hintPop = document.createElement('div');
    hintPop.className = 'colhint-pop';
    hintPop.setAttribute('role', 'tooltip');
    hintPop.hidden = true;
    document.body.appendChild(hintPop);

    const openHint = (button) => {
      const title = button.getAttribute('data-title') || '';
      const hint = button.getAttribute('data-hint') || '';
      const details = button.getAttribute('data-details') || '';
      hintPop.innerHTML = '';
      const t = document.createElement('p');
      t.className = 'colhint-pop__title';
      t.textContent = title;
      hintPop.appendChild(t);
      const h = document.createElement('p');
      h.className = 'colhint-pop__hint';
      h.textContent = hint;
      hintPop.appendChild(h);
      if (details) {
        const d = document.createElement('p');
        d.className = 'colhint-pop__details';
        d.textContent = '· ' + details;
        hintPop.appendChild(d);
      }
      hintPop.hidden = false;
      const rect = button.getBoundingClientRect();
      const width = 270;
      const left = Math.max(8, Math.min(rect.left - width / 2 + rect.width / 2, window.innerWidth - width - 8));
      hintPop.style.left = left + 'px';
      hintPop.style.top = (rect.bottom + 8) + 'px';
    };
    const closeHint = () => { hintPop.hidden = true; };

    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-colhint]');
      if (button) {
        event.stopPropagation();
        event.preventDefault();
        openHint(button);
        return;
      }
      if (!hintPop.contains(event.target)) closeHint();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeHint();
    });
    window.addEventListener('scroll', closeHint, true);
    window.addEventListener('resize', closeHint);
  });
})();
