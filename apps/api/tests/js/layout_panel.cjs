// Прогон настоящего static/msb/layout.js в jsdom: поведение сворачиваемой
// панели конструктора. Запускается из tests/test_page_layout.py.
// Если jsdom не установлен — SKIP (тест честно пропускается).
const fs = require("fs");

let JSDOM;
try {
  JSDOM = require("jsdom").JSDOM;
} catch (err) {
  console.log(JSON.stringify({ skip: "jsdom not installed" }));
  process.exit(0);
}

const [htmlFile, jsFile] = process.argv.slice(2);
const dom = new JSDOM(fs.readFileSync(htmlFile, "utf8"), {
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;
window.eval(fs.readFileSync(jsFile, "utf8"));

const doc = window.document;
const q = (sel) => doc.querySelector(sel);
const click = (sel) => {
  const el = q(sel);
  if (!el) throw new Error("нет элемента " + sel);
  el.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
};
const visible = (sel) => {
  const el = q(sel);
  return !!el && !el.hasAttribute("hidden");
};

const out = {};

// 1. Панель свёрнута: видна только кнопка «Конструктор».
out.startsCollapsed = !visible("[data-lay-panel]");
out.expandBtnVisible = visible("[data-lay-expand]");

// 2. Раскрытие.
click("[data-lay-expand]");
out.opensOnClick = visible("[data-lay-panel]");
out.ariaExpanded = q("[data-lay-expand]").getAttribute("aria-expanded");

// 3. Режим «Блоки страницы»: подсказка и действия блоков, у колонок скрыто.
click("[data-lay-toggle]");
out.blockMode = {
  hint: visible('[data-lay-only].lay-panel__hint'),
  acts: visible('[data-lay-only].lay-panel__acts'),
  colHintHidden: !visible('[data-laycol-only].lay-panel__hint'),
  activeClass: q("[data-lay-toggle]").classList.contains("is-active"),
  rootHighlighted: q("[data-lay-root]").classList.contains("is-lay"),
  handles: doc.querySelectorAll("[data-lay-ctl]").length,
  blocks: doc.querySelectorAll(":scope > [data-block]").length ||
    q("[data-lay-root]").querySelectorAll(":scope > [data-block]").length,
};

// 4. Переключение на «Колонки таблицы»: блоки гаснут, включаются колонки.
if (q("[data-laycol-toggle]")) {
  click("[data-laycol-toggle]");
  out.colMode = {
    hint: visible('[data-laycol-only].lay-panel__hint'),
    acts: visible('[data-laycol-only].lay-panel__acts'),
    blockHintHidden: !visible('[data-lay-only].lay-panel__hint'),
    blockHandlesRemoved: doc.querySelectorAll("[data-lay-ctl]").length === 0,
    activeClass: q("[data-laycol-toggle]").classList.contains("is-active"),
    blockActiveRemoved: !q("[data-lay-toggle]").classList.contains("is-active"),
    tableHighlighted: q("#rlist-table").classList.contains("is-lay-cols"),
    handles: doc.querySelectorAll("[data-laycol-ctl]").length,
  };
}

// 5. Свернуть — панель прячется, оба режима выключены.
click("[data-lay-collapse]");
out.collapses = !visible("[data-lay-panel]");
out.modesOffAfterCollapse =
  !q("[data-lay-root]").classList.contains("is-lay") &&
  !q("#rlist-table").classList.contains("is-lay-cols") &&
  doc.querySelectorAll("[data-laycol-ctl]").length === 0;
out.ariaCollapsed = q("[data-lay-expand]").getAttribute("aria-expanded");

console.log(JSON.stringify(out));
