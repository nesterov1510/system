"use client";

// Шапка карточки ремонта.
//
// «Облегчённый» вариант: вместо трёх отдельных блоков (панель мастеров +
// карточка с градиентной плашкой + панель действий) — ОДНА компактная карточка.
// Убраны тяжёлый градиент, крупные иконки у каждого поля и лишние отступы:
// всё, что нужно оператору на приёмке, помещается в первый экран.

import Link from "next/link";
import { money, type Lookup, type Repair } from "@/lib/api";
import type { RepairCardState } from "./useRepairCard";

// Статус в карточке — 4 этапа (как на доске), полный список статусов живёт
// в настройках и проверяется сервером.
const STAGES = [
  { status: "Принято", label: "Новый ремонт", color: "msb-badge-info" },
  { status: "Диагностика", label: "Диагностика", color: "msb-badge-warning" },
  { status: "В ремонте", label: "В ремонте", color: "msb-badge-cyan" },
  { status: "Готово к выдаче", label: "Закончен", color: "msb-badge-success" },
];

const STAGE_OF: Record<string, string> = {
  Принято: "Принято",
  Диагностика: "Диагностика",
  Согласование: "В ремонте",
  "Ожидание запчастей": "В ремонте",
  "В ремонте": "В ремонте",
  "Готово к выдаче": "Готово к выдаче",
  Выдано: "Готово к выдаче",
  "Не забрано": "Готово к выдаче",
  Архив: "Готово к выдаче",
  Отказ: "Готово к выдаче",
};

export function stageRep(status: string): string {
  return STAGE_OF[status] ?? "Принято";
}

export function stageMeta(status: string) {
  return STAGES.find((s) => s.status === stageRep(status)) ?? STAGES[0];
}

const TERMINAL = ["Выдано", "Не забрано", "Архив", "Отказ"];

function fmt(dt?: string | null) {
  return dt ? new Date(dt).toLocaleString("ru") : "—";
}

function fmtDate(dt?: string | null) {
  return dt ? new Date(dt).toLocaleDateString("ru") : "—";
}

/** Компактная пара «подпись: значение» в одну строку. */
function Fact({
  label,
  value,
  mono,
  accent,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
  accent?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] leading-tight text-slate-400">{label}</dt>
      <dd
        className={`truncate text-sm leading-snug ${mono ? "font-mono" : "font-medium"} ${
          accent ?? "text-slate-800"
        }`}
        title={value || undefined}
      >
        {value || "—"}
      </dd>
    </div>
  );
}

