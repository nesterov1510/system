"use client";

import { useEffect, useState } from "react";
import { api, type EtaPrediction, type StatTile } from "@/lib/api";

export default function DashboardPage() {
  const [tiles, setTiles] = useState<StatTile[]>([]);
  const [overview, setOverview] = useState<{
    total: number;
    active: number;
    overdue_storage: number;
  } | null>(null);
  const [eta, setEta] = useState<EtaPrediction | null>(null);
  const [etaType, setEtaType] = useState("ТВ");
  const [etaBrand, setEtaBrand] = useState("Samsung");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.statsTiles().then(setTiles).catch((e) => setError(e.message));
    api.statsOverview().then(setOverview).catch(() => {});
  }, []);

  async function runEta() {
    setEta(null);
    setError(null);
    try {
      const r = await api.predictEta({
        device_type: etaType,
        brand: etaBrand || null,
      });
      setEta(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Курс ремонта</h1>

      {/* Overview */}
      {overview && (
        <div className="grid grid-cols-3 gap-3">
          <Card label="Всего ремонтов" value={String(overview.total)} />
          <Card label="В работе" value={String(overview.active)} />
          <Card
            label="Просрочка хранения"
            value={String(overview.overdue_storage)}
            accent={overview.overdue_storage > 0}
          />
        </div>
      )}

      {/* Tiles */}
      <div className="space-y-3">
        {tiles
          .filter((t) => t.group === "Всего" || !t.message)
          .map((t) => (
            <div
              key={t.group}
              className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-200"
            >
              <div className="text-sm font-semibold text-gray-700">{t.group}</div>
              {t.message ? (
                <div className="mt-1 text-sm text-gray-400">{t.message}</div>
              ) : (
                <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                  <Stat label="Срок" value={`${t.avg_days} дн`} sub={`p90 ${t.p90_days}`} />
                  <Stat label="Чек" value={`${t.avg_price?.toLocaleString("ru")} ₽`} sub={`n=${t.n}`} />
                  <Stat label="SLA" value={`${t.sla_pct}%`} sub={`медиана ${t.median_days}д`} />
                </div>
              )}
            </div>
          ))}
      </div>

      {/* AI ETA */}
      <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
        <h2 className="text-sm font-semibold text-gray-700">
          AI-прогноз срока (ETA)
        </h2>
        <div className="mt-3 flex gap-2">
          <input
            value={etaType}
            onChange={(e) => setEtaType(e.target.value)}
            placeholder="Тип (ТВ)"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
          <input
            value={etaBrand}
            onChange={(e) => setEtaBrand(e.target.value)}
            placeholder="Бренд"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
          <button
            onClick={runEta}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
          >
            Прогноз
          </button>
        </div>

        {eta && (
          <div className="mt-3 rounded-lg bg-gray-50 p-3 text-sm">
            {eta.message === "мало данных" ? (
              <span className="text-gray-400">
                ⚠ Мало данных — честно не прогнозируем (n={eta.n})
              </span>
            ) : (
              <div className="flex items-center gap-4">
                <div>
                  <div className="text-xs text-gray-400">Прогноз</div>
                  <div className="text-2xl font-bold text-gray-900">
                    {eta.eta_days} дн
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-400">Источник</div>
                  <div className="text-sm font-medium text-gray-700">
                    {eta.source === "ai" ? "AI" : "статистика"}
                  </div>
                </div>
                {eta.confidence != null && (
                  <div>
                    <div className="text-xs text-gray-400">Уверенность</div>
                    <div className="text-sm font-medium text-gray-700">
                      {Math.round(eta.confidence * 100)}%
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}

function Card({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl p-4 text-center ring-1 ${
        accent ? "bg-red-50 ring-red-200" : "bg-white ring-gray-200"
      }`}
    >
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="mt-1 text-xs text-gray-500">{label}</div>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-gray-400">{label}</div>
      <div className="text-base font-semibold text-gray-900">{value}</div>
      {sub && <div className="text-[11px] text-gray-400">{sub}</div>}
    </div>
  );
}
