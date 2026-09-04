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
  // Прогноз суммы ремонта (единственная карточка вкладки «Курс»).
  const [pType, setPType] = useState("ТВ");
  const [pBrand, setPBrand] = useState("");
  const [hint, setHint] = useState<{
    price_min?: number | null;
    price_max?: number | null;
    n?: number | null;
  } | null>(null);
  const [hintMsg, setHintMsg] = useState<string | null>(null);
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

  // Прогноз суммы ремонта по прайсу (вилка price_min–price_max).
  async function runPriceHint() {
    setHint(null);
    setHintMsg(null);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (pType) params.type = pType;
      if (pBrand) params.brand = pBrand;
      const r = await api.priceHint(params);
      if (r.hint) setHint(r.hint);
      else setHintMsg(r.message || "Нет данных по прайсу");
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

      {/* Прогноз: сумма ремонта — единственная карточка вкладки «Курс» */}
      <div className="msb-card-solid p-6">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <span>📈</span> Прогноз: сумма ремонта
        </h2>
        <div className="mt-4 grid gap-3 sm:flex sm:flex-wrap">
          <input value={pType} onChange={(e) => setPType(e.target.value)}
            placeholder="Тип (ТВ)" className="msb-input min-w-0 flex-1" />
          <input value={pBrand} onChange={(e) => setPBrand(e.target.value)}
            placeholder="Бренд" className="msb-input min-w-0 flex-1" />
          <button onClick={runPriceHint} className="msb-btn-primary">
            Прогнозировать
          </button>
        </div>
        {hintMsg && (
          <p className="mt-3 text-sm text-slate-500">📊 {hintMsg}</p>
        )}
        {hint && (
          <div className="mt-4 flex flex-wrap items-center gap-6 rounded-xl bg-gradient-to-r from-emerald-50 to-msb-50 p-5 ring-1 ring-emerald-200 animate-slide-up">
            <div className="text-center">
              <div className="text-xs font-medium uppercase tracking-wide text-msb-600">Прогноз</div>
              <div className="text-3xl font-extrabold text-slate-900">
                {money(hint.price_min ?? 0)}
                <span className="text-lg font-medium text-slate-500"> – {money(hint.price_max ?? 0)}</span>
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Источник</div>
              <div className="text-sm font-semibold text-slate-700">Прайс (n={hint.n ?? 0})</div>
            </div>
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