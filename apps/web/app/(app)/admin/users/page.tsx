"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type User } from "@/lib/api";

const ROLES: Array<{ value: string; label: string }> = [
  { value: "admin", label: "Админ" },
  { value: "manager", label: "Менеджер" },
  { value: "operator", label: "Оператор" },
  { value: "master", label: "Мастер" },
  { value: "callcenter", label: "Call-центр" },
];

const ROLE_COLORS: Record<string, string> = {
  admin: "bg-red-100 text-red-700 ring-red-200",
  manager: "bg-blue-100 text-blue-700 ring-blue-200",
  operator: "bg-emerald-100 text-emerald-700 ring-emerald-200",
  master: "bg-amber-100 text-amber-700 ring-amber-200",
  callcenter: "bg-purple-100 text-purple-700 ring-purple-200",
};

const EMPTY_FORM = { name: "", email: "", phone: "", password: "", role: "operator" };

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState<User | null>(null);

  const load = useCallback(() => {
    api.adminUsers().then(setUsers).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  function resetForm() {
    setForm(EMPTY_FORM);
    setEditing(null);
    setShowForm(false);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setMsg(null);
    try {
      if (editing) {
        const patch: Record<string, unknown> = {
          name: form.name,
          phone: form.phone || null,
          role: form.role,
        };
        if (form.password) patch.password = form.password;
        await api.updateUser(editing.id, patch);
        setMsg("Пользователь обновлён");
      } else {
        await api.createUser({
          name: form.name,
          email: form.email,
          phone: form.phone || null,
          password: form.password,
          role: form.role,
        });
        setMsg("Пользователь создан");
      }
      resetForm();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    }
  }

  async function toggleActive(user: User) {
    setError(null);
    try {
      await api.updateUser(user.id, { active: !user.active });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    }
  }

  async function deactivate(user: User) {
    if (!confirm(`Отключить пользователя ${user.name}?`)) return;
    setError(null);
    try {
      await api.deactivateUser(user.id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    }
  }

  function startEdit(user: User) {
    setEditing(user);
    setForm({
      name: user.name,
      email: user.email,
      phone: user.phone ?? "",
      password: "",
      role: user.role,
    });
    setShowForm(true);
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Сотрудники</h1>
          <p className="mt-1 text-sm text-slate-500">{users.length} пользователей в системе</p>
        </div>
        <button onClick={() => { resetForm(); setShowForm((v) => !v); }}
          className="msb-btn-primary">
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
          </svg>
          Добавить
        </button>
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

      {/* Form */}
      {showForm && (
        <form onSubmit={submit} className="mb-6 msb-card-solid p-5 space-y-4 animate-slide-up">
          <h3 className="text-sm font-semibold text-slate-700">
            {editing ? "Редактирование" : "Новый сотрудник"}
          </h3>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <div>
              <label className="msb-label">ФИО *</label>
              <input className="msb-input" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div>
              <label className="msb-label">Роль</label>
              <select className="msb-input" value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {ROLES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="msb-label">Email *</label>
              <input className="msb-input" type="email" value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                disabled={!!editing} required />
            </div>
            <div>
              <label className="msb-label">Телефон</label>
              <input className="msb-input" value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
            <div>
              <label className="msb-label">{editing ? "Новый пароль" : "Пароль *"}</label>
              <input className="msb-input" type="password" value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={!editing} minLength={6}
                placeholder={editing ? "Оставьте пустым чтобы не менять" : "Минимум 6 символов"} />
            </div>
          </div>
          <div className="flex gap-3">
            <button className="msb-btn-primary">{editing ? "Сохранить" : "Создать"}</button>
            <button type="button" onClick={resetForm} className="msb-btn-secondary">Отмена</button>
          </div>
        </form>
      )}

      {/* Users table */}
      <div className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/50">
                <th className="px-5 py-4 text-xs font-semibold uppercase tracking-wider text-slate-500">Сотрудник</th>
                <th className="px-5 py-4 text-xs font-semibold uppercase tracking-wider text-slate-500">Роль</th>
                <th className="hidden sm:table-cell px-5 py-4 text-xs font-semibold uppercase tracking-wider text-slate-500">Телефон</th>
                <th className="px-5 py-4 text-xs font-semibold uppercase tracking-wider text-slate-500">Статус</th>
                <th className="px-5 py-4 text-xs font-semibold uppercase tracking-wider text-slate-500 text-right">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-msb-500 to-msb-700 text-xs font-bold text-white shadow-sm">
                        {u.name.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="font-medium text-slate-900">{u.name}</div>
                        <div className="text-xs text-slate-400">{u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <span className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ring-1 ${ROLE_COLORS[u.role] ?? "bg-slate-100 text-slate-600 ring-slate-200"}`}>
                      {ROLES.find((r) => r.value === u.role)?.label ?? u.role}
                    </span>
                  </td>
                  <td className="hidden sm:table-cell px-5 py-4 text-slate-600">{u.phone || "—"}</td>
                  <td className="px-5 py-4">
                    <button onClick={() => toggleActive(u)}
                      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                        u.active
                          ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-200"
                          : "bg-slate-100 text-slate-500 hover:bg-slate-200"
                      }`}>
                      {u.active ? "Активен" : "Отключён"}
                    </button>
                  </td>
                  <td className="px-5 py-4 text-right">
                    <button onClick={() => startEdit(u)}
                      className="text-sm font-medium text-msb-600 hover:text-msb-700 transition-colors mr-3">
                      Изменить
                    </button>
                    <button onClick={() => deactivate(u)}
                      className="text-sm font-medium text-red-500 hover:text-red-700 transition-colors">
                      Отключить
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}