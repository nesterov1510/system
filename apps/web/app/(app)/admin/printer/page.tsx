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
    ip: "", port: 631, mode: "agent", name: "Epson L3250",
  });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.getPrinter().then((r) => {
      setPrinter(r.printer);
      setJobs(r.recent_jobs);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  async function save() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await api.savePrinter(printer);
      setMsg("✅ Настройки принтера сохранены");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally { setBusy(false); }
  }

  async function test() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const r = await api.testPrint();
      setMsg(`✅ Тестовое задание создано (#${String(r.job_id).slice(0, 8)}) — print-agent должен напечатать его`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally { setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Принтер</h1>
        <p className="mt-1 text-sm text-slate-500">
          Настройка печати бланков (через print-agent)
        </p>
      </div>

      {msg && (
        <div className="flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700 ring-1 ring-emerald-200">
          <span>✅</span> {msg}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}

      <div className="msb-card-solid p-6 space-y-5">
        <h2 className="text-sm font-semibold text-slate-700">Настройки</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="msb-label">Название</label>
            <input className="msb-input" value={printer.name}
              onChange={(e) => setPrinter({ ...printer, name: e.target.value })} />
          </div>
          <div>
            <label className="msb-label">Режим печати</label>
            <select className="msb-input" value={printer.mode}
              onChange={(e) => setPrinter({ ...printer, mode: e.target.value })}>
              <option value="agent">Через драйвер ОС (print-agent)</option>
              <option value="ipp">Напрямую по IP (AirPrint/IPP)</option>
            </select>
          </div>
          <div>
            <label className="msb-label">IP-адрес</label>
            <input className="msb-input" value={printer.ip} placeholder="192.168.1.50"
              onChange={(e) => setPrinter({ ...printer, ip: e.target.value })} />
          </div>
          <div>
            <label className="msb-label">Порт (для IPP)</label>
            <input className="msb-input" type="number" value={printer.port}
              onChange={(e) => setPrinter({ ...printer, port: Number(e.target.value) })} />
          </div>
        </div>

        <div className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600 ring-1 ring-slate-200/50">
          <p className="font-semibold text-slate-700 mb-1">Как подключить Epson L3250:</p>
          <ol className="list-decimal space-y-1 pl-5">
            <li><b>Режим «Через драйвер ОС»</b> (надёжнее): установите принтер в Windows/Linux/macOS
              через драйвер Epson, запустите <code>apps/print-agent/agent.py</code> на той же машине.
              Имя принтера должно совпадать с указанным выше.</li>
            <li><b>Режим «Напрямую по IP»</b>: принтер в Wi-Fi с поддержкой AirPrint. Укажите IP,
              print-agent отправит PDF через IPP.</li>
          </ol>
        </div>

        <div className="flex gap-3">
          <button onClick={save} disabled={busy} className="msb-btn-primary">
            💾 Сохранить
          </button>
          <button onClick={test} disabled={busy} className="msb-btn-secondary">
            🖨️ Тестовая печать
          </button>
        </div>
      </div>

      <div className="msb-card-solid p-6">
        <h2 className="mb-4 text-sm font-semibold text-slate-700">Последние задания</h2>
        {jobs.length === 0 ? (
          <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-8 text-sm text-slate-400">
            Заданий пока нет
          </div>
        ) : (
          <div className="space-y-2">
            {jobs.map((j) => (
              <div key={j.id} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
                <div className="text-xs text-slate-500">
                  <span className="font-mono">#{j.id.slice(0, 8)}</span>
                  <span className="mx-2">·</span>
                  {new Date(j.created_at).toLocaleString("ru")}
                </div>
                <span className={`rounded-full px-3 py-1 text-xs font-medium ${
                  j.status === "done" ? "msb-badge-success" :
                  j.status === "failed" ? "msb-badge-danger" :
                  "msb-badge-gray"
                }`}>
                  {j.status === "done" ? "Готово" :
                   j.status === "failed" ? `Ошибка${j.error ? `: ${j.error}` : ""}` :
                   j.status === "queued" ? "В очереди" : j.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}