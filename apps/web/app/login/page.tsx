"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setSession } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@msb.local");
  const [password, setPassword] = useState("admin123");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await api.login(email, password);
      setSession(res.access_token, res.user);
      router.push("/repairs");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50 p-4">
      <div className="w-full max-w-sm animate-slide-up">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-msb-600 to-msb-800 shadow-lg shadow-msb-600/20">
            <span className="text-2xl font-extrabold text-white">MSB</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900">MSB</h1>
          <p className="mt-1 text-sm text-slate-500"></p>
        </div>

        <div className="rounded-2xl bg-white p-8 shadow-lg shadow-slate-200/60 ring-1 ring-slate-200">
          <form onSubmit={onSubmit} className="space-y-5">
            <div>
              <label className="msb-label">Email</label>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="msb-input"
                autoComplete="username"
                placeholder="email@example.com"
              />
            </div>
            <div>
              <label className="msb-label">Пароль</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="msb-input"
                autoComplete="current-password"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600 ring-1 ring-red-100">
                <span>⚠</span>
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="msb-btn-primary w-full py-3 text-base"
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Входим…
                </span>
              ) : (
                "Войти в систему"
              )}
            </button>
          </form>

          <div className="mt-6 rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-200/50">
            <p className="text-xs text-slate-500">
              <span className="font-medium text-slate-700">Демо-доступ:</span>{" "}
              admin@msb.local / admin123
            </p>
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          MSB v1.0 — Система управления сервисным центром
        </p>
      </div>
    </main>
  );
}