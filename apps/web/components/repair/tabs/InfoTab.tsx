"use client";

// Вкладка «Инфо»: фото ремонта + оформление починки (себестоимость, выплата
// мастерам, цена). Паспорт ремонта (клиент, техника, сроки, цена) теперь живёт
// в компактной шапке — дублировать его здесь не нужно, карточка стала легче.

import { useRef } from "react";
import { mediaUrl, money } from "@/lib/api";
import type { RepairCardState } from "../useRepairCard";

export default function InfoTab({ s }: { s: RepairCardState }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const f = s.finalizeForm;
  const profit = (Number(f.price) || 0) - (Number(f.cost) || 0);

  return (
    <div className="space-y-5">
      <section className="msb-card-solid p-4 sm:p-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="msb-section-title mb-0">📷 Фото</h2>
          <div>
            <button
              onClick={() => fileRef.current?.click()}
              disabled={s.busy}
              className="msb-btn-primary px-4 py-2 text-xs"
            >
              + Добавить
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              capture="environment"
              multiple
              onChange={s.onFiles}
              className="hidden"
            />
          </div>
        </div>

        {s.photos.length === 0 ? (
          <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-6 text-sm text-slate-400">
            Фото пока нет
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4">
            {s.photos.map((p) => (
              <a
                key={p.id}
                href={mediaUrl(p.url)}
                target="_blank"
                rel="noopener noreferrer"
                className="group relative aspect-square overflow-hidden rounded-xl bg-slate-100 ring-1 ring-slate-200"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={mediaUrl(p.url)}
                  alt={p.caption || "фото"}
                  loading="lazy"
                  className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                />
                {p.caption && (
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent p-1.5">
                    <p className="text-[10px] text-white">{p.caption}</p>
                  </div>
                )}
              </a>
            ))}
          </div>
        )}
      </section>

      <section className="msb-card-solid p-4 sm:p-5">
        <h2 className="msb-section-title mb-1">📋 Оформление починки</h2>

        {!s.canEditMoney ? (
          <p className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-500 ring-1 ring-slate-100">
            Себестоимость, выплату мастерам и цену заполняет администратор,
            менеджер или оператор кассы.
          </p>
        ) : (
          <>
            <p className="mb-4 text-xs text-slate-500">
              Итоговые цифры ремонта: сколько потратили, сколько выплатили
              мастерам и сколько берём с клиента.
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className="msb-label" htmlFor="fin-cost">
                  Расходы (себестоимость), ман.
                </label>
                <input
                  id="fin-cost"
                  type="number"
                  value={f.cost}
                  onChange={(e) => s.setFinalizeForm({ ...f, cost: e.target.value })}
                  placeholder="0"
                  className="msb-input"
                />
              </div>
              <div>
                <label className="msb-label" htmlFor="fin-payout">
                  Мастерам выплачено, ман.
                </label>
                <input
                  id="fin-payout"
                  type="number"
                  value={f.payout}
                  onChange={(e) => s.setFinalizeForm({ ...f, payout: e.target.value })}
                  placeholder="0"
                  className="msb-input"
                />
              </div>
              <div>
                <label className="msb-label" htmlFor="fin-price">
                  Цена ремонта, ман.
                </label>
                <input
                  id="fin-price"
                  type="number"
                  value={f.price}
                  onChange={(e) => s.setFinalizeForm({ ...f, price: e.target.value })}
                  placeholder="0"
                  className="msb-input"
                />
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 px-4 py-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-700">
                <input
                  type="checkbox"
                  checked={f.paid}
                  onChange={(e) => s.setFinalizeForm({ ...f, paid: e.target.checked })}
                  className="h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500"
                />
                Отмечено как оплачено
              </label>
              <div className="text-sm text-slate-600">
                Прибыль:{" "}
                <span className="font-bold text-emerald-600">{money(profit)}</span>
              </div>
            </div>

            <button
              onClick={s.finalize}
              disabled={s.busy}
              className="msb-btn-primary mt-3 w-full"
            >
              Сохранить оформление
            </button>
          </>
        )}
      </section>
    </div>
  );
}
