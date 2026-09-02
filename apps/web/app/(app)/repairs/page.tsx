"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, getStoredUser, type Lookup, type Repair } from "@/lib/api";
import { DEVICE_CLASSES, classIcon, normalizeClass } from "@/lib/catalog";

// Группы, в которые разбивается доска «Все ремонты».
const GROUPS = [
  { key: "new", title: "Новый ремонт", icon: "🆕", dot: "bg-blue-500",
    head: "text-blue-700 bg-blue-50 ring-blue-200",
    statuses: ["Принято"] },
  { key: "diag", title: "Диагностика", icon: "🔍", dot: "bg-amber-500",
    head: "text-amber-700 bg-amber-50 ring-amber-200",
    statuses: ["Диагностика"] },
  { key: "work", title: "В ремонте", icon: "🔧", dot: "bg-cyan-500",
    head: "text-cyan-700 bg-cyan-50 ring-cyan-200",
    statuses: ["Согласование", "Ожидание запчастей", "В ремонте"] },
  { key: "done", title: "Закончен", icon: "✅", dot: "bg-emerald-500",
    head: "text-emerald-700 bg-emerald-50 ring-emerald-200",
    statuses: ["Готово к выдаче", "Выдано", "Не забрано", "Архив", "Отказ"] },
];

const STATUS_CHIP: Record<string, string> = {
  Принято: "bg-blue-50 text-blue-700 ring-blue-200",
  Диагностика: "bg-amber-50 text-amber-700 ring-amber-200",
  Согласование: "bg-purple-50 text-purple-700 ring-purple-200",
  "Ожидание запчастей": "bg-orange-50 text-orange-700 ring-orange-200",
  "В ремонте": "bg-cyan-50 text-cyan-700 ring-cyan-200",
  "Готово к выдаче": "bg-emerald-50 text-emerald-700 ring-emerald-200",
  Выдано: "bg-slate-100 text-slate-600 ring-slate-300",
  "Не забрано": "bg-rose-50 text-rose-700 ring-rose-200",
  Архив: "bg-slate-100 text-slate-500 ring-slate-300",
  Отказ: "bg-red-50 text-red-700 ring-red-200",
};

function groupFor(status: string) {
  return GROUPS.find((g) => g.statuses.includes(status)) ?? GROUPS[0];
}

