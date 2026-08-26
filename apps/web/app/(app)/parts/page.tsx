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
      setForm({
        name: "", category: "", sku: "", stock_qty: 0, min_stock: 0,
        cost_price: "", sell_price: "", supplier: "",
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    }
  }

  async function adjustStock(part: Part, delta: number) {
    await api.updatePart(part.id, { stock_qty: Math.max(0, part.stock_qty + delta) });
    load();
  }

  const input = "rounded-lg border border-gray-300 px-3 py-2 text-sm";

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Склад запчастей</h1>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white"
        >
          + Запчасть
        </button>
      </div>

      <div className="mb-3 flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Поиск…"
          className={`${input} flex-1`}
        />
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={lowOnly}
            onChange={(e) => setLowOnly(e.target.checked)}
            className="h-5 w-5"
          />
          мало на складе
        </label>
      </div>

      {showForm && (
        <form
          onSubmit={submit}
          className="mb-4 rounded-2xl bg-white p-4 ring-1 ring-gray-200 space-y-3"
        >
          <div className="grid grid-cols-2 gap-3">
            <input className={input} placeholder="Название *" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            <input className={input} placeholder="Категория" value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })} />
            <input className={input} placeholder="SKU" value={form.sku}
              onChange={(e) => setForm({ ...form, sku: e.target.value })} />
            <input className={input} placeholder="Поставщик" value={form.supplier}
              onChange={(e) => setForm({ ...form, supplier: e.target.value })} />
            <input className={input} type="number" placeholder="Кол-во"
              value={form.stock_qty}
              onChange={(e) => setForm({ ...form, stock_qty: Number(e.target.value) })} />
            <input className={input} type="number" placeholder="Мин. остаток"
              value={form.min_stock}
              onChange={(e) => setForm({ ...form, min_stock: Number(e.target.value) })} />
            <input className={input} type="number" placeholder="Закуп (ман.)"
              value={form.cost_price}
              onChange={(e) => setForm({ ...form, cost_price: e.target.value })} />
            <input className={input} type="number" placeholder="Продажа (ман.)"
              value={form.sell_price}
              onChange={(e) => setForm({ ...form, sell_price: e.target.value })} />
          </div>
          <div className="flex gap-2">
            <button className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white">
              Сохранить
            </button>
            <button type="button" onClick={() => setShowForm(false)}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600">
              Отмена
            </button>
          </div>
        </form>
      )}

      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      <ul className="space-y-2">
        {parts.map((p) => {
          const low = p.stock_qty <= p.min_stock;
          return (
            <li key={p.id} className="flex items-center justify-between rounded-xl bg-white p-3 ring-1 ring-gray-200">
              <div>
                <div className="text-sm font-medium text-gray-900">{p.name}</div>
                <div className="text-xs text-gray-500">
                  {[p.category, p.sku].filter(Boolean).join(" · ")}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${low ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`}>
                  {p.stock_qty} шт
                </span>
                {p.sell_price != null && (
                  <span className="text-sm font-semibold text-gray-700">
                    {money(p.sell_price)}
                  </span>
                )}
                <div className="flex gap-1">
                  <button onClick={() => adjustStock(p, -1)}
                    className="h-8 w-8 rounded-lg border border-gray-200 text-gray-600">−</button>
                  <button onClick={() => adjustStock(p, 1)}
                    className="h-8 w-8 rounded-lg border border-gray-200 text-gray-600">+</button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
