"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface PrinterConfig {
  ip: string;
  port: number;
  mode: string;
  name: string;
}

interface LabelPrinterConfig extends PrinterConfig {
  width_mm: number;
  height_mm: number;
  media: string;
}

interface Job {
  id: string;
  status: string;
  error?: string | null;
  created_at: string;
  template_id?: string | null;
  printer_name?: string | null;
}

const DEFAULT_LABEL_PRINTER: LabelPrinterConfig = {
  ip: "192.168.5.238",
  port: 631,
  mode: "cups_remote",
  name: "3B-350B",
  width_mm: 58,
  height_mm: 38,
  media: "Custom.58x38mm",
};

export default function PrinterPage() {
  const [printer, setPrinter] = useState<PrinterConfig>({
    ip: "", port: 631, mode: "agent", name: "Epson L3250",
  });
  const [labelPrinter, setLabelPrinter] = useState<LabelPrinterConfig>(
    DEFAULT_LABEL_PRINTER,
  );
  const [jobs, setJobs] = useState<Job[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.getPrinter().then((r) => {
      setPrinter(r.printer);
      setLabelPrinter({ ...DEFAULT_LABEL_PRINTER, ...r.label_printer });
      setJobs(r.recent_jobs);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await action();
      setMsg(success);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  function isLabelJob(job: Job) {
    return job.template_id?.includes("label") ?? false;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Принтеры</h1>
        <p className="mt-1 text-sm text-slate-500">
          Основной бланк A4 и этикетка ремонта 58×38 мм
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

      <div className="msb-card-solid space-y-5 p-4 sm:p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Основной принтер бланков</h2>
          <p className="mt-1 text-xs text-slate-500">PDF-бланк ремонта (например, Epson L3250)</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="msb-label">Название / очередь</label>
            <input className="msb-input" value={printer.name}
              onChange={(e) => setPrinter({ ...printer, name: e.target.value })} />
          </div>
          <div>
            <label className="msb-label">Режим печати</label>
            <select className="msb-input" value={printer.mode}
              onChange={(e) => setPrinter({ ...printer, mode: e.target.value })}>
              <option value="agent">Через локальный драйвер print-agent</option>
              <option value="ipp">Напрямую по IP (AirPrint/IPP)</option>
            </select>
          </div>
          <div>
            <label className="msb-label">IP-адрес (только IPP)</label>
            <input className="msb-input" value={printer.ip} placeholder="192.168.1.50"
              onChange={(e) => setPrinter({ ...printer, ip: e.target.value })} />
          </div>
          <div>
            <label className="msb-label">Порт (только IPP)</label>
            <input className="msb-input" type="number" value={printer.port}
              onChange={(e) => setPrinter({ ...printer, port: Number(e.target.value) })} />
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <button onClick={() => run(
            () => api.savePrinter(printer),
            "Настройки основного принтера сохранены",
          )} disabled={busy} className="msb-btn-primary">
            💾 Сохранить
          </button>
          <button onClick={() => run(
            () => api.testPrint(),
            "Тестовый бланк поставлен в очередь",
          )} disabled={busy} className="msb-btn-secondary">
            🖨️ Тест A4
          </button>
        </div>
      </div>

      <div className="msb-card-solid space-y-5 p-4 sm:p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            Принтер этикеток 58×38 мм
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Print-agent на сервере отправляет PDF в удалённую CUPS-очередь.
            На этикетке печатаются ФИО, телефон и QR на карточку ремонта мастера.
          </p>
        </div>

        <div className="rounded-xl bg-blue-50 px-4 py-3 text-xs text-blue-800 ring-1 ring-blue-100">
          Маршрут: <code className="font-semibold">192.168.8.81</code>
          {" → "}<code className="font-semibold">{labelPrinter.ip}:{labelPrinter.port}</code>
          {" → "}<code className="font-semibold">{labelPrinter.name}</code>.
          На компьютере с принтером CUPS должен разрешать подключения от сервера.
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="msb-label">IP компьютера с CUPS</label>
            <input className="msb-input" value={labelPrinter.ip}
              placeholder="192.168.5.238"
              onChange={(e) => setLabelPrinter({ ...labelPrinter, ip: e.target.value })} />
          </div>
          <div>
            <label className="msb-label">Порт CUPS</label>
            <input className="msb-input" type="number" value={labelPrinter.port}
              onChange={(e) => setLabelPrinter({ ...labelPrinter, port: Number(e.target.value) })} />
          </div>
          <div>
            <label className="msb-label">Имя CUPS-очереди</label>
            <input className="msb-input" value={labelPrinter.name}
              placeholder="3B-350B"
              onChange={(e) => setLabelPrinter({ ...labelPrinter, name: e.target.value })} />
          </div>
          <div>
            <label className="msb-label">Media option CUPS</label>
            <input className="msb-input" value={labelPrinter.media}
              placeholder="Custom.58x38mm"
              onChange={(e) => setLabelPrinter({ ...labelPrinter, media: e.target.value })} />
            <p className="mt-1 text-xs text-slate-400">
              Если драйвер отклоняет Custom.58x38mm — очистите поле и задайте размер по умолчанию в CUPS.
            </p>
          </div>
          <div className="sm:col-span-2 rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
            <p className="text-xs font-semibold text-slate-600">Формат PDF: 58 × 38 мм</p>
            <p className="mt-1 text-xs text-slate-400">
              Размер зафиксирован под установленную этикетку и не меняется в настройках.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <button onClick={() => run(
            () => api.saveLabelPrinter(labelPrinter),
            "Настройки принтера этикеток сохранены",
          )} disabled={busy} className="msb-btn-primary">
            💾 Сохранить этикетку
          </button>
          <button onClick={() => run(
            () => api.testLabelPrint(),
            "Тестовая этикетка 58×38 поставлена в очередь",
          )} disabled={busy} className="msb-btn-secondary">
            🏷️ Тест 58×38
          </button>
        </div>
      </div>

      <div className="msb-card-solid p-4 sm:p-6">
        <h2 className="mb-4 text-sm font-semibold text-slate-700">Последние задания</h2>
        {jobs.length === 0 ? (
          <div className="flex items-center justify-center rounded-xl border-2 border-dashed border-slate-200 py-8 text-sm text-slate-400">
            Заданий пока нет
          </div>
        ) : (
          <div className="space-y-2">
            {jobs.map((j) => (
              <div key={j.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
                <div className="text-xs text-slate-500">
                  <span className="font-mono">#{j.id.slice(0, 8)}</span>
                  <span className="mx-2">·</span>
                  <span className={isLabelJob(j) ? "text-violet-700" : "text-blue-700"}>
                    {isLabelJob(j) ? "Этикетка" : "Бланк"}
                  </span>
                  {j.printer_name && <span> · {j.printer_name}</span>}
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
