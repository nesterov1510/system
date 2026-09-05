"use client";

// Вкладка «История»: лента событий ремонта (статусы, комментарии, печать,
// звонки, цены, назначения) + добавление комментария.

import type { RepairCardState } from "../useRepairCard";

const EVENT_LABELS: Record<string, string> = {
  status_change: "изменение статуса",
  comment: "комментарий",
  print: "печать",
  call: "звонок",
  price: "цена",
  photo: "фото",
  assign: "назначение",
  notify: "уведомление",
};

const EVENT_ICONS: Record<string, string> = {
  status_change: "🔄",
  comment: "💬",
  print: "🖨️",
  call: "📞",
  price: "💰",
  photo: "📷",
  assign: "👤",
  notify: "🔔",
};

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString("ru") : "—";
}

export default function TimelineTab({ s }: { s: RepairCardState }) {
  const events = s.repair?.events ?? [];

  return (
    <section className="msb-card-solid p-4 sm:p-5">
      <h2 className="msb-section-title mb-4">📜 История ремонта</h2>

      {events.length === 0 ? (
        <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-6 text-sm text-slate-400">
          История пока пуста
        </div>
      ) : (
        <ol className="relative">
          {events.map((e, i) => {
            const data = (e.data ?? {}) as Record<string, unknown>;
            return (
              <li key={e.id} className="relative flex gap-3 pb-5 last:pb-0">
                {i < events.length - 1 && (
                  <div className="absolute bottom-0 left-[15px] top-7 w-0.5 bg-slate-200" />
                )}
                <div className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white text-sm shadow-sm ring-1 ring-slate-200">
                  {EVENT_ICONS[e.type] ?? "📌"}
                </div>
                <div className="min-w-0 flex-1 pt-0.5">
                  <div className="flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                    <span>{fmt(e.created_at)}</span>
                    <span>·</span>
                    <span className="font-medium">{EVENT_LABELS[e.type] ?? e.type}</span>
                  </div>
                  {e.type === "status_change" && e.data && (
                    <div className="mt-1 text-sm text-slate-700">
                      <span className="text-slate-400">{String(data.from ?? "—")}</span>
                      <span className="mx-1.5 text-slate-300">→</span>
                      <span className="font-medium">{String(data.to ?? "")}</span>
                    </div>
                  )}
                  {/* data.message — человекочитаемое описание события: его пишут
                      комментарии, платежи, запчасти, назначения, печать и SMS.
                      Раньше лента показывала только комментарии, остальные
                      события выглядели пустыми строками. */}
                  {typeof data.message === "string" && data.message && e.type !== "status_change" && (
                    <div className="mt-1 rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-700 ring-1 ring-slate-100">
                      {String(data.message)}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      <div className="msb-divider mt-5 pt-4">
        <div className="flex gap-2">
          <input
            value={s.comment}
            onChange={(e) => s.setComment(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && s.addComment()}
            placeholder="Написать комментарий…"
            aria-label="Комментарий к ремонту"
            className="msb-input flex-1"
          />
          <button
            onClick={s.addComment}
            disabled={s.busy || !s.comment.trim()}
            className="msb-btn-primary"
          >
            Отправить
          </button>
        </div>
      </div>
    </section>
  );
}