export default function RepairsBoardPage() {
  const [repairs, setRepairs] = useState<Repair[]>([]);
  const [masters, setMasters] = useState<Lookup[]>([]);
  const [q, setQ] = useState("");
  const [masterFilter, setMasterFilter] = useState("");
  const [classFilter, setClassFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const currentUser = getStoredUser();

  function load() {
    api.repairs().then(setRepairs).catch((e) => setError(e.message));
  }

  async function removeRepair(r: Repair) {
    if (!confirm(`Удалить ремонт клиента «${r.client_name}» и все его данные? Это действие необратимо.`)) return;
    try {
      await api.deleteRepair(r.id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления");
    }
  }
  useEffect(load, []);
  useEffect(() => {
    api.masters().then(setMasters).catch(() => {});
  }, []);

  const filtered = useMemo(() => {
    return repairs.filter((r) => {
      if (masterFilter && r.master_id !== masterFilter) return false;
      if (classFilter && normalizeClass(r.device_type) !== classFilter) return false;
      if (q) {
        const hay = `${r.client_name ?? ""} ${r.client_phone ?? ""} ${r.brand ?? ""} ${r.model ?? ""}`.toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [repairs, masterFilter, classFilter, q]);

  const byGroup = useMemo(() => {
    const map: Record<string, Repair[]> = {};
    for (const g of GROUPS) map[g.key] = [];
    for (const r of filtered) map[groupFor(r.status).key].push(r);
    return map;
  }, [filtered]);

  const totalCount = repairs.length;
  const hasFilters = Boolean(q || masterFilter || classFilter);
  const reset = () => { setQ(""); setMasterFilter(""); setClassFilter(""); };

  return (
    <div>
      {/* Header */}
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-slate-900">Все ремонты</h1>
        <p className="mt-1 text-sm text-slate-500">
          {totalCount} всего · в работе{" "}
          {repairs.filter((r) => !["Выдано", "Архив", "Отказ", "Не забрано"].includes(r.status)).length}
        </p>
      </div>

      {/* Filters */}
      <div className="mb-5 flex flex-wrap items-center gap-2.5">
        <div className="relative min-w-[200px] flex-1">
          <svg className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск: телефон, клиент, бренд…"
            className="msb-input pl-10"
          />
        </div>
        <select
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
          className="msb-input w-full sm:w-auto"
        >
          <option value="">Все классы</option>
          {DEVICE_CLASSES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.icon} {c.label}
            </option>
          ))}
        </select>
        <select
          value={masterFilter}
          onChange={(e) => setMasterFilter(e.target.value)}
          className="msb-input w-full sm:w-auto"
        >
          <option value="">Все мастера</option>
          {masters.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
        {hasFilters && (
          <button onClick={reset} className="msb-btn-ghost text-sm text-slate-500">
            Сбросить
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> <span>{error}</span>
        </div>
      )}

      {/* Board columns */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {GROUPS.map((g) => {
          const list = byGroup[g.key];
          return (
            <section key={g.key} className="flex min-h-[120px] flex-col rounded-2xl bg-slate-100/70 ring-1 ring-slate-200/70">
              <header className={`flex items-center gap-2 rounded-t-2xl px-4 py-2.5 ring-1 ${g.head}`}>
                <span className="text-base leading-none">{g.icon}</span>
                <span className="text-sm font-bold">{g.title}</span>
                <span className={`ml-auto flex h-6 min-w-6 items-center justify-center rounded-full bg-white/70 px-1.5 text-xs font-bold ${g.dot}`}>
                  {list.length}
                </span>
              </header>
              <div className="flex flex-col gap-2.5 p-2.5">
                {list.length === 0 && (
                  <p className="px-1 py-4 text-center text-xs text-slate-400">Пусто</p>
                )}
                {list.map((r) => (
                  <Link
                    key={r.id}
                    href={`/repairs/${r.id}`}
                    className="group rounded-xl bg-white p-3 shadow-sm ring-1 ring-slate-200 transition-all hover:ring-2 hover:ring-msb-400 hover:shadow-md"
                  >
                    {/* Техника — на первых позициях */}
                    <div className="flex items-start gap-2">
                      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-lg">
                        {classIcon(r.device_type)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] font-medium uppercase tracking-wide text-msb-600">
                          {normalizeClass(r.device_type)}
                        </div>
                        <div className="truncate text-sm font-bold text-slate-900">
                          {[r.brand, r.model].filter(Boolean).join(" ") || "Без модели"}
                        </div>
                      </div>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${STATUS_CHIP[r.status] ?? "bg-slate-100 text-slate-600 ring-slate-300"}`}>
                        {r.status}
                      </span>
                      {currentUser?.role === "admin" && (
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            removeRepair(r);
                          }}
                          title="Удалить ремонт"
                          className="shrink-0 rounded-lg p-1 text-slate-300 transition-colors hover:bg-red-50 hover:text-red-600"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      )}
                    </div>

                    {/* Клиент */}
                    <div className="mt-2.5 border-t border-slate-100 pt-2">
                      <div className="flex items-center gap-1.5 text-sm font-medium text-slate-800">
                        <span className="text-xs">👤</span>
                        <span className="truncate">{r.client_name}</span>
                      </div>
                      <a href={`tel:${r.client_phone}`} className="mt-0.5 flex items-center gap-1.5 text-xs text-msb-600 font-medium">
                        <span className="text-[10px]">📞</span> {r.client_phone}
                      </a>
                    </div>

                    {/* Мастер + срок + оплата */}
                    <div className="mt-2 flex items-center justify-between gap-2 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
                      <span className="flex min-w-0 items-center gap-1">
                        <span className="text-[10px]">🔧</span>
                        <span className="truncate">{r.master_name || "—"}</span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        {r.eta_days != null && <span>ETA {r.eta_days}д</span>}
                        {r.price_final != null && (
                          <span className={r.paid ? "font-semibold text-emerald-600" : "font-semibold text-red-600"}>
                            {r.paid ? "опл." : "не опл."}
                          </span>
                        )}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      {filtered.length === 0 && !error && (
        <div className="mt-4 rounded-2xl bg-white py-10 text-center text-sm text-slate-400 shadow-sm ring-1 ring-slate-200">
          Ремонтов не найдено
        </div>
      )}
    </div>
  );
}
