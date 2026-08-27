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
    api
      .printTemplates()
      .then((list) => {
        setTemplates(list);
        if (!active && list[0]) setActive(list[0]);
      })
      .catch((e) => setError(e.message));
    api
      .printTemplatesMeta()
      .then((m) => setFields(m.fields))
      .catch(() => {});
  }, [active]);

  useEffect(load, [load]);

  const current = active ?? {
    name: "Новый шаблон",
    is_default: false,
    body: {},
  };

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
      const res = await api.savePrintTemplate({
        id: current.id,
        name: current.name,
        body: current.body,
        is_default: current.is_default,
      });
      setMsg("Сохранено");
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

  const input =
    "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm";
  const label = "mb-1 block text-xs font-medium text-gray-500";

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-4 text-xl font-semibold">Шаблон бланка</h1>

      <div className="grid gap-4 md:grid-cols-[240px_1fr]">
        {/* Список шаблонов */}
        <aside className="space-y-2">
          {templates.map((t) => (
            <button
              key={t.id}
              onClick={() => setActive(t)}
              className={`w-full rounded-lg px-3 py-2.5 text-left text-sm ${
                active?.id === t.id
                  ? "bg-slate-900 text-white"
                  : "bg-white text-gray-700 ring-1 ring-gray-200"
              }`}
            >
              {t.name}
              {t.is_default && <span className="ml-1 text-xs opacity-70">· дефолт</span>}
            </button>
          ))}
          <button
            onClick={() =>
              setActive({ name: "Новый шаблон", is_default: false, body: {} })
            }
            className="w-full rounded-lg border border-dashed border-gray-300 px-3 py-2.5 text-left text-sm text-gray-500"
          >
            + Новый шаблон
          </button>
        </aside>

        {/* Редактор */}
        <section className="space-y-4 rounded-2xl bg-white p-5 ring-1 ring-gray-200">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Название</label>
              <input
                className={input}
                value={current.name}
                onChange={(e) =>
                  setActive((p) => ({ ...p!, name: e.target.value }))
                }
              />
            </div>
            <div>
              <label className={label}>Формат бумаги</label>
              <select
                className={input}
                value={current.body.paper ?? "A4"}
                onChange={(e) => update({ paper: e.target.value })}
              >
                <option value="A4">A4</option>
                <option value="A5">A5</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Раскладка экземпляров</label>
              <select
                className={input}
                value={current.body.layout ?? "one-per-page"}
                onChange={(e) => update({ layout: e.target.value })}
              >
                <option value="one-per-page">По 1 на странице</option>
                <option value="two-per-page">2 на одном листе (разрезать)</option>
              </select>
            </div>
            <div>
              <label className={label}>Кол-во экземпляров</label>
              <select
                className={input}
                value={current.body.copies ?? 2}
                onChange={(e) => update({ copies: Number(e.target.value) })}
              >
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Название сервиса (brand)</label>
              <input
                className={input}
                value={current.body.brand ?? ""}
                onChange={(e) => update({ brand: e.target.value })}
              />
            </div>
            <div>
              <label className={label}>Заголовок</label>
              <input
                className={input}
                value={current.body.title ?? ""}
                onChange={(e) => update({ title: e.target.value })}
              />
            </div>
          </div>

          <div>
            <label className={label}>
              Подзаголовок (доступны {`{city}`} и {`{branch}`})
            </label>
            <input
              className={input}
              value={current.body.subtitle ?? ""}
              onChange={(e) => update({ subtitle: e.target.value })}
            />
          </div>

          {/* Поля */}
          <div>
            <label className={label}>Поля на бланке (порядок = порядок в списке)</label>
            <div className="flex flex-wrap gap-2">
              {fields.map((f) => {
                const on = (current.body.fields ?? []).includes(f);
                return (
                  <button
                    key={f}
                    onClick={() => toggleField(f)}
                    className={`rounded-full px-3 py-1.5 text-xs font-medium ${
                      on
                        ? "bg-slate-900 text-white"
                        : "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {FIELD_LABELS[f] ?? f}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className={label}>
              Юр. текст хранения (пусто = из настроек)
            </label>
            <textarea
              className={`${input} min-h-[80px]`}
              value={current.body.legal_text ?? ""}
              onChange={(e) => update({ legal_text: e.target.value || null })}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Футер</label>
              <input
                className={input}
                value={current.body.footer ?? ""}
                onChange={(e) => update({ footer: e.target.value })}
              />
            </div>
            <label className="flex items-end gap-2 pb-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={current.body.signature !== false}
                onChange={(e) => update({ signature: e.target.checked })}
                className="h-5 w-5"
              />
              Место подписей
            </label>
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={current.is_default}
              onChange={(e) =>
                setActive((p) => ({ ...p!, is_default: e.target.checked }))
              }
              className="h-5 w-5"
            />
            Шаблон по умолчанию
          </label>

          <div className="flex gap-2">
            <button
              onClick={save}
              className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white"
            >
              Сохранить
            </button>
            <button
              onClick={preview}
              className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700"
            >
              Превью
            </button>
          </div>

          {msg && <p className="text-sm text-green-600">{msg}</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </section>
      </div>

      {/* Превью PDF */}
      {previewUrl && (
        <div className="mt-4 rounded-2xl bg-white p-4 ring-1 ring-gray-200">
          <h2 className="mb-2 text-sm font-semibold text-gray-500">Превью</h2>
          <iframe
            src={previewUrl}
            className="h-[80vh] w-full rounded-lg border border-gray-200"
            title="preview"
          />
        </div>
      )}
    </div>
  );
}
