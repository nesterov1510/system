"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  api,
  downloadPdfBase64,
  getStoredUser,
  hasRole,
  mediaUrl,
  money,
  type Lookup,
  type Part,
  type PartOrder,
  type Payment,
  type Photo,
  type Repair,
  type RepairPart,
} from "@/lib/api";
import { checkPhone } from "@/lib/phone";

// Статус ремонта в карточке — только 4 этапа (как и на доске).
const STAGES = [
  { status: "Принято", label: "Новый ремонт", color: "msb-badge-info" },
  { status: "Диагностика", label: "Диагностика", color: "msb-badge-warning" },
  { status: "В ремонте", label: "В ремонте", color: "msb-badge-cyan" },
  { status: "Готово к выдаче", label: "Закончен", color: "msb-badge-success" },
];
// Из какого «этапа» текущий статус (чтобы показать выбранную колонку).
const STAGE_OF: Record<string, string> = {
  Принято: "Принято",
  Диагностика: "Диагностика",
  Согласование: "В ремонте",
  "Ожидание запчастей": "В ремонте",
  "В ремонте": "В ремонте",
  "Готово к выдаче": "Готово к выдаче",
  Выдано: "Готово к выдаче",
  "Не забрано": "Готово к выдаче",
  Архив: "Готово к выдаче",
  Отказ: "Готово к выдаче",
};
function stageRep(status: string): string {
  return STAGE_OF[status] ?? "Принято";
}
function stageMeta(status: string) {
  const rep = stageRep(status);
  return STAGES.find((s) => s.status === rep) ?? STAGES[0];
}

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
  // --- данные для печатного бланка ---
  const [mastersList, setMastersList] = useState<Lookup[]>([]);
  const [partOrders, setPartOrders] = useState<PartOrder[]>([]);
  const [blankMasters, setBlankMasters] = useState<string[]>([]);
  const [blankFault, setBlankFault] = useState("");
  const [blankWork, setBlankWork] = useState("");
  const [blankWarranty, setBlankWarranty] = useState("");
  const [blankEta, setBlankEta] = useState("");
  const [blankPrice, setBlankPrice] = useState("");
  const [orderName, setOrderName] = useState("");
  const [orderQty, setOrderQty] = useState("1");
  const [blankSaved, setBlankSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [printMsg, setPrintMsg] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [pdfFilename, setPdfFilename] = useState("blank.pdf");
  const [activeTab, setActiveTab] = useState("info");
  const fileRef = useRef<HTMLInputElement>(null);
  // Модалка SMS клиенту при «Ремонт закончен».
  const [smsModal, setSmsModal] = useState<{ to: string; text: string } | null>(null);
  const [smsSending, setSmsSending] = useState(false);
  const [smsMsg, setSmsMsg] = useState<string | null>(null);

  // 7) Мастер/помощники — теперь сразу видны и меняются в шапке карточки,
  // не только во вкладке «Бланк».
  const [topMasterOpen, setTopMasterOpen] = useState(false);
  const [topMasterId, setTopMasterId] = useState("");
  const [topHelperIds, setTopHelperIds] = useState<string[]>([]);
  const [topAssignBusy, setTopAssignBusy] = useState(false);

  // 6) Второй контакт по ремонту (владелец техники vs. тот, кто её доставил).
  const [contact2ModalOpen, setContact2ModalOpen] = useState(false);
  const [contact2Name, setContact2Name] = useState("");
  const [contact2Phone, setContact2Phone] = useState("");
  const [contact2Busy, setContact2Busy] = useState(false);
  const [contact2Error, setContact2Error] = useState<string | null>(null);

  const load = useCallback(() => {
    api.repair(id).then(setRepair).catch((e) => setError(e.message));
    api.photos(id).then(setPhotos).catch(() => {});
    api.repairParts(id).then(setRepairParts).catch(() => {});
    api.parts().then(setPartsCatalog).catch(() => {});
    api.payments(id).then(setPayments).catch(() => {});
    api.partOrders(id).then(setPartOrders).catch(() => {});
    api.masters().then(setMastersList).catch(() => {});
  }, [id]);

  useEffect(load, [load]);

  const currentUser = getStoredUser();

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

  async function removeThis() {
    if (!repair) return;
    if (!confirm(`Удалить ремонт ${repair.number} и все его данные? Это действие необратимо.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteRepair(id);
      window.location.href = "/repairs";
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления");
      setBusy(false);
    }
  }

  async function doPrint() {
    setBusy(true);
    setPrintMsg(null);
    setPdfBase64(null);
    setError(null);
    try {
      const res = await api.print(id);
      setPdfBase64(res.pdf_base64);
      setPdfFilename(`blank-${repair?.number || id}.pdf`);
      setPrintMsg("Бланк A4 поставлен в очередь печати.");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка печати");
    } finally {
      setBusy(false);
    }
  }

  async function doPrintLabel() {
    setBusy(true);
    setPrintMsg(null);
    setPdfBase64(null);
    setError(null);
    try {
      const res = await api.printLabel(id);
      setPdfBase64(res.pdf_base64);
      setPdfFilename(`label-${repair?.number || id}.pdf`);
      setPrintMsg("Этикетка 58×38 поставлена в очередь печати.");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка печати этикетки");
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
      setBlankMasters(repair.master_ids ?? []);
      setBlankFault(repair.fault_master ?? "");
      setBlankWork(repair.work_done ?? "");
      setBlankWarranty(repair.warranty_text ?? "");
      setBlankEta(repair.eta_days?.toString() ?? "");
      setBlankPrice(repair.price_final?.toString() ?? "");
      setTopMasterId(repair.master_ids?.[0] ?? "");
      setTopHelperIds(repair.helper_ids ?? []);
      setContact2Name(repair.contact2_name ?? "");
      setContact2Phone(repair.contact2_phone ?? "");
    }
  }, [repair]);

  const canAssignMaster = hasRole(currentUser, "admin") || hasRole(currentUser, "operator");

  // Смена основного мастера прямо в шапке карточки (не только во вкладке «Бланк»).
  async function saveTopMaster() {
    setTopAssignBusy(true);
    setError(null);
    try {
      const otherMasters = (repair?.master_ids ?? []).slice(1);
      const newMasterIds = topMasterId
        ? [topMasterId, ...otherMasters.filter((m) => m !== topMasterId)]
        : otherMasters;
      const updated = await api.updateRepair(id, {
        master_ids: newMasterIds,
        helper_ids: topHelperIds,
      });
      setRepair(updated);
      setTopMasterOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка назначения мастера");
    } finally {
      setTopAssignBusy(false);
    }
  }

  function toggleTopHelper(userId: string) {
    setTopHelperIds((prev) =>
      prev.includes(userId) ? prev.filter((h) => h !== userId) : [...prev, userId],
    );
  }

  // Второй контакт по ремонту (item 6).
  async function saveContact2() {
    setContact2Error(null);
    if (contact2Phone.trim()) {
      const check = checkPhone(contact2Phone);
      if (!check.valid) {
        setContact2Error(check.message || "Некорректный номер телефона");
        alert(check.message || "Некорректный номер телефона. Исправьте номер телефона.");
        return;
      }
    }
    setContact2Busy(true);
    setError(null);
    try {
      const updated = await api.updateRepair(id, {
        contact2_name: contact2Name.trim() || null,
        contact2_phone: contact2Phone.trim() || null,
      });
      setRepair(updated);
      setContact2ModalOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения контакта");
    } finally {
      setContact2Busy(false);
    }
  }

  // --- бланк: сохранение и заказанные запчасти ---
  async function saveBlank() {
    setBusy(true);
    setError(null);
    setBlankSaved(false);
    try {
      const updated = await api.updateRepair(id, {
        master_ids: blankMasters,
        fault_master: blankFault.trim() || null,
        work_done: blankWork.trim() || null,
        warranty_text: blankWarranty.trim() || null,
        eta_days: blankEta ? Number(blankEta) : null,
        price_final: blankPrice ? Number(blankPrice) : null,
      });
      setRepair(updated);
      setBlankSaved(true);
      setTimeout(() => setBlankSaved(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  function toggleMaster(masterId: string) {
    setBlankMasters((prev) =>
      prev.includes(masterId)
        ? prev.filter((m) => m !== masterId)
        : [...prev, masterId],
    );
  }

  async function addOrder() {
    const name = orderName.trim();
    if (!name) return;
    setBusy(true);
    try {
      await api.addPartOrder(id, { name, qty: Number(orderQty) || 1 });
      setOrderName("");
      setOrderQty("1");
      setPartOrders(await api.partOrders(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function removeOrder(orderId: string) {
    setBusy(true);
    try {
      await api.removePartOrder(id, orderId);
      setPartOrders(await api.partOrders(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

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

  // --- «Ремонт закончен» + SMS клиенту ---
  async function openFinish() {
    if (!repair) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.finishRepair(id);
      setRepair(res.repair);
      setSmsMsg(null);
      setSmsModal({ to: res.sms.to, text: res.sms.text });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  function closeSmsModal() {
    setSmsModal(null);
    setSmsMsg(null);
  }

  async function sendSmsNow() {
    if (!smsModal) return;
    setSmsSending(true);
    setSmsMsg(null);
    try {
      await api.sendFinishSms(id, smsModal.text.trim());
      setSmsMsg("SMS отправлено клиенту ✓");
      setRepair(await api.repair(id));
    } catch (e) {
      setSmsMsg(`Не удалось отправить SMS: ${e instanceof Error ? e.message : "Ошибка"}`);
    } finally {
      setSmsSending(false);
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
    { id: "blank", label: "Бланк", icon: "🖨️" },
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
        <div className="flex flex-wrap gap-2">
          <button onClick={doPrintLabel} disabled={busy}
            className="msb-btn-primary">
            🏷️ Этикетка 58×38
          </button>
          <button onClick={doPrint} disabled={busy}
            className="msb-btn-secondary">
            🖨️ Бланк A4
          </button>
          {(hasRole(currentUser, "admin") || hasRole(currentUser, "operator")) &&
            !["Выдано", "Не забрано", "Архив", "Отказ"].includes(repair.status) && (
              <button onClick={openFinish} disabled={busy}
                className="rounded-xl bg-emerald-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-emerald-700">
                ✅ Ремонт закончен
              </button>
            )}
          {hasRole(currentUser, "admin") && (
            <button onClick={removeThis} disabled={busy}
              className="rounded-xl bg-red-50 px-3 py-2 text-sm font-medium text-red-600 ring-1 ring-red-200 transition-colors hover:bg-red-100">
              🗑 Удалить
            </button>
          )}
        </div>
      </div>

      {/* 7) Мастер/помощники — видно сразу, сменить можно тут же, без вкладки «Бланк» */}
      <div className="msb-card-solid p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <div>
              <p className="text-xs font-medium text-slate-500">Мастер</p>
              <p className="text-sm font-semibold text-slate-800">
                {repair.master_names?.[0] || repair.master_name || "— не назначен —"}
              </p>
            </div>
            {repair.helper_names && repair.helper_names.length > 0 && (
              <div>
                <p className="text-xs font-medium text-slate-500">
                  Помощник(и) <span className="text-slate-400">(Inžiner (kömekçi))</span>
                </p>
                <p className="text-sm font-semibold text-slate-800">
                  {repair.helper_names.join(", ")}
                </p>
              </div>
            )}
          </div>
          {canAssignMaster && (
            <button onClick={() => setTopMasterOpen((v) => !v)}
              className="msb-btn-secondary text-xs py-2 px-4">
              {topMasterOpen ? "Свернуть" : "✏️ Сменить / назначить"}
            </button>
          )}
        </div>

        {topMasterOpen && canAssignMaster && (
          <div className="mt-4 space-y-4 border-t border-slate-100 pt-4">
            <div>
              <label className="msb-label">Основной мастер</label>
              <select className="msb-input" value={topMasterId}
                onChange={(e) => setTopMasterId(e.target.value)}>
                <option value="">— не назначен —</option>
                {mastersList.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="msb-label">
                Помощники <span className="text-slate-400">(в бланке — «Inžiner (kömekçi)»)</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {mastersList.filter((m) => m.id !== topMasterId).map((m) => {
                  const active = topHelperIds.includes(m.id);
                  return (
                    <button key={m.id} type="button" onClick={() => toggleTopHelper(m.id)}
                      className={`rounded-xl px-3 py-2 text-sm font-medium ring-1 transition-all ${
                        active
                          ? "bg-msb-600 text-white ring-msb-600"
                          : "bg-white text-slate-600 ring-slate-200 hover:ring-msb-300"}`}>
                      {m.name}
                    </button>
                  );
                })}
              </div>
            </div>
            <button onClick={saveTopMaster} disabled={topAssignBusy}
              className="msb-btn-primary">
              {topAssignBusy ? "Сохраняем…" : "Сохранить назначение"}
            </button>
          </div>
        )}
      </div>

      {/* Header Card */}
      <div className="msb-card-solid overflow-hidden">
        <div className="bg-gradient-to-r from-msb-600 to-msb-800 px-6 py-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-msb-200">Ремонт</p>
              <h1 className="font-mono text-2xl font-extrabold text-white">{repair.number}</h1>
            </div>
            <select
              value={stageRep(repair.status)}
              onChange={(e) => changeStatus(e.target.value)}
              disabled={busy}
              className={`rounded-xl border-0 px-4 py-2 text-sm font-semibold outline-none focus:ring-2 focus:ring-white/50 ${stageMeta(repair.status).color}`}>
              {STAGES.map((s) => (
                <option key={s.status} value={s.status}>{s.label}</option>
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
          {/* 6) Второй контакт по ремонту — напр. владелец техники и доставщик */}
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
            {repair.contact2_name || repair.contact2_phone ? (
              <div className="text-sm">
                <span className="font-medium text-slate-500">Второй контакт:</span>{" "}
                <span className="font-medium text-slate-800">{repair.contact2_name || "—"}</span>
                {repair.contact2_phone && (
                  <span className="ml-2 font-mono text-slate-600">{repair.contact2_phone}</span>
                )}
              </div>
            ) : (
              <span className="text-sm text-slate-400">Второй контакт не указан</span>
            )}
            <button onClick={() => setContact2ModalOpen(true)}
              className="ml-auto text-xs font-semibold text-msb-600 hover:text-msb-700">
              {repair.contact2_name || repair.contact2_phone ? "✏️ Изменить" : "＋ Добавить"}
            </button>
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

        {/* Бланк для печати */}
        {activeTab === "blank" && (
          <div className="msb-card-solid p-6">
            <h2 className="msb-section-title mb-1">🖨️ Данные для бланка</h2>
            <p className="mb-5 text-xs text-slate-500">
              Всё, что заполнено здесь, печатается в бланке ремонта.
            </p>

            {/* Мастера */}
            <label className="msb-label">
              Мастера <span className="text-slate-400">(Inžiner 1…4)</span>
            </label>
            <div className="flex flex-wrap gap-2">
              {mastersList.length === 0 && (
                <span className="text-sm text-slate-400">Список мастеров пуст</span>
              )}
              {mastersList.map((m) => {
                const idx = blankMasters.indexOf(m.id);
                const active = idx >= 0;
                return (
                  <button key={m.id} type="button" onClick={() => toggleMaster(m.id)}
                    disabled={busy}
                    className={`rounded-xl px-3 py-2 text-sm font-medium ring-1 transition-all ${
                      active
                        ? "bg-msb-600 text-white ring-msb-600"
                        : "bg-white text-slate-600 ring-slate-200 hover:ring-msb-300"}`}>
                    {active && <span className="mr-1 font-bold">{idx + 1}.</span>}
                    {m.name}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-xs text-slate-400">
              Можно выбрать нескольких — в бланке они встанут в строки «Inžiner» по порядку.
              Первый считается основным мастером ремонта.
            </p>

            <div className="mt-5 grid gap-4 sm:grid-cols-3">
              <div>
                <label className="msb-label">
                  Цена ремонта, ман. <span className="text-slate-400">(Gürleşilen baha)</span>
                </label>
                <input type="number" value={blankPrice} placeholder="0"
                  onChange={(e) => setBlankPrice(e.target.value)} className="msb-input" />
              </div>
              <div>
                <label className="msb-label">
                  Срок ремонта, дней <span className="text-slate-400">(Aýdylan wagty)</span>
                </label>
                <input type="number" value={blankEta} placeholder="0"
                  onChange={(e) => setBlankEta(e.target.value)} className="msb-input" />
              </div>
              <div>
                <label className="msb-label">
                  Гарантия <span className="text-slate-400">(Kepillik)</span>
                </label>
                <input value={blankWarranty} placeholder="напр. 3 aý"
                  onChange={(e) => setBlankWarranty(e.target.value)} className="msb-input" />
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {["1 aý", "3 aý", "6 aý", "1 ýyl"].map((w) => (
                    <button key={w} type="button" onClick={() => setBlankWarranty(w)}
                      className="rounded-lg bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200">
                      {w}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div>
                <label className="msb-label">
                  Неисправности <span className="text-slate-400">(Kemçilik)</span>
                </label>
                <textarea value={blankFault} rows={4}
                  onChange={(e) => setBlankFault(e.target.value)}
                  placeholder={"Одна неисправность — одна строка:\nНе включается\nШумит вентилятор"}
                  className="msb-input resize-y" />
              </div>
              <div>
                <label className="msb-label">
                  Что починили <span className="text-slate-400">(Düzedilen enjamyn görkezmesi)</span>
                </label>
                <textarea value={blankWork} rows={4}
                  onChange={(e) => setBlankWork(e.target.value)}
                  placeholder="Заменена клавиатура, чистка системы охлаждения…"
                  className="msb-input resize-y" />
              </div>
            </div>

            <div className="mt-4 flex items-center gap-3">
              <button onClick={saveBlank} disabled={busy} className="msb-btn-primary">
                Сохранить для печати
              </button>
              {blankSaved && (
                <span className="text-sm font-medium text-emerald-600">✓ Сохранено</span>
              )}
              <button onClick={doPrint} disabled={busy} className="msb-btn-secondary ml-auto">
                🖨️ Печать A4
              </button>
            </div>

            {/* Заказанные запчасти */}
            <h2 className="msb-section-title mt-8 mb-1">
              📦 Заказанные запчасти
            </h2>
            <p className="mb-4 text-xs text-slate-500">
              Sargalan gerek bolan ätiýaçlyk şaýlary — что заказали под этот ремонт.
              Установленные запчасти берутся из вкладки «Запчасти».
            </p>
            {partOrders.length === 0 ? (
              <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-6 text-sm text-slate-400">
                Ничего не заказано
              </div>
            ) : (
              <div className="space-y-2">
                {partOrders.map((o) => (
                  <div key={o.id}
                    className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
                    <div>
                      <span className="text-sm font-medium text-slate-800">{o.name}</span>
                      <span className="ml-2 text-xs text-slate-500">×{o.qty}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-slate-500">
                        {o.ordered_at ? new Date(o.ordered_at).toLocaleDateString("ru") : "—"}
                      </span>
                      <button onClick={() => removeOrder(o.id)} disabled={busy}
                        className="text-xs font-medium text-red-500 transition-colors hover:text-red-700">
                        Удалить
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4 flex flex-wrap items-end gap-3">
              <div className="min-w-[200px] flex-1">
                <label className="msb-label">Название запчасти</label>
                <input value={orderName} onChange={(e) => setOrderName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") addOrder(); }}
                  placeholder="Матрица 15.6 FHD" className="msb-input" />
              </div>
              <div className="w-24">
                <label className="msb-label">Кол-во</label>
                <input type="number" min={1} value={orderQty}
                  onChange={(e) => setOrderQty(e.target.value)} className="msb-input" />
              </div>
              <button onClick={addOrder} disabled={busy || !orderName.trim()}
                className="msb-btn-primary">
                + Заказать
              </button>
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

      {/* SMS-модалка «Ремонт закончен» */}
      {smsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={closeSmsModal} />
          <div className="relative w-full max-w-md msb-card-solid p-6 animate-slide-up">
            <div className="flex items-start justify-between gap-3">
              <h3 className="msb-section-title">✅ Ремонт закончен</h3>
              <button onClick={closeSmsModal} className="text-slate-400 hover:text-slate-600">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <p className="mb-4 text-sm text-slate-600">
              Ремонт переведён в статус «Готово к выдаче». Отправить уведомление
              клиенту по SMS? Текст можно изменить или пропустить.
            </p>
            <div className="mb-3 flex items-center gap-2 rounded-xl bg-slate-50 px-4 py-2.5 text-sm text-slate-600 ring-1 ring-slate-100">
              <span>📞</span>
              <span className="font-medium">{smsModal.to}</span>
            </div>
            <label className="msb-label">Текст SMS</label>
            <textarea
              value={smsModal.text}
              onChange={(e) => setSmsModal({ ...smsModal, text: e.target.value })}
              rows={4}
              className="msb-input resize-y mb-4"
            />
            {smsMsg && (
              <div className={`mb-4 rounded-xl px-4 py-2.5 text-sm ring-1 ${
                smsMsg.startsWith("Не удалось")
                  ? "bg-red-50 text-red-600 ring-red-100"
                  : "bg-emerald-50 text-emerald-700 ring-emerald-200"
              }`}>
                {smsMsg}
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button onClick={sendSmsNow} disabled={smsSending || !smsModal.text.trim()}
                className="msb-btn-primary flex-1">
                {smsSending ? "Отправка…" : "📤 Отправить SMS"}
              </button>
              <button onClick={closeSmsModal} disabled={smsSending}
                className="msb-btn-secondary">
                Без SMS
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 6) Модалка второго контакта по ремонту */}
      {contact2ModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setContact2ModalOpen(false)} />
          <div className="relative w-full max-w-md msb-card-solid p-6 animate-slide-up">
            <div className="flex items-start justify-between gap-3">
              <h3 className="msb-section-title">📞 Второй контакт</h3>
              <button onClick={() => setContact2ModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <p className="mb-4 text-sm text-slate-600">
              Например: владелец техники и тот, кто её доставил — разные люди.
              Этот контакт привязан только к текущему ремонту.
            </p>
            <div className="space-y-3">
              <div>
                <label className="msb-label">Имя</label>
                <input className="msb-input" value={contact2Name}
                  onChange={(e) => setContact2Name(e.target.value)}
                  placeholder="Напр. курьер / доставщик" />
              </div>
              <div>
                <label className="msb-label">Телефон</label>
                <input className="msb-input" value={contact2Phone}
                  onChange={(e) => { setContact2Phone(e.target.value); setContact2Error(null); }}
                  inputMode="tel" placeholder="+993 61 000000" />
                {contact2Error && (
                  <p className="mt-1 text-xs font-medium text-red-600">⚠ {contact2Error}</p>
                )}
              </div>
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              <button onClick={saveContact2} disabled={contact2Busy}
                className="msb-btn-primary flex-1">
                {contact2Busy ? "Сохраняем…" : "Сохранить"}
              </button>
              <button onClick={() => setContact2ModalOpen(false)} disabled={contact2Busy}
                className="msb-btn-secondary">
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Print message */}
      {printMsg && (
        <div className="flex items-start gap-3 rounded-xl bg-emerald-50 px-5 py-4 ring-1 ring-emerald-200 animate-slide-up">
          <span className="text-lg leading-none">✅</span>
          <div className="flex-1">
            <p className="text-sm font-medium text-emerald-800">{printMsg}</p>
            {pdfBase64 && (
              <button onClick={() => downloadPdfBase64(pdfBase64, pdfFilename)}
                className="mt-2 msb-btn-secondary text-xs">
                ⬇ Скачать PDF
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