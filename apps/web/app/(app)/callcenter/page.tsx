"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Repair } from "@/lib/api";

const TABS = [
  { kind: "agree", label: "Согласовать цену" },
  { kind: "ready", label: "Сказать «готово»" },
  { kind: "overdue", label: "Просрочка хранения" },
];

export default function CallcenterPage() {
  const [kind, setKind] = useState("agree");
  const [items, setItems] = useState<Repair[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .callcenterQueue(kind)
      .then(setItems)
      .catch((e) => setError(e.message));
  }, [kind]);

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Call-центр</h1>

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.kind}
            onClick={() => setKind(t.kind)}
            className={`rounded-full px-4 py-2 text-sm font-medium ${
              kind === t.kind
                ? "bg-slate-900 text-white"
                : "bg-white text-gray-700 ring-1 ring-gray-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      {items.length === 0 && !error && (
        <p className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-gray-400">
          Очередь пуста — нечего согласовывать
        </p>
      )}

      <ul className="space-y-2">
        {items.map((r) => (
          <li
            key={r.id}
            className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-200"
          >
            <Link href={`/repairs/${r.id}`} className="block">
              <div className="flex items-center justify-between">
                <span className="font-mono font-semibold text-gray-900">
                  {r.number}
                </span>
                <span className="text-xs text-gray-500">{r.status}</span>
              </div>
              <div className="mt-1 text-sm text-gray-600">
                {[r.device_type, r.brand, r.model].filter(Boolean).join(" · ")}
              </div>
              <div className="mt-1 text-sm text-gray-700">
                {r.client_name} ·{" "}
                <a
                  href={`tel:${r.client_phone}`}
                  onClick={(e) => e.stopPropagation()}
                  className="text-blue-600"
                >
                  {r.client_phone}
                </a>
              </div>
              {kind === "overdue" && r.storage_until && (
                <div className="mt-1 text-xs text-red-500">
                  хранится до{" "}
                  {new Date(r.storage_until).toLocaleDateString("ru")}
                </div>
              )}
              {r.fault_client && (
                <div className="mt-1 text-xs text-gray-500">
                  «{r.fault_client}»
                </div>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
