"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type Lookup, type PriceHint, type Repair } from "@/lib/api";

const DEVICE_TYPES = ["ТВ", "Монитор", "Аудио", "Другое"];
const BRAND_CHIPS = ["Samsung", "LG", "Xiaomi", "Sony", "Philips", "TCL"];

export default function NewRepairPage() {
  const router = useRouter();
  const [cities, setCities] = useState<Lookup[]>([]);
  const [masters, setMasters] = useState<Lookup[]>([]);
  const [items, setItems] = useState<Lookup[]>([]);

  const [cityId, setCityId] = useState("");
  const [clientName, setClientName] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [deviceType, setDeviceType] = useState("ТВ");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [serial, setSerial] = useState("");
  const [complect, setComplect] = useState<string[]>([]);
  const [fault, setFault] = useState("");
  const [masterId, setMasterId] = useState("");
  const [etaDays, setEtaDays] = useState("");
  const [consent, setConsent] = useState(true);
  const [photos, setPhotos] = useState<File[]>([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Repair | null>(null);
  const [priceHint, setPriceHint] = useState<PriceHint | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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
  }, []);

  // Прайс-подсказка по типу/бренду.
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
        fault_client: fault || null,
        master_id: masterId || null,
        eta_days: etaDays ? parseInt(etaDays, 10) : null,
        eta_source: etaDays ? "manual" : null,
      });

      // Upload captured photos (best-effort, не блокирует выдачу номера).
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
      <div className="rounded-2xl bg-white p-8 text-center shadow-sm ring-1 ring-gray-200">
        <div className="text-4xl">✅</div>
        <p className="mt-2 text-sm text-gray-500">Принято</p>
        <p className="mt-2 font-mono text-2xl font-bold text-slate-900">
          {done.number}
        </p>
        <p className="mt-1 text-sm text-gray-500">
          Хранение до{" "}
          {done.storage_until
            ? new Date(done.storage_until).toLocaleDateString("ru")
            : "—"}
        </p>
        <div className="mt-6 grid gap-3">
          <button
            onClick={async () => {
              await api.print(done.id);
              alert("Задание на печать отправлено на принтер");
            }}
            className="rounded-lg bg-slate-900 px-4 py-3 font-semibold text-white"
          >
            🖨 Печатать бланк
          </button>
          <button
            onClick={() => router.push(`/repairs/${done.id}`)}
            className="rounded-lg border border-slate-300 px-4 py-3 font-semibold text-slate-700"
          >
            Открыть карточку
          </button>
          <button
            onClick={() => {
              setDone(null);
              setClientName("");
              setClientPhone("");
              setComplect([]);
              setFault("");
              setPhotos([]);
              setMasterId("");
              setEtaDays("");
            }}
            className="rounded-lg border border-gray-300 px-4 py-3 font-semibold text-gray-700"
          >
            ➕ Новая приёмка
          </button>
        </div>
      </div>
    );
  }

  const input =
    "w-full rounded-lg border border-gray-300 px-3 py-2.5 text-base";
  const label = "mb-1 block text-sm font-medium text-gray-700";

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="mb-4 text-xl font-semibold">Новая приёмка</h1>

      <div className="space-y-5 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
        {/* Шаг 1 — Клиент */}
        <section>
          <h2 className="mb-3 text-sm font-semibold text-gray-500">
            1 · Клиент
          </h2>
          <label className={label}>ФИО *</label>
          <input
            className={input}
            value={clientName}
            onChange={(e) => setClientName(e.target.value)}
          />
          <label className={`${label} mt-3`}>Телефон *</label>
          <input
            className={input}
            value={clientPhone}
            onChange={(e) => setClientPhone(e.target.value)}
            inputMode="tel"
            placeholder="+7 900 000-00-00"
          />
          <label className="mt-3 flex items-start gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 h-5 w-5"
            />
            Согласен с обработкой ПДн и хранением техники 3 месяца
          </label>
        </section>

        {/* Шаг 2 — Техника / комплект */}
        <section>
          <h2 className="mb-3 text-sm font-semibold text-gray-500">
            2 · Техника и комплект
          </h2>
          <div className="flex flex-wrap gap-2">
            {DEVICE_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => setDeviceType(t)}
                className={`rounded-lg px-4 py-2 text-sm font-medium ${
                  deviceType === t
                    ? "bg-slate-900 text-white"
                    : "bg-gray-100 text-gray-700"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {BRAND_CHIPS.map((b) => (
              <button
                key={b}
                onClick={() => setBrand(b)}
                className={`rounded-full px-3 py-1.5 text-sm ${
                  brand === b
                    ? "bg-slate-900 text-white"
                    : "bg-gray-100 text-gray-600"
                }`}
              >
                {b}
              </button>
            ))}
          </div>
          <input
            className={`${input} mt-3`}
            placeholder="Бренд"
            value={brand}
            onChange={(e) => setBrand(e.target.value)}
          />
          <div className="mt-3 grid grid-cols-2 gap-3">
            <input
              className={input}
              placeholder="Модель"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
            <input
              className={input}
              placeholder="Серийник"
              value={serial}
              onChange={(e) => setSerial(e.target.value)}
            />
          </div>

          {priceHint && (
            <div className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-800 ring-1 ring-blue-100">
              💰 Ориентир: {priceHint.price_min?.toLocaleString("ru")} –{" "}
              {priceHint.price_max?.toLocaleString("ru")} ₽
              {priceHint.typical_days_min != null && (
                <> · срок {priceHint.typical_days_min}
                  {priceHint.typical_days_min !== priceHint.typical_days_max
                    ? `–${priceHint.typical_days_max}`
                    : ""}{" "}
                  дн</>
              )}
            </div>
          )}

          <p className={`${label} mt-3`}>Комплектация</p>
          <div className="grid grid-cols-2 gap-2">
            {(items.length ? items.map((i) => ({ name: i.name })) : [])
              .map((it) => it.name)
              .map((item) => (
                <label
                  key={item}
                  className={`flex items-center gap-2 rounded-lg border px-3 py-3 text-sm ${
                    complect.includes(item)
                      ? "border-slate-900 bg-slate-50"
                      : "border-gray-300"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={complect.includes(item)}
                    onChange={() => toggleComplect(item)}
                    className="h-5 w-5"
                  />
                  {item}
                </label>
              ))}
          </div>
        </section>

        {/* Шаг 3 — Неисправность / мастер / ETA / фото */}
        <section>
          <h2 className="mb-3 text-sm font-semibold text-gray-500">
            3 · Неисправность, мастер и фото
          </h2>
          <textarea
            className={`${input} min-h-[80px]`}
            value={fault}
            onChange={(e) => setFault(e.target.value)}
            placeholder="неисправность со слов клиента (например: не включается)"
          />

          <div className="mt-3 grid grid-cols-2 gap-3">
            <div>
              <label className={label}>Мастер</label>
              <select
                className={input}
                value={masterId}
                onChange={(e) => setMasterId(e.target.value)}
              >
                <option value="">в очередь</option>
                {masters.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={label}>ETA (дней)</label>
              <input
                className={input}
                value={etaDays}
                onChange={(e) => setEtaDays(e.target.value)}
                inputMode="numeric"
                placeholder="авто"
              />
            </div>
          </div>

          <div className="mt-3">
            <button
              onClick={() => fileRef.current?.click()}
              className="rounded-lg border border-dashed border-gray-300 px-4 py-3 text-sm text-gray-600"
            >
              📷 Фото с камеры ({photos.length})
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              capture="environment"
              multiple
              onChange={(e) =>
                setPhotos((prev) => [...prev, ...Array.from(e.target.files || [])])
              }
              className="hidden"
            />
          </div>
        </section>

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
            {error}
          </p>
        )}

        <button
          onClick={submit}
          disabled={loading || !clientName || !clientPhone || !cityId}
          className="w-full rounded-lg bg-slate-900 px-4 py-4 text-base font-bold text-white disabled:opacity-40"
        >
          {loading ? "Принимаем…" : "Принять и печатать"}
        </button>
      </div>
    </div>
  );
}
