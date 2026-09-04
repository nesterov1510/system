"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, getStoredUser, hasRole, type Repair } from "@/lib/api";

interface ClientRow {
  id: string;
  full_name: string;
  phone: string;
  repairs_count: number;
}

interface ClientRepairSummary {
  total_repairs: number;
  active_repairs: number;
  completed_repairs: number;
  total_spent: number;
  last_visit: string | null;
}

export default function ClientsPage() {
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [selectedClient, setSelectedClient] = useState<{
    client: ClientRow;
    repairs: Repair[];
    summary: ClientRepairSummary;
  } | null>(null);
  const [loadingClientId, setLoadingClientId] = useState<string | null>(null);
  const currentUser = getStoredUser();

  function load() {
    api.listClients().then(setClients).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function removeClient(c: ClientRow) {
    if (!confirm(`Удалить контакт «${c.full_name}»? История его ремонтов останется, но из списка контактов он исчезнет.`)) return;
    setError(null);
    try {
      await api.deleteClient(c.id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления");
    }
  }

  async function openClient(c: ClientRow) {
    setLoadingClientId(c.id);
    setError(null);
    try {
      const repairs = await api.clientRepairs(c.id);
      const completed = repairs.filter(r => ["Выдано", "Архив"].includes(r.status));
      const totalSpent = repairs
        .filter(r => r.price_final != null)
        .reduce((s, r) => s + (r.price_final || 0), 0);
      const lastVisit = repairs.length > 0 && repairs[0].accepted_at
        ? repairs[0].accepted_at
        : null;
      const active = repairs.filter(
        r => !["Выдано", "Архив", "Отказ"].includes(r.status)
      ).length;
      setSelectedClient({
        client: c,
        repairs,
        summary: {
          total_repairs: repairs.length,
          active_repairs: active,
          completed_repairs: completed.length,
          total_spent: totalSpent,
          last_visit: lastVisit,
        },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setLoadingClientId(null);
    }
  }

  function closeClient() {
    setSelectedClient(null);
  }

  const filtered = useMemo(() => {
    if (!q.trim()) return clients;
    const needle = q.toLowerCase();
    return clients.filter(c =>
      c.full_name.toLowerCase().includes(needle) ||
      c.phone.toLowerCase().includes(needle)
    );
  }, [clients, q]);

  if (selectedClient) {
    return <ClientDetail data={selectedClient} onClose={closeClient} />;
  }

  return (
    <div className="mx-auto max-w-4xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Контакты</h1>
        <p className="mt-1 text-sm text-slate-500">
          {clients.length} уникальных клиентов ·{" "}
          {clients.reduce((s, c) => s + c.repairs_count, 0)} ремонтов всего
        </p>
      </div>

      {/* Search */}
      <div className="mb-6">
        <div className="relative">
          <svg className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск контакта: имя или телефон…"
            className="msb-input pl-10"
            autoFocus
          />
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}

      {/* Client list */}
      <div className="overflow-x-auto rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <span className="text-3xl mb-2">👥</span>
            <p className="text-sm font-medium">
              {q ? "Контакты не найдены" : "Пока нет контактов"}
            </p>
            <Link href="/repairs/new" className="msb-btn-primary mt-4">
              + Новая приёмка
            </Link>
          </div>
        ) : (
          <table className="w-full min-w-[620px] text-left">
            <thead className="bg-slate-50/50">
              <tr>
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Контакт</th>
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Телефон</th>
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 text-right">Ремонтов</th>
                <th className="px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 text-right">Действие</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(c => (
                <tr key={c.id} className="group odd:bg-slate-50/30 hover:bg-msb-50/50 transition-colors">
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-msb-500 to-msb-700 text-xs font-bold text-white">
                        {c.full_name.charAt(0).toUpperCase()}
                      </div>
                      <span className="text-sm font-medium text-slate-800">{c.full_name}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-sm text-slate-600 font-mono">{c.phone}</td>
                  <td className="px-5 py-4 text-right">
                    <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${
                      c.repairs_count > 0 ? "bg-msb-100 text-msb-700" : "bg-slate-100 text-slate-500"
                    }`}>
                      {c.repairs_count}
                    </span>
                  </td>
                  <td className="px-5 py-4 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <button onClick={() => openClient(c)} disabled={loadingClientId === c.id}
                        className="text-sm font-medium text-msb-600 hover:text-msb-700 transition-colors disabled:opacity-50">
                        {loadingClientId === c.id ? "Загрузка…" : "Открыть →"}
                      </button>
                      {hasRole(currentUser, "admin") && (
                        <button onClick={() => removeClient(c)}
                          className="text-sm font-medium text-red-500 hover:text-red-700 transition-colors">
                          Удалить
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function ClientDetail({
  data,
  onClose,
}: {
  data: { client: ClientRow; repairs: Repair[]; summary: ClientRepairSummary };
  onClose: () => void;
}) {
  const { client, repairs, summary } = data;
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

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <button onClick={onClose}
        className="msb-btn-ghost text-slate-500 hover:text-slate-700">
        ← Все контакты
      </button>

      {/* Client header */}
      <div className="msb-card-solid overflow-hidden">
        <div className="bg-gradient-to-r from-msb-600 to-msb-800 px-4 py-5 sm:px-6 sm:py-6">
          <div className="flex items-center gap-3 sm:gap-4">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white/20 text-xl font-extrabold text-white sm:h-16 sm:w-16 sm:text-2xl">
              {client.full_name.charAt(0).toUpperCase()}
            </div>
            <div>
              <h1 className="break-words text-xl font-extrabold text-white sm:text-2xl">{client.full_name}</h1>
              <p className="mt-0.5 text-msb-100 font-mono">{client.phone}</p>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-slate-100">
          <div className="p-4 text-center">
            <div className="text-2xl font-bold text-slate-900">{summary.total_repairs}</div>
            <div className="text-xs text-slate-500 mt-0.5">Всего ремонтов</div>
          </div>
          <div className="p-4 text-center">
            <div className="text-2xl font-bold text-msb-600">{summary.active_repairs}</div>
            <div className="text-xs text-slate-500 mt-0.5">Активных</div>
          </div>
          <div className="p-4 text-center">
            <div className="text-2xl font-bold text-emerald-600">{summary.completed_repairs}</div>
            <div className="text-xs text-slate-500 mt-0.5">Завершено</div>
          </div>
          <div className="p-4 text-center">
            <div className="text-2xl font-bold text-slate-900">
              {summary.total_spent > 0
                ? `${summary.total_spent.toLocaleString("ru")} ман.`
                : "—"}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">Потрачено</div>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="grid grid-cols-1 gap-2.5 sm:flex sm:gap-3">
        <Link href="/repairs/new" className="msb-btn-primary">
          + Новая приёмка
        </Link>
        <a href={`tel:${client.phone}`} className="msb-btn-secondary">
          📞 Позвонить
        </a>
      </div>

      {/* Repairs history */}
      <div className="msb-card-solid p-4 sm:p-6">
        <h2 className="msb-section-title mb-4 flex items-center gap-2">
          <span>📋</span> История ремонтов
        </h2>

        {repairs.length === 0 ? (
          <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-8 text-sm text-slate-400">
            История пуста
          </div>
        ) : (
          <div className="space-y-3">
            {repairs.map(r => (
              <Link key={r.id} href={`/repairs/${r.id}`}
                className="block rounded-xl bg-slate-50/50 p-4 ring-1 ring-slate-200 hover:ring-msb-300 hover:bg-msb-50/30 transition-all">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-slate-900">{r.number}</span>
                    <span className={`msb-badge ${STATUS_COLORS[r.status] ?? "msb-badge-gray"}`}>
                      {r.status}
                    </span>
                    {r.paid && <span className="msb-badge-success text-[10px]">Оплачено</span>}
                  </div>
                  <span className="text-xs text-slate-400">
                    {r.accepted_at ? new Date(r.accepted_at).toLocaleDateString("ru") : "—"}
                  </span>
                </div>
                <div className="mt-1.5 text-sm text-slate-600">
                  {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
                </div>
                {r.fault_client && (
                  <div className="mt-1 text-xs text-slate-500 italic">
                    «{r.fault_client}»
                  </div>
                )}
                {r.price_final != null && (
                  <div className="mt-1 text-sm text-slate-700">
                    Цена: <b>{r.price_final.toLocaleString("ru")} ман.</b>
                  </div>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}