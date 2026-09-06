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
  /** Ежедневное напоминание «заберите технику» после «Ремонт закончен». */
  pickup_reminder: string;
}

interface ReminderQueue {
  enabled: boolean;
  sms_window_open: boolean;
  local_time: string;
  schedule: {
    every_hours: number;
    first_delay_hours: number;
    check_interval_min: number;
    quiet_hours: string;
    max_count: number;
    statuses: string[];
  };
  items: Array<{
    id: string;
    number: string;
    status: string;
    client_name?: string | null;
    client_phone?: string | null;
    days_waiting?: number | null;
    sent_count: number;
    last_sent_at?: string | null;
    next_at?: string | null;
  }>;
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
  days: "Сколько дней ждёт",
  ready_date: "Дата готовности",
};

const DEFAULT_TEMPLATES: SmsTemplates = {
  master_assign: "",
  ready: "",
  pickup_reminder: "",
};

export default function SmsSettingsPage() {
  const [server, setServer] = useState<SmsServerConfig>(DEFAULT_SERVER);
  const [templates, setTemplates] = useState<SmsTemplates>(DEFAULT_TEMPLATES);
  const [fields, setFields] = useState<{
    master_assign: string[];
    ready: string[];
    pickup_reminder: string[];
  }>({ master_assign: [], ready: [], pickup_reminder: [] });
  const [queue, setQueue] = useState<ReminderQueue | null>(null);
  const [testPhone, setTestPhone] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .getSmsConfig()
      .then((r) => {
        setServer({ ...DEFAULT_SERVER, ...r.server });
        setTemplates({ ...DEFAULT_TEMPLATES, ...r.templates });
        setFields(r.template_fields);
      })
      .catch((e) => setError(e.message));
    api
      .remindersQueue()
      .then(setQueue)
      .catch(() => setQueue(null));
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

  function insertPlaceholder(target: keyof SmsTemplates, field: string) {
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

      {/* --- Ежедневное напоминание «заберите технику» --- */}
      <div className="msb-card-solid space-y-4 p-4 sm:p-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">
            Ежедневное напоминание клиенту («заберите технику»)
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            После «Ремонт закончен» клиент получает SMS о готовности, а затем —
            это напоминание <b>раз в сутки</b>, пока технику не заберут (статусы
            «Готово к выдаче» и «Не забрано»). После выдачи рассылка прекращается.
          </p>
        </div>
        <textarea
          className="msb-input resize-y"
          rows={4}
          value={templates.pickup_reminder}
          placeholder="Уважаемый клиент, просим забрать вашу технику из нашего сервиса MERYOSAB. Находимся по адресу: Парахат 3/2, ж14."
          onChange={(e) => setTemplates({ ...templates, pickup_reminder: e.target.value })}
        />
        <div className="flex flex-wrap gap-1.5">
          {fields.pickup_reminder.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => insertPlaceholder("pickup_reminder", f)}
              className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
              title={`Вставить {${f}}`}
            >
              {FIELD_LABELS[f] ?? f}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-400">
          Пустой текст = напоминание по умолчанию (название сервиса и адрес, как
          в подсказке выше). Название и адрес меняются здесь, без правки кода.
        </p>
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

      {/* --- Очередь напоминаний --- */}
      {queue && (
        <div className="msb-card-solid space-y-4 p-4 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-700">Очередь напоминаний</h2>
              <p className="mt-1 text-xs text-slate-500">
                Каждые {queue.schedule.check_interval_min} мин система проверяет
                список и шлёт SMS в разрешённое время ({queue.schedule.quiet_hours}).
                {queue.enabled ? "" : " Рассылка выключена (REMINDER_ENABLED=false)."}
                {!queue.sms_window_open && " Сейчас тихие часы — отправка приостановлена."}
              </p>
            </div>
            <button
              onClick={() =>
                run(async () => {
                  const r = await api.runReminders();
                  if (r.reason === "sms_disabled") {
                    throw new Error("SMS-шлюз выключен или не настроен — напоминания не отправлены");
                  }
                  if (r.reason === "quiet_hours") {
                    throw new Error("Сейчас тихие часы: напоминания уйдут в разрешённое время");
                  }
                  if (r.reason === "reminder_disabled") {
                    throw new Error("Рассылка напоминаний выключена (REMINDER_ENABLED=false)");
                  }
                  return r;
                }, "Прогон выполнен — см. результат в списке")
              }
              disabled={busy}
              className="msb-btn-secondary text-xs"
              title="Отправить подошедшие напоминания прямо сейчас"
            >
              ▶ Прогнать сейчас
            </button>
          </div>

          {queue.items.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-slate-200 py-6 text-center text-sm text-slate-400">
              В очереди никого нет — напоминания появятся после «Ремонт закончен»
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
                    <th className="py-2 pr-3 font-medium">Ремонт</th>
                    <th className="py-2 pr-3 font-medium">Клиент</th>
                    <th className="py-2 pr-3 font-medium">Ждёт</th>
                    <th className="py-2 pr-3 font-medium">Отправлено</th>
                    <th className="py-2 font-medium">Следующее</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {queue.items.map((i) => (
                    <tr key={i.id}>
                      <td className="py-2 pr-3 font-mono text-xs text-slate-800">{i.number}</td>
                      <td className="py-2 pr-3 text-slate-600">
                        {i.client_name || "—"}
                        {i.client_phone && (
                          <span className="ml-1 font-mono text-xs text-slate-400">{i.client_phone}</span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-slate-600">
                        {i.days_waiting != null ? `${i.days_waiting} дн.` : "—"}
                      </td>
                      <td className="py-2 pr-3 text-slate-600">{i.sent_count}</td>
                      <td className="py-2 text-xs text-slate-500">
                        {i.next_at ? new Date(i.next_at).toLocaleString("ru") : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
