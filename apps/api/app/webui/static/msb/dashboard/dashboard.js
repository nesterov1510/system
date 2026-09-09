(() => {
  'use strict';

  const root = document.querySelector('[data-finance-chart]');
  const dataNode = document.getElementById('dashboardFinanceData');
  if (!root || !dataNode) return;

  const endpoint = root.dataset.financeEndpoint;
  const plot = root.querySelector('[data-finance-plot]');
  const profitLine = root.querySelector('[data-profit-line]');
  const expenseLine = root.querySelector('[data-expense-line]');
  const profitArea = root.querySelector('[data-profit-area]');
  const highlight = root.querySelector('[data-finance-highlight]');
  const profitPoint = root.querySelector('[data-profit-point]');
  const expensePoint = root.querySelector('[data-expense-point]');
  const tooltip = root.querySelector('[data-finance-tooltip]');
  const tooltipDate = root.querySelector('[data-tooltip-date]');
  const tooltipProfit = root.querySelector('[data-tooltip-profit]');
  const tooltipExpense = root.querySelector('[data-tooltip-expense]');
  const xAxis = root.querySelector('[data-finance-x-axis]');
  const yAxis = root.querySelector('[data-finance-y-axis]');
  const caption = root.querySelector('[data-finance-caption]');
  const status = root.querySelector('[data-finance-status]');
  const periodRoot = root.querySelector('[data-finance-period]');
  const periodTrigger = root.querySelector('[data-finance-period-trigger]');
  const periodMenu = root.querySelector('[data-finance-period-menu]');
  const periodLabel = root.querySelector('[data-finance-period-label]');
  const customPanel = root.querySelector('[data-finance-custom]');
  const dateFrom = root.querySelector('[data-finance-date-from]');
  const dateTo = root.querySelector('[data-finance-date-to]');

  let currentData = {};
  let labels = [];
  let tooltipLabels = [];
  let turnover = [];
  let profit = [];
  let expenses = [];
  let count = 0;
  let currency = 'TMT';
  let maxValue = 100;

  const WIDTH = 1000;
  const HEIGHT = 320;
  const PAD_TOP = 15;
  const PAD_BOTTOM = 16;
  const usableHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;

  const formatMoney = value => `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Number(value) || 0)} ${currency}`;

  const niceMax = raw => {
    if (!Number.isFinite(raw) || raw <= 0) return 100;
    const padded = raw * 1.08;
    const exponent = Math.floor(Math.log10(padded));
    const magnitude = 10 ** exponent;
    const normalized = padded / magnitude;
    const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return nice * magnitude;
  };

  const xFor = index => count <= 1 ? WIDTH / 2 : (index / (count - 1)) * WIDTH;
  const yFor = value => PAD_TOP + usableHeight - ((Math.max(0, Number(value) || 0) / maxValue) * usableHeight);

  const pointsToPath = values => values.slice(0, count)
    .map((value, index) => `${index === 0 ? 'M' : 'L'} ${xFor(index).toFixed(2)} ${yFor(value).toFixed(2)}`)
    .join(' ');

  const axisMoney = value => new Intl.NumberFormat('ru-RU', {
    notation: value >= 10000 ? 'compact' : 'standard',
    maximumFractionDigits: value >= 1000 ? 1 : 0,
  }).format(value);

  const makeTickIndexes = total => {
    if (total <= 1) return [0];
    const desired = window.innerWidth < 600 ? 3 : 5;
    if (total <= desired) return [...Array(total).keys()];
    return [...new Set(Array.from({ length: desired }, (_, i) => Math.round((total - 1) * (i / (desired - 1)))))];
  };

  const hideHover = () => {
    highlight.style.visibility = 'hidden';
    profitPoint.style.visibility = 'hidden';
    expensePoint.style.visibility = 'hidden';
    tooltip.classList.remove('is-visible');
  };

  const render = data => {
    currentData = data || {};
    labels = Array.isArray(data.labels) ? data.labels : [];
    tooltipLabels = Array.isArray(data.tooltip_labels) && data.tooltip_labels.length ? data.tooltip_labels : labels;
    profit = Array.isArray(data.profit) ? data.profit.map(Number) : [];
    expenses = Array.isArray(data.expenses) ? data.expenses.map(Number) : [];
    turnover = Array.isArray(data.turnover)
      ? data.turnover.map(Number)
      : profit.map((value, index) => (Number(value) || 0) + (Number(expenses[index]) || 0));
    count = Math.min(labels.length, turnover.length, profit.length, expenses.length);
    currency = data.currency || 'TMT';

    if (!count) {
      profitLine.setAttribute('d', '');
      expenseLine.setAttribute('d', '');
      profitArea.setAttribute('d', '');
      return;
    }

    const turnoverTotal = turnover.slice(0, count).reduce((sum, value) => sum + (Number(value) || 0), 0);
    const profitTotal = profit.slice(0, count).reduce((sum, value) => sum + (Number(value) || 0), 0);
    const expenseTotal = expenses.slice(0, count).reduce((sum, value) => sum + (Number(value) || 0), 0);
    root.querySelector('[data-finance-turnover-total]').textContent = formatMoney(turnoverTotal);
    root.querySelector('[data-finance-profit-total]').textContent = formatMoney(profitTotal);
    root.querySelector('[data-finance-expense-total]').textContent = formatMoney(expenseTotal);

    maxValue = niceMax(Math.max(...profit.slice(0, count), ...expenses.slice(0, count), 0));
    const profitPath = pointsToPath(profit);
    const expensePath = pointsToPath(expenses);
    profitLine.setAttribute('d', profitPath);
    expenseLine.setAttribute('d', expensePath);
    profitArea.setAttribute('d', `${profitPath} L ${xFor(count - 1)} ${HEIGHT} L ${xFor(0)} ${HEIGHT} Z`);

    yAxis.replaceChildren();
    for (let i = 4; i >= 0; i -= 1) {
      const span = document.createElement('span');
      span.textContent = axisMoney((maxValue / 4) * i);
      yAxis.appendChild(span);
    }

    xAxis.replaceChildren();
    makeTickIndexes(count).forEach(index => {
      const span = document.createElement('span');
      span.textContent = labels[index] || '';
      span.style.left = `${count <= 1 ? 50 : (index / (count - 1)) * 100}%`;
      xAxis.appendChild(span);
    });

    if (caption) caption.textContent = data.caption || '';
    if (periodLabel) periodLabel.textContent = data.period_label || 'Период';
    if (dateFrom && data.date_from) dateFrom.value = data.date_from;
    if (dateTo && data.date_to) dateTo.value = data.date_to;

    root.querySelectorAll('[data-period-value]').forEach(button => {
      const active = button.dataset.periodValue === data.period;
      button.classList.toggle('is-active', active);
      let mark = button.querySelector('.finance-period__check');
      const legacyMark = [...button.children].find(node => node.tagName === 'SPAN' && node.textContent.trim() === '✓');
      if (legacyMark) legacyMark.remove();
      if (active && data.period !== 'custom') {
        mark = document.createElement('span');
        mark.className = 'finance-period__check';
        mark.textContent = '✓';
        button.appendChild(mark);
      } else if (mark) {
        mark.remove();
      }
    });

    hideHover();
  };

  const showIndex = index => {
    if (!count) return;
    const rect = plot.getBoundingClientRect();
    const ratio = count <= 1 ? .5 : index / (count - 1);
    const x = ratio * rect.width;
    const profitY = (yFor(profit[index]) / HEIGHT) * rect.height;
    const expenseY = (yFor(expenses[index]) / HEIGHT) * rect.height;

    highlight.style.left = `${x}px`;
    highlight.style.visibility = 'visible';
    profitPoint.style.left = `${x}px`;
    profitPoint.style.top = `${profitY}px`;
    profitPoint.style.visibility = 'visible';
    expensePoint.style.left = `${x}px`;
    expensePoint.style.top = `${expenseY}px`;
    expensePoint.style.visibility = 'visible';

    tooltipDate.textContent = tooltipLabels[index] || labels[index] || '—';
    tooltipProfit.textContent = formatMoney(profit[index]);
    tooltipExpense.textContent = formatMoney(expenses[index]);

    tooltip.classList.add('is-visible');
    const tooltipWidth = tooltip.offsetWidth || 170;
    let tooltipLeft = x + 12;
    if (tooltipLeft + tooltipWidth > rect.width - 8) tooltipLeft = x - tooltipWidth - 12;
    tooltip.style.left = `${Math.max(8, tooltipLeft)}px`;
    tooltip.style.top = `${Math.max(8, Math.min(profitY, expenseY) - 12)}px`;
  };

  const indexFromPointer = clientX => {
    const rect = plot.getBoundingClientRect();
    const localX = Math.max(0, Math.min(rect.width, clientX - rect.left));
    if (count <= 1) return 0;
    return Math.max(0, Math.min(count - 1, Math.round((localX / rect.width) * (count - 1))));
  };

  const setLoading = loading => {
    root.classList.toggle('is-loading', loading);
    if (status) {
      status.hidden = !loading;
      status.textContent = loading ? 'Обновляем финансовый график…' : '';
    }
  };

  const closeMenu = () => {
    if (!periodMenu) return;
    periodMenu.hidden = true;
    periodTrigger?.setAttribute('aria-expanded', 'false');
    customPanel.hidden = true;
  };

  const loadPeriod = async (period, from = '', to = '') => {
    if (!endpoint) return;
    const url = new URL(endpoint, window.location.origin);
    url.searchParams.set('period', period);
    if (from) url.searchParams.set('date_from', from);
    if (to) url.searchParams.set('date_to', to);

    setLoading(true);
    try {
      const response = await fetch(url, { headers: { Accept: 'application/json' } });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw new Error(payload.error || 'Не удалось загрузить данные.');
      render(payload);
      closeMenu();
    } catch (error) {
      if (status) {
        status.hidden = false;
        status.textContent = error.message || 'Ошибка загрузки финансовых данных.';
        status.classList.add('is-error');
        window.setTimeout(() => {
          status.hidden = true;
          status.classList.remove('is-error');
        }, 3500);
      }
    } finally {
      setLoading(false);
    }
  };

  try {
    render(JSON.parse(dataNode.textContent || '{}'));
  } catch (error) {
    console.error('MSB dashboard: finance data JSON invalid', error);
  }

  plot.addEventListener('pointermove', event => showIndex(indexFromPointer(event.clientX)));
  plot.addEventListener('pointerenter', event => showIndex(indexFromPointer(event.clientX)));
  plot.addEventListener('pointerleave', hideHover);
  plot.addEventListener('pointercancel', hideHover);

  periodTrigger?.addEventListener('click', event => {
    event.stopPropagation();
    const willOpen = periodMenu.hidden;
    periodMenu.hidden = !willOpen;
    periodTrigger.setAttribute('aria-expanded', String(willOpen));
    if (!willOpen) customPanel.hidden = true;
  });

  periodMenu?.addEventListener('click', event => {
    const button = event.target.closest('[data-period-value]');
    if (!button) return;
    const value = button.dataset.periodValue;
    if (value === 'custom') {
      customPanel.hidden = false;
      return;
    }
    loadPeriod(value);
  });

  root.querySelector('[data-custom-period-back]')?.addEventListener('click', event => {
    event.stopPropagation();
    customPanel.hidden = true;
  });

  root.querySelector('[data-custom-period-apply]')?.addEventListener('click', event => {
    event.stopPropagation();
    if (!dateFrom.value || !dateTo.value) return;
    loadPeriod('custom', dateFrom.value, dateTo.value);
  });

  document.addEventListener('click', event => {
    if (periodRoot && !periodRoot.contains(event.target)) closeMenu();
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeMenu();
  });

  window.addEventListener('resize', () => render(currentData));
})();
