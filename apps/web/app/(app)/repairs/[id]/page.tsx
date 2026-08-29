"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  api,
  downloadPdfBase64,
  mediaUrl,
  money,
  type Part,
  type Payment,
  type Photo,
  type Repair,
  type RepairPart,
} from "@/lib/api";

const STATUSES = [
  "Принято",
  "Диагностика",
  "Согласование",
  "Ожидание запчастей",
  "В ремонте",
  "Готово к выдаче",
  "Выдано",
  "Не забрано",
  "Архив",
  "Отказ",
];

const STATUS_COLORS: Record<string, string> = {
  Принято: "msb-badge-info",
  Диагностика: "msb-badge-warning",
  Согласование: "msb-badge-purple",
  "Ожидание запчастей": "bg-orange-100 text-orange-700",
  "В ремонте": "msb-badge-cyan",
  "Готово к выдаче": "msb-badge-success",
  Выдано: "msb-badge-gray",
  "Не забрано": "bg-rose-100 text-rose-700",
  Архив: "msb-badge-gray",
  Отказ: "msb-badge-danger",
};

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

const METHOD_LABELS: Record<string, string> = {
  cash: "Наличные",
  card: "Карта",
  transfer: "Перевод",
};

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString("ru") : "—";
}

export default function RepairCardPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [repair, setRepair] = useState<Repair | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [repairParts, setRepairParts] = useState<RepairPart[]>([]);
  const [partsCatalog, setPartsCatalog] = useState<Part[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState("cash");
  const [finalCost, setFinalCost] = useState("");
  const [finalPrice, setFinalPrice] = useState("");
  const [finalPaid, setFinalPaid] = useState(false);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [printMsg, setPrintMsg] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("info");
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    api.repair(id).then(setRepair).catch((e) => setError(e.message));
    api.photos(id).then(setPhotos).catch(() => {});
    api.repairParts(id).then(setRepairParts).catch(() => {});
    api.parts().then(setPartsCatalog).catch(() => {});
    api.payments(id).then(setPayments).catch(() => {});
  }, [id]);

  useEffect(load, [load]);

  async function changeStatus(status: string) {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateRepair(id, { status });
      setRepair(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function doPrint() {
    setBusy(true);
    setPrintMsg(null);
    setPdfBase64(null);
    try {
      const res = await api.print(id);
      setPdfBase64(res.pdf_base64);
      setPrintMsg("Задание отправлено принтеру.");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка печати");
    } finally {
      setBusy(false);
    }
  }

  async function addComment() {
    if (!comment.trim()) return;
    setBusy(true);
    try {
      const updated = await api.comment(id, comment.trim());
      setRepair(updated);
      setComment("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function onFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setBusy(true);
    try {
      for (const f of files) {
        await api.uploadPhoto(id, f);
      }
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки фото");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function addPart(partId: string) {
    setBusy(true);
    try {
      await api.addRepairPart(id, partId, 1);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function removePart(rpId: string) {
    setBusy(true);
    try {
      await api.removeRepairPart(id, rpId);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function addPayment() {
    const amount = Number(payAmount);
    if (!amount || amount <= 0) return;
    setBusy(true);
    try {
      await api.addPayment(id, amount, payMethod);
      setPayAmount("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function refundPayment(paymentId: string) {
    setBusy(true);
    try {
      await api.deletePayment(paymentId);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (repair) {
      setFinalCost(repair.cost_amount?.toString() ?? "");
      setFinalPrice(repair.price_final?.toString() ?? "");
      setFinalPaid(repair.paid);
    }
  }, [repair]);

  async function finalize() {
    if (!repair) return;
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        cost_amount: finalCost ? Number(finalCost) : null,
        price_final: finalPrice ? Number(finalPrice) : null,
        paid: finalPaid,
      };
      if (finalPaid && repair.status === "Готово к выдаче") {
        payload.status = "Выдано";
      }
      await api.updateRepair(id, payload);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  if (!repair) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-400">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-msb-500 border-t-transparent" />
          <span className="text-sm font-medium">{error || "Загрузка…"}</span>
        </div>
      </div>
    );
  }

  const paidTotal = payments.reduce((s, p) => s + p.amount, 0);
  const priceFinal = repair.price_final ?? repair.price_max ?? 0;
  const balance = priceFinal - paidTotal;
  const complect = (repair.complectation as { items?: string[] } | null)?.items;

  const TABS = [
    { id: "info", label: "Инфо", icon: "📋" },
    { id: "parts", label: "Запчасти", icon: "🔩" },
    { id: "payment", label: "Оплата", icon: "💰" },
    { id: "timeline", label: "История", icon: "📜" },
  ];

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Back + Print */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/repairs"
          className="msb-btn-ghost text-slate-500 hover:text-slate-700">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          К доске
        </Link>
        <div className="flex gap-2">
          <button onClick={doPrint} disabled={busy}
            className="msb-btn-secondary">
            🖨️ Печать
          </button>
        </div>
      </div>

      {/* Header Card */}
      <div className="msb-card-solid overflow-hidden">
        <div className="bg-gradient-to-r from-msb-600 to-msb-800 px-6 py-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-msb-200">Ремонт</p>
              <h1 className="font-mono text-2xl font-extrabold text-white">{repair.number}</h1>
            </div>
            <select value={repair.status} onChange={(e) => changeStatus(e.target.value)}
              disabled={busy}
              className={`rounded-xl border-0 px-4 py-2 text-sm font-semibold outline-none focus:ring-2 focus:ring-white/50 ${
                STATUS_COLORS[repair.status] ?? "msb-badge-gray"
              }`}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="p-6">
          <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
            <Detail label="Клиент" value={repair.client_name} icon="👤" />
            <Detail label="Телефон" value={repair.client_phone} icon="📞" />
            <Detail label="Техника" value={[repair.device_type, repair.brand, repair.model].filter(Boolean).join(" · ")} icon="📺" />
            <Detail label="Серийный №" value={repair.serial} icon="🏷️" />
            <Detail label="Принято" value={fmt(repair.accepted_at)} icon="📅" />
            <Detail label="ETA / дней" value={repair.eta_days?.toString()} icon="⏱️" />
            <Detail label="Хранение до" value={fmt(repair.storage_until)} icon="📦" />
            <Detail label="Неисправность" value={repair.fault_client} icon="🔧" className="col-span-2" />
          </div>
          {complect && complect.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {complect.map((item) => (
                <span key={item} className="msb-badge-info">{item}</span>
              ))}
            </div>
          )}
          {repair.condition_notes && (
            <div className="mt-3 text-sm text-slate-600">
              <span className="font-medium text-slate-500">Состояние:</span> {repair.condition_notes}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 rounded-2xl bg-slate-100 p-1.5">
        {TABS.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex flex-1 items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-all ${
              activeTab === tab.id
                ? "bg-white text-msb-700 shadow-sm"
                : "text-slate-500 hover:text-slate-700"}`}>
            <span>{tab.icon}</span>
            <span className="hidden sm:inline">{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="animate-fade-in">
        {/* Info tab */}
        {activeTab === "info" && (
          <div className="msb-card-solid p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="msb-section-title">📷 Фото</h2>
              <button onClick={() => fileRef.current?.click()} disabled={busy}
                className="msb-btn-primary text-xs py-2 px-4">
                + Добавить
              </button>
              <input ref={fileRef} type="file" accept="image/*" capture="environment"
                multiple onChange={onFiles} className="hidden" />
            </div>
            {photos.length === 0 ? (
              <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-8 text-sm text-slate-400">
                Фото пока нет
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
                {photos.map((p) => (
                  <a key={p.id} href={mediaUrl(p.url)} target="_blank" rel="noopener noreferrer"
                    className="group relative aspect-square overflow-hidden rounded-xl bg-slate-100 ring-1 ring-slate-200">
                    <img src={mediaUrl(p.url)} alt={p.caption || "фото"}
                      className="h-full w-full object-cover transition-all duration-300 group-hover:scale-105" />
                    {p.caption && (
                      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent p-2">
                        <p className="text-[10px] text-white">{p.caption}</p>
                      </div>
                    )}
                  </a>
                ))}
              </div>
            )}

            {/* Оформление починки */}
            <h2 className="msb-section-title mt-8 mb-4">📋 Оформление починки</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="msb-label">Расходы (себестоимость), ман.</label>
                <input type="number" value={finalCost}
                  onChange={(e) => setFinalCost(e.target.value)} placeholder="0"
                  className="msb-input" />
              </div>
              <div>
                <label className="msb-label">Цена ремонта, ман.</label>
                <input type="number" value={finalPrice}
                  onChange={(e) => setFinalPrice(e.target.value)} placeholder="0"
                  className="msb-input" />
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
              <label className="flex items-center gap-2 text-sm font-medium text-slate-700 cursor-pointer">
                <input type="checkbox" checked={finalPaid}
                  onChange={(e) => setFinalPaid(e.target.checked)}
                  className="h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500" />
                Отмечено как оплачено
              </label>
              <div className="text-sm text-slate-600">
                Прибыль: <span className="font-bold text-emerald-600">{money((Number(finalPrice) || 0) - (Number(finalCost) || 0))}</span>
              </div>
            </div>
            <button onClick={finalize} disabled={busy}
              className="msb-btn-primary mt-4 w-full">
              Сохранить оформление
            </button>
          </div>
        )}

        {/* Parts tab */}
        {activeTab === "parts" && (
          <div className="msb-card-solid p-6">
            <h2 className="msb-section-title mb-4">🔩 Запчасти</h2>
            {repairParts.length === 0 ? (
              <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-8 text-sm text-slate-400">
                Запчасти не добавлены
              </div>
            ) : (
              <div className="space-y-2">
                {repairParts.map((rp) => (
                  <div key={rp.id}
                    className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
                    <div>
                      <span className="text-sm font-medium text-slate-800">{rp.part_name}</span>
                      <span className="ml-2 text-xs text-slate-500">×{rp.qty}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      {rp.price != null && (
                        <span className="text-sm font-semibold text-slate-800">{money(rp.price * rp.qty)}</span>
                      )}
                      <button onClick={() => removePart(rp.id)} disabled={busy}
                        className="text-xs font-medium text-red-500 hover:text-red-700 transition-colors">
                        Удалить
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4">
              <label className="msb-label">Добавить запчасть</label>
              <select onChange={(e) => { if (e.target.value) addPart(e.target.value); e.target.value = ""; }}
                disabled={busy} defaultValue=""
                className="msb-input">
                <option value="">Выберите запчасть…</option>
                {partsCatalog.filter(p => p.stock_qty > 0).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.stock_qty} шт · {money(p.sell_price)}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Payment tab */}
        {activeTab === "payment" && (
          <div className="msb-card-solid p-6">
            <h2 className="msb-section-title mb-4">💰 Оплата</h2>

            <div className="grid grid-cols-3 gap-3 mb-5">
              <div className="msb-stat text-center">
                <div className="text-xs text-slate-500">К оплате</div>
                <div className="text-xl font-bold text-slate-900">{money(priceFinal)}</div>
              </div>
              <div className="msb-stat text-center">
                <div className="text-xs text-slate-500">Оплачено</div>
                <div className="text-xl font-bold text-emerald-600">{money(paidTotal)}</div>
              </div>
              <div className="msb-stat text-center">
                <div className="text-xs text-slate-500">Остаток</div>
                <div className={`text-xl font-bold ${balance > 0 ? "text-amber-600" : "text-slate-900"}`}>
                  {money(balance > 0 ? balance : 0)}
                </div>
              </div>
            </div>

            {payments.length > 0 && (
              <div className="mb-4 space-y-2">
                {payments.map((p) => (
                  <div key={p.id}
                    className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
                    <div className="text-sm text-slate-600">
                      {new Date(p.paid_at).toLocaleDateString("ru")} · {METHOD_LABELS[p.method] ?? p.method}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-semibold text-slate-800">{money(p.amount)}</span>
                      <button onClick={() => refundPayment(p.id)} disabled={busy}
                        className="text-xs font-medium text-red-500 hover:text-red-700 transition-colors">
                        Отменить
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="flex flex-wrap gap-3">
              <input type="number" value={payAmount}
                onChange={(e) => setPayAmount(e.target.value)}
                placeholder="Сумма" className="msb-input w-32" />
              <select value={payMethod} onChange={(e) => setPayMethod(e.target.value)}
                className="msb-input flex-1 min-w-[120px]">
                <option value="cash">Наличные</option>
                <option value="card">Карта</option>
                <option value="transfer">Перевод</option>
              </select>
              <button onClick={addPayment} disabled={busy || !payAmount}
                className="msb-btn-primary">
                Принять платёж
              </button>
            </div>
          </div>
        )}

        {/* Timeline tab */}
        {activeTab === "timeline" && (
          <div className="msb-card-solid p-6">
            <h2 className="msb-section-title mb-4">📜 История ремонта</h2>

            {repair.events.length === 0 ? (
              <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-8 text-sm text-slate-400">
                История пока пуста
              </div>
            ) : (
              <div className="relative space-y-0">
                {repair.events.map((e, i) => (
                  <div key={e.id} className="relative flex gap-4 pb-6 last:pb-0">
                    {/* Timeline line */}
                    {i < repair.events.length - 1 && (
                      <div className="absolute left-[17px] top-8 bottom-0 w-0.5 bg-slate-200" />
                    )}
                    {/* Dot */}
                    <div className="relative z-10 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white shadow-sm ring-1 ring-slate-200">
                      <span className="text-sm">{EVENT_ICONS[e.type] ?? "📌"}</span>
                    </div>
                    {/* Content */}
                    <div className="flex-1 min-w-0 pt-1">
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <span>{fmt(e.created_at)}</span>
                        <span>·</span>
                        <span className="font-medium">{EVENT_LABELS[e.type] ?? e.type}</span>
                      </div>
                      {e.type === "status_change" && e.data && (
                        <div className="mt-1 text-sm text-slate-700">
                          <span className="text-slate-400">{String((e.data as Record<string, unknown>).from ?? "—")}</span>
                          <span className="mx-1.5 text-slate-300">→</span>
                          <span className="font-medium">{String((e.data as Record<string, unknown>).to ?? "")}</span>
                        </div>
                      )}
                      {e.type === "comment" && e.data && (
                        <div className="mt-1 rounded-xl bg-slate-50 px-4 py-2.5 text-sm text-slate-700 ring-1 ring-slate-100">
                          {String((e.data as Record<string, unknown>).message ?? "")}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* New comment */}
            <div className="mt-6 msb-divider pt-4">
              <div className="flex gap-3">
                <input value={comment} onChange={(e) => setComment(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addComment()}
                  placeholder="Написать комментарий…" className="msb-input flex-1" />
                <button onClick={addComment} disabled={busy || !comment.trim()}
                  className="msb-btn-primary">
                  Отправить
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Print message */}
      {printMsg && (
        <div className="flex items-start gap-3 rounded-xl bg-emerald-50 px-5 py-4 ring-1 ring-emerald-200 animate-slide-up">
          <span className="text-lg leading-none">✅</span>
          <div className="flex-1">
            <p className="text-sm font-medium text-emerald-800">{printMsg}</p>
            {pdfBase64 && (
              <button onClick={() => downloadPdfBase64(pdfBase64, `blank-${repair.number}.pdf`)}
                className="mt-2 msb-btn-secondary text-xs">
                ⬇ Скачать PDF бланка
              </button>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}
    </div>
  );
}

function Detail({ label, value, icon, className }: {
  label: string; value?: string | null; icon?: string; className?: string;
}) {
  return (
    <div className={className}>
      <div className="flex items-center gap-1 text-xs font-medium text-slate-500">
        {icon && <span>{icon}</span>}
        <span>{label}</span>
      </div>
      <div className="mt-0.5 text-sm font-medium text-slate-800">{value || "—"}</div>
    </div>
  );
}