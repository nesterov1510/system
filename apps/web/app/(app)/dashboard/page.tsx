"use client";

import { useEffect, useState } from "react";
import { api, money, type EtaPrediction, type StatTile } from "@/lib/api";

export default function DashboardPage() {
  const [tiles, setTiles] = useState<StatTile[]>([]);
  const [overview, setOverview] = useState<{
    total: number;
    active: number;
    overdue_storage: number;
    low_stock: number;
    revenue: number;
    revenue_30d: number;
    finished_count: number;
    finished_revenue: number;
    finished_cost: number;
    profit: number;
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
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Курс ремонта</h1>
        <p className="mt-1 text-sm text-slate-500">Сводка по сервисному центру</p>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}

      {/* Overview Cards */}
      {overview && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricCard
              label="Всего ремонтов"
              value={String(overview.total)}
              icon="📋"
              color="blue"
            />
            <MetricCard
              label="В работе"
              value={String(overview.active)}
              icon="🔧"
              color="cyan"
            />
            <MetricCard
              label="Просрочка хранения"
              value={String(overview.overdue_storage)}
              icon="⚠️"
              color={overview.overdue_storage > 0 ? "red" : "gray"}
            />
            <MetricCard
              label="Мало на складе"
              value={String(overview.low_stock)}
              icon="📦"
              color={overview.low_stock > 0 ? "amber" : "gray"}
            />
          </div>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricCard
              label="Выручка (30 дней)"
              value={money(overview.revenue_30d)}
              icon="💰"
              color="emerald"
            />
            <MetricCard
              label="Расходы (за всё время)"
              value={money(overview.finished_cost)}
              icon="💸"
              color="rose"
            />
            <MetricCard
              label="Прибыль"
              value={money(overview.profit)}
              icon="📈"
              color={overview.profit < 0 ? "red" : "emerald"}
            />
            <MetricCard
              label="Выручка (всего)"
              value={money(overview.revenue)}
              icon="🏦"
              color="purple"
            />
          </div>
        </>
      )}

      {/* Статистика по группам */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-700">Статистика по направлениям</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {tiles
            .filter((t) => t.group === "Всего" || !t.message)
            .map((t) => (
              <div key={t.group} className="msb-card-solid p-5">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-700">{t.group}</h3>
                  <span className="msb-badge-info">{t.n} ремонтов</span>
                </div>
                {t.message ? (
                  <p className="mt-3 text-sm text-slate-400">{t.message}</p>
                ) : (
                  <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                    <MiniStat label="Срок" value={`${t.avg_days ?? "—"} дн`} sub={`p90 ${t.p90_days ?? "—"}`} />
                    <MiniStat label="Чек" value={money(t.avg_price)} sub={`n=${t.n}`} />
                    <MiniStat label="SLA" value={`${t.sla_pct ?? 0}%`} sub={`мед. ${t.median_days ?? 0}д`} />
                  </div>
                )}
              </div>
            ))}
        </div>
      </div>

      {/* AI ETA */}
      <div className="msb-card-solid p-6">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <span>🤖</span> AI-прогноз срока ремонта
        </h2>
        <div className="mt-4 flex flex-wrap gap-3">
          <input value={etaType} onChange={(e) => setEtaType(e.target.value)}
            placeholder="Тип (ТВ)" className="msb-input flex-1 min-w-[120px]" />
          <input value={etaBrand} onChange={(e) => setEtaBrand(e.target.value)}
            placeholder="Бренд" className="msb-input flex-1 min-w-[120px]" />
          <button onClick={runEta} className="msb-btn-primary">
            Получить прогноз
          </button>
        </div>
        {eta && (
          <div className="mt-4 rounded-xl bg-gradient-to-r from-msb-50 to-blue-50 p-5 ring-1 ring-msb-100 animate-slide-up">
            {eta.message === "мало данных" ? (
              <div className="flex items-center gap-3 text-sm">
                <span className="text-2xl">📊</span>
                <div>
                  <p className="font-medium text-slate-700">Недостаточно данных</p>
                  <p className="text-xs text-slate-500 mt-0.5">Честно не прогнозируем (n={eta.n})</p>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-6">
                <div className="text-center">
                  <div className="text-xs font-medium text-msb-600 uppercase tracking-wide">Прогноз</div>
                  <div className="text-3xl font-extrabold text-slate-900">{eta.eta_days} <span className="text-lg font-medium text-slate-500">дн</span></div>
                </div>
                <div className="h-10 w-px bg-msb-200" />
                <div>
                  <div className="text-xs text-slate-500">Источник</div>
                  <div className="text-sm font-semibold text-slate-700">
                    {eta.source === "ai" ? "🤖 AI-модель" : "📊 Статистика"}
                  </div>
                </div>
                {eta.confidence != null && (
                  <>
                    <div className="h-10 w-px bg-msb-200" />
                    <div>
                      <div className="text-xs text-slate-500">Уверенность</div>
                      <div className="text-sm font-semibold text-slate-700">{Math.round(eta.confidence * 100)}%</div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, icon, color }: {
  label: string; value: string; icon: string; color: string;
}) {
  const colorMap: Record<string, string> = {
    blue: "from-blue-50 to-blue-100/50 ring-blue-200 text-blue-700",
    cyan: "from-cyan-50 to-cyan-100/50 ring-cyan-200 text-cyan-700",
    red: "from-red-50 to-red-100/50 ring-red-200 text-red-700",
    amber: "from-amber-50 to-amber-100/50 ring-amber-200 text-amber-700",
    emerald: "from-emerald-50 to-emerald-100/50 ring-emerald-200 text-emerald-700",
    rose: "from-rose-50 to-rose-100/50 ring-rose-200 text-rose-700",
    purple: "from-purple-50 to-purple-100/50 ring-purple-200 text-purple-700",
    gray: "from-slate-50 to-slate-100/50 ring-slate-200 text-slate-600",
  };
  return (
    <div className={`msb-card-solid bg-gradient-to-br ${colorMap[color] ?? colorMap.gray} p-4`}>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-2xl font-bold">{value}</div>
          <div className="mt-1 text-xs font-medium opacity-80">{label}</div>
        </div>
        <span className="text-xl">{icon}</span>
      </div>
    </div>
  );
}

function MiniStat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-0.5 text-base font-bold text-slate-800">{value}</div>
      {sub && <div className="text-[10px] text-slate-400">{sub}</div>}
    </div>
  );
}