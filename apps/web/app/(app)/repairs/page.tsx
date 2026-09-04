"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, getStoredUser, hasRole, money, type Lookup, type Repair, type RepairsStats } from "@/lib/api";
import { classIcon, normalizeClass } from "@/lib/catalog";

// Этапы (вкладки). Внутри каждого — список ремонтов таблицей.
const STAGES = [
  { key: "all", label: "Все", icon: "🗂️" },
  { key: "new", label: "Новый ремонт", icon: "🆕" },
  { key: "diag", label: "Диагностика", icon: "🔍" },
  { key: "work", label: "В ремонте", icon: "🔧" },
  { key: "done", label: "Закончен", icon: "✅" },
];

// status -> этап
const STAGE_OF: Record<string, string> = {
  Принято: "new",
  Диагностика: "diag",
  Согласование: "work",
  "Ожидание запчастей": "work",
  "В ремонте": "work",
  "Готово к выдаче": "done",
  Выдано: "done",
  "Не забрано": "done",
  Архив: "done",
  Отказ: "done",
};
const STAGE_LABEL: Record<string, string> = {
  new: "Новый ремонт",
  diag: "Диагностика",
  work: "В ремонте",
  done: "Закончен",
};
const STAGE_CHIP: Record<string, string> = {
  new: "bg-blue-50 text-blue-700 ring-blue-200",
  diag: "bg-amber-50 text-amber-700 ring-amber-200",
  work: "bg-cyan-50 text-cyan-700 ring-cyan-200",
  done: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};
function stageOf(status: string): string {
  return STAGE_OF[status] ?? "new";
}

const PAGE_SIZE = 15;

