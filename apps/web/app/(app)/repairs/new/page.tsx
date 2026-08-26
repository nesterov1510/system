"use client";

import { useEffect, useState } from "react";
import { api, type Repair } from "@/lib/api";

const DEVICE_TYPES = ["ТВ", "Монитор", "Аудио", "Другое"];
const BRAND_CHIPS = ["Samsung", "LG", "Xiaomi", "Sony", "Philips", "TCL"];
const COMPLECT_ITEMS = ["ПДУ", "Кабель питания", "Подставка", "Документы"];

export default function NewRepairPage() {
  const [cities, setCities] = useState<Array<{ id: string; name: string }>>([]);
  const [cityId, setCityId] = useState("");
  const [clientName, setClientName] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [deviceType, setDeviceType] = useState("ТВ");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [serial, setSerial] = useState("");
  const [complect, setComplect] = useState<string[]>([]);
  const [fault, setFault] = useState("");
  const [consent, setConsent] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Repair | null>(null);

  useEffect(() => {
    api.cities().then((c) => {
      setCities(c);
      if (c[0]) setCityId(c[0].id);
    });
  }, []);

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
      });
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
            onClick={() => {
              setDone(null);
              setClientName("");
              setClientPhone("");
              setComplect([]);
              setFault("");
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

          <p className={`${label} mt-3`}>Комплектация</p>
          <div className="grid grid-cols-2 gap-2">
            {COMPLECT_ITEMS.map((item) => (
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

        {/* Шаг 3 — Неисправность */}
        <section>
          <h2 className="mb-3 text-sm font-semibold text-gray-500">
            3 · Неисправность (со слов клиента)
          </h2>
          <textarea
            className={`${input} min-h-[80px]`}
            value={fault}
            onChange={(e) => setFault(e.target.value)}
            placeholder="например: не включается"
          />
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
