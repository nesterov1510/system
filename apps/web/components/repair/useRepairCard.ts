"use client";

// Состояние и действия карточки ремонта.
//
// Раньше всё это жило прямо в page.tsx: ~40 useState, 7 параллельных запросов
// при каждом открытии карточки и 1300 строк разметки в одном файле. Здесь —
// та же логика, но:
//   1. данные вкладок подгружаются ЛЕНИВО (по открытию вкладки), а не все сразу;
//   2. связанные поля сгруппированы в объекты вместо десятка отдельных useState;
//   3. страница стала тонкой обёрткой над презентационными компонентами.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  getStoredUser,
  hasRole,
  type Lookup,
  type Part,
  type PartOrder,
  type Payment,
  type Photo,
  type Repair,
  type RepairPart,
} from "@/lib/api";
import { checkPhone } from "@/lib/phone";

export type TabId = "info" | "parts" | "blank" | "payment" | "timeline";

export const TABS: Array<{ id: TabId; label: string; icon: string }> = [
  { id: "info", label: "Инфо", icon: "📋" },
  { id: "parts", label: "Запчасти", icon: "🔩" },
  { id: "blank", label: "Бланк", icon: "🖨️" },
  { id: "payment", label: "Оплата", icon: "💰" },
  { id: "timeline", label: "История", icon: "📜" },
];

/** Данные для печатного бланка — одним объектом вместо 8 отдельных useState. */
export interface BlankForm {
  masters: string[];
  fault: string;
  work: string;
  warranty: string;
  eta: string;
  price: string;
}

/** Оформление починки (вкладка «Инфо»). */
export interface FinalizeForm {
  cost: string;
  payout: string;
  price: string;
  paid: boolean;
}

const EMPTY_BLANK: BlankForm = {
  masters: [],
  fault: "",
  work: "",
  warranty: "",
  eta: "",
  price: "",
};

const EMPTY_FINALIZE: FinalizeForm = { cost: "", payout: "", price: "", paid: false };

