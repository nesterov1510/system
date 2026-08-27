"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Repair } from "@/lib/api";

const TABS = [
  { kind: "agree", label: "Согласовать цену", icon: "💰" },
  { kind: "ready", label: "Сказать «готово»", icon: "✅" },
  { kind: "overdue", label: "Просрочка хранения", icon: "⚠️" },
];

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

export default function CallcenterPage() {
  const [kind, setKind] = useState("agree");
  const [items, setItems] = useState<Repair[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .callcenterQueue(kind)
      .then(setItems)
      .catch((e) => setError(e.message));
  }, [kind]);

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Call-центр</h1>
        <p className="mt-1 text-sm text-slate-500">Очередь звонков и уведомлений клиентов</p>
      </div>

      {/* Tabs */}
      <div className="mb-6 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t.kind} onClick={() => setKind(t.kind)}
            className={`flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium transition-all ${
              kind === t.kind
                ? "bg-msb-600 text-white shadow-sm"
                : "bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-slate-300"}`}>
            <span>{t.icon}</span>
            <span>{t.label}</span>
            {kind === t.kind && items.length > 0 && (
              <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-white/20 px-1.5 text-xs font-bold">
                {items.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}

      {items.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 py-16 text-slate-400">
          <span className="text-4xl mb-3">📞</span>
          <p className="text-sm font-medium">Очередь пуста</p>
          <p className="text-xs mt-1">Нечего согласовывать или обзванивать</p>
        </div>
      )}

      <div className="space-y-3">
        {items.map((r) => (
          <Link key={r.id} href={`/repairs/${r.id}`}
            className="group block animate-slide-up">
            <div className="msb-card-solid p-5 transition-all duration-200 group-hover:shadow-md group-hover:-translate-y-0.5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-base font-bold text-slate-900">
                      {r.number}
                    </span>
                    <span className={`h-2 w-2 rounded-full ${STATUS_DOT[r.status] ?? "bg-slate-400"}`} />
                    <span className="text-xs text-slate-500">{r.status}</span>
                  </div>
                  <div className="mt-1.5 text-sm font-medium text-slate-700">
                    {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
                  </div>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
                <div className="flex items-center gap-1.5 text-slate-600">
                  <span>👤</span>
                  <span>{r.client_name}</span>
                </div>
                <a href={`tel:${r.client_phone}`} onClick={(e) => e.stopPropagation()}
                  className="flex items-center gap-1.5 text-msb-600 hover:text-msb-700 font-medium">
                  <span>📞</span>
                  <span>{r.client_phone}</span>
                </a>
              </div>

              {kind === "overdue" && r.storage_until && (
                <div className="mt-2 flex items-center gap-1.5 text-xs text-red-600">
                  <span>⚠</span>
                  <span>Хранится до {new Date(r.storage_until).toLocaleDateString("ru")}</span>
                </div>
              )}

              {r.fault_client && (
                <div className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500 ring-1 ring-slate-100">
                  «{r.fault_client}»
                </div>
              )}

              {r.price_final != null && (
                <div className="mt-2 flex items-center gap-3 text-sm">
                  <span className="msb-badge-info">Цена: {new Intl.NumberFormat("ru").format(r.price_final)} ман.</span>
                  {r.paid && <span className="msb-badge-success">Оплачено</span>}
                </div>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}