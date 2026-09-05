"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  api,
  downloadPdfBase64,
  getStoredUser,
  hasRole,
  money,
  type Lookup,
  type PriceHint,
  type Repair,
} from "@/lib/api";
import { checkPhone } from "@/lib/phone";
import DeviceCombinedField, {
  joinDeviceCombined,
  splitDeviceCombined,
} from "@/components/DeviceCombinedField";
import IntakeDoneDialog, { type LabelState } from "@/components/repair/IntakeDoneDialog";

// Сколько секунд окно «ремонт принят» висит перед автопереходом на доску.
// За это время оператор успевает снять этикетку с принтера и наклеить её.
const REDIRECT_SECONDS = 6;

// Техника делится на классы: телевизоры / компьютеры / бытовая техника / другое.
const DEVICE_TYPES = ["Телевизоры", "Компьютеры", "Бытовая техника", "Другое"];
const DEVICE_ICONS: Record<string, string> = {
  Телевизоры: "📺",
  Компьютеры: "🖥️",
  "Бытовая техника": "🧺",
  Другое: "⚙️",
};
const BRAND_CHIPS = ["Samsung", "LG", "Xiaomi", "Sony", "Philips", "TCL"];
const CONDITION_ITEMS = ["Линии на экране", "Царапины"];

const SECTION_STEPS = [
  { id: "client", label: "Клиент", icon: "👤" },
  { id: "device", label: "Техника", icon: "📺" },
  { id: "service", label: "Сервис", icon: "🔧" },
];

interface ClientLookup {
  found: boolean;
  multiple?: boolean;
  candidates?: Array<{ id: string; full_name: string; phone: string; repairs_count: number }>;
  client?: { id: string; full_name: string; phone: string };
  repairs?: Array<{
    id: string; number: string; status: string;
    device_type: string; brand?: string | null; model?: string | null;
    accepted_at: string | null;
    price_final?: number | null;
    paid: boolean;
  }>;
  repairs_count?: number;
}

interface ClientRow {
  id: string;
  full_name: string;
  phone: string;
  repairs_count: number;
}

