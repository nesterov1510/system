"use client";

import { useCallback, useEffect, useState } from "react";
import { api, money, type Part } from "@/lib/api";

export default function PartsPage() {
  const [parts, setParts] = useState<Part[]>([]);
  const [q, setQ] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    category: "",
    sku: "",
    stock_qty: 0,
    min_stock: 0,
    cost_price: "",
    sell_price: "",
    supplier: "",
  });

  const load = useCallback(() => {
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (lowOnly) params.low_stock = "true";
    api.parts(params).then(setParts).catch((e) => setError(e.message));
  }, [q, lowOnly]);

  useEffect(load, [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createPart({
        name: form.name,
        category: form.category || null,
        sku: form.sku || null,
        stock_qty: Number(form.stock_qty) || 0,
        min_stock: Number(form.min_stock) || 0,
        cost_price: form.cost_price ? Number(form.cost_price) : null,
        sell_price: form.sell_price ? Number(form.sell_price) : null,
        supplier: form.supplier || null,
      });
      setShowForm(false);
      setForm({ name: "", category: "", sku: "", stock_qty: 0, min_stock: 0, cost_price: "", sell_price: "", supplier: "" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    }
  }

  async function adjustStock(part: Part, delta: number) {
    await api.updatePart(part.id, { stock_qty: Math.max(0, part.stock_qty + delta) });
    load();
  }

  const allCategories = [...new Set(parts.map((p) => p.category).filter(Boolean))] as string[];
  const [catFilter, setCatFilter] = useState("");

  const filtered = parts.filter((p) => {
    if (catFilter && p.category !== catFilter) return false;
    return true;
  });

  return (
    <div className="mx-auto max-w-4xl">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Склад запчастей</h1>
          <p className="mt-1 text-sm text-slate-500">
            {parts.length} позиций · {parts.filter((p) => p.stock_qty <= p.min_stock).length} требуют пополнения
          </p>
        </div>
        <button onClick={() => setShowForm((v) => !v)}
          className="msb-btn-primary">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Новая запчасть
        </button>
      </div>

      {/* Filters */}
      <div className="mb-4 grid gap-2.5 sm:flex sm:flex-wrap sm:items-center sm:gap-3">
        <div className="relative min-w-0 sm:flex-1">
          <svg className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск запчастей…" className="msb-input pl-10" />
        </div>
        <select value={catFilter} onChange={(e) => setCatFilter(e.target.value)}
          className="msb-input w-full sm:w-auto sm:min-w-[130px]">
          <option value="">Все категории</option>
          {allCategories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none whitespace-nowrap">
          <input type="checkbox" checked={lowOnly}
            onChange={(e) => setLowOnly(e.target.checked)}
            className="h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500" />
          Мало на складе
        </label>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}

      {/* New part form */}
      {showForm && (
        <form onSubmit={submit} className="mb-6 msb-card-solid p-5 space-y-4 animate-slide-up">
          <h3 className="text-sm font-semibold text-slate-700">Новая запчасть</h3>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="sm:col-span-2">
              <label className="msb-label">Название *</label>
              <input className="msb-input" placeholder="Блок питания" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div>
              <label className="msb-label">Категория</label>
              <input className="msb-input" placeholder="Электроника" value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })} />
            </div>
            <div>
              <label className="msb-label">SKU</label>
              <input className="msb-input" placeholder="PS-001" value={form.sku}
                onChange={(e) => setForm({ ...form, sku: e.target.value })} />
            </div>
            <div>
              <label className="msb-label">Количество</label>
              <input className="msb-input" type="number" placeholder="10" value={form.stock_qty}
                onChange={(e) => setForm({ ...form, stock_qty: Number(e.target.value) })} />
            </div>
            <div>
              <label className="msb-label">Мин. остаток</label>
              <input className="msb-input" type="number" placeholder="2" value={form.min_stock}
                onChange={(e) => setForm({ ...form, min_stock: Number(e.target.value) })} />
            </div>
            <div>
              <label className="msb-label">Закуп (ман.)</label>
              <input className="msb-input" type="number" placeholder="100" value={form.cost_price}
                onChange={(e) => setForm({ ...form, cost_price: e.target.value })} />
            </div>
            <div>
              <label className="msb-label">Продажа (ман.)</label>
              <input className="msb-input" type="number" placeholder="250" value={form.sell_price}
                onChange={(e) => setForm({ ...form, sell_price: e.target.value })} />
            </div>
            <div>
              <label className="msb-label">Поставщик</label>
              <input className="msb-input" placeholder="ООО Техно" value={form.supplier}
                onChange={(e) => setForm({ ...form, supplier: e.target.value })} />
            </div>
          </div>
          <div className="flex gap-3">
            <button className="msb-btn-primary">Сохранить</button>
            <button type="button" onClick={() => setShowForm(false)} className="msb-btn-secondary">Отмена</button>
          </div>
        </form>
      )}

      {/* Parts list */}
      <div className="space-y-2">
        {filtered.map((p) => {
          const low = p.stock_qty <= p.min_stock;
          return (
            <div key={p.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-white px-5 py-4 shadow-sm ring-1 ring-slate-200/70 transition-all duration-200 hover:shadow-md animate-fade-in">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-900">{p.name}</span>
                  {p.category && (
                    <span className="msb-badge-gray text-[10px]">{p.category}</span>
                  )}
                </div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {[p.sku, p.supplier].filter(Boolean).join(" · ")}
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-bold ${
                    low
                      ? "bg-red-100 text-red-700"
                      : "bg-emerald-100 text-emerald-700"
                  }`}>
                    {p.stock_qty} шт
                  </span>
                  <div className="text-[10px] text-slate-400 mt-0.5">
                    мин. {p.min_stock}
                  </div>
                </div>
                {p.sell_price != null && (
                  <div className="text-sm font-bold text-slate-800 min-w-[80px] text-right">
                    {money(p.sell_price)}
                  </div>
                )}
                <div className="flex items-center gap-1">
                  <button onClick={() => adjustStock(p, -1)}
                    className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-100 transition-colors">
                    −
                  </button>
                  <button onClick={() => adjustStock(p, 1)}
                    className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-100 transition-colors">
                    +
                  </button>
                </div>
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 py-16 text-slate-400">
            <span className="text-4xl mb-3">📦</span>
            <p className="text-sm font-medium">Запчасти не найдены</p>
            <button onClick={() => setShowForm(true)} className="msb-btn-primary mt-4">
              + Добавить первую запчасть
            </button>
          </div>
        )}
      </div>
    </div>
  );
}