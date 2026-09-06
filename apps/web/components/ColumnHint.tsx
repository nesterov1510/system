"use client";

// Кнопка-пояснение к колонке таблицы.
//
// Заголовки колонок в списке ремонтов сокращены (эмодзи + короткое слово),
// поэтому рядом с каждым стоит «?» с человеческим объяснением: что это за
// колонка и откуда берутся значения.
//
// Подсказка рисуется через position:fixed, а не absolute: таблица лежит в
// `overflow-x-auto`, и обычный absolutely-позиционированный поповер там
// обрезался бы (или растягивал прокрутку).

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

interface Props {
  /** Краткий заголовок колонки (показывается в шапке таблицы). */
  label: string;
  /** Полное пояснение: что это за колонка. */
  hint: string;
  /** Необязательные строки-уточнения (например, из каких полей считается). */
  details?: string[];
}

export default function ColumnHint({ label, hint, details }: Props) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  const place = useCallback(() => {
    const el = btnRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const width = 260;
    // Не вылезать за правый край экрана.
    const left = Math.max(8, Math.min(r.left - width / 2 + r.width / 2, window.innerWidth - width - 8));
    setPos({ top: r.bottom + 6, left });
  }, []);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onDown = (e: MouseEvent | TouchEvent) => {
      const t = e.target as Node;
      if (popRef.current?.contains(t) || btnRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onScroll = () => setOpen(false);
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("touchstart", onDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("touchstart", onDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Что означает колонка «${label}»`}
        aria-expanded={open}
        title={hint}
        className="inline-flex h-4 w-4 min-h-0 shrink-0 items-center justify-center rounded-full bg-slate-200 text-[10px] font-bold leading-none text-slate-600 transition-colors hover:bg-msb-500 hover:text-white"
      >
        ?
      </button>

      {open && pos && (
        <div
          ref={popRef}
          role="tooltip"
          style={{ top: pos.top, left: pos.left, width: 260 }}
          className="fixed z-[60] rounded-xl bg-slate-900 p-3 text-left shadow-xl"
        >
          <p className="text-xs font-semibold text-white">{label}</p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-200">{hint}</p>
          {details && details.length > 0 && (
            <ul className="mt-2 space-y-1 border-t border-white/10 pt-2">
              {details.map((d) => (
                <li key={d} className="text-[11px] leading-snug text-slate-300">
                  · {d}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
