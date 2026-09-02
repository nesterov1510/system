"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, getStoredUser, money, type Repair } from "@/lib/api";
import { classIcon, normalizeClass } from "@/lib/catalog";

// Этапы (вкладки). Внутри каждого — список ремонтов таблицей.
const STAGES = [
  { key: "all", label: "Все", icon: "🗂️" },
  { key: "new", label: "Новый ремонт", icon: "🆕" },
  { key: "diag", label: "Диагностика", icon: "🔍" },
  { key: "work", label: "В ремонте", icon: "🔧" },
  { key: "done", label: "Закончен", icon: "✅" },
];

// status -> этап
const STAGE_OF: Record<string, string> = {
  Принято: "new",
  Диагностика: "diag",
  Согласование: "work",
  "Ожидание запчастей": "work",
  "В ремонте": "work",
  "Готово к выдаче": "done",
  Выдано: "done",
  "Не забрано": "done",
  Архив: "done",
  Отказ: "done",
};
const STAGE_LABEL: Record<string, string> = {
  new: "Новый ремонт",
  diag: "Диагностика",
  work: "В ремонте",
  done: "Закончен",
};
const STAGE_CHIP: Record<string, string> = {
  new: "bg-blue-50 text-blue-700 ring-blue-200",
  diag: "bg-amber-50 text-amber-700 ring-amber-200",
  work: "bg-cyan-50 text-cyan-700 ring-cyan-200",
  done: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};
function stageOf(status: string): string {
  return STAGE_OF[status] ?? "new";
}

const PAGE_SIZE = 15;

