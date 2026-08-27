"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface PrinterConfig {
  ip: string;
  port: number;
  mode: string;
  name: string;
}

interface Job {
  id: string;
  status: string;
  error?: string | null;
  created_at: string;
}

export default function PrinterPage() {
  const [printer, setPrinter] = useState<PrinterConfig>({
    ip: "",
    port: 631,
    mode: "agent",
    name: "Epson L3250",
  });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .getPrinter()
      .then((r) => {
        setPrinter(r.printer);
        setJobs(r.recent_jobs);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  async function save() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await api.savePrinter(printer);
      setMsg("Настройки принтера сохранены");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const r = await api.testPrint();
      setMsg(`Тестовое задание создано (#${String(r.job_id).slice(0, 8)}) — принтер должен начать печать`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm";
  const label = "mb-1 block text-xs font-medium text-gray-500";

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Принтер</h1>

      <div className="rounded-2xl bg-white p-5 ring-1 ring-gray-200">
        <h2 className="mb-3 font-semibold">Настройки печати</h2>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={label}>Название принтера</label>
            <input
              className={input}
              value={printer.name}
              onChange={(e) => setPrinter({ ...printer, name: e.target.value })}
            />
          </div>
          <div>
            <label className={label}>Режим печати</label>
            <select
              className={input}
              value={printer.mode}
              onChange={(e) => setPrinter({ ...printer, mode: e.target.value })}
            >
              <option value="agent">Через драйвер ОС (print-agent)</option>
              <option value="ipp">Напрямую по IP (AirPrint/IPP)</option>
            </select>
          </div>
          <div>
            <label className={label}>IP-адрес принтера</label>
            <input
              className={input}
              value={printer.ip}
              onChange={(e) => setPrinter({ ...printer, ip: e.target.value })}
              placeholder="192.168.1.50"
            />
          </div>
          <div>
            <label className={label}>Порт (для IPP)</label>
            <input
              className={input}
              type="number"
              value={printer.port}
              onChange={(e) =>
                setPrinter({ ...printer, port: Number(e.target.value) })
              }
            />
          </div>
        </div>

        <div className="mt-4 rounded-lg bg-gray-50 p-3 text-xs text-gray-600">
          <p className="font-medium text-gray-700">Как подключить Epson L3250:</p>
          <ol className="mt-1 list-decimal space-y-1 pl-4">
            <li>
              <b>Режим «Через драйвер ОС»</b> (надёжнее всего): установите принтер
              в Windows через драйвер Epson, запустите print-agent на этом же
              компьютере. IP в этом случае не обязателен.
            </li>
            <li>
              <b>Режим «Напрямую по IP»</b>: принтер должен быть в Wi-Fi и
              поддерживать AirPrint (L3250 поддерживает). Узнайте IP принтера
              (печать сетевой страницы / настройки Wi-Fi) и впишите его выше.
              Агент отправит PDF напрямую на порт 631.
            </li>
          </ol>
        </div>

        <div className="mt-4 flex gap-2">
          <button
            onClick={save}
            disabled={busy}
            className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
          >
            Сохранить
          </button>
          <button
            onClick={test}
            disabled={busy}
            className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 disabled:opacity-40"
          >
            🖨 Тестовая печать
          </button>
        </div>

        {msg && <p className="mt-3 text-sm text-green-600">{msg}</p>}
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>

      <div className="rounded-2xl bg-white p-5 ring-1 ring-gray-200">
        <h2 className="mb-3 font-semibold">Последние задания печати</h2>
        {jobs.length === 0 ? (
          <p className="text-sm text-gray-400">Заданий пока нет</p>
        ) : (
          <ul className="space-y-2">
            {jobs.map((j) => (
              <li
                key={j.id}
                className="flex items-center justify-between text-sm"
              >
                <span className="font-mono text-xs text-gray-500">
                  #{j.id.slice(0, 8)} ·{" "}
                  {new Date(j.created_at).toLocaleString("ru")}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    j.status === "done"
                      ? "bg-green-100 text-green-700"
                      : j.status === "failed"
                      ? "bg-red-100 text-red-700"
                      : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {j.status}
                  {j.error ? ` · ${j.error}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