function todayISO(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() - offsetDays);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export default function RepairsBoardPage() {
  const [tab, setTab] = useState("all");
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [data, setData] = useState<{
    items: Repair[];
    total: number;
    page: number;
    page_size: number;
  }>({ items: [], total: 0, page: 1, page_size: PAGE_SIZE });
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const currentUser = getStoredUser();
  const showCounts = hasRole(currentUser, "admin") || hasRole(currentUser, "operator");

  // Фильтры: дата (пресеты + интервал, «по приёму / по закрытию»), мастера (мульти), «ждут назначения».
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [dateField, setDateField] = useState<"accepted" | "ready">("accepted");
  const [masterSel, setMasterSel] = useState<string[]>([]);
  const [mastersList, setMastersList] = useState<Lookup[]>([]);
  const [unassigned, setUnassigned] = useState(false);
  const [stats, setStats] = useState<RepairsStats | null>(null);

  useEffect(() => {
    api.masters().then(setMastersList).catch(() => {});
  }, []);

  const filterParams = useMemo(
    () => ({
      stage: tab === "all" ? undefined : tab,
      q: appliedQ || undefined,
      master_ids: masterSel.length ? masterSel.join(",") : undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      date_field: dateField,
      unassigned: unassigned || undefined,
    }),
    [tab, appliedQ, masterSel, dateFrom, dateTo, dateField, unassigned],
  );

  useEffect(() => {
    setLoading(true);
    api
      .repairs({ ...filterParams, page, page_size: PAGE_SIZE })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
    // Карточки — по тому же срезу, что и таблица.
    api
      .repairsStats(filterParams)
      .then(setStats)
      .catch(() => setStats(null));
  }, [filterParams, page]);

  useEffect(() => {
    if (!showCounts) return;
    api.stageCounts().then(setCounts).catch(() => {});
  }, [showCounts, data.total]);

  // Debounce поиска
  useEffect(() => {
    const t = setTimeout(() => setAppliedQ(q.trim()), 350);
    return () => clearTimeout(t);
  }, [q]);

  // Смена фильтра — на первую страницу
  useEffect(() => {
    setPage(1);
  }, [tab, appliedQ, dateFrom, dateTo, dateField, masterSel, unassigned]);

  function applyPreset(preset: "" | "week" | "month" | "year") {
    if (!preset) {
      setDateFrom("");
      setDateTo("");
      return;
    }
    const days = preset === "week" ? 7 : preset === "month" ? 30 : 365;
    setDateFrom(todayISO(days - 1));
    setDateTo(todayISO(0));
  }

  const activePreset =
    dateFrom && dateTo
      ? (["week", "month", "year"] as const).find(
          (p) => dateFrom === todayISO((p === "week" ? 7 : p === "month" ? 30 : 365) - 1) && dateTo === todayISO(0),
        )
      : undefined;

  function toggleMaster(id: string) {
    setMasterSel((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const sumOf = (r: Repair) => r.price_final ?? r.price_max ?? null;

  return (
    <div>
      {/* Header */}
      <div className="mb-4">
        <h1 className="text-2xl font-bold text-slate-900">Все ремонты</h1>
        <p className="mt-1 text-sm text-slate-500">{data.total} ремонтов</p>
      </div>

      {/* Stage tabs */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {STAGES.map((s) => {
          const n = counts?.[s.key];
          return (
            <button
              key={s.key}
              onClick={() => setTab(s.key)}
              className={`flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold transition-all ${
                tab === s.key
                  ? "bg-msb-600 text-white shadow-sm"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              <span>{s.icon}</span> {s.label}
              {showCounts && n != null && (
                <span
                  className={`ml-0.5 flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-bold ${
                    tab === s.key ? "bg-white/25 text-white" : "bg-msb-600/10 text-msb-700"
                  }`}
                >
                  {n}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Карточки-суммарики — по текущей выборке (те же фильтры, что и таблица) */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <div className="msb-card-solid p-4">
          <div className="text-lg font-bold text-slate-900">{stats ? money(stats.total_sum) : "—"}</div>
          <div className="mt-0.5 text-xs font-medium text-slate-500">Общая сумма всех ремонтов</div>
        </div>
        <div className="msb-card-solid p-4">
          <div className="text-lg font-bold text-rose-600">{stats ? money(stats.parts_cost) : "—"}</div>
          <div className="mt-0.5 text-xs font-medium text-slate-500">Общие расходы (запчасти)</div>
        </div>
        <div className="msb-card-solid p-4">
          <div className={`text-lg font-bold ${stats && stats.profit < 0 ? "text-red-600" : "text-emerald-600"}`}>
            {stats ? money(stats.profit) : "—"}
          </div>
          <div className="mt-0.5 text-xs font-medium text-slate-500">Общая прибыль</div>
        </div>
        <div className="msb-card-solid p-4">
          <div className="text-lg font-bold text-amber-600">{stats ? money(stats.master_payout) : "—"}</div>
          <div className="mt-0.5 text-xs font-medium text-slate-500">Сумма, выплаченная мастерам</div>
        </div>
        <div className="msb-card-solid p-4">
          <div className="text-lg font-bold text-slate-900">{stats ? stats.clients_unique : "—"}</div>
          <div className="mt-0.5 text-xs font-medium text-slate-500">Количество клиентов</div>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-4 space-y-3 rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <div className="flex flex-wrap items-center gap-3">
          {/* Пресеты + ручной интервал */}
          <div className="flex overflow-hidden rounded-xl ring-1 ring-slate-200">
            {([
              ["", "Все"],
              ["week", "Неделя"],
              ["month", "Месяц"],
              ["year", "Год"],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => applyPreset(key)}
                className={`px-3 py-2 text-xs font-semibold transition-colors ${
                  (activePreset ?? "") === key
                    ? "bg-msb-600 text-white"
                    : "bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="msb-input w-auto"
            title="с"
          />
          <span className="text-xs text-slate-400">по</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="msb-input w-auto"
            title="по"
          />
          {/* Срез: по приёму / по закрытию */}
          <div className="flex overflow-hidden rounded-xl ring-1 ring-slate-200">
            {(
              [
                ["accepted", "по приёму"],
                ["ready", "по закрытию"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setDateField(key)}
                className={`px-3 py-2 text-xs font-semibold transition-colors ${
                  dateField === key
                    ? "bg-slate-700 text-white"
                    : "bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {/* Ждут назначения */}
          <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={unassigned}
              onChange={(e) => setUnassigned(e.target.checked)}
              className="h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500"
            />
            Ждут назначения
          </label>
        </div>
        {/* Мастера (мультивыбор) */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Мастера:</span>
          {mastersList.length === 0 && <span className="text-xs text-slate-400">список пуст</span>}
          {mastersList.map((m) => {
            const active = masterSel.includes(m.id);
            return (
              <button
                key={m.id}
                onClick={() => toggleMaster(m.id)}
                className={`rounded-xl px-3 py-1.5 text-xs font-medium ring-1 transition-all ${
                  active
                    ? "bg-msb-600 text-white ring-msb-600"
                    : "bg-white text-slate-600 ring-slate-200 hover:ring-msb-300"
                }`}
              >
                {m.name}
              </button>
            );
          })}
          {masterSel.length > 0 && (
            <button onClick={() => setMasterSel([])} className="text-xs font-medium text-slate-400 hover:text-slate-600">
              сбросить
            </button>
          )}
          <div className="relative ml-auto min-w-[220px] flex-1 sm:max-w-xs">
            <svg className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Поиск: клиент, телефон, бренд…"
              className="msb-input pl-10"
            />
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> <span>{error}</span>
        </div>
      )}

      {/* List: ровно 10 колонок */}
      <div className="overflow-x-auto rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        <table className="w-full min-w-[1280px] text-left">
          <thead className="bg-slate-50/50">
            <tr>
              {[
                "Дата",
                "Название техники",
                "Кто принял технику",
                "Причина поломки",
                "Общая сумма ремонта",
                "Расходы на запчасти и какие запчасти",
                "Имя и номер клиента",
                "Мастер(а) и помощники",
                "Какому мастеру сколько было оплачено",
                "Итоговая сумма ремонта",
              ].map((h) => (
                <th key={h} className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={10} className="py-12 text-center text-sm text-slate-400">
                  <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-msb-500 border-t-transparent align-middle" />
                  Загрузка…
                </td>
              </tr>
            ) : data.items.length === 0 ? (
              <tr>
                <td colSpan={10} className="py-12 text-center text-sm text-slate-400">
                  Ремонтов не найдено
                </td>
              </tr>
            ) : (
              data.items.map((r) => {
                const stage = stageOf(r.status);
                const hasMasters = (r.master_names?.length ?? 0) > 0;
                const sum = sumOf(r);
                const partsNames = r.parts_names ?? [];
                const helperNames = r.helper_names ?? [];
                return (
                  <tr key={r.id} className="transition-colors hover:bg-msb-50/40">
                    {/* 1. Дата: по выбранному срезу (приём/закрытие) */}
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
                      {(() => {
                        const dt = dateField === "ready" ? r.ready_at : r.accepted_at;
                        return dt ? new Date(dt).toLocaleDateString("ru") : "—";
                      })()}
                    </td>
                    {/* 2. Название техники */}
                    <td className="px-4 py-3">
                      <Link href={`/repairs/${r.id}`} className="flex items-center gap-2.5">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-lg">
                          {classIcon(r.device_type)}
                        </span>
                        <span>
                          <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-msb-600">
                            {normalizeClass(r.device_type)}
                            {r.is_delivery && (
                              <span title="Заказ с доставкой" className="text-sm normal-case">🚚</span>
                            )}
                          </span>
                          <span className="block text-sm font-bold text-slate-900">
                            {[r.brand, r.model].filter(Boolean).join(" ") || "Без модели"}
                          </span>
                        </span>
                      </Link>
                    </td>
                    {/* 3. Кто принял технику */}
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {r.accepted_by_name || "—"}
                    </td>
                    {/* 4. Причина поломки */}
                    <td className="max-w-[220px] px-4 py-3 text-xs text-slate-600">
                      <span className="line-clamp-2">{r.fault_client || r.fault_master || "—"}</span>
                    </td>
                    {/* 5. Общая сумма ремонта (сумма к оплате клиенту) */}
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      {sum != null ? (
                        <span className="text-sm font-semibold text-slate-800">{money(sum)}</span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    {/* 6. Расходы на запчасти и какие запчасти */}
                    <td className="max-w-[240px] px-4 py-3">
                      {r.parts_cost != null ? (
                        <div>
                          <div className="text-sm font-semibold text-rose-600">{money(r.parts_cost)}</div>
                          {partsNames.length > 0 && (
                            <div className="text-[11px] leading-4 text-slate-500">{partsNames.join(", ")}</div>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    {/* 7. Имя и номер клиента */}
                    <td className="whitespace-nowrap px-4 py-3">
                      <Link href={`/repairs/${r.id}`} className="block">
                        <span className="text-sm font-medium text-slate-800">{r.client_name}</span>
                      </Link>
                      <a href={`tel:${r.client_phone}`} className="text-xs font-medium text-msb-600 hover:text-msb-700">
                        {r.client_phone}
                      </a>
                    </td>
                    {/* 8. Мастер(а) и помощники */}
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {hasMasters ? (
                        <div>
                          <div className="font-medium text-slate-800">{r.master_names?.join(", ")}</div>
                          {helperNames.length > 0 && (
                            <div className="text-[11px] text-slate-400">пом. {helperNames.join(", ")}</div>
                          )}
                        </div>
                      ) : (
                        <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500 ring-1 ring-slate-200">
                          Не назначен
                        </span>
                      )}
                    </td>
                    {/* 9. Какому мастеру сколько было оплачено */}
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      {r.master_payout != null ? (
                        <span className="text-sm font-semibold text-amber-600">{money(r.master_payout)}</span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    {/* 10. Итоговая сумма ремонта (то же поле, что и 5) */}
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      {sum != null ? (
                        <span className="text-sm font-bold text-slate-900">{money(sum)}</span>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {!loading && data.total > 0 && (
        <div className="mt-4 flex items-center justify-between gap-3">
          <span className="text-sm text-slate-500">
            {data.total} ремонтов · стр. {data.page} из {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="msb-btn-secondary disabled:opacity-40"
            >
              ← Назад
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="msb-btn-secondary disabled:opacity-40"
            >
              Вперёд →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