export default function RepairsBoardPage() {
  const [tab, setTab] = useState("all");
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [data, setData] = useState<{
    items: Repair[];
    total: number;
    page: number;
    page_size: number;
  }>({ items: [], total: 0, page: 1, page_size: PAGE_SIZE });
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const currentUser = getStoredUser();
  // Счётчики по этапам показывает админу/оператору.
  const showCounts = currentUser?.role === "admin" || currentUser?.role === "operator";

  // Счётчики по этапам (сколько техники на каждом этапе)
  useEffect(() => {
    if (!showCounts) return;
    api.stageCounts().then(setCounts).catch(() => {});
  }, [showCounts, data.total]);

  // Debounce поиска
  useEffect(() => {
    const t = setTimeout(() => setAppliedQ(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  // Смена вкладки/поиска сбрасывает на первую страницу
  useEffect(() => {
    setPage(1);
  }, [tab, appliedQ]);

  useEffect(() => {
    setLoading(true);
    api
      .repairs({
        stage: tab === "all" ? undefined : tab,
        q: appliedQ || undefined,
        page,
        page_size: PAGE_SIZE,
      })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [tab, appliedQ, page]);

  async function removeRepair(r: Repair) {
    if (!confirm(`Удалить ремонт «${r.number}» и все его данные? Это действие необратимо.`)) return;
    try {
      await api.deleteRepair(r.id);
      // если удалили последний на странице — уходим на предыдущую
      if (data.items.length === 1 && page > 1) setPage(page - 1);
      else {
        const d = await api.repairs({
          stage: tab === "all" ? undefined : tab,
          q: appliedQ || undefined,
          page,
          page_size: PAGE_SIZE,
        });
        setData(d);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления");
    }
  }

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

  return (
    <div>
      {/* Header */}
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-slate-900">Все ремонты</h1>
        <p className="mt-1 text-sm text-slate-500">{data.total} ремонтов</p>
      </div>

      {/* Stage tabs (для админа/оператора — счётчики техники на каждом этапе) */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {STAGES.map((s) => {
          const n = counts?.[s.key];
          return (
            <button
              key={s.key}
              onClick={() => setTab(s.key)}
              className={`flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold transition-all ${
                tab === s.key
                  ? "bg-msb-600 text-white shadow-sm"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              <span>{s.icon}</span> {s.label}
              {showCounts && n != null && (
                <span
                  className={`ml-0.5 flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-bold ${
                    tab === s.key
                      ? "bg-white/25 text-white"
                      : "bg-msb-600/10 text-msb-700"
                  }`}
                >
                  {n}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Search */}
      <div className="mb-4">
        <div className="relative">
          <svg className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск: клиент, телефон, бренд, модель…"
            className="msb-input pl-10"
          />
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> <span>{error}</span>
        </div>
      )}

      {/* List */}
      <div className="overflow-x-auto rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        <table className="w-full min-w-[760px] text-left">
          <thead className="bg-slate-50/50">
            <tr>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Техника
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Клиент
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Мастер
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Этап
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Принято
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                ETA
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 text-right">
                Оплата
              </th>
              {currentUser?.role === "admin" && (
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 text-right">
                  Действия
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={currentUser?.role === "admin" ? 8 : 7} className="py-12 text-center text-sm text-slate-400">
                  <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-msb-500 border-t-transparent align-middle" />
                  Загрузка…
                </td>
              </tr>
            ) : data.items.length === 0 ? (
              <tr>
                <td colSpan={currentUser?.role === "admin" ? 8 : 7} className="py-12 text-center text-sm text-slate-400">
                  Ремонтов не найдено
                </td>
              </tr>
            ) : (
              data.items.map((r) => {
                const stage = stageOf(r.status);
                return (
                  <tr key={r.id} className="group hover:bg-msb-50/40 transition-colors">
                    {/* Техника — на первых позициях */}
                    <td className="px-5 py-4">
                      <Link href={`/repairs/${r.id}`} className="flex items-center gap-2.5">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-lg">
                          {classIcon(r.device_type)}
                        </span>
                        <span>
                          <span className="block text-[11px] font-medium uppercase tracking-wide text-msb-600">
                            {normalizeClass(r.device_type)}
                          </span>
                          <span className="block text-sm font-bold text-slate-900">
                            {[r.brand, r.model].filter(Boolean).join(" ") || "Без модели"}
                          </span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-5 py-4 whitespace-nowrap">
                      <Link href={`/repairs/${r.id}`} className="block">
                        <span className="text-sm font-medium text-slate-800">{r.client_name}</span>
                      </Link>
                      <a href={`tel:${r.client_phone}`} className="text-xs text-msb-600 hover:text-msb-700 font-medium">
                        {r.client_phone}
                      </a>
                    </td>
                    <td className="px-5 py-4 text-xs text-slate-600">
                      {r.master_name || "—"}
                    </td>
                    <td className="px-5 py-4">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${STAGE_CHIP[stage] ?? "bg-slate-100 text-slate-600 ring-slate-300"}`}>
                        {STAGE_LABEL[stage] ?? r.status}
                      </span>
                    </td>
                    <td className="px-5 py-4 text-xs text-slate-500 whitespace-nowrap">
                      {r.accepted_at ? new Date(r.accepted_at).toLocaleDateString("ru") : "—"}
                    </td>
                    <td className="px-5 py-4 text-right text-xs text-slate-500 whitespace-nowrap">
                      {r.eta_days != null ? `${r.eta_days} дн` : "—"}
                    </td>
                    <td className="px-5 py-4 text-right whitespace-nowrap">
                      {r.price_final != null ? (
                        <span className={`text-sm font-semibold ${r.paid ? "text-emerald-600" : "text-red-600"}`}>
                          {r.paid ? "Оплачено" : money(r.price_final)}
                        </span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    {currentUser?.role === "admin" && (
                      <td className="px-5 py-4 text-right">
                        <button onClick={() => removeRepair(r)}
                          title="Удалить ремонт"
                          className="rounded-lg p-2 text-slate-300 transition-colors hover:bg-red-50 hover:text-red-600">
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {!loading && data.total > 0 && (
        <div className="mt-4 flex items-center justify-between gap-3">
          <span className="text-sm text-slate-500">
            {data.total} ремонтов · стр. {data.page} из {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="msb-btn-secondary disabled:opacity-40"
            >
              ← Назад
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="msb-btn-secondary disabled:opacity-40"
            >
              Вперёд →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