export default function NewRepairPage() {
  const router = useRouter();
  const [cities, setCities] = useState<Lookup[]>([]);
  const [masters, setMasters] = useState<Lookup[]>([]);
  const [items, setItems] = useState<Lookup[]>([]);

  const [cityId, setCityId] = useState("");
  const [clientName, setClientName] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [existingClient, setExistingClient] = useState<ClientLookup | null>(null);
  const [lookingUp, setLookingUp] = useState(false);

  // 1) Выбор контакта из уже существующих в системе (не из контактов телефона).
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerResults, setPickerResults] = useState<ClientRow[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);

  // 6) Второй контакт по ремонту (напр. владелец техники ≠ доставивший).
  const [contact2Open, setContact2Open] = useState(false);
  const [contact2Name, setContact2Name] = useState("");
  const [contact2Phone, setContact2Phone] = useState("");
  const [contact2Error, setContact2Error] = useState<string | null>(null);

  const [deviceType, setDeviceType] = useState("Телевизоры");
  // 3) Марка + модель + серийный номер — одно поле, сегменты через «..».
  const [deviceCombined, setDeviceCombined] = useState("");
  const { brand, model, serial } = splitDeviceCombined(deviceCombined);
  const [complect, setComplect] = useState<string[]>([]);
  const [conditions, setConditions] = useState<string[]>([]);
  const [conditionOther, setConditionOther] = useState("");
  const [fault, setFault] = useState("");
  const [masterId, setMasterId] = useState("");
  const [etaDays, setEtaDays] = useState("");
  const [consent, setConsent] = useState(true);
  const [consentRepair, setConsentRepair] = useState(true);
  // Заказ доставлен курьером / забран с адреса клиента (а не принесён лично).
  const [isDelivery, setIsDelivery] = useState(false);
  const [photos, setPhotos] = useState<File[]>([]);
  const [step, setStep] = useState(0);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Repair | null>(null);
  // Этикетка печатается сама, сразу после сохранения (см. useEffect ниже).
  const [labelState, setLabelState] = useState<LabelState>("idle");
  const [labelMessage, setLabelMessage] = useState<string | null>(null);
  const [labelPdf, setLabelPdf] = useState<string | null>(null);
  // Обратный отсчёт до перехода на «Все ремонты»; null = автопереход выключен.
  const [redirectIn, setRedirectIn] = useState<number | null>(null);
  const labelAutoRef = useRef(false);
  const [priceHint, setPriceHint] = useState<PriceHint | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // 4) Печать бланка: спрашиваем «успешно?» и предлагаем повтор / регистрацию без печати.
  const [printAttempts, setPrintAttempts] = useState(0);
  const [printAsking, setPrintAsking] = useState(false);
  const [printBusy, setPrintBusy] = useState(false);
  const [printPdf, setPrintPdf] = useState<string | null>(null);
  const [printMsg, setPrintMsg] = useState<string | null>(null);

  const currentUser = getStoredUser();
  // Назначать мастера на ремонт могут только admin и operator.
  const canAssign =
    hasRole(currentUser, "admin") || hasRole(currentUser, "operator");

  useEffect(() => {
    Promise.all([
      api.cities(),
      api.masters(),
      api.complectationItems(),
    ]).then(([c, m, it]) => {
      setCities(c);
      setMasters(m);
      setItems(it);
      if (c[0]) setCityId(c[0].id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Поиск существующего клиента по телефону
  useEffect(() => {
    const phone = clientPhone.trim();
    if (phone.length < 5) {
      setExistingClient(null);
      return;
    }
    setLookingUp(true);
    const t = setTimeout(() => {
      api.lookupClient(phone)
        .then((r) => setExistingClient(r))
        .catch(() => setExistingClient(null))
        .finally(() => setLookingUp(false));
    }, 400);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientPhone]);

  useEffect(() => {
    if (!deviceType) return;
    const params: Record<string, string> = { type: deviceType };
    if (brand) params.brand = brand;
    const t = setTimeout(() => {
      api
        .priceHint(params)
        .then((r) => setPriceHint(r.hint))
        .catch(() => setPriceHint(null));
    }, 300);
    return () => clearTimeout(t);
  }, [deviceType, brand]);

  // Поиск по контактам, уже сохранённым в системе (не из контактов телефона).
  useEffect(() => {
    if (!pickerOpen) return;
    setPickerLoading(true);
    const t = setTimeout(() => {
      api
        .listClients(pickerQuery.trim() || undefined)
        .then(setPickerResults)
        .catch(() => setPickerResults([]))
        .finally(() => setPickerLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [pickerOpen, pickerQuery]);

  function pickContact(c: ClientRow) {
    setClientName(c.full_name);
    setClientPhone(c.phone);
    setPhoneError(null);
    setPickerOpen(false);
    setPickerQuery("");
  }

  function toggleComplect(item: string) {
    setComplect((prev) =>
      prev.includes(item) ? prev.filter((x) => x !== item) : [...prev, item],
    );
  }

  function toggleCondition(item: string) {
    setConditions((prev) =>
      prev.includes(item) ? prev.filter((x) => x !== item) : [...prev, item],
    );
  }

  function buildConditionNotes(): string {
    const parts = [...conditions];
    if (conditionOther.trim()) parts.push(conditionOther.trim());
    return parts.join(", ");
  }

  function validatePhoneField(phone: string, setter: (m: string | null) => void): boolean {
    const result = checkPhone(phone);
    if (!result.valid) {
      setter(result.message || "Некорректный номер телефона");
      alert(result.message || "Некорректный номер телефона. Исправьте номер телефона.");
      return false;
    }
    setter(null);
    return true;
  }

  const canProceedStep0 = clientName.trim() && clientPhone.trim() && consentRepair;
  const canProceedStep1 = deviceType && brand;

  async function submit() {
    if (!validatePhoneField(clientPhone, setPhoneError)) return;
    if (contact2Phone.trim() && !validatePhoneField(contact2Phone, setContact2Error)) return;

    setLoading(true);
    setError(null);
    setPrintMsg(null);
    setPrintPdf(null);
    setPrintAttempts(0);
    setPrintAsking(false);
    setLabelState("idle");
    setLabelMessage(null);
    setLabelPdf(null);
    setRedirectIn(null);
    labelAutoRef.current = false;
    try {
      const repair = await api.createRepair({
        city_id: cityId,
        client: {
          full_name: clientName,
          phone: clientPhone,
          consent_pdn: consent,
          consent_storage: consent,
        },
        contact2_name: contact2Name || null,
        contact2_phone: contact2Phone || null,
        device_type: deviceType,
        brand: brand || null,
        model: model || null,
        serial: serial || null,
        complectation: { items: complect },
        condition_notes: buildConditionNotes() || null,
        fault_client: fault || null,
        master_id: masterId || null,
        eta_days: etaDays ? parseInt(etaDays, 10) : null,
        eta_source: etaDays ? "manual" : null,
        consent_repair: consentRepair,
        is_delivery: isDelivery,
      });

      if (photos.length) {
        for (const f of photos) {
          await api.uploadPhoto(repair.id, f).catch(() => {});
        }
      }
      setDone(repair);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setLoading(false);
    }
  }

  async function printLabel(repairId: string) {
    setLabelState("printing");
    setLabelMessage(null);
    setLabelPdf(null);
    try {
      const result = await api.printLabel(repairId);
      setLabelPdf(result.pdf_base64);
      setLabelState("ok");
    } catch (e) {
      // Ремонт уже сохранён — печать этикетки не должна его откатывать.
      // Но и уходить с доски молча нельзя: оператор должен увидеть проблему.
      setLabelMessage(e instanceof Error ? e.message : "Ошибка печати этикетки");
      setLabelState("error");
      setRedirectIn(null);
    }
  }

  // Сохранили ремонт → этикетка уходит на принтер АВТОМАТИЧЕСКИ (один раз).
  useEffect(() => {
    if (!done || labelAutoRef.current) return;
    labelAutoRef.current = true;
    printLabel(done.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);

  // Этикетка напечатана → включаем обратный отсчёт перехода на «Все ремонты».
  useEffect(() => {
    if (done && labelState === "ok") setRedirectIn(REDIRECT_SECONDS);
  }, [done, labelState]);

  // Сам отсчёт: раз в секунду минус один, на нуле — переход.
  useEffect(() => {
    if (redirectIn === null) return;
    if (redirectIn <= 0) {
      router.push("/repairs");
      return;
    }
    const t = setTimeout(() => setRedirectIn((n) => (n === null ? null : n - 1)), 1000);
    return () => clearTimeout(t);
  }, [redirectIn, router]);

  // 4) Печать бланка A4: после печати спрашиваем «успешно ли напечатано?».
  // Если нет — предлагаем напечатать заново; если и вторая попытка не удалась —
  // третий вариант «зарегистрирован без печати» + сообщение об ошибке админу.
  async function printBlank() {
    if (!done) return;
    setRedirectIn(null);
    setPrintBusy(true);
    setPrintMsg(null);
    try {
      const res = await api.print(done.id);
      setPrintPdf(res.pdf_base64);
      setPrintAttempts((n) => n + 1);
      setPrintAsking(true);
    } catch (e) {
      setPrintMsg(e instanceof Error ? e.message : "Ошибка печати");
      setPrintAttempts((n) => n + 1);
      setPrintAsking(true);
    } finally {
      setPrintBusy(false);
    }
  }

  function confirmPrintSuccess() {
    setPrintAsking(false);
    setPrintMsg("✅ Бланк напечатан успешно.");
  }

  async function confirmPrintFailed() {
    setPrintAsking(false);
    if (printAttempts >= 2) {
      // Третья функция: «зарегистрирован без печати» + сообщение об ошибке разработчику/админу.
      if (!done) return;
      try {
        await api.reportPrintFailure(done.id, "Печать не удалась дважды подряд");
        setPrintMsg(
          "⚠ Зарегистрировано без печати. Об ошибке уведомлён администратор/разработчик.",
        );
      } catch (e) {
        setPrintMsg(
          e instanceof Error ? e.message : "Не удалось отправить сообщение об ошибке",
        );
      }
    } else {
      // Предлагаем напечатать заново.
      await printBlank();
    }
  }

  /** Сброс формы — «➕ Новая приёмка» в окне успеха. */
  function resetIntake() {
    labelAutoRef.current = false;
    setDone(null);
    setClientName("");
    setClientPhone("");
    setPhoneError(null);
    setExistingClient(null);
    setContact2Name("");
    setContact2Phone("");
    setContact2Error(null);
    setContact2Open(false);
    setIsDelivery(false);
    setDeviceCombined("");
    setComplect([]);
    setConditions([]);
    setConditionOther("");
    setFault("");
    setPhotos([]);
    setMasterId("");
    setEtaDays("");
    setLabelState("idle");
    setLabelMessage(null);
    setLabelPdf(null);
    setRedirectIn(null);
    setPrintMsg(null);
    setPrintPdf(null);
    setPrintAttempts(0);
    setPrintAsking(false);
    setStep(0);
  }

  // Приёмка завершена: вместо отдельного экрана — модальное окно.
  // Этикетка к этому моменту уже отправлена на принтер автоматически,
  // а через REDIRECT_SECONDS окно само уводит оператора на «Все ремонты».
  if (done) {
    return (
      <IntakeDoneDialog
        repair={done}
        labelState={labelState}
        labelMessage={labelMessage}
        labelPdf={labelPdf}
        onRetryLabel={() => printLabel(done.id)}
        blank={{
          busy: printBusy,
          asking: printAsking,
          attempts: printAttempts,
          message: printMsg,
          pdf: printPdf,
        }}
        onPrintBlank={printBlank}
        onBlankSuccess={confirmPrintSuccess}
        onBlankFailed={confirmPrintFailed}
        redirectIn={redirectIn}
        onGoList={() => router.push("/repairs")}
        onOpenCard={() => router.push(`/repairs/${done.id}`)}
        onNewIntake={resetIntake}
      />
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      {/* Progress Steps */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">Новая приёмка</h1>
        <div className="mt-4 flex max-w-full items-center gap-1 overflow-x-auto pb-1 custom-scroll">
          {SECTION_STEPS.map((s, i) => (
            <div key={s.id} className="flex items-center gap-2">
              <button
                onClick={() => i <= step && setStep(i)}
                className={`flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition-all ${
                  i === step
                    ? "bg-msb-600 text-white shadow-sm"
                    : i < step
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-slate-100 text-slate-400"
                }`}
              >
                <span>{i < step ? "✓" : s.icon}</span>
                <span className="hidden sm:inline">{s.label}</span>
              </button>
              {i < SECTION_STEPS.length - 1 && (
                <div className={`h-px w-6 ${i < step ? "bg-emerald-400" : "bg-slate-200"}`} />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="msb-card-solid divide-y divide-slate-100 overflow-hidden">
        {/* Step 0 — Client */}
        {step === 0 && (
          <div className="p-6 animate-fade-in">
            <h2 className="msb-section-title flex items-center gap-2">
              <span>👤</span> Данные клиента
            </h2>
            <div className="mt-4 space-y-4">
              <div className="flex items-center justify-between">
                <label className="msb-label mb-0">Телефон *</label>
                <button type="button" onClick={() => setPickerOpen(true)}
                  className="mb-1.5 text-xs font-semibold text-msb-600 hover:text-msb-700">
                  👥 Выбрать из контактов
                </button>
              </div>
              <div className="relative -mt-3">
                <input className="msb-input pr-10" value={clientPhone}
                  onChange={(e) => { setClientPhone(e.target.value); setPhoneError(null); }}
                  onBlur={() => clientPhone.trim() && validatePhoneField(clientPhone, setPhoneError)}
                  inputMode="tel" placeholder="+993 61 000000" />
                {lookingUp && (
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin rounded-full border-2 border-msb-500 border-t-transparent" />
                )}
              </div>
              {phoneError ? (
                <p className="mt-1 text-xs font-medium text-red-600">⚠ {phoneError}</p>
              ) : (
                <p className="mt-1 text-xs text-slate-400">
                  Введите телефон — если клиент уже обращался, мы покажем его историю
                </p>
              )}

              {/* Подсказка по существующему клиенту */}
              {existingClient?.found && !existingClient.multiple && existingClient.client && (
                <div className="rounded-xl bg-emerald-50 px-4 py-3 ring-1 ring-emerald-200">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-emerald-700">
                        Похожий контакт найден
                      </p>
                      <p className="text-sm font-medium text-emerald-900">
                        {existingClient.client.full_name} · {existingClient.client.phone}
                      </p>
                    </div>
                    <span className="msb-badge-success">
                      {existingClient.repairs_count || 0} ремонт(ов)
                    </span>
                  </div>
                  <button type="button"
                    onClick={() => setClientName(existingClient.client!.full_name)}
                    className="mt-2.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 transition-colors">
                    ✓ Заполнить имя из контакта
                  </button>
                  {existingClient.repairs && existingClient.repairs.length > 0 && (
                    <div className="mt-3 space-y-1.5 max-h-40 overflow-y-auto custom-scroll">
                      {existingClient.repairs.slice(0, 5).map((r) => (
                        <Link key={r.id} href={`/repairs/${r.id}`}
                          className="flex items-center justify-between rounded-lg bg-white/60 px-3 py-2 text-xs hover:bg-white transition-colors">
                          <span className="font-mono font-semibold text-slate-700">
                            {r.number}
                          </span>
                          <span className="text-slate-600 truncate flex-1 mx-2">
                            {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
                          </span>
                          <span className="text-slate-400">
                            {r.accepted_at ? new Date(r.accepted_at).toLocaleDateString("ru") : ""}
                          </span>
                        </Link>
                      ))}
                      {existingClient.repairs.length > 5 && (
                        <p className="text-xs text-emerald-700 text-center pt-1">
                          и ещё {existingClient.repairs.length - 5}...
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {existingClient?.found && existingClient.multiple && (
                <div className="rounded-xl bg-amber-50 px-4 py-3 ring-1 ring-amber-200">
                  <p className="text-xs font-semibold text-amber-700">
                    Найдено несколько клиентов с похожим номером
                  </p>
                  <div className="mt-2 space-y-1.5">
                    {existingClient.candidates?.map((c) => (
                      <button key={c.id} type="button"
                        onClick={() => setClientName(c.full_name)}
                        className="flex items-center justify-between w-full rounded-lg bg-white/60 px-3 py-2 text-xs hover:bg-white transition-colors text-left">
                        <span className="font-medium text-slate-800">{c.full_name}</span>
                        <span className="text-slate-400 font-mono">{c.phone}</span>
                        <span className="msb-badge-warning">{c.repairs_count} ремонт.</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <label className="msb-label">ФИО клиента *</label>
                <input className="msb-input" value={clientName}
                  onChange={(e) => setClientName(e.target.value)}
                  placeholder="Иванов Иван Иванович" />
              </div>

              {/* 6) Второй контакт: напр. владелец техники и тот, кто её доставил — разные люди. */}
              {!contact2Open ? (
                <button type="button" onClick={() => setContact2Open(true)}
                  className="text-sm font-medium text-msb-600 hover:text-msb-700">
                  ＋ Добавить второй номер телефона (например, доставщика)
                </button>
              ) : (
                <div className="rounded-xl border border-slate-200 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Второй контакт
                    </p>
                    <button type="button"
                      onClick={() => {
                        setContact2Open(false);
                        setContact2Name("");
                        setContact2Phone("");
                        setContact2Error(null);
                      }}
                      className="text-xs text-slate-400 hover:text-red-500">
                      Убрать
                    </button>
                  </div>
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
                      onBlur={() => contact2Phone.trim() && validatePhoneField(contact2Phone, setContact2Error)}
                      inputMode="tel" placeholder="+993 61 000000" />
                    {contact2Error && (
                      <p className="mt-1 text-xs font-medium text-red-600">⚠ {contact2Error}</p>
                    )}
                  </div>
                </div>
              )}

              {/* Заказ с доставкой: техника не принесена лично, а доставлена
                  курьером / забрана с адреса клиента. */}
              <label className="flex items-center gap-3 rounded-xl bg-amber-50/60 p-4 text-sm text-slate-700 ring-1 ring-amber-100">
                <input type="checkbox" checked={isDelivery}
                  onChange={(e) => setIsDelivery(e.target.checked)}
                  className="h-5 w-5 rounded border-slate-300 text-amber-600 focus:ring-amber-500" />
                <span className="flex items-center gap-1.5">
                  <span>🚚</span>
                  <b>Заказ с доставкой</b>
                  <span className="text-slate-400">(доставлен курьером / забран с адреса)</span>
                </span>
              </label>

              <div className="rounded-xl bg-blue-50/50 p-4 ring-1 ring-blue-100 space-y-3">
                <label className="flex items-start gap-3 text-sm text-slate-700">
                  <input type="checkbox" checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                    className="mt-0.5 h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500" />
                  <span>Согласен с обработкой ПДн и хранением техники 3 месяца</span>
                </label>
                <label className="flex items-start gap-3 text-sm text-slate-700">
                  <input type="checkbox" checked={consentRepair}
                    onChange={(e) => setConsentRepair(e.target.checked)}
                    className="mt-0.5 h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500" />
                  <span><b>Согласие на диагностику и ремонт</b> (разборка, замена компонентов)</span>
                </label>
              </div>
            </div>
            <div className="mt-6 flex justify-end">
              <button onClick={() => setStep(1)}
                disabled={!canProceedStep0}
                className="msb-btn-primary">
                Далее → Техника
              </button>
            </div>
          </div>
        )}

        {/* Step 1 — Device */}
        {step === 1 && (
          <div className="p-6 animate-fade-in">
            <h2 className="msb-section-title flex items-center gap-2">
              <span>📺</span> Техника и комплектация
            </h2>

            <div className="mt-4">
              <label className="msb-label">Класс техники</label>
              <div className="flex flex-wrap gap-2">
                {DEVICE_TYPES.map((t) => (
                  <button key={t} onClick={() => setDeviceType(t)}
                    className={`flex items-center gap-1.5 rounded-xl px-5 py-2.5 text-sm font-medium transition-all ${
                      deviceType === t
                        ? "bg-msb-600 text-white shadow-sm"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
                    <span>{DEVICE_ICONS[t]}</span> {t}
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-4">
              <label className="msb-label">Бренд (быстрый выбор)</label>
              <div className="flex flex-wrap gap-2">
                {BRAND_CHIPS.map((b) => (
                  <button key={b}
                    onClick={() => setDeviceCombined(joinDeviceCombined(b, model, serial))}
                    className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all ${
                      brand === b
                        ? "bg-msb-600 text-white shadow-sm"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
                    {b}
                  </button>
                ))}
              </div>
            </div>

            {/* 3) Марка + модель + серийный номер — одно поле, сегменты через
                две точки подряд «..» (не через пробелы — их «съедает» автокоррекция
                на телефонах). Разделитель подсвечивается зелёным, текст — заглавными. */}
            <div className="mt-4">
              <label className="msb-label">
                Марка..Модель..Серийный номер
                <span className="ml-1 font-normal normal-case text-slate-400">
                  (разделяйте двумя точками «..» — автоматически ЗАГЛАВНЫМИ)
                </span>
              </label>
              <DeviceCombinedField
                value={deviceCombined}
                onChange={setDeviceCombined}
                placeholder="SAMSUNG..UE55..SN1234567"
              />
              <div className="mt-1.5 flex flex-wrap gap-3 text-xs text-slate-500">
                <span>Марка: <b className="text-slate-700">{brand || "—"}</b></span>
                <span>Модель: <b className="text-slate-700">{model || "—"}</b></span>
                <span>С/н: <b className="text-slate-700">{serial || "—"}</b></span>
              </div>
            </div>

            {priceHint && (
              <div className="mt-4 flex items-center gap-3 rounded-xl bg-blue-50 px-4 py-3 text-sm text-blue-800 ring-1 ring-blue-100">
                <span>💰</span>
                <div>
                  <span className="font-medium">Ориентир цены:</span>{" "}
                  {money(priceHint.price_min)} – {money(priceHint.price_max)}
                  {priceHint.typical_days_min != null && (
                    <> · срок {priceHint.typical_days_min}
                      {priceHint.typical_days_min !== priceHint.typical_days_max
                        ? `–${priceHint.typical_days_max}` : ""} дн</>
                  )}
                </div>
              </div>
            )}

            <div className="mt-4">
              <label className="msb-label">Комплектация</label>
              <div className="grid gap-2 sm:grid-cols-2">
                {(items.length ? items.map((i) => i.name) : []).map((item) => (
                  <label key={item}
                    className={`flex items-center gap-3 rounded-xl border-2 px-4 py-3 text-sm font-medium transition-all cursor-pointer ${
                      complect.includes(item)
                        ? "border-msb-500 bg-msb-50 text-msb-700"
                        : "border-slate-200 text-slate-600 hover:border-slate-300"}`}>
                    <input type="checkbox" checked={complect.includes(item)}
                      onChange={() => toggleComplect(item)}
                      className="h-5 w-5 rounded border-slate-300 text-msb-600 focus:ring-msb-500" />
                    {item}
                  </label>
                ))}
              </div>
            </div>

            <div className="mt-4">
              <label className="msb-label">Внешний вид / дефекты</label>
              <div className="grid gap-2 sm:grid-cols-2">
                {CONDITION_ITEMS.map((item) => (
                  <label key={item}
                    className={`flex items-center gap-3 rounded-xl border-2 px-4 py-3 text-sm font-medium transition-all cursor-pointer ${
                      conditions.includes(item)
                        ? "border-amber-500 bg-amber-50 text-amber-700"
                        : "border-slate-200 text-slate-600 hover:border-slate-300"}`}>
                    <input type="checkbox" checked={conditions.includes(item)}
                      onChange={() => toggleCondition(item)}
                      className="h-5 w-5 rounded border-slate-300 text-amber-500 focus:ring-amber-500" />
                    {item}
                  </label>
                ))}
              </div>
              <input className="msb-input mt-2" placeholder="Другое…" value={conditionOther}
                onChange={(e) => setConditionOther(e.target.value)} />
            </div>

            <div className="mt-6 flex items-center justify-between">
              <button onClick={() => setStep(0)}
                className="msb-btn-ghost">← Назад</button>
              <button onClick={() => setStep(2)} disabled={!canProceedStep1}
                className="msb-btn-primary">
                Далее → Сервис
              </button>
            </div>
          </div>
        )}

        {/* Step 2 — Service */}
        {step === 2 && (
          <div className="p-6 animate-fade-in">
            <h2 className="msb-section-title flex items-center gap-2">
              <span>🔧</span> Неисправность, мастер и фото
            </h2>

            <div className="mt-4">
              <label className="msb-label">Неисправность со слов клиента</label>
              <textarea className="msb-input min-h-[100px] resize-y"
                value={fault} onChange={(e) => setFault(e.target.value)}
                placeholder="Опишите неисправность: не включается, не видит Wi-Fi, разбит экран…" />
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="msb-label">Мастер</label>
                {!canAssign ? (
                  <div
                    title="Назначает администратор или оператор"
                    className="flex items-center gap-2 rounded-xl bg-slate-50 px-4 py-2.5 text-sm font-medium text-slate-500 ring-1 ring-slate-100"
                  >
                    <span>🔒</span> Назначает администратор или оператор
                  </div>
                ) : (
                  <select className="msb-input" value={masterId}
                    onChange={(e) => setMasterId(e.target.value)}>
                    <option value="">В очередь (любой мастер)</option>
                    {masters.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                )}
              </div>
              <div>
                <label className="msb-label">ETA (плановый срок, дней)</label>
                <input className="msb-input" value={etaDays}
                  onChange={(e) => setEtaDays(e.target.value)}
                  inputMode="numeric" placeholder="Авто" />
              </div>
            </div>

            <div className="mt-4">
              <label className="msb-label">Фото техники</label>
              <div className="flex flex-wrap items-center gap-3">
                <button onClick={() => fileRef.current?.click()}
                  className="flex items-center gap-2 rounded-xl border-2 border-dashed border-slate-300 px-5 py-3 text-sm text-slate-500 transition-all hover:border-msb-400 hover:text-msb-600">
                  <span className="text-lg">📷</span>
                  <span>{photos.length > 0 ? `Выбрано: ${photos.length}` : "Добавить фото"}</span>
                </button>
                {photos.length > 0 && (
                  <div className="flex -space-x-2">
                    {photos.slice(0, 5).map((f, i) => (
                      <div key={i} className="flex h-10 w-10 items-center justify-center rounded-full bg-msb-100 text-xs font-bold text-msb-700 ring-2 ring-white">
                        {i + 1}
                      </div>
                    ))}
                    {photos.length > 5 && (
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-500 ring-2 ring-white">
                        +{photos.length - 5}
                      </div>
                    )}
                  </div>
                )}
                <input ref={fileRef} type="file" accept="image/*"
                  capture="environment" multiple
                  onChange={(e) =>
                    setPhotos((prev) => [...prev, ...Array.from(e.target.files || [])])}
                  className="hidden" />
              </div>
            </div>

            {error && (
              <div className="mt-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
                <span>⚠</span> {error}
              </div>
            )}

            <div className="mt-6 flex items-center justify-between">
              <button onClick={() => setStep(1)}
                className="msb-btn-ghost">← Назад</button>
              <button onClick={submit} disabled={loading}
                className="msb-btn-primary px-8 py-3">
                {loading ? (
                  <span className="flex items-center gap-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    Принимаем…
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <span>✓</span> Принять технику
                  </span>
                )}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 1) Выбор контакта из уже существующих в системе (не из контактов телефона) */}
      {pickerOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setPickerOpen(false)} />
          <div className="relative w-full max-w-md msb-card-solid p-6 animate-slide-up">
            <div className="flex items-center justify-between gap-3">
              <h3 className="msb-section-title">👥 Контакты в системе</h3>
              <button onClick={() => setPickerOpen(false)} className="text-slate-400 hover:text-slate-600">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <input className="msb-input mt-4" value={pickerQuery}
              onChange={(e) => setPickerQuery(e.target.value)}
              placeholder="Поиск по имени или телефону…" autoFocus />
            <div className="mt-3 max-h-72 space-y-1.5 overflow-y-auto custom-scroll">
              {pickerLoading && (
                <p className="py-6 text-center text-sm text-slate-400">Загрузка…</p>
              )}
              {!pickerLoading && pickerResults.length === 0 && (
                <p className="py-6 text-center text-sm text-slate-400">Контакты не найдены</p>
              )}
              {pickerResults.map((c) => (
                <button key={c.id} type="button" onClick={() => pickContact(c)}
                  className="flex w-full items-center justify-between rounded-lg bg-slate-50 px-3 py-2.5 text-left text-sm hover:bg-msb-50 transition-colors">
                  <span className="font-medium text-slate-800">{c.full_name}</span>
                  <span className="font-mono text-xs text-slate-500">{c.phone}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
