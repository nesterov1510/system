// Конструктор блоков страницы: админ переставляет блоки (стрелки или
// перетаскивание), порядок сохраняется лично ему через POST /ui/layout.
(() => {
  "use strict";
  const bar = document.querySelector("[data-lay-bar]");
  const root = document.querySelector("[data-lay-root]");
  if (!bar || !root) return;

  const form = bar.querySelector("[data-lay-form]");
  const onlyEdit = Array.from(bar.querySelectorAll("[data-lay-only]"));
  const editing = () => bar.classList.contains("is-editing");
  // Блоки — прямые потомки контейнера, порядок задаётся CSS `order`.
  const blocks = () => Array.from(root.querySelectorAll(":scope > [data-block]"));

  const applyOrders = () => {
    blocks().forEach((el, i) => {
      el.style.order = String(i);
    });
  };

  const swap = (el, dir) => {
    const list = blocks();
    const i = list.indexOf(el);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= list.length) return;
    if (dir < 0) root.insertBefore(el, list[j]);
    else root.insertBefore(list[j], el);
    applyOrders();
  };

  const control = (el) => {
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
    up.addEventListener("click", () => swap(el, -1));
    const down = document.createElement("button");
    down.type = "button";
    down.className = "lay-btn";
    down.textContent = "↓";
    down.title = "Опустить блок";
    down.addEventListener("click", () => swap(el, 1));
    ctl.append(title, up, down);
    return ctl;
  };

  const setMode = (on) => {
    bar.classList.toggle("is-editing", on);
    root.classList.toggle("is-lay", on);
    onlyEdit.forEach((el) => {
      el.hidden = !on;
    });
    blocks().forEach((el) => {
      const old = el.querySelector(":scope > [data-lay-ctl]");
      if (old) old.remove();
      el.draggable = on;
      if (on) el.prepend(control(el));
    });
    const btn = bar.querySelector("[data-lay-toggle]");
    if (btn) btn.textContent = on ? "✕ Закрыть конструктор" : "🧩 Конструктор блоков";
  };

  bar.querySelector("[data-lay-toggle]")?.addEventListener("click", () => setMode(!editing()));

  // Перетаскивание мышью.
  let dragged = null;
  root.addEventListener("dragstart", (e) => {
    if (!editing()) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (["input", "textarea", "select", "a", "button"].includes(tag)) return;
    const el = e.target.closest("[data-block]");
    if (!el || el.parentElement !== root) return;
    dragged = el;
    el.classList.add("is-dragging");
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
  });
  root.addEventListener("dragover", (e) => {
    if (!dragged) return;
    e.preventDefault();
    const target = e.target.closest("[data-block]");
    if (!target || target === dragged || target.parentElement !== root) return;
    const box = target.getBoundingClientRect();
    const after = e.clientY - box.top > box.height / 2;
    root.insertBefore(dragged, after ? target.nextSibling : target);
    applyOrders();
  });
  root.addEventListener("dragend", () => {
    if (dragged) dragged.classList.remove("is-dragging");
    dragged = null;
    applyOrders();
  });

  const submit = (order) => {
    if (!form) return;
    form.elements.order.value = order.join(",");
    form.submit();
  };

  bar.querySelector("[data-lay-save]")?.addEventListener("click", () => {
    submit(blocks().map((el) => el.dataset.block));
  });
  bar.querySelector("[data-lay-reset]")?.addEventListener("click", () => {
    submit((bar.dataset.default || "").split(",").filter(Boolean));
  });
})();
