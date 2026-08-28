"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface DiscoveredPrinter {
  name: string;
  source: "cups" | "network";
  ip: string;
  port: number;
  uri: string;
  status: string;
  label: string;
}

interface Job {
  id: string;
  status: string;
  error?: string | null;
  created_at: string;
}

export default function PrinterPage() {
  const [printerName, setPrinterName] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [discovered, setDiscovered] = useState<DiscoveredPrinter[]>([]);
  const [scanning, setScanning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.getPrinter().then((r) => {
      setPrinterName(r.printer?.name || "");
      setJobs(r.recent_jobs);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  async function scanPrinters() {
    setScanning(true);
    setDiscovered([]);
    try {
      const res = await api.discoverPrinters();
      setDiscovered((res.printers || []).map(p => ({...p, source: p.source as "cups" | "network"})));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setScanning(false);
    }
  }

  function selectPrinter(p: DiscoveredPrinter) {
    setPrinterName(p.name);
    setMsg(`Выбран: ${p.label}`);
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await api.savePrinter({ name: printerName, mode: "cups", ip: "", port: 631 });
      setMsg("✅ Принтер сохранён");
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
      setMsg(`✅ Тест #${String(r.job_id).slice(0, 8)} отправлен`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка печати");
    } finally {
      setBusy(false);
    }
  }

  async function cancelAll() {
    setBusy(true);
    try {
      await api.cancelAllPrintJobs();
      setMsg("✅ Очередь очищена");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  const queuedCount = jobs.filter(j => j.status === "queued" || j.status === "processing").length;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Принтер</h1>
        <p className="mt-1 text-sm text-slate-500">Настройка печати бланков</p>
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

      {/* Current printer name */}
      <div className="msb-card-solid p-6 space-y-4">
        <h2 className="text-sm font-semibold text-slate-700">Имя принтера в CUPS</h2>
        <div>
          <label className="msb-label">Имя очереди (lpstat -p покажет)</label>
          <input className="msb-input font-mono"
            value={printerName}
            onChange={(e) => setPrinterName(e.target.value)}
            placeholder="EPSON_L3250_Series@EPSON858161.local"
          />
          <p className="mt-1 text-xs text-slate-400">
            Точное имя из CUPS. Узнать: <code className="bg-slate-100 px-1 rounded">lpstat -p</code>
          </p>
        </div>

        <div className="flex gap-3">
          <button onClick={save} disabled={busy || !printerName.trim()}
            className="msb-btn-primary">
            💾 Сохранить
          </button>
          <button onClick={test} disabled={busy || !printerName.trim()}
            className="msb-btn-secondary">
            🖨️ Тестовая печать
          </button>
        </div>
      </div>

      {/* Discover */}
      <div className="msb-card-solid p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Найти принтеры в CUPS</h2>
          <button onClick={scanPrinters} disabled={scanning}
            className="msb-btn-primary">
            {scanning ? "Сканирование…" : "Найти"}
          </button>
        </div>
        <p className="text-xs text-slate-400">
          Показывает все принтеры, установленные в CUPS на этой машине
        </p>

        {discovered.length > 0 && (
          <div className="space-y-2">
            {discovered.filter(p => p.source === "cups").map((p, i) => (
              <button key={i} onClick={() => selectPrinter(p)}
                className={`w-full text-left rounded-xl border-2 px-4 py-3 transition-all ${
                  printerName === p.name
                    ? "border-msb-500 bg-msb-50"
                    : "border-slate-200 hover:border-msb-300 hover:bg-slate-50"
                }`}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-semibold text-slate-800">
                    {p.name}
                  </span>
                  <span className={`h-2 w-2 rounded-full ${
                    p.status === "idle" ? "bg-emerald-500" : "bg-amber-500"
                  }`} />
                </div>
              </button>
            ))}
          </div>
        )}

        {!scanning && discovered.length === 0 && (
          <p className="text-xs text-slate-400 text-center py-4">
            Нажмите «Найти» для сканирования CUPS
          </p>
        )}
      </div>

      {/* Print Queue */}
      <div className="msb-card-solid p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-700">Очередь печати</h2>
          <div className="flex items-center gap-3">
            {queuedCount > 0 && (
              <>
                <span className="msb-badge-warning">{queuedCount} в очереди</span>
                <button onClick={cancelAll} disabled={busy}
                  className="text-xs font-medium text-red-500 hover:text-red-700">
                  ✕ Очистить
                </button>
              </>
            )}
          </div>
        </div>
        {jobs.length === 0 ? (
          <p className="text-xs text-slate-400 text-center py-4">Очередь пуста</p>
        ) : (
          <div className="space-y-2">
            {jobs.map((j) => (
              <div key={j.id} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
                <div className="text-xs text-slate-500">
                  <span className="font-mono">#{j.id.slice(0, 8)}</span>
                  <span className="mx-2">·</span>
                  {new Date(j.created_at).toLocaleString("ru")}
                </div>
                <div className="flex items-center gap-2">
                  {j.error && (
                    <span className="max-w-[200px] truncate text-xs text-red-500" title={j.error}>{j.error}</span>
                  )}
                  <span className={`rounded-full px-3 py-1 text-xs font-medium ${
                    j.status === "done" ? "msb-badge-success"
                    : j.status === "failed" ? "msb-badge-danger"
                    : j.status === "processing" ? "msb-badge-info"
                    : j.status === "cancelled" ? "msb-badge-gray"
                    : "msb-badge-warning"
                  }`}>
                    {j.status === "done" ? "✓" : j.status === "failed" ? "✗" : j.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}