"use client";

// Окно, которое показывается сразу после приёмки техники.
//
// Сценарий на стойке: оператор нажал «Принять технику» → данные сохранены →
// этикетка 58×38 ушла на принтер АВТОМАТИЧЕСКИ (кликать ничего не нужно) →
// это окно сообщает «сохранено, этикетка напечатана — проверьте принтер» →
// через несколько секунд сам уходит на доску «Все ремонты».
//
// Если принтер не настроен/не ответил — окно честно показывает ошибку,
// автопереход отключается и оператор может повторить печать.

import { downloadPdfBase64, type Repair } from "@/lib/api";

export type LabelState = "idle" | "printing" | "ok" | "error";

export interface BlankState {
  busy: boolean;
  /** Сервер ответил — спрашиваем оператора, реально ли бланк вышел из принтера. */
  asking: boolean;
  attempts: number;
  message: string | null;
  pdf: string | null;
}

interface Props {
  repair: Repair;
  labelState: LabelState;
  labelMessage: string | null;
  labelPdf: string | null;
  onRetryLabel: () => void;
  blank: BlankState;
  onPrintBlank: () => void;
  onBlankSuccess: () => void;
  onBlankFailed: () => void;
  /** Секунд до автоперехода; null — автопереход выключен. */
  redirectIn: number | null;
  onGoList: () => void;
  onOpenCard: () => void;
  onNewIntake: () => void;
}

export default function IntakeDoneDialog({
  repair,
  labelState,
  labelMessage,
  labelPdf,
  onRetryLabel,
  blank,
  onPrintBlank,
  onBlankSuccess,
  onBlankFailed,
  redirectIn,
  onGoList,
  onOpenCard,
  onNewIntake,
}: Props) {
  const storage = repair.storage_until
    ? new Date(repair.storage_until).toLocaleDateString("ru")
    : "—";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Ремонт принят"
    >
      {/* Фон затемняем, но не закрываемся по клику: окно должно быть прочитано. */}
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" />

      <div className="msb-card-solid animate-slide-up relative w-full max-w-md p-6 text-center">
        <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-100 to-emerald-50 shadow-sm ring-1 ring-emerald-200">
          <span className="text-3xl">✅</span>
        </div>

        <h2 className="text-lg font-bold text-slate-900">Данные успешно сохранены</h2>
        <p className="mt-0.5 text-sm text-slate-500">Техника принята в ремонт</p>

        <p className="mt-3 font-mono text-2xl font-extrabold tracking-tight text-slate-900">
          {repair.number}
        </p>
        <p className="text-sm text-slate-500">Хранение до {storage}</p>

        {/* --- Статус этикетки --- */}
        <div
          className={`mt-4 rounded-xl px-4 py-3 text-left text-sm ring-1 ${
            labelState === "error"
              ? "bg-red-50 text-red-700 ring-red-100"
              : labelState === "ok"
                ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
                : "bg-slate-50 text-slate-600 ring-slate-200"
          }`}
        >
          {labelState === "printing" || labelState === "idle" ? (
            <p className="flex items-center gap-2">
              <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" />
              Печатаем этикетку 58×38…
            </p>
          ) : labelState === "ok" ? (
            <>
              <p className="font-medium">
                🏷️ Этикетка напечатана — проверьте принтер.
              </p>
              <p className="mt-0.5 text-xs text-emerald-700/80">
                Наклейте её на технику: на этикетке QR-код на карточку ремонта.
              </p>
              {labelPdf && (
                <button
                  onClick={() => downloadPdfBase64(labelPdf, `label-${repair.number}.pdf`)}
                  className="mt-1.5 text-xs font-semibold text-emerald-800 underline"
                >
                  ⬇ Скачать PDF этикетки
                </button>
              )}
            </>
          ) : (
            <>
              <p className="font-medium">⚠️ Этикетка не напечаталась</p>
              <p className="mt-0.5 text-xs">
                {labelMessage || "Принтер не ответил."} Проверьте принтер этикеток
                (настройка — «Админ → Принтер») и повторите печать. Ремонт при
                этом сохранён.
              </p>
              <button
                onClick={onRetryLabel}
                className="mt-2 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-700"
              >
                🔁 Повторить печать этикетки
              </button>
            </>
          )}
        </div>

        {/* --- Бланк A4 (по желанию оператора) --- */}
        {blank.asking && (
          <div className="mt-3 rounded-xl bg-amber-50 px-4 py-3 text-left text-sm ring-1 ring-amber-200">
            <p className="font-semibold text-amber-800">Бланк A4 распечатан успешно?</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                onClick={onBlankSuccess}
                className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-emerald-700"
              >
                ✓ Да, напечатано
              </button>
              <button
                onClick={onBlankFailed}
                className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-700"
              >
                ✗ Нет
                {blank.attempts >= 2 ? " — зарегистрировать без печати" : ", напечатать заново"}
              </button>
            </div>
          </div>
        )}

        {blank.message && (
          <div
            className={`mt-3 rounded-xl px-4 py-2.5 text-left text-sm ring-1 ${
              blank.message.startsWith("⚠")
                ? "bg-amber-50 text-amber-800 ring-amber-200"
                : "bg-emerald-50 text-emerald-700 ring-emerald-200"
            }`}
          >
            <p>{blank.message}</p>
            {blank.pdf && (
              <button
                onClick={() => downloadPdfBase64(blank.pdf!, `blank-${repair.number}.pdf`)}
                className="mt-1.5 text-xs font-semibold underline"
              >
                ⬇ Скачать PDF бланка
              </button>
            )}
          </div>
        )}

        {/* --- Автопереход --- */}
        <p className="mt-4 text-xs text-slate-400" aria-live="polite">
          {redirectIn !== null
            ? `Переход ко всем ремонтам через ${redirectIn} с…`
            : labelState === "error"
              ? "Автопереход отключён — сначала разберитесь с печатью."
              : "Автопереход отключён."}
        </p>

        <div className="mt-3 space-y-2">
          <button onClick={onGoList} className="msb-btn-primary w-full">
            📋 Ко всем ремонтам
          </button>
          <div className="flex gap-2">
            <button
              onClick={onPrintBlank}
              disabled={blank.busy}
              className="msb-btn-secondary flex-1 text-xs"
            >
              {blank.busy ? "Печатаем…" : "🖨️ Бланк A4"}
            </button>
            <button onClick={onOpenCard} className="msb-btn-secondary flex-1 text-xs">
              Открыть карточку
            </button>
          </div>
          <button onClick={onNewIntake} className="msb-btn-ghost w-full text-xs text-slate-600">
            ➕ Новая приёмка
          </button>
        </div>
      </div>
    </div>
  );
}
