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

const STATUS_STYLES: Record<string, string> = {
  Принято: "bg-blue-50 border-blue-200",
  Диагностика: "bg-amber-50 border-amber-200",
  Согласование: "bg-purple-50 border-purple-200",
  "Ожидание запчастей": "bg-orange-50 border-orange-200",
  "В ремонте": "bg-cyan-50 border-cyan-200",
  "Готово к выдаче": "bg-green-50 border-green-200",
  Выдано: "bg-gray-50 border-gray-200",
  Отказ: "bg-red-50 border-red-200",
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

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Доска ремонтов</h1>
        <Link
          href="/repairs/new"
          className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white"
        >
          + Приёмка
        </Link>
      </div>

      {/* Фильтры */}
      <div className="mb-4 flex flex-wrap gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Поиск: № / телефон / бренд"
          className="min-w-[200px] flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
        <select
          value={masterFilter}
          onChange={(e) => setMasterFilter(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
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
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
        >
          <option value="">Все статусы</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      {/* Канбан (горизонтальный скролл на мобильном) */}
      <div className="flex gap-3 overflow-x-auto pb-4">
        {STATUSES.map((s) => (
          <div
            key={s}
            className="w-64 shrink-0 rounded-xl bg-gray-100/70 p-2"
          >
            <div className="mb-2 flex items-center justify-between px-1">
              <span className="text-xs font-semibold text-gray-500">{s}</span>
              <span className="rounded-full bg-white px-2 py-0.5 text-xs text-gray-500">
                {grouped[s]?.length ?? 0}
              </span>
            </div>
            <div className="space-y-2">
              {(grouped[s] ?? []).map((r) => (
                <div
                  key={r.id}
                  className={`block rounded-lg border bg-white p-3 ${STATUS_STYLES[s] ?? "border-gray-200"}`}
                >
                  <Link href={`/repairs/${r.id}`} className="block">
                    <div className="font-mono text-sm font-semibold text-gray-900">
                      {r.number}
                    </div>
                    <div className="mt-0.5 text-xs text-gray-600">
                      {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
                    </div>
                    <div className="mt-0.5 text-xs text-gray-500">
                      {r.client_name}
                    </div>
                  </Link>
                  <select
                    value={r.status}
                    onChange={(e) => move(r, e.target.value)}
                    className="mt-2 w-full rounded border border-gray-200 px-1 py-1 text-xs text-gray-600"
                  >
                    {STATUSES.map((st) => (
                      <option key={st} value={st}>
                        {st}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
