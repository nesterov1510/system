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
  operator: "bg-green-100 text-green-700",
  master: "bg-amber-100 text-amber-700",
};

export default function ChatPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.channels().then((ch) => {
      setChannels(ch);
      if (ch[0]) setActive(ch[0].id);
    });
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

  const me = getStoredUser();

  return (
    <div className="flex min-h-[calc(100vh-11rem)] flex-col gap-3 lg:h-[calc(100vh-10rem)] lg:flex-row lg:gap-4">
      {/* Sidebar */}
      <aside className="shrink-0 lg:w-48">
        <h2 className="msb-section-title mb-2 px-1">Каналы</h2>
        <div className="flex gap-2 overflow-x-auto pb-1 custom-scroll lg:block lg:space-y-1.5">
          {channels.map((c) => (
            <button key={c.id} onClick={() => setActive(c.id)}
              className={`shrink-0 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition-all lg:w-full lg:px-4 ${
                active === c.id
                  ? "bg-msb-600 text-white shadow-sm"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-msb-200"
              }`}>
              <div className="flex items-center gap-2">
                <span className="text-base">💬</span>
                <span className="max-w-32 truncate">{c.name}</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      {/* Chat area */}
      <section className="flex min-h-[28rem] flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        {/* Messages */}
        <div className="flex-1 space-y-4 overflow-y-auto p-5 custom-scroll">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <span className="text-4xl mb-3">💬</span>
              <p className="text-sm font-medium">Сообщений пока нет</p>
              <p className="text-xs mt-1">Напишите первое сообщение</p>
            </div>
          )}
          {messages.map((m) => {
            const isMe = m.author?.id === me?.id;
            return (
              <div key={m.id} className={`flex ${isMe ? "justify-end" : "justify-start"} animate-slide-up`}>
                <div className={`max-w-[85%] sm:max-w-[70%] ${isMe ? "order-1" : ""}`}>
                  <div className={`flex items-center gap-2 mb-1 px-1 ${isMe ? "justify-end" : ""}`}>
                    <span className={`text-xs font-medium ${isMe ? "text-msb-600" : "text-slate-500"}`}>
                      {m.author?.name ?? "…"}
                    </span>
                    {m.author?.role && (
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${ROLE_COLORS[m.author.role] ?? "bg-slate-100 text-slate-600"}`}>
                        {m.author.role === "admin" ? "Админ" :
                         m.author.role === "master" ? "Мастер" :
                         m.author.role === "operator" ? "Оператор" :
                         m.author.role}
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
        <div className="border-t border-slate-100 p-4">
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
      </section>
    </div>
  );
}