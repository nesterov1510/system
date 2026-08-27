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

// Новые стили для карточек, основанные на MSB
const STATUS_CARD_STYLES: Record<string, string> = {
  Принято: "border-l-blue-500 bg-gradient-to-r from-blue-50/80 to-white",
  Диагностика: "border-l-amber-500 bg-gradient-to-r from-amber-50/80 to-white",
  Согласование: "border-l-purple-500 bg-gradient-to-r from-purple-50/80 to-white",
  "Ожидание запчастей": "border-l-orange-500 bg-gradient-to-r from-orange-50/80 to-white",
  "В ремонте": "border-l-cyan-500 bg-gradient-to-r from-cyan-50/80 to-white",
  "Готово к выдаче": "border-l-emerald-500 bg-gradient-to-r from-emerald-50/80 to-white",
  Выдано: "border-l-slate-400 bg-gradient-to-r from-slate-50/80 to-white",
  "Не забрано": "border-l-rose-500 bg-gradient-to-r from-rose-50/80 to-white",
  Архив: "border-l-slate-300 bg-gradient-to-r from-slate-50/60 to-white",
  Отказ: "border-l-red-500 bg-gradient-to-r from-red-50/80 to-white",
};

const STATUS_COLUMN_BG: Record<string, string> = {
  Принято: "bg-blue-50/30",
  Диагностика: "bg-amber-50/30",
  Согласование: "bg-purple-50/30",
  "Ожидание запчастей": "bg-orange-50/30",
  "В ремонте": "bg-cyan-50/30",
  "Готово к выдаче": "bg-emerald-50/30",
  Выдано: "bg-slate-100/50",
  "Не забрано": "bg-rose-50/30",
  Архив: "bg-slate-50/50",
  Отказ: "bg-red-50/30",
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
      load();
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

  const grouped = useMemo(() => {
    const g: Record<string, Repair[]> = {};
    for (const s of STATUSES) g[s] = [];
    for (const r of filtered) {
      (g[r.status] ?? (g[r.status] = [])).push(r);
    }
    return g;
  }, [filtered]);

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
            <h1 className="text-2xl font-bold text-slate-900">Доска ремонтов</h1>
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

      {/* Kanban */}
      <div className="flex gap-4 overflow-x-auto pb-4 custom-scroll">
        {STATUSES.map((s) => {
          const items = grouped[s] ?? [];
          return (
            <div
              key={s}
              className={`w-72 shrink-0 rounded-2xl p-3 ${STATUS_COLUMN_BG[s] ?? "bg-slate-50/50"}`}
            >
              {/* Column header */}
              <div className="mb-3 flex items-center justify-between px-1">
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[s] ?? "bg-slate-400"}`} />
                  <span className="text-xs font-semibold text-slate-600">{s}</span>
                </div>
                <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-white/80 px-1.5 text-xs font-medium text-slate-500 shadow-sm ring-1 ring-slate-200/50">
                  {items.length}
                </span>
              </div>

              {/* Cards */}
              <div className="space-y-2.5">
                {items.map((r) => (
                  <div
                    key={r.id}
                    className={`rounded-xl border-l-4 shadow-sm ring-1 ring-slate-200/50 transition-all duration-200 hover:shadow-md ${STATUS_CARD_STYLES[s] ?? "bg-white"}`}
                  >
                    <Link href={`/repairs/${r.id}`} className="block p-3.5">
                      {/* Top row: Number + Payment Status */}
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-lg font-bold text-slate-900">
                          {r.number}
                        </span>
                        {r.paid ? (
                          <span className="msb-badge-success text-[10px] px-1.5 py-0.5">Оплачено</span>
                        ) : r.price_final != null ? (
                          <span className="msb-badge-danger text-[10px] px-1.5 py-0.5">Не оплачено</span>
                        ) : (
                          <span className="msb-badge-gray text-[10px] px-1.5 py-0.5">Цена не установлена</span>
                        )}
                      </div>

                      {/* Device info */}
                      <div className="mt-1.5 text-xs font-medium text-slate-700">
                        <span className="mr-1">{DEVICE_ICON_MAP[r.device_type] ?? '⚙️'}</span>
                        {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
                      </div>

                      {/* Client info */}
                      {r.client_name && (
                        <div className="mt-1 flex items-center gap-1 text-xs text-slate-500">
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                          </svg>
                          {r.client_name}
                        </div>
                      )}

                      {/* Phone and ETA */}
                      <div className="mt-1.5 flex items-center justify-between gap-3 text-sm">
                        <a href={`tel:${r.client_phone}`} className="flex items-center gap-1.5 text-msb-600 font-medium hover:text-msb-700">
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.586a1 1 0 01.954.783l3.586 14.34A1 1 0 0116.954 21h4.586a2 2 0 012-2V5a2 2 0 00-2-2h-4.143a2 2 0 00-2 2V5z" />
                          </svg>
                          {r.client_phone}
                        </a>
                        {r.eta_days != null && (
                          <span className="flex items-center gap-1 text-xs text-slate-500">
                            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            ~{r.eta_days} дн
                          </span>
                        )}
                      </div>
                    </Link>
                    <div className="border-t border-slate-100 px-3.5 py-2">
                      <select
                        value={r.status}
                        onChange={(e) => move(r, e.target.value)}
                        className="w-full rounded-lg border-0 bg-slate-50 px-2 py-1.5 text-xs font-medium text-slate-600 ring-1 ring-slate-200/50 focus:ring-2 focus:ring-msb-500/30"
                      >
                        {STATUSES.map((st) => (
                          <option key={st} value={st}>{st}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                ))}
                {items.length === 0 && (
                  <div className="flex items-center justify-center py-8 text-xs text-slate-400">
                    Нет ремонтов в этом статусе
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}