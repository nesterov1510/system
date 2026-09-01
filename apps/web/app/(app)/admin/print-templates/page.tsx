"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Template {
  id?: string;
  name: string;
  is_default: boolean;
  body: Record<string, any>;
}

const FIELD_LABELS: Record<string, string> = {
  client: "Клиент",
  phone: "Телефон",
  device: "Техника",
  serial: "Серийник",
  complect: "Комплект",
  fault: "Неисправность",
  accepted_by: "Принял",
  master: "Мастер",
  storage_until: "Хранение до",
  eta: "Срок (дней)",
};

export default function PrintTemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [fields, setFields] = useState<string[]>([]);
  const [active, setActive] = useState<Template | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.printTemplates().then((list) => {
      setTemplates(list);
      if (!active && list[0]) setActive(list[0]);
    }).catch((e) => setError(e.message));
    api.printTemplatesMeta().then((m) => setFields(m.fields)).catch(() => {});
  }, [active]);

  useEffect(load, [load]);

  const current = active ?? { name: "Новый шаблон", is_default: false, body: {} };

  function update(patch: Partial<Template["body"]>) {
    setActive((prev) => ({
      ...(prev ?? { name: "Новый шаблон", is_default: false, body: {} }),
      body: { ...(prev?.body ?? {}), ...patch },
    }));
  }

  function toggleField(f: string) {
    const cur = new Set<string>(current.body.fields ?? []);
    if (cur.has(f)) cur.delete(f);
    else cur.add(f);
    update({ fields: Array.from(cur) });
  }

  async function save() {
    setMsg(null);
    setError(null);
    try {
      await api.savePrintTemplate({
        id: current.id,
        name: current.name,
        body: current.body,
        is_default: current.is_default,
      });
      setMsg("✅ Шаблон сохранён");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    }
  }

  async function preview() {
    setError(null);
    try {
      const blob = await api.previewPrintTemplate(current.body);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка превью");
    }
  }

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Шаблоны бланков</h1>
        <p className="mt-1 text-sm text-slate-500">Настройка внешнего вида печатных бланков</p>
      </div>

      {msg && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700 ring-1 ring-emerald-200">
          <span>✅</span> {msg}
        </div>
      )}
      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
        {/* Templates list */}
        <aside className="space-y-2">
          <h2 className="msb-section-title mb-3 px-2">Шаблоны</h2>
          {templates.map((t) => (
            <button key={t.id} onClick={() => setActive(t)}
              className={`w-full rounded-xl px-4 py-3 text-left text-sm font-medium transition-all ${
                active?.id === t.id
                  ? "bg-msb-600 text-white shadow-sm"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-msb-200"
              }`}>
              <div className="flex items-center justify-between">
                <span>{t.name}</span>
                {t.is_default && <span className="text-[10px] opacity-70">★</span>}
              </div>
            </button>
          ))}
          <button onClick={() => setActive({ name: "Новый шаблон", is_default: false, body: {} })}
            className="w-full rounded-xl border-2 border-dashed border-slate-300 px-4 py-3 text-left text-sm text-slate-500 hover:border-msb-400 hover:text-msb-600 transition-colors">
            + Новый шаблон
          </button>
        </aside>

        {/* Editor */}
        <section className="msb-card-solid p-4 sm:p-6 space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="msb-label">Название</label>
              <input className="msb-input" value={current.name}
                onChange={(e) => setActive((p) => ({ ...p!, name: e.target.value }))} />
            </div>
            <div>
              <label className="msb-label">Формат бумаги</label>
              <select className="msb-input" value={current.body.paper ?? "A4"}
                onChange={(e) => update({ paper: e.target.value })}>
                <option value="A4">A4</option>
                <option value="A5">A5</option>
              </select>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="msb-label">Раскладка</label>
              <select className="msb-input" value={current.body.layout ?? "one-per-page"}
                onChange={(e) => update({ layout: e.target.value })}>
                <option value="one-per-page">По 1 на странице</option>
                <option value="two-per-page">2 на листе (с разрезом)</option>
              </select>
            </div>
            <div>
              <label className="msb-label">Копий</label>
              <select className="msb-input" value={current.body.copies ?? 2}
                onChange={(e) => update({ copies: Number(e.target.value) })}>
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="msb-label">Название сервиса</label>
              <input className="msb-input" value={current.body.brand ?? ""}
                onChange={(e) => update({ brand: e.target.value })} />
            </div>
            <div>
              <label className="msb-label">Заголовок</label>
              <input className="msb-input" value={current.body.title ?? ""}
                onChange={(e) => update({ title: e.target.value })} />
            </div>
          </div>

          <div>
            <label className="msb-label">Подзаголовок (доступны {'{city}'} и {'{branch}'})</label>
            <input className="msb-input" value={current.body.subtitle ?? ""}
              onChange={(e) => update({ subtitle: e.target.value })} />
          </div>

          {/* Fields */}
          <div>
            <label className="msb-label">Поля на бланке</label>
            <div className="flex flex-wrap gap-2">
              {fields.map((f) => {
                const on = (current.body.fields ?? []).includes(f);
                return (
                  <button key={f} onClick={() => toggleField(f)}
                    className={`rounded-full px-4 py-1.5 text-xs font-medium transition-all ${
                      on
                        ? "bg-msb-600 text-white shadow-sm"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}>
                    {FIELD_LABELS[f] ?? f}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="msb-label">Юр. текст хранения (пусто = из настроек)</label>
            <textarea className="msb-input min-h-[80px] resize-y"
              value={current.body.legal_text ?? ""}
              onChange={(e) => update({ legal_text: e.target.value || null })} />
          </div>

          <div className="flex flex-wrap gap-3">
            <div className="flex-1 min-w-[200px]">
              <label className="msb-label">Футер</label>
              <input className="msb-input" value={current.body.footer ?? ""}
                onChange={(e) => update({ footer: e.target.value })} />
            </div>
            <label className="flex items-end gap-2 pb-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" checked={current.body.signature !== false}
                onChange={(e) => update({ signature: e.target.checked })}
                className="h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500" />
              Подписи
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" checked={current.is_default}
                onChange={(e) => setActive((p) => ({ ...p!, is_default: e.target.checked }))}
                className="h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500" />
              По умолчанию
            </label>
          </div>

          <div className="flex gap-3 pt-2">
            <button onClick={save} className="msb-btn-primary">
              💾 Сохранить
            </button>
            <button onClick={preview} className="msb-btn-secondary">
              👁️ Превью PDF
            </button>
          </div>
        </section>
      </div>

      {/* Preview */}
      {previewUrl && (
        <div className="mt-6 msb-card-solid p-4 animate-fade-in">
          <h2 className="msb-section-title mb-3">Превью</h2>
          <iframe src={previewUrl} className="h-[80vh] w-full rounded-xl border border-slate-200" title="preview" />
        </div>
      )}
    </div>
  );
}