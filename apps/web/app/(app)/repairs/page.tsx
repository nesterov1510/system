"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type Lookup, type Repair } from "@/lib/api";

const STATUSES = [
  "Принято",
  "Диагностика",
  "Согласование",
  "Ожидание запчастей",
  "В ремонте",
  "Готово к выдаче",
  "Выдано",
  "Не забрано",
  "Архив",
  "Отказ",
];

// Цветовые стили для статусов (для бейджей)
const STATUS_COLORS: Record<string, string> = {
  Принято: "msb-badge-info",
  Диагностика: "msb-badge-warning",
  Согласование: "msb-badge-purple",
  "Ожидание запчастей": "bg-orange-100 text-orange-700",
  "В ремонте": "msb-badge-cyan",
  "Готово к выдаче": "msb-badge-success",
  Выдано: "msb-badge-gray",
  "Не забрано": "bg-rose-100 text-rose-700",
  Архив: "msb-badge-gray",
  Отказ: "msb-badge-danger",
};

const STATUS_DOT: Record<string, string> = {
  Принято: "bg-blue-500",
  Диагностика: "bg-amber-500",
  Согласование: "bg-purple-500",
  "Ожидание запчастей": "bg-orange-500",
  "В ремонте": "bg-cyan-500",
  "Готово к выдаче": "bg-emerald-500",
  Выдано: "bg-slate-400",
  "Не забрано": "bg-rose-500",
  Архив: "bg-slate-300",
  Отказ: "bg-red-500",
};

const DEVICE_ICON_MAP: Record<string, string> = {
  ТВ: "📺",
  Монитор: "🖥️",
  Аудио: "🔊",
  Другое: "⚙️",
};

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString("ru") : "—";
}

export default function RepairsBoardPage() {
  const [repairs, setRepairs] = useState<Repair[]>([]);
  const [masters, setMasters] = useState<Lookup[]>([]);
  const [q, setQ] = useState("");
  const [masterFilter, setMasterFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  function load() {
    api.repairs().then(setRepairs).catch((e) => setError(e.message));
  }
  useEffect(load, []);
  useEffect(() => {
    api.masters().then(setMasters).catch(() => {});
  }, []);

  async function move(repair: Repair, status: string) {
    setRepairs((prev) =>
      prev.map((r) => (r.id === repair.id ? { ...r, status } : r)),
    );
    try {
      await api.updateRepair(repair.id, { status });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
      load(); // Reload to revert UI if API fails
    }
  }

  const filtered = useMemo(() => {
    return repairs.filter((r) => {
      if (masterFilter && r.master_id !== masterFilter) return false;
      if (statusFilter && r.status !== statusFilter) return false;
      if (q) {
        const hay = `${r.number} ${r.client_name ?? ""} ${r.client_phone ?? ""} ${r.brand ?? ""} ${r.model ?? ""}`.toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [repairs, masterFilter, statusFilter, q]);

  const totalCount = repairs.length;
  const activeCount = repairs.filter(
    (r) => !["Выдано", "Архив", "Отказ", "Не забрано"].includes(r.status)
  ).length;

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Все ремонты</h1>
            <p className="mt-1 text-sm text-slate-500">
              {totalCount} всего · {activeCount} в работе
            </p>
          </div>
          <Link href="/repairs/new" className="msb-btn-primary">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Новая приёмка
          </Link>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <svg className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск: номер, телефон, бренд…"
            className="msb-input pl-10"
          />
        </div>
        <select
          value={masterFilter}
          onChange={(e) => setMasterFilter(e.target.value)}
          className="msb-input w-auto min-w-[140px]"
        >
          <option value="">Все мастера</option>
          {masters.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="msb-input w-auto min-w-[140px]"
        >
          <option value="">Все статусы</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {(q || masterFilter || statusFilter) && (
          <button
            onClick={() => { setQ(""); setMasterFilter(""); setStatusFilter(""); }}
            className="msb-btn-ghost text-sm text-slate-500"
          >
            Сбросить
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span>
          <span>{error}</span>
        </div>
      )}

      {/* Repairs List */}
      <div className="rounded-2xl bg-white shadow-sm ring-1 ring-slate-200 overflow-hidden">
        <table className="w-full text-left">
          <thead className="bg-slate-50/50">
            <tr>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <div className="flex items-center gap-1">
                  № Ремонта
                </div>
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <div className="flex items-center gap-1">
                  Клиент
                </div>
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <div className="flex items-center gap-1">
                  Техника
                </div>
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <div className="flex items-center gap-1">
                  Мастер
                </div>
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <div className="flex items-center gap-1">
                  Статус
                </div>
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 text-right">
                <div className="flex items-center gap-1">
                  ETA
                </div>
              </th>
              <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 text-right">
                <div className="flex items-center gap-1">
                  Оплата
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && !error && (
              <tr className="text-center text-slate-400">
                <td colSpan={7} className="py-8 text-sm">
                  Ремонтов не найдено
                </td>
              </tr>
            )}
            {filtered.map((r) => (
              <tr key={r.id} className="group odd:bg-slate-50/30 hover:bg-msb-50/50 transition-colors duration-200">
                <td className="px-5 py-4 text-sm font-mono font-bold text-slate-900 whitespace-nowrap">
                  <Link href={`/repairs/${r.id}`} className="flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${STATUS_DOT[r.status] ?? "bg-slate-400"}`} />
                    {r.number}
                  </Link>
                </td>
                <td className="px-5 py-4 whitespace-nowrap">
                  <div className="text-sm font-medium text-slate-800">{r.client_name}</div>
                  <a href={`tel:${r.client_phone}`} className="text-xs text-msb-600 hover:text-msb-700 font-medium">
                    {r.client_phone}
                  </a>
                </td>
                <td className="px-5 py-4 text-xs text-slate-600">
                  <span className="mr-1">{DEVICE_ICON_MAP[r.device_type] ?? '⚙️'}</span>
                  {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
                </td>
                <td className="px-5 py-4 text-xs text-slate-600">
                  {r.master?.name || "—"}
                </td>
                <td className="px-5 py-4">
                  <span className={`msb-badge ${STATUS_COLORS[r.status] ?? "msb-badge-gray"}`}>
                    {r.status}
                  </span>
                </td>
                <td className="px-5 py-4 text-right text-xs text-slate-500 whitespace-nowrap">
                  {r.eta_days != null ? `${r.eta_days} дн` : "—"}
                </td>
                <td className="px-5 py-4 text-right whitespace-nowrap">
                  {r.price_final != null ? (
                    <span className={`font-semibold ${r.paid ? "text-emerald-600" : "text-red-600"}`}>
                      {r.paid ? "Оплачено" : "Не оплачено"}
                    </span>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}