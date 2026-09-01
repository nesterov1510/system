"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type Lookup, type Repair } from "@//lib/api";

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

// Типы техники — ТВ вынесен на первую позицию.
const DEVICE_TYPES = ["ТВ", "Монитор", "Аудио", "Другое"];

// Группировка доски по этапам ремонта.
const BOARD_GROUPS: Array<{
  key: string;
  label: string;
  accent: string;
  statuses: string[];
}> = [
  {
    key: "new",
    label: "Новый ремонт",
    accent: "border-t-sky-400",
    statuses: ["Принято"],
  },
  {
    key: "diag",
    label: "Диагностика в ремонте",
    accent: "border-t-amber-400",
    statuses: ["Диагностика", "Согласование", "Ожидание запчастей", "В ремонте"],
  },
  {
    key: "done",
    label: "Закончен",
    accent: "border-t-emerald-400",
    statuses: ["Готово к выдаче", "Выдано", "Не забрано", "Архив", "Отказ"],
  },
];

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString("ru") : "—";
}

// ТВ-ремонты всегда в начале списка, затем по дате приёмки (свежие выше).
function sortTvFirst(list: Repair[]): Repair[] {
  return [...list].sort((a, b) => {
    const at = a.device_type === "ТВ" ? 0 : 1;
    const bt = b.device_type === "ТВ" ? 0 : 1;
    if (at !== bt) return at - bt;
    return (b.accepted_at ?? "").localeCompare(a.accepted_at ?? "");
  });
}

export default function RepairsBoardPage() {
  const [repairs, setRepairs] = useState<Repair[]>([]);
  const [masters, setMasters] = useState<Lookup[]>([]);
  const [q, setQ] = useState("");
  const [masterFilter, setMasterFilter] = useState("");
  const [deviceFilter, setDeviceFilter] = useState("");
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
      if (deviceFilter && r.device_type !== deviceFilter) return false;
      if (q) {
        const hay = `${r.client_name ?? ""} ${r.client_phone ?? ""} ${r.brand ?? ""} ${r.model ?? ""} ${r.master_name ?? ""} ${r.device_type ?? ""}`.toLowerCase();
        if (!hay.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [repairs, masterFilter, deviceFilter, q]);

  const groups = useMemo(
    () =>
      BOARD_GROUPS.map((g) => ({
        ...g,
        items: sortTvFirst(filtered.filter((r) => g.statuses.includes(r.status))),
      })),
    [filtered],
  );

  const totalCount = repairs.length;
  const activeCount = repairs.filter(
    (r) => !["Выдано", "Архив", "Отказ", "Не забрано"].includes(r.status),
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
      <div className="mb-6 grid gap-2.5 sm:flex sm:flex-wrap sm:items-center sm:gap-3">
        <div className="relative min-w-0 sm:flex-1">
          <svg className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск: телефон, клиент, бренд, мастер…"
            className="msb-input pl-10"
          />
        </div>
        <select
          value={deviceFilter}
          onChange={(e) => setDeviceFilter(e.target.value)}
          className="msb-input w-full sm:w-auto sm:min-w-[130px]"
        >
          <option value="">Вся техника</option>
          {DEVICE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          value={masterFilter}
          onChange={(e) => setMasterFilter(e.target.value)}
          className="msb-input w-full sm:w-auto sm:min-w-[140px]"
        >
          <option value="">Все мастера</option>
          {masters.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
        {(q || masterFilter || deviceFilter) && (
          <button
            onClick={() => { setQ(""); setMasterFilter(""); setDeviceFilter(""); }}
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

      {/* Kanban board — 3 колонки по этапам */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {groups.map((g) => (
          <section
            key={g.key}
            className={`flex flex-col rounded-2xl bg-slate-50/60 shadow-sm ring-1 ring-slate-200 border-t-4 ${g.accent}`}
          >
            <div className="flex items-center justify-between px-4 py-3">
              <h2 className="text-sm font-semibold text-slate-700">{g.label}</h2>
              <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-500 ring-1 ring-slate-200">
                {g.items.length}
              </span>
            </div>
            <div className="flex flex-col gap-2.5 px-3 pb-3">
              {g.items.length === 0 && (
                <div className="rounded-xl border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
                  Нет ремонтов
                </div>
              )}
              {g.items.map((r) => (
                <RepairCard key={r.id} r={r} onMove={move} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function RepairCard({ r, onMove }: { r: Repair; onMove: (r: Repair, status: string) => void }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm transition-shadow hover:shadow-md">
      <Link href={`/repairs/${r.id}`} className="block">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-800">{r.client_name}</div>
            <a
              href={`tel:${r.client_phone}`}
              onClick={(e) => e.stopPropagation()}
              className="text-xs text-msb-600 hover:text-msb-700 font-medium"
            >
              {r.client_phone}
            </a>
          </div>
          <span className="shrink-0 text-lg leading-none" title={r.device_type}>
            {DEVICE_ICON_MAP[r.device_type] ?? "⚙️"}
          </span>
        </div>

        <div className="mt-1.5 text-xs text-slate-600">
          {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          <span>Мастер: {r.master_name || "—"}</span>
          <span>Принят: {fmt(r.accepted_at).split(",")[0]}</span>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className={`msb-badge ${STATUS_COLORS[r.status] ?? "msb-badge-gray"}`}>
            {r.status}
          </span>
          {r.eta_days != null && (
            <span className="text-xs text-slate-400">~{r.eta_days} дн</span>
          )}
          {r.price_final != null && (
            <span className={`text-xs font-semibold ${r.paid ? "text-emerald-600" : "text-red-600"}`}>
              {r.paid ? "Оплачено" : "Не оплачено"}
            </span>
          )}
        </div>
      </Link>

      <select
        value={r.status}
        onChange={(e) => onMove(r, e.target.value)}
        className="mt-2.5 w-full rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs text-slate-600 focus:border-msb-400 focus:outline-none"
        title="Сменить статус"
      >
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </div>
  );
}
