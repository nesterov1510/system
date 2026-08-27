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
    // Relative to the current origin so it works behind the preview proxy too.
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
      } catch {
        /* ignore */
      }
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
      // WS broadcast will deliver it; avoid double-add by not pushing locally.
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка отправки");
    }
  }, [active, text]);

  const me = getStoredUser();

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-3">
      {/* Channels */}
      <aside className="w-36 shrink-0 space-y-1 sm:w-44">
        {channels.map((c) => (
          <button
            key={c.id}
            onClick={() => setActive(c.id)}
            className={`w-full rounded-lg px-3 py-2.5 text-left text-sm ${
              active === c.id
                ? "bg-slate-900 text-white"
                : "bg-white text-gray-700 ring-1 ring-gray-200"
            }`}
          >
            {c.name}
          </button>
        ))}
      </aside>

      {/* Messages */}
      <section className="flex flex-1 flex-col rounded-xl bg-white ring-1 ring-gray-200">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.length === 0 && (
            <p className="py-8 text-center text-sm text-gray-400">
              Сообщений пока нет
            </p>
          )}
          {messages.map((m) => (
            <div key={m.id}>
              <div className="text-xs text-gray-400">
                {m.author?.name ?? "…"} ·{" "}
                {new Date(m.created_at).toLocaleTimeString("ru", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </div>
              <div className="mt-0.5 text-sm text-gray-800">{m.text}</div>
              {m.repair_preview && (
                <a
                  href={`/repairs`}
                  className="mt-1 inline-block rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs text-blue-700"
                >
                  #{m.repair_preview.number} · {m.repair_preview.status}
                </a>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-gray-200 p-3">
          <div className="flex gap-2">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Сообщение… (#TV-MSK-00001)"
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
            />
            <button
              onClick={send}
              className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white"
            >
              ➤
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
