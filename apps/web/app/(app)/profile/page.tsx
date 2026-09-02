"use client";

import { useEffect, useState } from "react";
import { api, getToken, getStoredUser, setSession } from "@/lib/api";

export default function ProfilePage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [telegram, setTelegram] = useState("");
  const [current, setCurrent] = useState("");
  const [newPass, setNewPass] = useState("");
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .me()
      .then((u) => {
        setName(u.name);
        setEmail(u.email);
        setPhone(u.phone ?? "");
        setTelegram(u.telegram ?? "");
        setRole(u.role);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        name,
        email,
        phone: phone || null,
        telegram: telegram || null,
      };
      if (newPass) {
        payload.current_password = current;
        payload.new_password = newPass;
      }
      const updated = await api.updateMe(payload);
      setMsg("Профиль сохранён");
      setCurrent("");
      setNewPass("");
      // Обновляем локального пользователя (имя/email в шапке).
      const token = getToken();
      if (token) setSession(token, updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-24 text-slate-400">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-msb-500 border-t-transparent" />
      </div>
    );
  }

  const me = getStoredUser();
  const ROLE_LABEL: Record<string, string> = {
    admin: "Администратор",
    manager: "Менеджер",
    operator: "Оператор",
    master: "Мастер",
    callcenter: "Call-центр",
  };

  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-msb-500 to-msb-700 text-xl font-extrabold text-white shadow-sm">
          {(me?.name || name).charAt(0).toUpperCase()}
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Профиль</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Роль: {ROLE_LABEL[role] ?? role}
          </p>
        </div>
      </div>

      {msg && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700 ring-1 ring-emerald-200">
          <span>✅</span> {msg}
        </div>
      )}
      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
          <span>⚠</span> {error}
        </div>
      )}

      <form onSubmit={save} className="msb-card-solid space-y-4 p-6">
        <div>
          <label className="msb-label">Имя и фамилия</label>
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Имя Фамилия" className="msb-input" required />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="msb-label">Телефон</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)}
              inputMode="tel" placeholder="+993 61 000000" className="msb-input" />
          </div>
          <div>
            <label className="msb-label">Telegram</label>
            <input value={telegram} onChange={(e) => setTelegram(e.target.value)}
              placeholder="@username" className="msb-input" />
          </div>
        </div>
        <div>
          <label className="msb-label">Email (для входа)</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            className="msb-input" required />
        </div>

        <div className="msb-divider my-1" />
        <p className="text-sm font-semibold text-slate-700">Смена пароля</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="msb-label">Текущий пароль</label>
            <input type="password" value={current}
              onChange={(e) => setCurrent(e.target.value)}
              className="msb-input" autoComplete="current-password" />
          </div>
          <div>
            <label className="msb-label">Новый пароль</label>
            <input type="password" value={newPass}
              onChange={(e) => setNewPass(e.target.value)}
              className="msb-input" autoComplete="new-password"
              placeholder="мин. 6 символов" />
          </div>
        </div>
        <p className="text-xs text-slate-400">
          Чтобы сменить пароль — заполните оба поля. Иначе просто сохраните профиль.
        </p>

        <button type="submit" disabled={busy} className="msb-btn-primary w-full">
          {busy ? "Сохраняем…" : "Сохранить"}
        </button>
      </form>
    </div>
  );
}
