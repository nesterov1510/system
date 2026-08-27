"use client";

import { useEffect, useState } from "react";
import { fetchPublicRepair, money, type PublicRepair } from "@/lib/api";

const STATUS_ORDER = [
  "Принято",
  "Диагностика",
  "Согласование",
  "Ожидание запчастей",
  "В ремонте",
  "Готово к выдаче",
  "Выдано",
];

const STATUS_COLORS: Record<string, string> = {
  Принято: "bg-blue-500",
  Диагностика: "bg-amber-500",
  Согласование: "bg-purple-500",
  "Ожидание запчастей": "bg-orange-500",
  "В ремонте": "bg-cyan-500",
  "Готово к выдаче": "bg-emerald-500",
  Выдано: "bg-slate-400",
  Отказ: "bg-red-500",
};

const STATUS_LABELS: Record<string, string> = {
  Принято: "Принято в ремонт",
  Диагностика: "Диагностика",
  Согласование: "Согласование",
  "Ожидание запчастей": "Ожидание запчастей",
  "В ремонте": "В ремонте",
  "Готово к выдаче": "Готово к выдаче",
  Выдано: "Выдано",
  Отказ: "Отказ",
};

function fmt(dt?: string | null) {
  return dt ? new Date(dt).toLocaleDateString("ru") : "—";
}

export default function PublicRepairView({ token }: { token: string }) {
  const [data, setData] = useState<PublicRepair | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPublicRepair(token)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Ошибка"));
  }, [token]);

  if (error) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50 p-6">
        <div className="w-full max-w-md msb-card-solid p-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-100 text-3xl">
            🔍
          </div>
          <h1 className="text-lg font-bold text-slate-800">Ремонт не найден</h1>
          <p className="mt-2 text-sm text-slate-500">{error}</p>
          <p className="mt-1 text-sm text-slate-400">Проверьте QR-код или обратитесь в сервисный центр.</p>
          <a href="tel:" className="mt-6 inline-flex items-center gap-2 text-msb-600 font-medium text-sm hover:text-msb-700">
            📞 Позвонить в сервис
          </a>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50 text-slate-400">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-msb-500 border-t-transparent" />
          <span className="text-sm font-medium">Загрузка…</span>
        </div>
      </main>
    );
  }

  const statusIndex = STATUS_ORDER.indexOf(data.status);
  const progress = statusIndex >= 0
    ? Math.round((statusIndex / (STATUS_ORDER.length - 1)) * 100)
    : 0;

  const complect = (data.complectation as { items?: string[] } | null)?.items;
  const stats = data.city_stats;

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50/30">
      {/* Header */}
      <div className="bg-gradient-to-r from-msb-600 to-msb-800 px-4 py-6 text-white">
        <div className="mx-auto max-w-md">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/20 backdrop-blur-sm">
              <span className="text-xs font-extrabold">MSB</span>
            </div>
            <span className="text-sm font-medium opacity-80">Мастер Сервис Бюро</span>
          </div>
          <p className="text-sm font-medium text-msb-200">Статус вашего ремонта</p>
          <h1 className="mt-1 font-mono text-2xl font-extrabold tracking-tight">{data.number}</h1>
        </div>
      </div>

      <div className="mx-auto max-w-md px-4 -mt-4">
        {/* Status card */}
        <div className="msb-card-solid p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className={`h-3 w-3 rounded-full ${STATUS_COLORS[data.status] ?? "bg-slate-400"}`} />
              <span className="text-base font-semibold text-slate-800">
                {STATUS_LABELS[data.status] ?? data.status}
              </span>
            </div>
            <span className="text-sm text-slate-400">{progress}%</span>
          </div>
          <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full rounded-full progress-bar ${STATUS_COLORS[data.status] ?? "bg-slate-400"}`}
              style={{ width: `${Math.max(progress, 4)}%` }}
            />
          </div>

          <dl className="mt-5 space-y-3 text-sm">
            <PublicRow label="Техника" value={[data.device_type, data.brand, data.model].filter(Boolean).join(" · ")} />
            {complect && complect.length > 0 && (
              <PublicRow label="Комплект" value={complect.join(", ")} />
            )}
            <PublicRow label="Принято" value={fmt(data.accepted_at)} />
            {data.eta_days != null && (
              <PublicRow label="Плановый срок" value={`~${data.eta_days} дней`} />
            )}
            {data.ready_at && <PublicRow label="Готово" value={fmt(data.ready_at)} />}
            {data.issued_at && <PublicRow label="Выдано" value={fmt(data.issued_at)} />}
            {data.storage_until && (
              <PublicRow label="Хранение до" value={fmt(data.storage_until)} />
            )}
          </dl>
        </div>

        {/* Storage info */}
        {data.storage_text && (
          <div className="mt-3 rounded-2xl bg-amber-50 p-5 ring-1 ring-amber-200">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-amber-800">
              <span>⚠️</span> Условия хранения
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-amber-900">
              {data.storage_text}
            </p>
          </div>
        )}

        {/* City stats */}
        {stats && (
          <div className="mt-3 msb-card-solid p-5">
            <h2 className="text-sm font-semibold text-slate-700">
              Как обычно у нас
            </h2>
            {stats.message === "мало данных" || (stats.n != null && stats.n < stats.threshold) ? (
              <p className="mt-2 text-sm text-slate-400">Пока недостаточно данных для статистики.</p>
            ) : (
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-gradient-to-br from-msb-50 to-blue-50 p-4 text-center ring-1 ring-msb-100">
                  <div className="text-xs font-medium text-msb-600 uppercase tracking-wide">Средний срок</div>
                  <div className="mt-1 text-2xl font-bold text-slate-800">{stats.avg_days} <span className="text-sm font-medium text-slate-500">дн</span></div>
                </div>
                <div className="rounded-xl bg-gradient-to-br from-emerald-50 to-teal-50 p-4 text-center ring-1 ring-emerald-100">
                  <div className="text-xs font-medium text-emerald-600 uppercase tracking-wide">Средний чек</div>
                  <div className="mt-1 text-2xl font-bold text-slate-800">{money(stats.avg_price)}</div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Contacts */}
        {(data.branch_name || data.branch_phone) && (
          <div className="mt-3 msb-card-solid p-5 text-sm">
            <h2 className="font-semibold text-slate-700">Контакты сервиса</h2>
            {data.branch_name && (
              <p className="mt-2 text-slate-600">{data.branch_name}</p>
            )}
            {data.branch_phone && (
              <a href={`tel:${data.branch_phone}`}
                className="mt-2 inline-flex items-center gap-2 text-msb-600 font-semibold hover:text-msb-700">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-msb-50 text-lg ring-1 ring-msb-100">
                  📞
                </span>
                {data.branch_phone}
              </a>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="mt-8 mb-6 text-center">
          <div className="flex items-center justify-center gap-2 text-xs text-slate-400">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-msb-600 to-msb-800">
              <span className="text-[8px] font-bold text-white">MSB</span>
            </div>
            <span>Мастер Сервис Бюро</span>
          </div>
        </div>
      </div>
    </main>
  );
}

function PublicRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-right font-medium text-slate-800">{value}</dd>
    </div>
  );
}