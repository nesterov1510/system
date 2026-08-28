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
  const [selectedPrinter, setSelectedPrinter] = useState<{
    name: string;
    mode: string;
    ip: string;
    port: number;
  }>({ name: "", mode: "cups", ip: "", port: 631 });

  const [discovered, setDiscovered] = useState<DiscoveredPrinter[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .getPrinter()
      .then((r) => {
        setSelectedPrinter(r.printer);
        setJobs(r.recent_jobs);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  async function scanPrinters() {
    setScanning(true);
    setScanError(null);
    setDiscovered([]);
    try {
      const res = await api.discoverPrinters();
      setDiscovered((res.printers || []).map(p => ({...p, source: p.source as "cups" | "network"})));
      if ((res.printers || []).length === 0) {
        setScanError("Принтеры не найдены. Убедитесь, что принтер включён и подключён к сети.");
      }
    } catch (e) {
      setScanError(e instanceof Error ? e.message : "Ошибка поиска");
    } finally {
      setScanning(false);
    }
  }

  function selectPrinter(p: DiscoveredPrinter) {
    const mode = p.source === "cups" ? "cups" : "ipp";
    setSelectedPrinter({
      name: p.name,
      mode,
      ip: p.ip || "",
      port: p.port || 631,
    });
    setMsg(`Выбран: ${p.label}`);
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await api.savePrinter(selectedPrinter);
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
      setMsg(`✅ Тестовое задание #${String(r.job_id).slice(0, 8)} отправлено на печать`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка печати");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Принтер</h1>
        <p className="mt-1 text-sm text-slate-500">
          Автопоиск и настройка печати бланков
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

      {/* Scan Section */}
      <div className="msb-card-solid p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">🔍 Найти принтеры в сети</h2>
          <button onClick={scanPrinters} disabled={scanning}
            className="msb-btn-primary">
            {scanning ? (
              <span className="flex items-center gap-2">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Сканирование…
              </span>
            ) : (
              "Найти принтеры"
            )}
          </button>
        </div>

        {scanError && (
          <p className="text-sm text-amber-600">{scanError}</p>
        )}

        {discovered.length > 0 && (
          <div className="space-y-2">
            {discovered.map((p, i) => (
              <button key={i} onClick={() => selectPrinter(p)}
                className={`w-full text-left rounded-xl border-2 px-4 py-3 transition-all ${
                  selectedPrinter.name === p.name
                    ? "border-msb-500 bg-msb-50"
                    : "border-slate-200 hover:border-msb-300 hover:bg-slate-50"
                }`}>
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm font-semibold text-slate-800">
                      {p.name}
                    </span>
                    <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      p.source === "cups"
                        ? "bg-blue-100 text-blue-700"
                        : "bg-emerald-100 text-emerald-700"
                    }`}>
                      {p.source === "cups" ? "CUPS" : "Сетевой"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {p.ip && (
                      <span className="text-xs text-slate-400 font-mono">{p.ip}</span>
                    )}
                    <span className={`h-2 w-2 rounded-full ${
                      p.status === "idle" ? "bg-emerald-500" : "bg-amber-500"
                    }`} />
                  </div>
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
              Нажмите «Найти принтеры» для сканирования сети
            </div>
          </div>
        )}
      </div>

      {/* Current Selection */}
      <div className="msb-card-solid p-6 space-y-4">
        <h2 className="text-sm font-semibold text-slate-700">Текущий принтер</h2>
        {selectedPrinter.name ? (
          <div className="rounded-xl bg-emerald-50 px-4 py-3 ring-1 ring-emerald-100">
            <div className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-full bg-emerald-500" />
              <span className="text-sm font-semibold text-emerald-800">
                {selectedPrinter.name}
              </span>
              <span className="msb-badge-info text-[10px]">{selectedPrinter.mode}</span>
            </div>
            {selectedPrinter.ip && (
              <p className="mt-1 text-xs text-emerald-600">
                IP: {selectedPrinter.ip}:{selectedPrinter.port}
              </p>
            )}
          </div>
        ) : (
          <div className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-500 ring-1 ring-slate-100">
            Принтер не выбран. Найдите и выберите принтер выше.
          </div>
        )}

        <div className="flex gap-3">
          <button onClick={save} disabled={busy || !selectedPrinter.name}
            className="msb-btn-primary">
            💾 Сохранить выбор
          </button>
          <button onClick={test} disabled={busy || !selectedPrinter.name}
            className="msb-btn-secondary">
            🖨️ Тестовая печать
          </button>
        </div>
      </div>

      {/* Recent Jobs */}
      <div className="msb-card-solid p-6">
        <h2 className="mb-4 text-sm font-semibold text-slate-700">Последние задания печати</h2>
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
                  j.status === "done" ? "msb-badge-success"
                  : j.status === "failed" ? "msb-badge-danger"
                  : j.status === "processing" ? "msb-badge-info"
                  : "msb-badge-gray"
                }`}>
                  {j.status === "done" ? "✓ Готово"
                   : j.status === "failed" ? `✗ ${j.error || "Ошибка"}`
                   : j.status === "processing" ? "⏳ Обработка"
                   : j.status === "queued" ? "📋 В очереди"
                   : j.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}