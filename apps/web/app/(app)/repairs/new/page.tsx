"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, getStoredUser, money, type Lookup, type PriceHint, type Repair } from "@/lib/api";

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

export default function NewRepairPage() {
  const router = useRouter();
  const [cities, setCities] = useState<Lookup[]>([]);
  const [masters, setMasters] = useState<Lookup[]>([]);
  const [items, setItems] = useState<Lookup[]>([]);

  const [cityId, setCityId] = useState("");
  const [clientName, setClientName] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [existingClient, setExistingClient] = useState<ClientLookup | null>(null);
  const [lookingUp, setLookingUp] = useState(false);
  const [deviceType, setDeviceType] = useState("Телевизоры");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [serial, setSerial] = useState("");
  const [complect, setComplect] = useState<string[]>([]);
  const [conditions, setConditions] = useState<string[]>([]);
  const [conditionOther, setConditionOther] = useState("");
  const [fault, setFault] = useState("");
  const [masterId, setMasterId] = useState("");
  const [etaDays, setEtaDays] = useState("");
  const [consent, setConsent] = useState(true);
  const [consentRepair, setConsentRepair] = useState(true);
  const [photos, setPhotos] = useState<File[]>([]);
  const [step, setStep] = useState(0);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Repair | null>(null);
  const [priceHint, setPriceHint] = useState<PriceHint | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const currentUser = getStoredUser();

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
      if (currentUser?.role === "master" && currentUser.id) {
        setMasterId(currentUser.id);
      }
    });
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
        .then((r) => {
          setExistingClient(r);
          // Если нашли ровно одного — подставим имя, если оно пустое
          if (r.found && !r.multiple && r.client && !clientName.trim()) {
            setClientName(r.client.full_name);
          }
        })
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

  const canProceedStep0 = clientName.trim() && clientPhone.trim() && consentRepair;
  const canProceedStep1 = deviceType && brand;

  async function submit() {
    setLoading(true);
    setError(null);
    try {
      const repair = await api.createRepair({
        city_id: cityId,
        client: {
          full_name: clientName,
          phone: clientPhone,
          consent_pdn: consent,
          consent_storage: consent,
        },
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

  if (done) {
    return (
      <div className="mx-auto max-w-md animate-slide-up">
        <div className="msb-card-solid p-8 text-center">
          <div className="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-100 to-emerald-50 shadow-sm ring-1 ring-emerald-200">
            <span className="text-4xl">✅</span>
          </div>
          <p className="text-sm font-medium text-emerald-600">Техника принята</p>
          <p className="mt-2 font-mono text-3xl font-extrabold text-slate-900 tracking-tight">
            {done.number}
          </p>
          <p className="mt-2 text-sm text-slate-500">
            Хранение до {done.storage_until
              ? new Date(done.storage_until).toLocaleDateString("ru")
              : "—"}
          </p>

          <div className="mt-8 space-y-3">
            <button
              onClick={async () => {
                try {
                  await api.print(done.id);
                  alert("✅ Бланк отправлен на печать");
                } catch { alert("Ошибка печати"); }
              }}
              className="msb-btn-primary w-full"
            >
              🖨️ Печатать бланк
            </button>
            <button
              onClick={() => router.push(`/repairs/${done.id}`)}
              className="msb-btn-secondary w-full"
            >
              Открыть карточку ремонта
            </button>
            <button
              onClick={() => {
                setDone(null);
                setClientName("");
                setClientPhone("");
                setExistingClient(null);
                setComplect([]);
                setConditions([]);
                setConditionOther("");
                setFault("");
                setPhotos([]);
                setMasterId("");
                setEtaDays("");
                setStep(0);
              }}
              className="msb-btn-ghost w-full text-slate-600"
            >
              ➕ Новая приёмка
            </button>
          </div>
        </div>
      </div>
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
              <div>
                <label className="msb-label">Телефон *</label>
                <div className="relative">
                  <input className="msb-input pr-10" value={clientPhone}
                    onChange={(e) => setClientPhone(e.target.value)}
                    inputMode="tel" placeholder="+993 61 000000" />
                  {lookingUp && (
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin rounded-full border-2 border-msb-500 border-t-transparent" />
                  )}
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  Введите телефон — если клиент уже обращался, мы покажем его историю
                </p>
              </div>

              {/* Подсказка по существующему клиенту */}
              {existingClient?.found && !existingClient.multiple && existingClient.client && (
                <div className="rounded-xl bg-emerald-50 px-4 py-3 ring-1 ring-emerald-200">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-emerald-700">
                        ✅ Клиент найден
                      </p>
                      <p className="text-sm font-medium text-emerald-900">
                        {existingClient.client.full_name}
                      </p>
                    </div>
                    <span className="msb-badge-success">
                      {existingClient.repairs_count || 0} ремонт(ов)
                    </span>
                  </div>
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
              <label className="msb-label">Бренд</label>
              <div className="flex flex-wrap gap-2">
                {BRAND_CHIPS.map((b) => (
                  <button key={b} onClick={() => setBrand(b)}
                    className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all ${
                      brand === b
                        ? "bg-msb-600 text-white shadow-sm"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
                    {b}
                  </button>
                ))}
              </div>
              <input className="msb-input mt-2" placeholder="Или введите вручную…"
                value={brand} onChange={(e) => setBrand(e.target.value)} />
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="msb-label">Модель</label>
                <input className="msb-input" placeholder="UE55" value={model}
                  onChange={(e) => setModel(e.target.value)} />
              </div>
              <div>
                <label className="msb-label">Серийный номер</label>
                <input className="msb-input" placeholder="SN…" value={serial}
                  onChange={(e) => setSerial(e.target.value)} />
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
                {currentUser?.role === "master" ? (
                  <div className="flex items-center gap-2 rounded-xl bg-msb-50 px-4 py-2.5 text-sm font-medium text-msb-700 ring-1 ring-msb-100">
                    <span>✓</span> Вы (приёмку ведёте сами)
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
                    <span>✓</span> Принять и печатать
                  </span>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}