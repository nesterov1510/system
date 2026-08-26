// Минимальный API-клиент. Токен хранится в localStorage (MVP);
// production-путь — httpOnly refresh cookie + тихий refresh.

// Пустая строка => относительные пути, Next.js проксирует /api на backend
// (см. rewrites в next.config.mjs). Для прямого подключения задайте
// NEXT_PUBLIC_API_URL=http://host:8000.
const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

export interface User {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  role: string;
  city_id?: string | null;
  branch_id?: string | null;
  active: boolean;
}

export interface Channel {
  id: string;
  slug: string;
  name: string;
  kind: string;
}

export interface Repair {
  id: string;
  number: string;
  public_token: string;
  device_type: string;
  brand?: string | null;
  model?: string | null;
  status: string;
  client_name?: string | null;
  client_phone?: string | null;
  fault_client?: string | null;
  accepted_at: string;
  storage_until?: string | null;
  master_id?: string | null;
  eta_days?: number | null;
  price_min?: number | null;
  price_max?: number | null;
  events: Array<{ id: string; type: string; data?: Record<string, unknown> | null; created_at: string }>;
}

const TOKEN_KEY = "remontflow_token";
const USER_KEY = "remontflow_user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string, user: User) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as User) : null;
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined") {
    clearSession();
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : JSON.stringify(body?.detail || body);
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; refresh_token: string; user: User }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
    ),
  me: () => request<User>("/api/auth/me"),
  channels: () => request<Channel[]>("/api/chat/channels"),
  messages: (channelId: string) =>
    request<Array<Record<string, unknown>>>(`/api/chat/channels/${channelId}/messages`),
  sendMessage: (channelId: string, text: string) =>
    request<Record<string, unknown>>(`/api/chat/channels/${channelId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  repairs: () => request<Repair[]>("/api/repairs"),
  cities: () => request<Array<{ id: string; name: string; slug: string }>>("/api/admin/cities"),
  createRepair: (payload: Record<string, unknown>) =>
    request<Repair>("/api/repairs", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
  print: (repairId: string) =>
    request<{ job_id: string; status: string }>(`/api/repairs/${repairId}/print`, {
      method: "POST",
    }),
};
