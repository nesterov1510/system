"use client";

// Карточка ремонта.
//
// Страница — тонкая обёртка: состояние и действия живут в useRepairCard,
// разметка — в RepairHeader, вкладках и RepairModals. Так карточка стала
// заметно легче и для оператора (одна компактная шапка вместо трёх блоков,
// плотнее отступы, без тяжёлого градиента), и для кода (~1300 строк → ~120).

import { useParams } from "next/navigation";
import { downloadPdfBase64 } from "@/lib/api";
import RepairHeader from "@/components/repair/RepairHeader";
import RepairModals from "@/components/repair/RepairModals";
import { TABS, useRepairCard } from "@/components/repair/useRepairCard";
import InfoTab from "@/components/repair/tabs/InfoTab";
import PartsTab from "@/components/repair/tabs/PartsTab";
import BlankTab from "@/components/repair/tabs/BlankTab";
import PaymentTab from "@/components/repair/tabs/PaymentTab";
import TimelineTab from "@/components/repair/tabs/TimelineTab";

export default function RepairCardPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";
  const s = useRepairCard(id);

  if (!s.repair) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-400">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-msb-500 border-t-transparent" />
          <span className="text-sm font-medium">{s.error || "Загрузка…"}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      {s.error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100"
        >
          <span>⚠</span> {s.error}
        </div>
      )}

      <RepairHeader s={s} />

      {s.printMsg && (
        <div className="animate-slide-up flex items-start gap-3 rounded-xl bg-emerald-50 px-4 py-3 ring-1 ring-emerald-200">
          <span className="text-lg leading-none">✅</span>
          <div className="flex-1">
            <p className="text-sm font-medium text-emerald-800">{s.printMsg}</p>
            {s.pdfBase64 && (
              <button
                onClick={() => downloadPdfBase64(s.pdfBase64!, s.pdfFilename)}
                className="msb-btn-secondary mt-2 text-xs"
              >
                ⬇ Скачать PDF
              </button>
            )}
          </div>
          <button
            onClick={() => s.setPrintMsg(null)}
            aria-label="Скрыть"
            className="min-h-0 p-1 text-emerald-500 hover:text-emerald-700"
          >
            ✕
          </button>
        </div>
      )}

      <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => s.setActiveTab(tab.id)}
            aria-current={s.activeTab === tab.id}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              s.activeTab === tab.id
                ? "bg-white text-msb-700 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            <span aria-hidden>{tab.icon}</span>
            <span className="hidden sm:inline">{tab.label}</span>
          </button>
        ))}
      </div>

      <div className="animate-fade-in">
        {s.activeTab === "info" && <InfoTab s={s} />}
        {s.activeTab === "parts" && <PartsTab s={s} />}
        {s.activeTab === "blank" && <BlankTab s={s} />}
        {s.activeTab === "payment" && <PaymentTab s={s} />}
        {s.activeTab === "timeline" && <TimelineTab s={s} />}
      </div>

      <RepairModals s={s} />
    </div>
  );
}
