"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface SmsServerConfig {
  enabled: boolean;
  url: string;
  username: string;
  password: string;
  verify_ssl: boolean;
  timeout_sec: number;
}

interface SmsTemplates {
  master_assign: string;
  ready: string;
}

const DEFAULT_SERVER: SmsServerConfig = {
  enabled: false,
  url: "",
  username: "",
  password: "",
  verify_ssl: false,
  timeout_sec: 10,
};

const FIELD_LABELS: Record<string, string> = {
  master_name: "Имя мастера",
  number: "Номер ремонта",
  device: "Устройство",
  serial: "Серийный номер",
  client_name: "Имя клиента",
  client_phone: "Телефон клиента",
  fault: "Неисправность",
  eta_days: "Срок (дней)",
};

export default function SmsSettingsPage() {
  const [server, setServer] = useState<SmsServerConfig>(DEFAULT_SERVER);
  const [templates, setTemplates] = useState<SmsTemplates>({ master_assign: "", ready: "" });
  const [fields, setFields] = useState<{ master_assign: string[]; ready: string[] }>({
    master_assign: [],
    ready: [],
  });
  const [testPhone, setTestPhone] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .getSmsConfig()
      .then((r) => {
        setServer({ ...DEFAULT_SERVER, ...r.server });
        setTemplates(r.templates);
        setFields(r.template_fields);
      })
      .catch((e) => setError(e.message));
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

  function insertPlaceholder(target: "master_assign" | "ready", field: string) {
    setTemplates((t) => ({ ...t, [target]: `${t[target]}{${field}}` }));
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">SMS-уведомления</h1>
        <p className="mt-1 text-sm text-slate-500">
          Шлюз для отправки SMS мастерам и клиентам + редактируемые шаблоны текста
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

      {/* --- Шлюз --- */}
      <div className="msb-card-solid space-y-5 p-4 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">SMS-шлюз</h2>
            <p className="mt-1 text-xs text-slate-500">
              HTTP API вида <code>POST /api/3rdparty/v1/messages</code>, basic-auth
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium text-slate-600">
            <input
              type="checkbox"
              checked={server.enabled}
              onChange={(e) => setServer({ ...server, enabled: e.target.checked })}
              className="h-4 w-4 rounded border-slate-300"
            />
            Включено
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="msb-label">Адрес шлюза (URL)</label>
            <input
              className="msb-input"
              value={server.url}
              placeholder="https://192.168.5.238/api/3rdparty/v1/messages"
              onChange={(e) => setServer({ ...server, url: e.target.value })}
            />
          </div>
          <div>
            <label className="msb-label">Логин</label>
            <input
              className="msb-input"
              value={server.username}
              placeholder="56FNPL"
              onChange={(e) => setServer({ ...server, username: e.target.value })}
            />
          </div>
          <div>
            <label className="msb-label">Пароль</label>
            <input
              className="msb-input"
              type="text"
              value={server.password}
              placeholder="uv9bmvwgdrcs5z"
              onChange={(e) => setServer({ ...server, password: e.target.value })}
            />
            <p className="mt-1 text-xs text-slate-400">
              Если оставить маску «••••••••» — сохранённый пароль не изменится.
            </p>
          </div>
          <div>
            <label className="msb-label">Таймаут (сек)</label>
            <input
              className="msb-input"
              type="number"
              value={server.timeout_sec}
              onChange={(e) => setServer({ ...server, timeout_sec: Number(e.target.value) })}
            />
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={server.verify_ssl}
                onChange={(e) => setServer({ ...server, verify_ssl: e.target.checked })}
                className="h-4 w-4 rounded border-slate-300"
              />
              Проверять SSL-сертификат шлюза
            </label>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => run(() => api.saveSmsConfig(server), "Настройки SMS-шлюза сохранены")}
            disabled={busy}
            className="msb-btn-primary"
          >
            💾 Сохранить
          </button>
        </div>

        <div className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-100">
          <label className="msb-label">Тестовая отправка</label>
          <div className="flex flex-wrap gap-2">
            <input
              className="msb-input flex-1 min-w-[200px]"
              value={testPhone}
              placeholder="+993 61 000000"
              onChange={(e) => setTestPhone(e.target.value)}
            />
            <button
              onClick={() => run(() => api.testSms(testPhone), "Тестовое SMS отправлено ✓")}
              disabled={busy || !testPhone.trim()}
              className="msb-btn-secondary"
            >
              📤 Отправить тест
            </button>
          </div>
        </div>
      </div>

      {/* --- Шаблон: мастеру при назначении --- */}
      <div className="msb-card-solid space-y-4 p-4 sm:p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            Шаблон SMS мастеру (при назначении на ремонт)
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Оставьте пустым, чтобы использовать текст по умолчанию
          </p>
        </div>
        <textarea
          className="msb-input resize-y"
          rows={5}
          value={templates.master_assign}
          placeholder="Уважаемый(ая) {master_name}! Вам назначен ремонт № {number}, {device}..."
          onChange={(e) => setTemplates({ ...templates, master_assign: e.target.value })}
        />
        <div className="flex flex-wrap gap-1.5">
          {fields.master_assign.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => insertPlaceholder("master_assign", f)}
              className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
              title={`Вставить {${f}}`}
            >
              {FIELD_LABELS[f] ?? f}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => run(() => api.saveSmsTemplates(templates), "Шаблоны SMS сохранены")}
            disabled={busy}
            className="msb-btn-primary"
          >
            💾 Сохранить шаблоны
          </button>
        </div>
      </div>

      {/* --- Шаблон: клиенту о готовности --- */}
      <div className="msb-card-solid space-y-4 p-4 sm:p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            Шаблон SMS клиенту («Ремонт закончен» — забрать технику)
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Этот текст предлагается по умолчанию при нажатии «Ремонт закончен» на
            карточке ремонта — его ещё можно отредактировать перед отправкой.
          </p>
        </div>
        <textarea
          className="msb-input resize-y"
          rows={4}
          value={templates.ready}
          placeholder="Здравствуйте, {client_name}! Ваш заказ № {number} ({device}) готов к выдаче."
          onChange={(e) => setTemplates({ ...templates, ready: e.target.value })}
        />
        <div className="flex flex-wrap gap-1.5">
          {fields.ready.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => insertPlaceholder("ready", f)}
              className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
              title={`Вставить {${f}}`}
            >
              {FIELD_LABELS[f] ?? f}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => run(() => api.saveSmsTemplates(templates), "Шаблоны SMS сохранены")}
            disabled={busy}
            className="msb-btn-primary"
          >
            💾 Сохранить шаблоны
          </button>
        </div>
      </div>
    </div>
  );
}
