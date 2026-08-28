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
  const [config, setConfig] = useState<{
    name: string;
    mode: string; // cups | ipp | agent
    ip: string;
    port: number;
  }>({ name: "", mode: "agent", ip: "", port: 631 });

  const [discovered, setDiscovered] = useState<DiscoveredPrinter[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.getPrinter().then((r) => {
      setConfig(r.printer);
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
    setScanError(null);
    setDiscovered([]);
    try {
      const res = await api.discoverPrinters();
      setDiscovered((res.printers || []).map(p => ({...p, source: p.source as "cups" | "network"})));
    } catch (e) {
      setScanError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setScanning(false);
    }
  }

  function selectPrinter(p: DiscoveredPrinter) {
    if (p.source === "cups") {
      setConfig({ name: p.name, mode: "cups", ip: "", port: 631 });
    } else {
      setConfig({ name: "", mode: p.uri.startsWith("ipp") ? "ipp" : "raw", ip: p.ip, port: p.port });
    }
    setMsg(`Выбран: ${p.label}`);
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await api.savePrinter(config);
      setMsg("✅ Настройки принтера сохранены");
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
        <p className="mt-1 text-sm text-slate-500">
          Настройка печати бланков
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

      {/* Printer Config */}
      <div className="msb-card-solid p-6 space-y-4">
        <h2 className="text-sm font-semibold text-slate-700">Настройки принтера</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="msb-label">Режим печати</label>
            <select className="msb-input" value={config.mode}
              onChange={(e) => setConfig({ ...config, mode: e.target.value, name: "", ip: "", port: 631 })}>
              <option value="cups">CUPS (локальный драйвер)</option>
              <option value="ipp">IPP (сетевой, порт 631)</option>
              <option value="raw">Raw (сетевой, порт 9100)</option>
            </select>
          </div>

          {config.mode === "cups" && (
            <div>
              <label className="msb-label">Имя очереди CUPS *</label>
              <input className="msb-input font-mono" value={config.name}
                onChange={(e) => setConfig({ ...config, name: e.target.value })}
                placeholder="EPSON_L3250_Series@EPSON858161.local" required />
              <p className="mt-1 text-xs text-slate-400">
                Точное имя из `lpstat -p`
              </p>
            </div>
          )}
          {(config.mode === "ipp" || config.mode === "raw") && (
            <>
              <div>
                <label className="msb-label">IP-адрес *</label>
                <input className="msb-input" value={config.ip} placeholder="192.168.1.50"
                  onChange={(e) => setConfig({ ...config, ip: e.target.value })} required />
              </div>
              <div>
                <label className="msb-label">Порт *</label>
                <input className="msb-input" type="number" value={config.port} placeholder="631"
                  onChange={(e) => setConfig({ ...config, port: Number(e.target.value) })} required />
              </div>
            </>
          )}
        </div>

        <div className="flex gap-3">
          <button onClick={save} disabled={busy || (!config.name && config.mode === "cups") || (!config.ip && (config.mode === "ipp" || config.mode === "raw"))}
            className="msb-btn-primary">
            💾 Сохранить
          </button>
          <button onClick={test} disabled={busy || !config.name && config.mode === "cups" || (!config.ip && (config.mode === "ipp" || config.mode === "raw"))}
            className="msb-btn-secondary">
            🖨️ Тестовая печать
          </button>
        </div>
      </div>

      {/* Discover Section */}
      <div className="msb-card-solid p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Найти принтеры</h2>
          <button onClick={scanPrinters} disabled={scanning} className="msb-btn-primary">
            {scanning ? "Сканирование…" : "Найти"}
          </button>
        </div>
        <p className="text-xs text-slate-400">
          Сканирует CUPS-очереди и сетевые IP (IPP/Raw)
        </p>

        {scanError && <p className="text-sm text-amber-600">{scanError}</p>}

        {discovered.length > 0 && (
          <div className="space-y-2">
            {discovered.map((p, i) => (
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
                <p className="mt-0.5 text-xs text-slate-500">{p.label}</p>
              </button>
            ))}
          </div>
        )}

        {!scanning && discovered.length === 0 && !scanError && (
          <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-8 text-sm text-slate-400">
            <div className="text-center">
              <span className="text-2xl mb-2 block">🖨️</span>
              Нажмите «Найти принтеры»
            </div>
          </div>
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
                  ✕ Отменить все
                </button>
              </>
            )}
            <button onClick={load} className="text-xs text-slate-400 hover:text-slate-600">
              ↻ Обновить
            </button>
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
                    <span className="max-w-[200px] truncate text-xs text-red-500" title={j.error}>
                      {j.error}
                    </span>
                  )}
                  <span className={`rounded-full px-3 py-1 text-xs font-medium ${
                    j.status === "done" ? "msb-badge-success"
                    : j.status === "failed" ? "msb-badge-danger"
                    : j.status === "processing" ? "msb-badge-info"
                    : j.status === "cancelled" ? "msb-badge-gray"
                    : "msb-badge-warning"
                  }`}>
                    {j.status === "done" ? "✓ Готово"
                     : j.status === "failed" ? "✗ Ошибка"
                     : j.status === "processing" ? "⏳ Печатается…"
                     : j.status === "queued" ? "📋 В очереди"
                     : j.status === "cancelled" ? "Отменено"
                     : j.status}
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