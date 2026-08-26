"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  api,
  mediaUrl,
  type Photo,
  type Repair,
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
  Принято: "bg-blue-100 text-blue-700",
  Диагностика: "bg-amber-100 text-amber-700",
  Согласование: "bg-purple-100 text-purple-700",
  "Ожидание запчастей": "bg-orange-100 text-orange-700",
  "В ремонте": "bg-cyan-100 text-cyan-700",
  "Готово к выдаче": "bg-green-100 text-green-700",
  Выдано: "bg-gray-100 text-gray-600",
  Отказ: "bg-red-100 text-red-700",
};

const EVENT_LABELS: Record<string, string> = {
  status_change: "смена статуса",
  comment: "комментарий",
  print: "печать",
  call: "звонок",
  price: "цена",
  photo: "фото",
  assign: "назначение",
  notify: "уведомление",
};

function fmt(dt: string | null | undefined) {
  return dt ? new Date(dt).toLocaleString("ru") : "—";
}

export default function RepairCardPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [repair, setRepair] = useState<Repair | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [printMsg, setPrintMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    api.repair(id).then(setRepair).catch((e) => setError(e.message));
    api.photos(id).then(setPhotos).catch(() => {});
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
    try {
      await api.print(id);
      setPrintMsg("Задание на печать отправлено на принтер");
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

  if (!repair) {
    return (
      <div className="py-16 text-center text-gray-400">
        {error ? error : "Загрузка…"}
      </div>
    );
  }

  const complect = (repair.complectation as { items?: string[] } | null)?.items;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <Link href="/repairs" className="text-sm text-gray-500 hover:underline">
          ← Все ремонты
        </Link>
        <button
          onClick={doPrint}
          disabled={busy}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 disabled:opacity-40"
        >
          🖨 Повторить печать
        </button>
      </div>

      {/* Header */}
      <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
        <div className="flex items-start justify-between">
          <div>
            <div className="font-mono text-xl font-bold text-slate-900">
              {repair.number}
            </div>
            <div className="mt-1 text-sm text-gray-500">
              {[repair.device_type, repair.brand, repair.model]
                .filter(Boolean)
                .join(" · ")}
            </div>
          </div>
          <select
            value={repair.status}
            onChange={(e) => changeStatus(e.target.value)}
            disabled={busy}
            className={`rounded-full px-3 py-1.5 text-sm font-medium outline-none ${
              STATUS_COLORS[repair.status] ?? "bg-gray-100 text-gray-600"
            }`}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <Field label="Клиент" value={repair.client_name} />
          <Field label="Телефон" value={repair.client_phone} />
          <Field label="Серийник" value={repair.serial} />
          <Field label="Принято" value={fmt(repair.accepted_at)} />
          <Field label="ETA (дней)" value={repair.eta_days?.toString()} />
          <Field label="Хранение до" value={fmt(repair.storage_until)} />
        </div>

        {complect && complect.length > 0 && (
          <div className="mt-3 text-sm text-gray-600">
            <span className="text-gray-400">Комплект: </span>
            {complect.join(", ")}
          </div>
        )}
        {repair.fault_client && (
          <div className="mt-2 text-sm text-gray-600">
            <span className="text-gray-400">Неисправность: </span>
            {repair.fault_client}
          </div>
        )}
      </div>

      {/* Photos */}
      <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Фото</h2>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            📷 Добавить
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            multiple
            onChange={onFiles}
            className="hidden"
          />
        </div>
        {photos.length === 0 ? (
          <p className="text-sm text-gray-400">Фото пока нет</p>
        ) : (
          <div className="grid grid-cols-3 gap-2">
            {photos.map((p) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={p.id}
                src={mediaUrl(p.url)}
                alt={p.caption || "фото"}
                className="aspect-square w-full rounded-lg object-cover"
              />
            ))}
          </div>
        )}
      </div>

      {/* Timeline */}
      <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200">
        <h2 className="mb-3 font-semibold">История</h2>
        <ol className="space-y-2 border-l border-gray-200 pl-4">
          {repair.events.map((e) => (
            <li key={e.id} className="relative text-sm">
              <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-slate-300" />
              <span className="text-gray-500">{fmt(e.created_at)}</span>
              <span className="mx-1 text-gray-400">
                · {EVENT_LABELS[e.type] ?? e.type}
              </span>
              {e.type === "status_change" && e.data && (
                <span className="text-gray-700">
                  {String((e.data as Record<string, unknown>).from ?? "—")} →{" "}
                  {String((e.data as Record<string, unknown>).to ?? "")}
                </span>
              )}
              {e.type === "comment" && e.data && (
                <span className="block text-gray-700">
                  {String((e.data as Record<string, unknown>).message ?? "")}
                </span>
              )}
            </li>
          ))}
        </ol>

        <div className="mt-4 flex gap-2">
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addComment()}
            placeholder="Комментарий…"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
          />
          <button
            onClick={addComment}
            disabled={busy || !comment.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
          >
            Отправить
          </button>
        </div>
      </div>

      {printMsg && (
        <p className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">
          {printMsg}
        </p>
      )}
      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-xs text-gray-400">{label}</div>
      <div className="text-gray-800">{value || "—"}</div>
    </div>
  );
}
