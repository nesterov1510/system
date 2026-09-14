// Конструктор страницы: админ переставляет блоки и колонки таблицы.
// Порядок сохраняется лично ему через POST /ui/layout (user_page_layouts).
//
// Блоки — прямые потомки [data-lay-root], порядок задаётся CSS `order`.
// Колонки — в таблицах `order` не работает, поэтому ячейки переставляются
// по-настоящему: заголовки в thead и все td с тем же data-col в каждой строке.
(() => {
  "use strict";
  const bar = document.querySelector("[data-lay-bar]");
  const root = document.querySelector("[data-lay-root]");
  if (!bar || !root) return;

  const table = document.getElementById("rlist-table");
  const onlyBlock = Array.from(bar.querySelectorAll("[data-lay-only]"));
  const onlyCol = Array.from(bar.querySelectorAll("[data-laycol-only]"));
  const formBlock = bar.querySelector("[data-lay-form]");
  const formCol = bar.querySelector("[data-laycol-form]");
  const editingBlocks = () => bar.classList.contains("is-editing-blocks");
  const editingCols = () => bar.classList.contains("is-editing-cols");

  const submit = (form, order) => {
    if (!form) return;
    form.elements.order.value = order.join(",");
    form.submit();
  };

  // ------------------------------------------------------------------ блоки
  const blocks = () => Array.from(root.querySelectorAll(":scope > [data-block]"));

  const applyBlockOrders = () => {
    blocks().forEach((el, i) => {
      el.style.order = String(i);
    });
  };

  const moveBlock = (el, dir) => {
    const list = blocks();
    const i = list.indexOf(el);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= list.length) return;
    if (dir < 0) root.insertBefore(el, list[j]);
    else root.insertBefore(list[j], el);
    applyBlockOrders();
  };

  const blockControl = (el) => {
    const ctl = document.createElement("div");
    ctl.className = "lay-ctl";
    ctl.setAttribute("data-lay-ctl", "");
    const title = document.createElement("span");
    title.className = "lay-ctl__t";
    title.textContent = el.dataset.blockTitle || el.dataset.block || "";
    const up = document.createElement("button");
    up.type = "button";
    up.className = "lay-btn";
    up.textContent = "↑";
    up.title = "Поднять блок";
    up.addEventListener("click", () => moveBlock(el, -1));
    const down = document.createElement("button");
    down.type = "button";
    down.className = "lay-btn";
    down.textContent = "↓";
    down.title = "Опустить блок";
    down.addEventListener("click", () => moveBlock(el, 1));
    ctl.append(title, up, down);
    return ctl;
  };

  const setBlockMode = (on) => {
    setColMode(false);
    bar.classList.toggle("is-editing-blocks", on);
    bar.classList.toggle("is-editing", on);
    root.classList.toggle("is-lay", on);
    onlyBlock.forEach((el) => {
      el.hidden = !on;
    });
    blocks().forEach((el) => {
      const old = el.querySelector(":scope > [data-lay-ctl]");
      if (old) old.remove();
      el.draggable = on;
      if (on) el.prepend(blockControl(el));
    });
    const btn = bar.querySelector("[data-lay-toggle]");
    if (btn) btn.textContent = on ? "✕ Закрыть конструктор" : "🧩 Блоки страницы";
  };

  bar.querySelector("[data-lay-toggle]")?.addEventListener("click", () => setBlockMode(!editingBlocks()));

  let dragBlock = null;
  root.addEventListener("dragstart", (e) => {
    if (!editingBlocks()) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (["input", "textarea", "select", "a", "button"].includes(tag)) return;
    const el = e.target.closest("[data-block]");
    if (!el || el.parentElement !== root) return;
    dragBlock = el;
    el.classList.add("is-dragging");
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
  });
  root.addEventListener("dragover", (e) => {
    if (!dragBlock) return;
    e.preventDefault();
    const target = e.target.closest("[data-block]");
    if (!target || target === dragBlock || target.parentElement !== root) return;
    const box = target.getBoundingClientRect();
    const after = e.clientY - box.top > box.height / 2;
    root.insertBefore(dragBlock, after ? target.nextSibling : target);
    applyBlockOrders();
  });
  root.addEventListener("dragend", () => {
    if (dragBlock) dragBlock.classList.remove("is-dragging");
    dragBlock = null;
    applyBlockOrders();
  });

  bar.querySelector("[data-lay-save]")?.addEventListener("click", () => {
    submit(formBlock, blocks().map((el) => el.dataset.block));
  });
  bar.querySelector("[data-lay-reset]")?.addEventListener("click", () => {
    submit(formBlock, (bar.dataset.default || "").split(",").filter(Boolean));
  });

  // ----------------------------------------------------------------- колонки
  if (!table) return;
  const headRow = () => (table.tHead && table.tHead.rows[0]) || null;
  const columnKeys = () => {
    const head = headRow();
    return head ? Array.from(head.cells).map((c) => c.dataset.col || "") : [];
  };

  // Переставить колонки: заголовки в thead + ячейки той же колонки в tbody.
  const applyColumns = (order) => {
    const head = headRow();
    if (!head || !order || !order.length) return;
    const byKey = new Map(Array.from(head.cells).map((c) => [c.dataset.col, c]));
    const known = order.filter((k) => byKey.has(k));
    const rest = columnKeys().filter((k) => !known.includes(k));
    const rows = Array.prototype.concat.apply(
      [],
      Array.from(table.tBodies).map((tb) => Array.from(tb.rows))
    );
    known.concat(rest).forEach((key) => {
      const th = byKey.get(key);
      if (!th) return;
      head.appendChild(th);
      rows.forEach((tr) => {
        const cell = tr.querySelector(':scope > [data-col="' + key + '"]');
        if (cell) tr.appendChild(cell);
      });
    });
  };

  // Порядок, который сохранил админ, приходит из разметки (data-col-order).
  applyColumns((table.dataset.colOrder || "").split(",").filter(Boolean));

  const moveColumn = (key, dir) => {
    const keys = columnKeys();
    const i = keys.indexOf(key);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= keys.length) return;
    keys.splice(i, 1);
    keys.splice(j, 0, key);
    applyColumns(keys);
  };

  const colControl = (th) => {
    const ctl = document.createElement("span");
    ctl.className = "lay-ctl lay-ctl--col";
    ctl.setAttribute("data-laycol-ctl", "");
    const left = document.createElement("button");
    left.type = "button";
    left.className = "lay-btn";
    left.textContent = "←";
    left.title = "Сдвинуть колонку влево";
    left.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      moveColumn(th.dataset.col, -1);
    });
    const right = document.createElement("button");
    right.type = "button";
    right.className = "lay-btn";
    right.textContent = "→";
    right.title = "Сдвинуть колонку вправо";
    right.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      moveColumn(th.dataset.col, 1);
    });
    ctl.append(left, right);
    return ctl;
  };

  function setColMode(on) {
    if (on) setBlockMode(false);
    bar.classList.toggle("is-editing-cols", on);
    bar.classList.toggle("is-editing", on);
    table.classList.toggle("is-lay-cols", on);
    onlyCol.forEach((el) => {
      el.hidden = !on;
    });
    const head = headRow();
    if (head) {
      Array.from(head.cells).forEach((th) => {
        const old = th.querySelector("[data-laycol-ctl]");
        if (old) old.remove();
        th.draggable = on;
        if (on) th.prepend(colControl(th));
      });
    }
    const btn = bar.querySelector("[data-laycol-toggle]");
    if (btn) btn.textContent = on ? "✕ Закрыть конструктор" : "🔀 Колонки таблицы";
  }

  bar.querySelector("[data-laycol-toggle]")?.addEventListener("click", () => setColMode(!editingCols()));

  let dragCol = null;
  table.addEventListener("dragstart", (e) => {
    if (!editingCols()) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (["input", "textarea", "select", "a", "button"].includes(tag)) return;
    const th = e.target.closest("th[data-col]");
    if (!th) return;
    dragCol = th.dataset.col;
    th.classList.add("is-dragging");
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
  });
  table.addEventListener("dragover", (e) => {
    if (!dragCol) return;
    e.preventDefault();
    const th = e.target.closest("th[data-col]");
    if (!th || th.dataset.col === dragCol) return;
    const keys = columnKeys();
    const from = keys.indexOf(dragCol);
    const to = keys.indexOf(th.dataset.col);
    if (from < 0 || to < 0 || from === to) return;
    keys.splice(from, 1);
    keys.splice(to, 0, dragCol);
    applyColumns(keys);
  });
  table.addEventListener("dragend", () => {
    const head = headRow();
    if (head) {
      Array.from(head.cells).forEach((th) => th.classList.remove("is-dragging"));
    }
    dragCol = null;
  });

  bar.querySelector("[data-laycol-save]")?.addEventListener("click", () => {
    submit(formCol, columnKeys().filter(Boolean));
  });
  bar.querySelector("[data-laycol-reset]")?.addEventListener("click", () => {
    submit(formCol, (bar.dataset.colsDefault || "").split(",").filter(Boolean));
  });
})();
