"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken, getStoredUser, type Channel } from "@/lib/api";

interface Message {
  id: string;
  channel_id: string;
  text: string;
  repair_ref?: string | null;
  created_at: string;
  author?: { id: string; name: string; role: string } | null;
  repair_preview?: {
    number: string;
    status: string;
    device_type: string;
    brand?: string | null;
    model?: string | null;
  } | null;
}

const ROLE_COLORS: Record<string, string> = {
  admin: "bg-red-100 text-red-700",
  manager: "bg-blue-100 text-blue-700",
  operator: "bg-green-100 text-green-700",
  master: "bg-amber-100 text-amber-700",
  callcenter: "bg-purple-100 text-purple-700",
};
const ROLE_LABEL: Record<string, string> = {
  admin: "Админ",
  manager: "Менеджер",
  operator: "Оператор",
  master: "Мастер",
  callcenter: "Call-центр",
};

export default function ChatPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [users, setUsers] = useState<Array<{ id: string; name: string; role: string }>>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadChannels = useCallback(async () => {
    const ch = await api.channels();
    setChannels(ch);
    setActive((cur) => cur ?? ch[0]?.id ?? null);
  }, []);

  useEffect(() => {
    loadChannels().catch((e) => setError(e.message));
  }, [loadChannels]);

  useEffect(() => {
    api.chatUsers().then(setUsers).catch(() => {});
  }, []);

  useEffect(() => {
    if (!active) return;
    api
      .messages(active)
      .then((m) => setMessages(m as unknown as Message[]))
      .catch((e) => setError(e.message));
  }, [active]);

  useEffect(() => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const wsBase =
      process.env.NEXT_PUBLIC_WS_URL || `${scheme}://${window.location.host}`;
    const token = getToken();
    if (!token) return;
    const ws = new WebSocket(`${wsBase}/ws?token=${encodeURIComponent(token)}`);
    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data);
        if (event.type === "chat.message" && event.channel_id === active) {
          setMessages((prev) => [...prev, event.message as Message]);
        }
      } catch { /* ignore */ }
    };
    wsRef.current = ws;
    return () => ws.close();
  }, [active]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    if (!active || !text.trim()) return;
    const body = text.trim();
    setText("");
    try {
      await api.sendMessage(active, body);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка отправки");
    }
  }, [active, text]);

  async function startDirect(userId: string) {
    setStarting(true);
    setError(null);
    try {
      const ch = await api.openDirect(userId);
      setChannels((prev) =>
        prev.some((c) => c.id === ch.id) ? prev : [...prev, ch],
      );
      setActive(ch.id);
      setPickerOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setStarting(false);
    }
  }

  const me = getStoredUser();
  const publicChannels = channels.filter((c) => c.kind !== "direct");
  const directChannels = channels.filter((c) => c.kind === "direct");
  const activeChannel = channels.find((c) => c.id === active) || null;

  return (
    <div className="flex min-h-[calc(100vh-11rem)] flex-col gap-3 lg:h-[calc(100vh-10rem)] lg:flex-row lg:gap-4">
      {/* Sidebar */}
      <aside className="shrink-0 lg:w-56">
        <div className="mb-2 flex items-center justify-between px-1">
          <h2 className="msb-section-title">Чаты</h2>
          <button onClick={() => setPickerOpen((v) => !v)}
            className="msb-btn-primary px-2.5 py-1 text-xs">
            + Личное
          </button>
        </div>

        {/* Новое личное — выбор сотрудника */}
        {pickerOpen && (
          <div className="mb-2 rounded-xl bg-white p-2 shadow-sm ring-1 ring-slate-200 animate-slide-up">
            <p className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Кому написать
            </p>
            <div className="max-h-56 space-y-1 overflow-y-auto custom-scroll">
              {users.length === 0 && (
                <p className="px-2 py-2 text-xs text-slate-400">
                  {starting ? "…" : "Нет сотрудников"}
                </p>
              )}
              {users.map((u) => (
                <button key={u.id} onClick={() => startDirect(u.id)}
                  disabled={starting}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-msb-50 transition-colors">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-msb-500 to-msb-700 text-[10px] font-bold text-white">
                    {u.name.charAt(0).toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-medium text-slate-700">
                    {u.name}
                  </span>
                  <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-medium ${ROLE_COLORS[u.role] ?? "bg-slate-100 text-slate-600"}`}>
                    {ROLE_LABEL[u.role] ?? u.role}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-3">
          {publicChannels.length > 0 && (
            <div>
              <p className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Общие
              </p>
              <div className="space-y-1.5">
                {publicChannels.map((c) => (
                  <ChannelBtn key={c.id} c={c} active={active === c.id} onClick={() => setActive(c.id)} />
                ))}
              </div>
            </div>
          )}
          {directChannels.length > 0 && (
            <div>
              <p className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Личные
              </p>
              <div className="space-y-1.5">
                {directChannels.map((c) => (
                  <ChannelBtn key={c.id} c={c} active={active === c.id} onClick={() => setActive(c.id)} direct />
                ))}
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* Chat area */}
      <section className="flex min-h-[28rem] flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        {/* Header */}
        {activeChannel && (
          <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-3">
            <span className="text-lg">
              {activeChannel.kind === "direct" ? "👤" : "💬"}
            </span>
            <span className="font-semibold text-slate-800">
              {activeChannel.kind === "direct" && activeChannel.peer
                ? activeChannel.peer.name
                : activeChannel.name}
            </span>
            {activeChannel.kind === "direct" && activeChannel.peer && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${ROLE_COLORS[activeChannel.peer.role] ?? "bg-slate-100 text-slate-600"}`}>
                {ROLE_LABEL[activeChannel.peer.role] ?? activeChannel.peer.role}
              </span>
            )}
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 space-y-4 overflow-y-auto p-5 custom-scroll">
          {!activeChannel && (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <span className="mb-3 text-4xl">💬</span>
              <p className="text-sm font-medium">Выберите чат или напишите сотруднику</p>
            </div>
          )}
          {activeChannel && messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <span className="mb-3 text-4xl">{activeChannel.kind === "direct" ? "👤" : "💬"}</span>
              <p className="text-sm font-medium">Сообщений пока нет</p>
              <p className="mt-1 text-xs">Напишите первое сообщение</p>
            </div>
          )}
          {messages.map((m) => {
            const isMe = m.author?.id === me?.id;
            return (
              <div key={m.id} className={`flex ${isMe ? "justify-end" : "justify-start"} animate-slide-up`}>
                <div className={`max-w-[85%] sm:max-w-[70%] ${isMe ? "order-1" : ""}`}>
                  <div className={`mb-1 flex items-center gap-2 px-1 ${isMe ? "justify-end" : ""}`}>
                    <span className={`text-xs font-medium ${isMe ? "text-msb-600" : "text-slate-500"}`}>
                      {m.author?.name ?? "…"}
                    </span>
                    {m.author?.role && (
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${ROLE_COLORS[m.author.role] ?? "bg-slate-100 text-slate-600"}`}>
                        {ROLE_LABEL[m.author.role] ?? m.author.role}
                      </span>
                    )}
                    <span className="text-[10px] text-slate-400">
                      {new Date(m.created_at).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                  <div className={`rounded-2xl px-4 py-3 text-sm ${
                    isMe
                      ? "bg-msb-600 text-white rounded-tr-md"
                      : "bg-slate-100 text-slate-800 rounded-tl-md"
                  }`}>
                    <p>{m.text}</p>
                  </div>
                  {m.repair_preview && (
                    <a href="/repairs"
                      className={`mt-1.5 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium ${
                        isMe ? "text-msb-200 bg-msb-700/20" : "text-msb-700 bg-msb-50 ring-1 ring-msb-100"
                      }`}>
                      <span>🔧</span>
                      #{m.repair_preview.number} · {m.repair_preview.status}
                    </a>
                  )}
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        {activeChannel && (
          <div className="border-t border-slate-100 p-4">
            {error && (
              <div className="mb-2 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-600 ring-1 ring-red-100">
                <span>⚠</span> {error}
              </div>
            )}
            <div className="flex gap-3">
              <input value={text} onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
                placeholder="Сообщение… (#TV-MSK-00001 для ссылки на ремонт)"
                className="msb-input flex-1" />
              <button onClick={send} disabled={!text.trim()}
                className="msb-btn-primary px-5">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function ChannelBtn({ c, active, onClick, direct }: {
  c: Channel; active: boolean; onClick: () => void; direct?: boolean;
}) {
  const label = direct && c.peer ? c.peer.name : c.name;
  return (
    <button onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition-all ${
        active
          ? "bg-msb-600 text-white shadow-sm"
          : "bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-msb-200"
      }`}>
      <span className="text-base">{direct ? "👤" : "💬"}</span>
      <span className="max-w-32 truncate">{label}</span>
    </button>
  );
}
