"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  money,
  EQUIPMENT_STATUS,
  type Equipment,
  type Part,
} from "@/lib/api";

type Tab = "parts" | "equipment";

export default function PartsPage() {
  const [tab, setTab] = useState<Tab>("parts");

  return (
    <div className="mx-auto max-w-4xl">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Склад</h1>
          <p className="mt-1 text-sm text-slate-500">
            Запчасти и купленная техника
          </p>
        </div>
        <div className="flex gap-1 rounded-2xl bg-slate-100 p-1.5">
          <button
            onClick={() => setTab("parts")}
            className={`rounded-xl px-4 py-2 text-sm font-medium transition-all ${
              tab === "parts"
                ? "bg-white text-msb-700 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            🔩 Запчасти
          </button>
          <button
            onClick={() => setTab("equipment")}
            className={`rounded-xl px-4 py-2 text-sm font-medium transition-all ${
              tab === "equipment"
                ? "bg-white text-msb-700 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            🖥️ Техника
          </button>
        </div>
      </div>

      {tab === "parts" ? <PartsTab /> : <EquipmentTab />}
    </div>
  );
}

/* ========================================================================== */
/* Запчасти                                                                    */
/* ========================================================================== */

function PartsTab() {
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
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-500">
          {parts.length} позиций · {parts.filter((p) => p.stock_qty <= p.min_stock).length} требуют пополнения
        </p>
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

/* ========================================================================== */
/* Купленная техника                                                           */
/* ========================================================================== */

const EMPTY_EQ_FORM = {
  name: "",
  brand: "",
  model: "",
  purchase_price: "",
  purchased_at: "",
  storage_place: "",
  components: "",
  status: "in_stock",
  notes: "",
};

function todayStr(): string {
  // Локальная дата (не UTC) — чтобы «сегодня» не сдвигалось ночью.
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function EquipmentTab() {
  const [items, setItems] = useState<Equipment[]>([]);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Форма (создание/редактирование) — модалка.
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...EMPTY_EQ_FORM, purchased_at: todayStr() });
  // Просмотр — модалка.
  const [view, setView] = useState<Equipment | null>(null);

  const load = useCallback(() => {
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (statusFilter) params.status = statusFilter;
    api.equipment(params).then(setItems).catch((e) => setError(e.message));
  }, [q, statusFilter]);

  useEffect(load, [load]);

  function openCreate() {
    setEditingId(null);
    setForm({ ...EMPTY_EQ_FORM, purchased_at: todayStr() });
    setError(null);
    setFormOpen(true);
  }

  function openEdit(eq: Equipment) {
    setEditingId(eq.id);
    setForm({
      name: eq.name,
      brand: eq.brand ?? "",
      model: eq.model ?? "",
      purchase_price: eq.purchase_price != null ? String(eq.purchase_price) : "",
      purchased_at: (eq.purchased_at || "").slice(0, 10),
      storage_place: eq.storage_place ?? "",
      components: (eq.components ?? []).join(", "),
      status: eq.status,
      notes: eq.notes ?? "",
    });
    setError(null);
    setFormOpen(true);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const components = form.components
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      brand: form.brand.trim() || null,
      model: form.model.trim() || null,
      purchase_price: form.purchase_price ? Number(form.purchase_price) : null,
      // Наивная строка (без «Z») — вся БД хранит naive UTC, а aware-datetime
      // роняет asyncpg (DataError). Обед 12:00 — безопасный «день в себе»,
      // дата стабильно вернётся тем же календарным днём при любом смещении.
      purchased_at: form.purchased_at ? `${form.purchased_at}T12:00:00` : null,
      components: components.length ? components : null,
      storage_place: form.storage_place.trim() || null,
      status: form.status,
      notes: form.notes.trim() || null,
    };
    try {
      if (editingId) {
        await api.updateEquipment(editingId, payload);
      } else {
        await api.createEquipment(payload);
      }
      setFormOpen(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(eq: Equipment, status: string) {
    setError(null);
    try {
      await api.setEquipmentStatus(eq.id, status);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    }
  }

  async function remove(eq: Equipment) {
    if (!confirm(`Удалить технику «${eq.name}» со склада?`)) return;
    setError(null);
    try {
      await api.deleteEquipment(eq.id);
      setView(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    }
  }

  const btnAction =
    "rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 whitespace-nowrap";

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-500">
          {items.length} ед. · купленная техника (скрап, доноры)
        </p>
        <button onClick={openCreate} className="msb-btn-primary">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Новая техника
        </button>
      </div>

      {/* Filters */}
      <div className="mb-4 grid gap-2.5 sm:flex sm:flex-wrap sm:items-center sm:gap-3">
        <div className="relative min-w-0 sm:flex-1">
          <svg className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск: название, марка, модель…" className="msb-input pl-10" />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className="msb-input w-full sm:w-auto sm:min-w-[170px]">
          <option value="">Все статусы</option>
          {Object.entries(EQUIPMENT_STATUS).map(([value, m]) => (
            <option key={value} value={value}>{m.label}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}

      {/* List */}
      {items.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 py-16 text-slate-400">
          <span className="text-4xl mb-3">🖥️</span>
          <p className="text-sm font-medium">Техника не найдена</p>
          <button onClick={openCreate} className="msb-btn-primary mt-4">
            + Добавить первую технику
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl bg-white shadow-sm ring-1 ring-slate-200/70 animate-fade-in">
          <table className="w-full min-w-[920px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase tracking-wider text-slate-400">
                <th className="px-4 py-3 font-semibold">Дата</th>
                <th className="px-4 py-3 font-semibold">Вид техники</th>
                <th className="px-4 py-3 font-semibold">Марка / модель</th>
                <th className="px-4 py-3 font-semibold">Место хранения</th>
                <th className="px-4 py-3 font-semibold text-right">Цена покупки</th>
                <th className="px-4 py-3 font-semibold text-right">Действия</th>
              </tr>
            </thead>
            <tbody>
              {items.map((eq) => {
                const status = EQUIPMENT_STATUS[eq.status] ?? {
                  label: eq.status,
                  badge: "bg-slate-100 text-slate-600",
                };
                return (
                  <tr key={eq.id} className="border-b border-slate-50 transition-colors last:border-0 hover:bg-slate-50/60">
                    <td className="whitespace-nowrap px-4 py-3 text-slate-500">
                      {new Date(eq.purchased_at).toLocaleDateString("ru")}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-900">{eq.name}</span>
                          {(eq.components?.length ?? 0) > 0 && (
                            <span className="text-[10px] text-slate-400">
                              {eq.components!.length} комплект.
                            </span>
                          )}
                        </div>
                        <span className={`inline-flex w-fit items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold ${status.badge}`}>
                          {status.label}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {[eq.brand, eq.model].filter(Boolean).join(" ") || "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                      {eq.storage_place || "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-800">
                      {money(eq.purchase_price)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1.5">
                        <button onClick={() => setView(eq)} title="Просмотреть"
                          className={btnAction}>
                          👁 Просмотр
                        </button>
                        <button onClick={() => openEdit(eq)} title="Редактировать"
                          className={btnAction}>
                          ✏️ Изменить
                        </button>
                        <button
                          disabled={eq.status === "dismantled"}
                          onClick={() => setStatus(eq, "dismantled")}
                          title="Отметить: разобран"
                          className={btnAction}>
                          🛠 Разобран
                        </button>
                        <button
                          disabled={eq.status === "partial"}
                          onClick={() => setStatus(eq, "partial")}
                          title="Отметить: частично разобран"
                          className={btnAction}>
                          ½ Част. разобран
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Модалка: создание / редактирование */}
      {formOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setFormOpen(false)} />
          <div className="relative w-full max-w-lg msb-card-solid p-6 animate-slide-up max-h-[90vh] overflow-y-auto custom-scroll">
            <div className="flex items-start justify-between gap-3">
              <h3 className="msb-section-title">
                {editingId ? "Редактировать технику" : "Новая техника"}
              </h3>
              <button onClick={() => setFormOpen(false)} className="text-slate-400 hover:text-slate-600">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <form onSubmit={submit} className="mt-4 space-y-4">
              <div>
                <label className="msb-label">Вид техники *</label>
                <input className="msb-input" placeholder="Ноутбук, Монитор, Телевизор, Холодильник…"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="msb-label">Марка</label>
                  <input className="msb-input" placeholder="Samsung"
                    value={form.brand}
                    onChange={(e) => setForm({ ...form, brand: e.target.value })} />
                </div>
                <div>
                  <label className="msb-label">Модель</label>
                  <input className="msb-input" placeholder="UE55"
                    value={form.model}
                    onChange={(e) => setForm({ ...form, model: e.target.value })} />
                </div>
                <div>
                  <label className="msb-label">Дата покупки</label>
                  <input className="msb-input" type="date"
                    value={form.purchased_at}
                    onChange={(e) => setForm({ ...form, purchased_at: e.target.value })} />
                </div>
                <div>
                  <label className="msb-label">За сколько купили, ман.</label>
                  <input className="msb-input" type="number" placeholder="2500"
                    value={form.purchase_price}
                    onChange={(e) => setForm({ ...form, purchase_price: e.target.value })} />
                </div>
                <div>
                  <label className="msb-label">Место хранения</label>
                  <input className="msb-input" placeholder="Склад, полка 3"
                    value={form.storage_place}
                    onChange={(e) => setForm({ ...form, storage_place: e.target.value })} />
                </div>
                <div>
                  <label className="msb-label">Статус</label>
                  <select className="msb-input" value={form.status}
                    onChange={(e) => setForm({ ...form, status: e.target.value })}>
                    {Object.entries(EQUIPMENT_STATUS).map(([value, m]) => (
                      <option key={value} value={value}>{m.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="msb-label">
                  Комплектующие внутри <span className="text-slate-400">(опционально)</span>
                </label>
                <input className="msb-input" placeholder="Через запятую: Матрица, Блок питания, Пульт"
                  value={form.components}
                  onChange={(e) => setForm({ ...form, components: e.target.value })} />
                <p className="mt-1 text-xs text-slate-400">
                  Что лежит внутри: при разборке эти позиции можно выдавать в ремонты.
                </p>
              </div>
              <div>
                <label className="msb-label">
                  Примечание <span className="text-slate-400">(опционально)</span>
                </label>
                <textarea className="msb-input resize-y" rows={2} placeholder="Скол крышки, без зарядки…"
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="submit" disabled={busy} className="msb-btn-primary">
                  {busy ? "Сохраняем…" : editingId ? "Сохранить" : "Добавить"}
                </button>
                <button type="button" onClick={() => setFormOpen(false)} disabled={busy}
                  className="msb-btn-secondary">
                  Отмена
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Модалка: просмотр */}
      {view && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setView(null)} />
          <div className="relative w-full max-w-md msb-card-solid p-6 animate-slide-up">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="msb-section-title">{view.name}</h3>
                <p className="mt-1 text-sm text-slate-500">
                  {[view.brand, view.model].filter(Boolean).join(" ") || "Без марки/модели"}
                </p>
              </div>
              <button onClick={() => setView(null)} className="text-slate-400 hover:text-slate-600">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-500">Дата покупки</dt>
                <dd className="font-medium text-slate-800">
                  {new Date(view.purchased_at).toLocaleDateString("ru")}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-500">Цена покупки</dt>
                <dd className="font-bold text-slate-800">{money(view.purchase_price)}</dd>
              </div>
              {view.storage_place && (
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-slate-500">Место хранения</dt>
                  <dd className="font-medium text-slate-800">{view.storage_place}</dd>
                </div>
              )}
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate-500">Статус</dt>
                <dd>
                  <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-bold ${
                    (EQUIPMENT_STATUS[view.status] ?? { badge: "bg-slate-100 text-slate-600" }).badge
                  }`}>
                    {EQUIPMENT_STATUS[view.status]?.label ?? view.status}
                  </span>
                </dd>
              </div>
              {(view.components?.length ?? 0) > 0 && (
                <div>
                  <dt className="text-slate-500">Комплектующие внутри</dt>
                  <dd className="mt-1.5 flex flex-wrap gap-1.5">
                    {view.components!.map((c) => (
                      <span key={c} className="msb-badge-info">{c}</span>
                    ))}
                  </dd>
                </div>
              )}
              {view.notes && (
                <div>
                  <dt className="text-slate-500">Примечание</dt>
                  <dd className="mt-1 rounded-xl bg-slate-50 px-3 py-2 text-slate-700 ring-1 ring-slate-100">
                    {view.notes}
                  </dd>
                </div>
              )}
            </dl>

            <div className="mt-5 flex flex-wrap gap-2">
              <button onClick={() => { const eq = view; setView(null); openEdit(eq); }}
                className="msb-btn-secondary flex-1">
                ✏️ Редактировать
              </button>
              <button onClick={() => remove(view)}
                className="rounded-xl bg-red-50 px-3 py-2 text-sm font-medium text-red-600 ring-1 ring-red-200 transition-colors hover:bg-red-100">
                🗑 Удалить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
