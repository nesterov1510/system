"use client";

// Вкладка «Бланк»: данные, которые уходят в печатный бланк A4
// (Inžiner 1…4, Kemçilik, Gürleşilen baha, Kepillik…) + заказанные запчасти.

import type { RepairCardState } from "../useRepairCard";

const WARRANTY_PRESETS = ["1 aý", "3 aý", "6 aý", "1 ýyl"];

export default function BlankTab({ s }: { s: RepairCardState }) {
  const b = s.blank;

  return (
    <div className="space-y-5">
      <section className="msb-card-solid p-4 sm:p-5">
        <h2 className="msb-section-title mb-1">🖨️ Данные для бланка</h2>
        <p className="mb-4 text-xs text-slate-500">
          Всё, что заполнено здесь, печатается в бланке ремонта.
        </p>

        <span className="msb-label">
          Мастера <span className="text-slate-400">(Inžiner 1…4)</span>
        </span>
        <div className="flex flex-wrap gap-1.5">
          {s.mastersList.length === 0 && (
            <span className="text-sm text-slate-400">Список мастеров пуст</span>
          )}
          {s.mastersList.map((m) => {
            const idx = b.masters.indexOf(m.id);
            const active = idx >= 0;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => s.toggleBlankMaster(m.id)}
                disabled={s.busy || !s.canAssignMaster}
                title={s.canAssignMaster ? undefined : "Назначает администратор или оператор"}
                className={`rounded-lg px-3 py-2 text-sm font-medium ring-1 transition-colors ${
                  active
                    ? "bg-msb-600 text-white ring-msb-600"
                    : "bg-white text-slate-600 ring-slate-200 hover:ring-msb-300"
                } ${!s.canAssignMaster ? "cursor-not-allowed opacity-60" : ""}`}
              >
                {active && <span className="mr-1 font-bold">{idx + 1}.</span>}
                {m.name}
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Можно выбрать нескольких — в бланке они встанут в строки «Inžiner» по
          порядку. Первый считается основным мастером ремонта.
          {!s.canAssignMaster && " Назначает администратор или оператор."}
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div>
            <label className="msb-label" htmlFor="blank-price">
              Цена ремонта, ман. <span className="text-slate-400">(Gürleşilen baha)</span>
            </label>
            <input
              id="blank-price"
              type="number"
              value={b.price}
              placeholder="0"
              disabled={!s.canEditMoney}
              onChange={(e) => s.setBlank({ ...b, price: e.target.value })}
              className="msb-input"
            />
          </div>
          <div>
            <label className="msb-label" htmlFor="blank-eta">
              Срок ремонта, дней <span className="text-slate-400">(Aýdylan wagty)</span>
            </label>
            <input
              id="blank-eta"
              type="number"
              value={b.eta}
              placeholder="0"
              onChange={(e) => s.setBlank({ ...b, eta: e.target.value })}
              className="msb-input"
            />
          </div>
          <div>
            <label className="msb-label" htmlFor="blank-warranty">
              Гарантия <span className="text-slate-400">(Kepillik)</span>
            </label>
            <input
              id="blank-warranty"
              value={b.warranty}
              placeholder="напр. 3 aý"
              onChange={(e) => s.setBlank({ ...b, warranty: e.target.value })}
              className="msb-input"
            />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {WARRANTY_PRESETS.map((w) => (
                <button
                  key={w}
                  type="button"
                  onClick={() => s.setBlank({ ...b, warranty: w })}
                  className="min-h-[44px] rounded-lg bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200 sm:min-h-0"
                >
                  {w}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div>
            <label className="msb-label" htmlFor="blank-fault">
              Неисправности <span className="text-slate-400">(Kemçilik)</span>
            </label>
            <textarea
              id="blank-fault"
              value={b.fault}
              rows={4}
              onChange={(e) => s.setBlank({ ...b, fault: e.target.value })}
              placeholder={"Одна неисправность — одна строка:\nНе включается\nШумит вентилятор"}
              className="msb-input resize-y"
            />
          </div>
          <div>
            <label className="msb-label" htmlFor="blank-work">
              Что починили{" "}
              <span className="text-slate-400">(Düzedilen enjamyn görkezmesi)</span>
            </label>
            <textarea
              id="blank-work"
              value={b.work}
              rows={4}
              onChange={(e) => s.setBlank({ ...b, work: e.target.value })}
              placeholder="Заменена клавиатура, чистка системы охлаждения…"
              className="msb-input resize-y"
            />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button onClick={s.saveBlank} disabled={s.busy} className="msb-btn-primary">
            Сохранить для печати
          </button>
          {s.blankSaved && (
            <span className="text-sm font-medium text-emerald-600">✓ Сохранено</span>
          )}
          <button onClick={s.doPrint} disabled={s.busy} className="msb-btn-secondary ml-auto">
            🖨️ Печать A4
          </button>
        </div>
      </section>

      <section className="msb-card-solid p-4 sm:p-5">
        <h2 className="msb-section-title mb-1">📦 Заказанные запчасти</h2>
        <p className="mb-3 text-xs text-slate-500">
          Sargalan gerek bolan ätiýaçlyk şaýlary — что заказали под этот ремонт.
          Установленные запчасти берутся из вкладки «Запчасти».
        </p>

        {s.partOrders.length === 0 ? (
          <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-6 text-sm text-slate-400">
            Ничего не заказано
          </div>
        ) : (
          <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl ring-1 ring-slate-100">
            {s.partOrders.map((o) => (
              <li
                key={o.id}
                className="flex items-center justify-between gap-3 bg-slate-50/60 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <span className="text-sm font-medium text-slate-800">{o.name}</span>
                  <span className="ml-2 text-xs text-slate-500">×{o.qty}</span>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className="text-xs text-slate-500">
                    {o.ordered_at ? new Date(o.ordered_at).toLocaleDateString("ru") : "—"}
                  </span>
                  <button
                    onClick={() => s.removeOrder(o.id)}
                    disabled={s.busy}
                    className="min-h-[44px] text-xs font-medium text-red-500 transition-colors hover:text-red-700 sm:min-h-0"
                  >
                    Удалить
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <div className="min-w-[200px] flex-1">
            <label className="msb-label" htmlFor="order-name">
              Название запчасти
            </label>
            <input
              id="order-name"
              value={s.orderName}
              onChange={(e) => s.setOrderName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") s.addOrder();
              }}
              placeholder="Матрица 15.6 FHD"
              className="msb-input"
            />
          </div>
          <div className="w-24">
            <label className="msb-label" htmlFor="order-qty">
              Кол-во
            </label>
            <input
              id="order-qty"
              type="number"
              min={1}
              value={s.orderQty}
              onChange={(e) => s.setOrderQty(e.target.value)}
              className="msb-input"
            />
          </div>
          <button
            onClick={s.addOrder}
            disabled={s.busy || !s.orderName.trim()}
            className="msb-btn-primary"
          >
            + Заказать
          </button>
        </div>
      </section>
    </div>
  );
}
