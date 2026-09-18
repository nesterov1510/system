// Прогон настоящего static/msb/layout.js в jsdom: проверяем, что сохранённый
// порядок колонок действительно применяется к таблице (заголовки + ячейки).
// Запускается из tests/test_page_layout.py. Если jsdom не установлен — SKIP.
const fs = require("fs");
const path = require("path");

let JSDOM;
try {
  JSDOM = require("jsdom").JSDOM;
} catch (err) {
  console.log(JSON.stringify({ skip: "jsdom not installed" }));
  process.exit(0);
}

const [htmlFile, jsFile] = process.argv.slice(2);
const html = fs.readFileSync(htmlFile, "utf8");
const js = fs.readFileSync(jsFile, "utf8");

const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true });
const { window } = dom;

// Скрипты в разметке не исполняем (они тянут сеть), нужен только layout.js.
window.eval(js);

const table = window.document.getElementById("rlist-table");
const head = Array.from(table.tHead.rows[0].cells).map((c) => c.dataset.col);
const rows = Array.from(table.tBodies[0].rows)
  .filter((tr) => tr.querySelector("[data-col]"))
  .map((tr) => Array.from(tr.cells).map((c) => c.dataset.col).filter(Boolean));
const firstRow = rows.length ? rows[0] : [];
const allRowsMatch = rows.every((r) => r.join(",") === firstRow.join(","));

console.log(JSON.stringify({ head, firstRow, allRowsMatch, rowCount: rows.length }));
