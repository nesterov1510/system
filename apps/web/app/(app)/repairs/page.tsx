"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Repair } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  Принято: "bg-blue-100 text-blue-700",
  Диагностика: "bg-amber-100 text-amber-700",
  Согласование: "bg-purple-100 text-purple-700",
  "Ожидание запчастей": "bg-orange-100 text-orange-700",
  "В ремонте": "bg-cyan-100 text-cyan-700",
  "Готово к выдаче": "bg-green-100 text-green-700",
  Выдано: "bg-gray-100 text-gray-600",
  Отказ: "bg-red-100 text-red-700",
};

export default function RepairsPage() {
  const [repairs, setRepairs] = useState<Repair[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .repairs()
      .then(setRepairs)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Ремонты</h1>
        <Link
          href="/repairs/new"
          className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white"
        >
          + Приёмка
        </Link>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {repairs.length === 0 && !error && (
        <p className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-gray-400">
          Пока нет ремонтов. Нажмите «+ Приёмка».
        </p>
      )}

      <ul className="space-y-2">
        {repairs.map((r) => (
          <li key={r.id}>
            <Link
              href={`/repairs/${r.id}`}
              className="block rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-200 transition hover:ring-slate-300"
            >
            <div className="flex items-center justify-between">
              <span className="font-mono font-semibold text-slate-900">
                {r.number}
              </span>
              <span
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                  STATUS_COLORS[r.status] ?? "bg-gray-100 text-gray-600"
                }`}
              >
                {r.status}
              </span>
            </div>
            <div className="mt-1 text-sm text-gray-600">
              {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
            </div>
            <div className="mt-1 text-sm text-gray-500">
              {r.client_name} · {r.client_phone}
            </div>
            <div className="mt-2 flex gap-2 text-xs text-gray-400">
              <span>принято {new Date(r.accepted_at).toLocaleString("ru")}</span>
            </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