function msg(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

export function useRepairCard(id: string) {
  const [repair, setRepair] = useState<Repair | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("info");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // --- данные вкладок (подгружаются по мере открытия) ---
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [repairParts, setRepairParts] = useState<RepairPart[]>([]);
  const [partsCatalog, setPartsCatalog] = useState<Part[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [partOrders, setPartOrders] = useState<PartOrder[]>([]);
  const [mastersList, setMastersList] = useState<Lookup[]>([]);
  const [loadedTabs, setLoadedTabs] = useState<Record<string, boolean>>({});

  // --- формы ---
  const [blank, setBlank] = useState<BlankForm>(EMPTY_BLANK);
  const [finalizeForm, setFinalizeForm] = useState<FinalizeForm>(EMPTY_FINALIZE);
  const [blankSaved, setBlankSaved] = useState(false);
  const [comment, setComment] = useState("");
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState("cash");
  const [manualPartName, setManualPartName] = useState("");
  const [manualPartPrice, setManualPartPrice] = useState("");
  const [orderName, setOrderName] = useState("");
  const [orderQty, setOrderQty] = useState("1");

  // --- печать ---
  const [printMsg, setPrintMsg] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [pdfFilename, setPdfFilename] = useState("blank.pdf");

  // --- назначение мастера (в шапке карточки) ---
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignMasterId, setAssignMasterId] = useState("");
  const [assignHelperIds, setAssignHelperIds] = useState<string[]>([]);
  const [assignBusy, setAssignBusy] = useState(false);

  // --- правка марки/модели/серийника (после приёмки) ---
  const [deviceEdit, setDeviceEdit] = useState<{
    open: boolean;
    brand: string;
    model: string;
    serial: string;
  }>({ open: false, brand: "", model: "", serial: "" });
  const [deviceBusy, setDeviceBusy] = useState(false);
  const [deviceError, setDeviceError] = useState<string | null>(null);

  // --- второй контакт ---
  const [contact2Open, setContact2Open] = useState(false);
  const [contact2Name, setContact2Name] = useState("");
  const [contact2Phone, setContact2Phone] = useState("");
  const [contact2Busy, setContact2Busy] = useState(false);
  const [contact2Error, setContact2Error] = useState<string | null>(null);

  // --- SMS клиенту при «Ремонт закончен» ---
  const [smsModal, setSmsModal] = useState<{ to: string; text: string } | null>(null);
  const [smsSending, setSmsSending] = useState(false);
  const [smsMsg, setSmsMsg] = useState<string | null>(null);

  const currentUser = useMemo(() => getStoredUser(), []);
  const canAssignMaster =
    hasRole(currentUser, "admin") || hasRole(currentUser, "operator");
  // Касса и финансовые поля — только админ/менеджер/оператор (как на сервере).
  const canEditMoney =
    hasRole(currentUser, "admin") ||
    hasRole(currentUser, "manager") ||
    hasRole(currentUser, "operator");
  const canFinish = canAssignMaster;
  const canDelete = hasRole(currentUser, "admin");
  // Зеркало серверной матрицы прав (app/core/permissions.py): показываем только
  // те кнопки, которые пользователю действительно разрешены.
  const canAddPart =
    canEditMoney || hasRole(currentUser, "master") || hasRole(currentUser, "callcenter");
  const canRemovePart = canEditMoney;
  // Паспорт техники (марка/модель/серийник) правят старшие роли — как на сервере.
  const canEditDevice = canEditMoney;
  const canTakePayment = canEditMoney;
  const canRefund = hasRole(currentUser, "admin") || hasRole(currentUser, "manager");

  // -------------------------------------------------------------------------
  // Загрузка
  // -------------------------------------------------------------------------
  const loadRepair = useCallback(() => {
    return api.repair(id).then(setRepair).catch((e) => setError(msg(e, "Ошибка")));
  }, [id]);

  /** Догрузить данные конкретной вкладки (один раз за открытие карточки). */
  const loadTab = useCallback(
    async (tab: TabId, force = false) => {
      if (!force && loadedTabs[tab]) return;
      setLoadedTabs((prev) => ({ ...prev, [tab]: true }));
      try {
        if (tab === "info") {
          const [p] = await Promise.all([api.photos(id)]);
          setPhotos(p);
        } else if (tab === "parts") {
          const [rp, catalog] = await Promise.all([api.repairParts(id), api.parts()]);
          setRepairParts(rp);
          setPartsCatalog(catalog);
        } else if (tab === "blank") {
          const [orders, masters] = await Promise.all([api.partOrders(id), api.masters()]);
          setPartOrders(orders);
          setMastersList(masters);
        } else if (tab === "payment") {
          setPayments(await api.payments(id));
        }
      } catch {
        /* данные вкладки не критичны для остальной карточки */
      }
    },
    [id, loadedTabs],
  );

  // Шапка карточки показывает мастеров — их список нужен сразу.
  useEffect(() => {
    loadRepair();
    api.masters().then(setMastersList).catch(() => {});
  }, [loadRepair]);

  useEffect(() => {
    loadTab(activeTab);
  }, [activeTab, loadTab]);

  /** Обновить ремонт + данные текущей вкладки. */
  const reload = useCallback(async () => {
    await loadRepair();
    await loadTab(activeTab, true);
  }, [loadRepair, loadTab, activeTab]);

  // Синхронизация форм с данными ремонта (после загрузки и после сохранения).
  useEffect(() => {
    if (!repair) return;
    setFinalizeForm({
      cost: repair.cost_amount?.toString() ?? "",
      payout: repair.master_payout?.toString() ?? "",
      price: repair.price_final?.toString() ?? "",
      paid: repair.paid,
    });
    setBlank({
      masters: repair.master_ids ?? [],
      fault: repair.fault_master ?? "",
      work: repair.work_done ?? "",
      warranty: repair.warranty_text ?? "",
      eta: repair.eta_days?.toString() ?? "",
      price: repair.price_final?.toString() ?? "",
    });
    setAssignMasterId(repair.master_ids?.[0] ?? "");
    setAssignHelperIds(repair.helper_ids ?? []);
    setContact2Name(repair.contact2_name ?? "");
    setContact2Phone(repair.contact2_phone ?? "");
    setDeviceEdit((prev) => ({
      open: prev.open,
      brand: repair.brand ?? "",
      model: repair.model ?? "",
      serial: repair.serial ?? "",
    }));
  }, [repair]);

  // -------------------------------------------------------------------------
  // Действия
  // -------------------------------------------------------------------------
  async function patchRepair(payload: Record<string, unknown>, errText = "Ошибка") {
    setBusy(true);
    setError(null);
    try {
      setRepair(await api.updateRepair(id, payload));
      return true;
    } catch (e) {
      setError(msg(e, errText));
      return false;
    } finally {
      setBusy(false);
    }
  }

  function openDeviceEdit() {
    if (!repair) return;
    setDeviceError(null);
    setDeviceEdit({
      open: true,
      brand: repair.brand ?? "",
      model: repair.model ?? "",
      serial: repair.serial ?? "",
    });
  }

  function closeDeviceEdit() {
    setDeviceError(null);
    setDeviceEdit((prev) => ({ ...prev, open: false }));
  }

  /** Сохранить марку/модель/серийный номер уже принятого ремонта. */
  async function saveDevice() {
    if (!repair) return;
    const brand = deviceEdit.brand.trim();
    if (!brand) {
      setDeviceError("Марка техники не может быть пустой");
      return;
    }
    setDeviceBusy(true);
    setDeviceError(null);
    const ok = await patchRepair(
      {
        brand,
        model: deviceEdit.model.trim() || null,
        serial: deviceEdit.serial.trim() || null,
      },
      "Не удалось сохранить данные техники",
    );
    setDeviceBusy(false);
    if (ok) setDeviceEdit((prev) => ({ ...prev, open: false }));
  }

  const changeStatus = (status: string) => patchRepair({ status });
  const toggleDelivery = (value: boolean) => patchRepair({ is_delivery: value });

  async function removeRepair() {
    if (!repair) return;
    if (
      !confirm(`Удалить ремонт ${repair.number} и все его данные? Это действие необратимо.`)
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteRepair(id);
      window.location.href = "/repairs";
    } catch (e) {
      setError(msg(e, "Ошибка удаления"));
      setBusy(false);
    }
  }

  async function print(kind: "blank" | "label") {
    setBusy(true);
    setPrintMsg(null);
    setPdfBase64(null);
    setError(null);
    try {
      const res = kind === "label" ? await api.printLabel(id) : await api.print(id);
      setPdfBase64(res.pdf_base64);
      setPdfFilename(`${kind === "label" ? "label" : "blank"}-${repair?.number || id}.pdf`);
      setPrintMsg(
        kind === "label"
          ? "Этикетка 58×38 поставлена в очередь печати."
          : "Бланк A4 поставлен в очередь печати.",
      );
      await loadRepair();
    } catch (e) {
      setError(msg(e, kind === "label" ? "Ошибка печати этикетки" : "Ошибка печати"));
    } finally {
      setBusy(false);
    }
  }

  const doPrint = () => print("blank");
  const doPrintLabel = () => print("label");

  async function addComment() {
    if (!comment.trim()) return;
    setBusy(true);
    try {
      setRepair(await api.comment(id, comment.trim()));
      setComment("");
    } catch (e) {
      setError(msg(e, "Ошибка"));
    } finally {
      setBusy(false);
    }
  }

  async function onFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setBusy(true);
    try {
      for (const f of files) await api.uploadPhoto(id, f);
      await Promise.all([loadRepair(), loadTab("info", true)]);
    } catch (err) {
      setError(msg(err, "Ошибка загрузки фото"));
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  async function addPart(partId: string) {
    setBusy(true);
    try {
      await api.addRepairPart(id, { part_id: partId, qty: 1 });
      await loadTab("parts", true);
    } catch (err) {
      setError(msg(err, "Ошибка"));
    } finally {
      setBusy(false);
    }
  }

  // Запчасть вручную: название + цена, за которую поставили. Если такой позиции
  // нет на складе — система создаст её с нулевым остатком.
  async function addManualPart() {
    const name = manualPartName.trim();
    if (!name) return;
    setBusy(true);
    try {
      await api.addRepairPart(id, {
        name,
        qty: 1,
        price: manualPartPrice ? Number(manualPartPrice) : null,
      });
      setManualPartName("");
      setManualPartPrice("");
      await loadTab("parts", true);
    } catch (err) {
      setError(msg(err, "Ошибка"));
    } finally {
      setBusy(false);
    }
  }

  async function removePart(rpId: string) {
    setBusy(true);
    try {
      await api.removeRepairPart(id, rpId);
      await loadTab("parts", true);
    } catch (err) {
      setError(msg(err, "Ошибка"));
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
      await loadTab("payment", true);
    } catch (err) {
      setError(msg(err, "Ошибка"));
    } finally {
      setBusy(false);
    }
  }

  async function refundPayment(paymentId: string) {
    setBusy(true);
    try {
      await api.deletePayment(paymentId);
      await loadTab("payment", true);
    } catch (err) {
      setError(msg(err, "Ошибка"));
    } finally {
      setBusy(false);
    }
  }

  async function saveAssign() {
    setAssignBusy(true);
    setError(null);
    try {
      const others = (repair?.master_ids ?? []).slice(1);
      const masterIds = assignMasterId
        ? [assignMasterId, ...others.filter((m) => m !== assignMasterId)]
        : others;
      setRepair(
        await api.updateRepair(id, {
          master_ids: masterIds,
          helper_ids: assignHelperIds,
        }),
      );
      setAssignOpen(false);
    } catch (e) {
      setError(msg(e, "Ошибка назначения мастера"));
    } finally {
      setAssignBusy(false);
    }
  }

  function toggleHelper(userId: string) {
    setAssignHelperIds((prev) =>
      prev.includes(userId) ? prev.filter((h) => h !== userId) : [...prev, userId],
    );
  }

  async function saveContact2() {
    setContact2Error(null);
    if (contact2Phone.trim()) {
      const check = checkPhone(contact2Phone);
      if (!check.valid) {
        const text = check.message || "Некорректный номер телефона";
        setContact2Error(text);
        return;
      }
    }
    setContact2Busy(true);
    setError(null);
    try {
      setRepair(
        await api.updateRepair(id, {
          contact2_name: contact2Name.trim() || null,
          contact2_phone: contact2Phone.trim() || null,
        }),
      );
      setContact2Open(false);
    } catch (e) {
      setError(msg(e, "Ошибка сохранения контакта"));
    } finally {
      setContact2Busy(false);
    }
  }

  async function saveBlank() {
    setBusy(true);
    setError(null);
    setBlankSaved(false);
    try {
      const payload: Record<string, unknown> = {
        fault_master: blank.fault.trim() || null,
        work_done: blank.work.trim() || null,
        warranty_text: blank.warranty.trim() || null,
        eta_days: blank.eta ? Number(blank.eta) : null,
        price_final: blank.price ? Number(blank.price) : null,
      };
      // Мастеров менять может только admin/operator — иначе сервер вернёт 403.
      if (canAssignMaster) payload.master_ids = blank.masters;
      setRepair(await api.updateRepair(id, payload));
      setBlankSaved(true);
      setTimeout(() => setBlankSaved(false), 2500);
    } catch (e) {
      setError(msg(e, "Ошибка"));
    } finally {
      setBusy(false);
    }
  }

  function toggleBlankMaster(masterId: string) {
    setBlank((prev) => ({
      ...prev,
      masters: prev.masters.includes(masterId)
        ? prev.masters.filter((m) => m !== masterId)
        : [...prev.masters, masterId],
    }));
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
      setError(msg(e, "Ошибка"));
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
      setError(msg(e, "Ошибка"));
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
        cost_amount: finalizeForm.cost ? Number(finalizeForm.cost) : null,
        master_payout: finalizeForm.payout ? Number(finalizeForm.payout) : null,
        price_final: finalizeForm.price ? Number(finalizeForm.price) : null,
        paid: finalizeForm.paid,
      };
      if (finalizeForm.paid && repair.status === "Готово к выдаче") {
        payload.status = "Выдано";
      }
      await api.updateRepair(id, payload);
      await reload();
    } catch (err) {
      setError(msg(err, "Ошибка"));
    } finally {
      setBusy(false);
    }
  }

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
      setError(msg(e, "Ошибка"));
    } finally {
      setBusy(false);
    }
  }

  function setSmsText(text: string) {
    setSmsModal((prev) => (prev ? { ...prev, text } : prev));
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
      setSmsMsg(`Не удалось отправить SMS: ${msg(e, "Ошибка")}`);
    } finally {
      setSmsSending(false);
    }
  }

  // -------------------------------------------------------------------------
  // Производные значения
  // -------------------------------------------------------------------------
  const paidTotal = payments.reduce((s, p) => s + p.amount, 0);
  const priceFinal = repair?.price_final ?? repair?.price_max ?? 0;
  const balance = priceFinal - paidTotal;
  const complect = (repair?.complectation as { items?: string[] } | null)?.items ?? [];

  return {
    // данные
    repair, photos, repairParts, partsCatalog, payments, partOrders, mastersList,
    // ui
    activeTab, setActiveTab, error, setError, busy, printMsg, setPrintMsg,
    pdfBase64, setPdfBase64, pdfFilename,
    // формы
    blank, setBlank, blankSaved, finalizeForm, setFinalizeForm, comment, setComment,
    payAmount, setPayAmount, payMethod, setPayMethod,
    manualPartName, setManualPartName, manualPartPrice, setManualPartPrice,
    orderName, setOrderName, orderQty, setOrderQty,
    assignOpen, setAssignOpen, assignMasterId, setAssignMasterId,
    assignHelperIds, assignBusy,
    deviceEdit, setDeviceEdit, deviceBusy, deviceError, setDeviceError,
    contact2Open, setContact2Open, contact2Name, setContact2Name,
    contact2Phone, setContact2Phone, contact2Busy, contact2Error, setContact2Error,
    smsModal, smsSending, smsMsg,
    // права
    currentUser, canAssignMaster, canEditMoney, canFinish, canDelete,
    canAddPart, canRemovePart, canTakePayment, canRefund, canEditDevice,
    // производные
    paidTotal, priceFinal, balance, complect,
    // действия
    reload, changeStatus, toggleDelivery, removeRepair, doPrint, doPrintLabel,
    openDeviceEdit, closeDeviceEdit, saveDevice,
    addComment, onFiles, addPart, addManualPart, removePart, addPayment,
    refundPayment, saveAssign, toggleHelper, saveContact2, saveBlank,
    toggleBlankMaster, addOrder, removeOrder, finalize, openFinish,
    setSmsText, closeSmsModal, sendSmsNow,
  };
}

export type RepairCardState = ReturnType<typeof useRepairCard>;
