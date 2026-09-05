"use client";

// Модалки карточки ремонта: уведомление клиента по SMS после «Ремонт закончен»
// и второй контакт по ремонту (владелец ≠ тот, кто привёз технику).

import { useEffect } from "react";
import type { RepairCardState } from "./useRepairCard";

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="msb-card-solid animate-slide-up relative w-full max-w-md p-5">
        <div className="mb-3 flex items-start justify-between gap-3">
          <h3 className="msb-section-title mb-0">{title}</h3>
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="min-h-0 -mr-1 -mt-1 p-1 text-slate-400 transition-colors hover:text-slate-600"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export default function RepairModals({ s }: { s: RepairCardState }) {
  return (
    <>
      {s.smsModal && (
        <Modal title="✅ Ремонт закончен" onClose={s.closeSmsModal}>
          <p className="mb-3 text-sm text-slate-600">
            Ремонт переведён в статус «Готово к выдаче». Отправить уведомление
            клиенту по SMS? Текст можно изменить или пропустить.
          </p>
          <div className="mb-3 flex items-center gap-2 rounded-xl bg-slate-50 px-4 py-2.5 text-sm text-slate-600 ring-1 ring-slate-100">
            <span>📞</span>
            <span className="font-medium">{s.smsModal.to}</span>
          </div>
          <label className="msb-label" htmlFor="sms-text">
            Текст SMS
          </label>
          <textarea
            id="sms-text"
            value={s.smsModal.text}
            onChange={(e) => s.setSmsText(e.target.value)}
            rows={4}
            className="msb-input mb-3 resize-y"
          />
          {s.smsMsg && (
            <div
              className={`mb-3 rounded-xl px-4 py-2.5 text-sm ring-1 ${
                s.smsMsg.startsWith("Не удалось")
                  ? "bg-red-50 text-red-600 ring-red-100"
                  : "bg-emerald-50 text-emerald-700 ring-emerald-200"
              }`}
            >
              {s.smsMsg}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={s.sendSmsNow}
              disabled={s.smsSending || !s.smsModal.text.trim()}
              className="msb-btn-primary flex-1"
            >
              {s.smsSending ? "Отправка…" : "📤 Отправить SMS"}
            </button>
            <button onClick={s.closeSmsModal} disabled={s.smsSending} className="msb-btn-secondary">
              Без SMS
            </button>
          </div>
        </Modal>
      )}

      {s.contact2Open && (
        <Modal title="📞 Второй контакт" onClose={() => s.setContact2Open(false)}>
          <p className="mb-3 text-sm text-slate-600">
            Например: владелец техники и тот, кто её доставил — разные люди. Этот
            контакт привязан только к текущему ремонту.
          </p>
          <div className="space-y-3">
            <div>
              <label className="msb-label" htmlFor="c2-name">
                Имя
              </label>
              <input
                id="c2-name"
                className="msb-input"
                value={s.contact2Name}
                onChange={(e) => s.setContact2Name(e.target.value)}
                placeholder="Напр. курьер / доставщик"
              />
            </div>
            <div>
              <label className="msb-label" htmlFor="c2-phone">
                Телефон
              </label>
              <input
                id="c2-phone"
                className="msb-input"
                value={s.contact2Phone}
                onChange={(e) => {
                  s.setContact2Phone(e.target.value);
                  s.setContact2Error(null);
                }}
                inputMode="tel"
                placeholder="+993 61 000000"
              />
              {s.contact2Error && (
                <p className="mt-1 text-xs font-medium text-red-600">⚠ {s.contact2Error}</p>
              )}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={s.saveContact2}
              disabled={s.contact2Busy}
              className="msb-btn-primary flex-1"
            >
              {s.contact2Busy ? "Сохраняем…" : "Сохранить"}
            </button>
            <button
              onClick={() => s.setContact2Open(false)}
              disabled={s.contact2Busy}
              className="msb-btn-secondary"
            >
              Отмена
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
