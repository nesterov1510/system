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

const ROLE_LABELS: Record<string, string> = Object.fromEntries(
  ROLES.map((r) => [r.value, r.label]),
);

const ROLE_COLORS: Record<string, string> = {
  admin: "bg-red-100 text-red-700",
  manager: "bg-blue-100 text-blue-700",
  operator: "bg-green-100 text-green-700",
  master: "bg-amber-100 text-amber-700",
  callcenter: "bg-purple-100 text-purple-700",
};

const EMPTY_FORM = {
  name: "",
  email: "",
  phone: "",
  password: "",
  role: "operator",
};

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

  const input = "rounded-lg border border-gray-300 px-3 py-2 text-sm";

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Пользователи</h1>
        <button
          onClick={() => {
            resetForm();
            setShowForm((v) => !v);
          }}
          className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white"
        >
          + Пользователь
        </button>
      </div>

      {msg && (
        <p className="mb-3 rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">
          {msg}
        </p>
      )}
      {error && (
        <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
          {error}
        </p>
      )}

      {showForm && (
        <form
          onSubmit={submit}
          className="mb-4 space-y-3 rounded-2xl bg-white p-4 ring-1 ring-gray-200"
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">
                ФИО *
              </label>
              <input
                className={`${input} w-full`}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">
                Роль
              </label>
              <select
                className={`${input} w-full`}
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                {ROLES.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">
                Email *
              </label>
              <input
                className={`${input} w-full`}
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                disabled={!!editing}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">
                Телефон
              </label>
              <input
                className={`${input} w-full`}
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">
                {editing ? "Новый пароль (пусто = не менять)" : "Пароль *"}
              </label>
              <input
                className={`${input} w-full`}
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={!editing}
                minLength={6}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white">
              {editing ? "Сохранить" : "Создать"}
            </button>
            <button
              type="button"
              onClick={resetForm}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600"
            >
              Отмена
            </button>
          </div>
        </form>
      )}

      <div className="overflow-x-auto rounded-2xl bg-white ring-1 ring-gray-200">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-200 text-xs text-gray-500">
            <tr>
              <th className="px-4 py-3">Сотрудник</th>
              <th className="px-4 py-3">Роль</th>
              <th className="px-4 py-3">Телефон</th>
              <th className="px-4 py-3">Статус</th>
              <th className="px-4 py-3 text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-gray-100 last:border-0">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">{u.name}</div>
                  <div className="text-xs text-gray-400">{u.email}</div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      ROLE_COLORS[u.role] ?? "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {ROLE_LABELS[u.role] ?? u.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600">{u.phone || "—"}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => toggleActive(u)}
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      u.active
                        ? "bg-green-100 text-green-700"
                        : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {u.active ? "активен" : "отключён"}
                  </button>
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => startEdit(u)}
                    className="mr-2 text-sm text-blue-600 hover:underline"
                  >
                    изменить
                  </button>
                  <button
                    onClick={() => deactivate(u)}
                    className="text-sm text-red-500 hover:underline"
                  >
                    отключить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