export default function RepairHeader({ s }: { s: RepairCardState }) {
  const repair: Repair = s.repair!;
  const device = [repair.brand, repair.model].filter(Boolean).join(" ");
  const masterNames = repair.master_names?.length
    ? repair.master_names
    : repair.master_name
      ? [repair.master_name]
      : [];

  return (
    <section className="msb-card-solid overflow-hidden">
      {/* Строка 1: назад · номер · статус · действия */}
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/70 px-3 py-2.5 sm:px-4">
        <Link
          href="/repairs"
          className="msb-btn-ghost -ml-1 shrink-0 px-2 py-1.5 text-slate-500 hover:text-slate-700"
          title="К списку ремонтов"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          <span className="hidden sm:inline">К доске</span>
        </Link>

        <h1 className="min-w-0 shrink font-mono text-base font-bold text-slate-900 sm:text-lg">
          {repair.number}
        </h1>

        <select
          value={stageRep(repair.status)}
          onChange={(e) => s.changeStatus(e.target.value)}
          disabled={s.busy}
          aria-label="Этап ремонта"
          className={`min-h-0 shrink-0 rounded-lg border-0 py-1.5 pl-2.5 pr-7 text-xs font-semibold outline-none focus:ring-2 focus:ring-msb-500/40 ${stageMeta(repair.status).color}`}
        >
          {STAGES.map((st) => (
            <option key={st.status} value={st.status}>
              {st.label}
            </option>
          ))}
        </select>

        {repair.status !== stageRep(repair.status) && (
          <span className="msb-badge-gray shrink-0 text-[10px]">{repair.status}</span>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <button
            onClick={s.doPrintLabel}
            disabled={s.busy}
            className="msb-btn-primary px-3 py-1.5 text-xs"
            title="Этикетка 58×38 мм с QR на карточку"
          >
            🏷️ <span className="hidden sm:inline">Этикетка</span>
          </button>
          <button
            onClick={s.doPrint}
            disabled={s.busy}
            className="msb-btn-secondary px-3 py-1.5 text-xs"
            title="Бланк приёма A4"
          >
            🖨️ <span className="hidden sm:inline">Бланк A4</span>
          </button>
          {s.canFinish && !TERMINAL.includes(repair.status) && (
            <button
              onClick={s.openFinish}
              disabled={s.busy}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-emerald-700 disabled:opacity-40"
            >
              ✅ <span className="hidden sm:inline">Закончен</span>
            </button>
          )}
          {s.canDelete && (
            <button
              onClick={s.removeRepair}
              disabled={s.busy}
              className="rounded-lg bg-red-50 px-2.5 py-1.5 text-xs font-medium text-red-600 ring-1 ring-red-200 transition-colors hover:bg-red-100 disabled:opacity-40"
              title="Удалить ремонт"
            >
              🗑
            </button>
          )}
        </div>
      </div>

      {/* Строка 2: техника и ключевые факты */}
      <div className="px-3 py-3 sm:px-4">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-sm font-semibold text-slate-900">
            {repair.device_type}
          </span>
          {device && <span className="text-sm text-slate-600">{device}</span>}
          {repair.serial && (
            <span className="font-mono text-xs text-slate-400">SN {repair.serial}</span>
          )}
        </div>

        <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5 sm:grid-cols-3 lg:grid-cols-6">
          <Fact label="Клиент" value={repair.client_name} />
          <Fact label="Телефон" value={repair.client_phone} mono />
          <Fact label="Принято" value={fmtDate(repair.accepted_at)} />
          <Fact
            label="Срок, дн."
            value={repair.eta_days?.toString() ?? null}
            accent={repair.eta_days ? "text-slate-800" : undefined}
          />
          <Fact label="Хранение до" value={fmtDate(repair.storage_until)} />
          <Fact
            label="Цена"
            value={repair.price_final != null ? money(repair.price_final) : null}
            accent={repair.paid ? "text-emerald-600" : "text-slate-800"}
          />
        </dl>

        {repair.fault_client && (
          <p className="mt-3 text-sm leading-snug text-slate-600">
            <span className="font-medium text-slate-500">Неисправность:</span>{" "}
            {repair.fault_client}
          </p>
        )}
        {repair.condition_notes && (
          <p className="mt-1 text-sm leading-snug text-slate-600">
            <span className="font-medium text-slate-500">Состояние:</span>{" "}
            {repair.condition_notes}
          </p>
        )}

        {/* Комплектация + маркеры (доставка, второй контакт) — чипами в одну строку */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {s.complect.map((item) => (
            <span key={item} className="msb-badge-info px-2 py-0.5 text-[11px]">
              {item}
            </span>
          ))}

          <label
            className={`msb-badge px-2 py-0.5 text-[11px] ${
              repair.is_delivery
                ? "bg-amber-100 text-amber-800"
                : "bg-slate-100 text-slate-400"
            } cursor-pointer select-none`}
            title="Заказ доставлен курьером / забран с адреса"
          >
            <input
              type="checkbox"
              checked={!!repair.is_delivery}
              disabled={s.busy}
              onChange={(e) => s.toggleDelivery(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-slate-300 text-amber-600 focus:ring-amber-500"
            />
            🚚 Доставка
          </label>

          <button
            onClick={() => s.setContact2Open(true)}
            className={`msb-badge min-h-[44px] px-2 py-0.5 text-[11px] transition-colors sm:min-h-0 ${
              repair.contact2_name || repair.contact2_phone
                ? "bg-slate-100 text-slate-600 hover:bg-slate-200"
                : "bg-slate-50 text-slate-400 hover:bg-slate-100"
            }`}
            title="Второй контакт: напр. владелец техники ≠ тот, кто её привёз"
          >
            {repair.contact2_name || repair.contact2_phone
              ? `👤 ${repair.contact2_name || "контакт"}${
                  repair.contact2_phone ? ` · ${repair.contact2_phone}` : ""
                }`
              : "＋ Второй контакт"}
          </button>
        </div>

        {/* Мастера — инлайн, без отдельной карточки */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-3">
          <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
            Мастер
          </span>
          {masterNames.length ? (
            masterNames.map((name) => (
              <span key={name} className="msb-badge bg-msb-50 px-2 py-0.5 text-[11px] text-msb-700">
                {name}
              </span>
            ))
          ) : (
            <span className="text-xs italic text-slate-400">не назначен</span>
          )}
          {repair.helper_names?.map((name) => (
            <span key={name} className="msb-badge-gray px-2 py-0.5 text-[11px]">
              {name} <span className="text-slate-400">(kömekçi)</span>
            </span>
          ))}

          {s.canAssignMaster ? (
            <button
              onClick={() => s.setAssignOpen((v: boolean) => !v)}
              className="ml-auto min-h-[44px] px-2 text-xs font-semibold text-msb-600 hover:text-msb-700 sm:min-h-0"
            >
              {s.assignOpen ? "Свернуть" : "✏️ Назначить"}
            </button>
          ) : (
            <span className="ml-auto text-[11px] italic text-slate-400">
              назначает администратор или оператор
            </span>
          )}
        </div>

        {s.assignOpen && s.canAssignMaster && (
          <AssignPanel s={s} mastersList={s.mastersList} />
        )}
      </div>
    </section>
  );
}

function AssignPanel({
  s,
  mastersList,
}: {
  s: RepairCardState;
  mastersList: Lookup[];
}) {
  return (
    <div className="mt-3 space-y-3 rounded-xl bg-slate-50 p-3 ring-1 ring-slate-100">
      <div>
        <label className="msb-label" htmlFor="assign-master">
          Основной мастер
        </label>
        <select
          id="assign-master"
          className="msb-input"
          value={s.assignMasterId}
          onChange={(e) => s.setAssignMasterId(e.target.value)}
        >
          <option value="">— не назначен —</option>
          {mastersList.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <span className="msb-label">
          Помощники <span className="text-slate-400">(в бланке — «Inžiner (kömekçi)»)</span>
        </span>
        <div className="flex flex-wrap gap-1.5">
          {mastersList
            .filter((m) => m.id !== s.assignMasterId)
            .map((m) => {
              const active = s.assignHelperIds.includes(m.id);
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => s.toggleHelper(m.id)}
                  className={`rounded-lg px-2.5 py-1.5 text-xs font-medium ring-1 transition-colors ${
                    active
                      ? "bg-msb-600 text-white ring-msb-600"
                      : "bg-white text-slate-600 ring-slate-200 hover:ring-msb-300"
                  }`}
                >
                  {m.name}
                </button>
              );
            })}
        </div>
      </div>
      <button
        onClick={s.saveAssign}
        disabled={s.assignBusy}
        className="msb-btn-primary px-4 py-2 text-xs"
      >
        {s.assignBusy ? "Сохраняем…" : "Сохранить назначение"}
      </button>
    </div>
  );
}
