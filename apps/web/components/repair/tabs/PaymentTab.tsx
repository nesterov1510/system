"use client";

// Вкладка «Оплата»: к оплате / оплачено / остаток, история платежей и приём
// нового. Кнопки зависят от прав: платёж принимает касса (админ/менеджер/
// оператор), сторнируют только админ и менеджер.

import { money } from "@/lib/api";
import type { RepairCardState } from "../useRepairCard";

const METHOD_LABELS: Record<string, string> = {
  cash: "Наличные",
  card: "Карта",
  transfer: "Перевод",
};

export default function PaymentTab({ s }: { s: RepairCardState }) {
  const balance = s.balance > 0 ? s.balance : 0;

  return (
    <section className="msb-card-solid p-4 sm:p-5">
      <h2 className="msb-section-title mb-3">💰 Оплата</h2>

      <div className="mb-4 grid grid-cols-3 gap-2">
        <Stat label="К оплате" value={money(s.priceFinal)} />
        <Stat label="Оплачено" value={money(s.paidTotal)} tone="text-emerald-600" />
        <Stat
          label="Остаток"
          value={money(balance)}
          tone={balance > 0 ? "text-amber-600" : "text-slate-900"}
        />
      </div>

      {s.payments.length > 0 && (
        <ul className="mb-4 divide-y divide-slate-100 overflow-hidden rounded-xl ring-1 ring-slate-100">
          {s.payments.map((p) => (
            <li
              key={p.id}
              className="flex items-center justify-between gap-3 bg-slate-50/60 px-3 py-2.5"
            >
              <div className="min-w-0 text-sm text-slate-600">
                {new Date(p.paid_at).toLocaleDateString("ru")} ·{" "}
                {METHOD_LABELS[p.method] ?? p.method}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="text-sm font-semibold text-slate-800">{money(p.amount)}</span>
                {s.canRefund && (
                  <button
                    onClick={() => s.refundPayment(p.id)}
                    disabled={s.busy}
                    className="min-h-[44px] text-xs font-medium text-red-500 transition-colors hover:text-red-700 sm:min-h-0"
                  >
                    Отменить
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {s.canTakePayment ? (
        <div className="flex flex-wrap gap-2">
          <input
            type="number"
            value={s.payAmount}
            onChange={(e) => s.setPayAmount(e.target.value)}
            placeholder="Сумма"
            aria-label="Сумма платежа"
            className="msb-input w-32"
          />
          <select
            value={s.payMethod}
            onChange={(e) => s.setPayMethod(e.target.value)}
            aria-label="Способ оплаты"
            className="msb-input min-w-[120px] flex-1"
          >
            <option value="cash">Наличные</option>
            <option value="card">Карта</option>
            <option value="transfer">Перевод</option>
          </select>
          <button
            onClick={s.addPayment}
            disabled={s.busy || !s.payAmount}
            className="msb-btn-primary"
          >
            Принять платёж
          </button>
        </div>
      ) : (
        <p className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-500 ring-1 ring-slate-100">
          Платежи принимает касса: администратор, менеджер или оператор.
        </p>
      )}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="msb-stat px-2 py-3 text-center">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-lg font-bold sm:text-xl ${tone ?? "text-slate-900"}`}>{value}</div>
    </div>
  );
}
