"use client";

// Вкладка «Запчасти»: что списано под ремонт (со склада или вручную).
// Права повторяют серверную матрицу: мастер может списать деталь, но цену
// задают только старшие роли, убирают позицию тоже только они.

import { money } from "@/lib/api";
import type { RepairCardState } from "../useRepairCard";

export default function PartsTab({ s }: { s: RepairCardState }) {
  const total = s.repairParts.reduce(
    (sum, rp) => sum + (rp.price != null ? rp.price * rp.qty : 0),
    0,
  );

  return (
    <section className="msb-card-solid p-4 sm:p-5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="msb-section-title mb-0">🔩 Запчасти</h2>
        {s.repairParts.length > 0 && (
          <span className="text-sm text-slate-500">
            Итого: <b className="text-slate-800">{money(total)}</b>
          </span>
        )}
      </div>

      {s.repairParts.length === 0 ? (
        <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-6 text-sm text-slate-400">
          Запчасти не добавлены
        </div>
      ) : (
        <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl ring-1 ring-slate-100">
          {s.repairParts.map((rp) => (
            <li
              key={rp.id}
              className="flex items-center justify-between gap-3 bg-slate-50/60 px-3 py-2.5"
            >
              <div className="min-w-0">
                <span className="text-sm font-medium text-slate-800">{rp.part_name}</span>
                {rp.is_manual && (
                  <span className="msb-badge-gray ml-1.5 px-2 py-0.5 text-[10px]">вручную</span>
                )}
                <span className="ml-2 text-xs text-slate-500">×{rp.qty}</span>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                {rp.price != null && (
                  <span className="text-sm font-semibold text-slate-800">
                    {money(rp.price * rp.qty)}
                  </span>
                )}
                {s.canRemovePart && (
                  <button
                    onClick={() => s.removePart(rp.id)}
                    disabled={s.busy}
                    className="min-h-[44px] text-xs font-medium text-red-500 transition-colors hover:text-red-700 sm:min-h-0"
                  >
                    Удалить
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {!s.canAddPart ? (
        <p className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-500 ring-1 ring-slate-100">
          Списывать запчасти под ремонт может оператор, менеджер, администратор
          или мастер, который ведёт этот ремонт.
        </p>
      ) : (
        <div className="mt-4 space-y-3">
          <div>
            <label className="msb-label" htmlFor="part-catalog">
              Добавить со склада
            </label>
            <select
              id="part-catalog"
              defaultValue=""
              disabled={s.busy}
              onChange={(e) => {
                if (e.target.value) s.addPart(e.target.value);
                e.target.value = "";
              }}
              className="msb-input"
            >
              <option value="">Выберите запчасть…</option>
              {s.partsCatalog
                .filter((p) => p.stock_qty > 0)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.stock_qty} шт
                    {s.canEditMoney ? ` · ${money(p.sell_price)}` : ""}
                  </option>
                ))}
            </select>
          </div>

          {s.canEditMoney && (
            <div className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-100">
              <label className="msb-label" htmlFor="part-manual">
                Или вручную — название + цена
              </label>
              <div className="mt-1.5 flex flex-wrap items-end gap-2">
                <input
                  id="part-manual"
                  value={s.manualPartName}
                  onChange={(e) => s.setManualPartName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") s.addManualPart();
                  }}
                  placeholder="Напр. Матрица 15.6 FHD"
                  className="msb-input min-w-[180px] flex-1"
                />
                <input
                  type="number"
                  value={s.manualPartPrice}
                  onChange={(e) => s.setManualPartPrice(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") s.addManualPart();
                  }}
                  placeholder="Цена, ман."
                  aria-label="Цена запчасти"
                  className="msb-input w-32"
                />
                <button
                  onClick={s.addManualPart}
                  disabled={s.busy || !s.manualPartName.trim()}
                  className="msb-btn-primary px-4"
                >
                  + Добавить
                </button>
              </div>
              <p className="mt-2 text-xs text-slate-400">
                Впишите запчасть, которую поставили под ремонт, и её цену — даже
                если её нет на складе.
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
