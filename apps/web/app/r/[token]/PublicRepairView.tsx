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
  "Готово к выдаче": "bg-green-500",
  Выдано: "bg-gray-500",
  Отказ: "bg-red-500",
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
      <main className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
        <div className="w-full max-w-md rounded-2xl bg-white p-8 text-center ring-1 ring-gray-200">
          <div className="text-3xl">🔍</div>
          <h1 className="mt-3 text-lg font-semibold text-gray-800">
            Ремонт не найден
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {error}. Проверьте QR-код или обратитесь в сервисный центр.
          </p>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50 text-gray-400">
        Загрузка…
      </main>
    );
  }

  const statusIndex = STATUS_ORDER.indexOf(data.status);
  const progress =
    statusIndex >= 0 ? Math.round((statusIndex / (STATUS_ORDER.length - 1)) * 100) : 0;

  const complect = (data.complectation as { items?: string[] } | null)?.items;
  const stats = data.city_stats;

  return (
    <main className="min-h-screen bg-gray-50 py-8">
      <div className="mx-auto max-w-md px-4">
        <div className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
          <div className="text-center">
            <div className="text-sm text-gray-500">Ваш ремонт</div>
            <div className="mt-1 font-mono text-xl font-bold text-gray-900">
              {data.number}
            </div>
          </div>

          {/* Статус + прогресс */}
          <div className="mt-5">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-gray-800">{data.status}</span>
              <span className="text-gray-400">{progress}%</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-100">
              <div
                className={`h-full rounded-full ${
                  STATUS_COLORS[data.status] ?? "bg-gray-400"
                }`}
                style={{ width: `${Math.max(progress, 4)}%` }}
              />
            </div>
          </div>

          {/* Техника */}
          <dl className="mt-5 space-y-2 text-sm">
            <Row label="Техника" value={[data.device_type, data.brand, data.model].filter(Boolean).join(" · ")} />
            {complect && complect.length > 0 && (
              <Row label="Комплект" value={complect.join(", ")} />
            )}
            <Row label="Принято" value={fmt(data.accepted_at)} />
            {data.eta_days != null && (
              <Row label="Плановый срок" value={`${data.eta_days} дн`} />
            )}
            {data.ready_at && <Row label="Готово" value={fmt(data.ready_at)} />}
            {data.issued_at && <Row label="Выдано" value={fmt(data.issued_at)} />}
            {data.storage_until && (
              <Row label="Хранение до" value={fmt(data.storage_until)} />
            )}
          </dl>
        </div>

        {/* Условия хранения */}
        {data.storage_text && (
          <div className="mt-3 rounded-2xl bg-amber-50 p-5 ring-1 ring-amber-200">
            <h2 className="text-sm font-semibold text-amber-800">
              ⚠ Условия хранения
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-amber-900">
              {data.storage_text}
            </p>
          </div>
        )}

        {/* «Как обычно» по городу */}
        {stats && (
          <div className="mt-3 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
            <h2 className="text-sm font-semibold text-gray-700">
              Как обычно у нас в городе
            </h2>
            {stats.message === "мало данных" || stats.n < stats.threshold ? (
              <p className="mt-2 text-sm text-gray-400">
                Пока недостаточно данных для статистики.
              </p>
            ) : (
              <div className="mt-2 grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-xs text-gray-400">Средний срок</div>
                  <div className="text-lg font-semibold text-gray-800">
                    {stats.avg_days} дн
                  </div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-xs text-gray-400">Средний чек</div>
                  <div className="text-lg font-semibold text-gray-800">
                    {money(stats.avg_price)}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Контакты */}
        {(data.branch_name || data.branch_phone) && (
          <div className="mt-3 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200 text-sm text-gray-600">
            <div className="font-medium text-gray-800">Контакты сервиса</div>
            {data.branch_name && <div className="mt-1">{data.branch_name}</div>}
            {data.branch_phone && (
              <a href={`tel:${data.branch_phone}`} className="mt-1 block text-blue-600">
                ☎ {data.branch_phone}
              </a>
            )}
          </div>
        )}
      </div>
    </main>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-gray-400">{label}</dt>
      <dd className="text-right font-medium text-gray-800">{value}</dd>
    </div>
  );
}
