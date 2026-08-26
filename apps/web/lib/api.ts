// Минимальный API-клиент. Токен хранится в localStorage (MVP);
// production-путь — httpOnly refresh cookie + тихий refresh.

// Пустая строка => относительные пути, Next.js проксирует /api и /media на backend
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

export interface Lookup {
  id: string;
  name: string;
  slug?: string;
  address?: string;
  city_id?: string;
}

export interface RepairEvent {
  id: string;
  type: string;
  actor_id?: string | null;
  data?: Record<string, unknown> | null;
  created_at: string;
}

export interface Photo {
  id: string;
  repair_id: string;
  caption?: string | null;
  created_at: string;
  url: string;
}

export interface PriceItem {
  id: string;
  device_type?: string | null;
  brand?: string | null;
  model_or_line?: string | null;
  fault?: string | null;
  city_id?: string | null;
  price_min?: number | null;
  price_max?: number | null;
  price_avg?: number | null;
  typical_days?: number | null;
  source?: string | null;
  active: boolean;
}

export interface PriceHint {
  price_min?: number | null;
  price_max?: number | null;
  typical_days_min?: number | null;
  typical_days_max?: number | null;
  n?: number | null;
}

export interface StatTile {
  group: string;
  n: number;
  threshold: number;
  avg_days?: number | null;
  median_days?: number | null;
  p90_days?: number | null;
  avg_price?: number | null;
  sla_pct?: number | null;
  message?: string | null;
}

export interface EtaPrediction {
  eta_days?: number | null;
  source?: string | null;
  confidence?: number | null;
  message?: string | null;
  n?: number | null;
}

export interface Repair {
  id: string;
  number: string;
  public_token: string;
  city_id: string;
  branch_id?: string | null;
  device_type: string;
  brand?: string | null;
  model?: string | null;
  serial?: string | null;
  complectation?: Record<string, unknown> | null;
  fault_client?: string | null;
  fault_master?: string | null;
  condition_notes?: string | null;
  status: string;
  client_name?: string | null;
  client_phone?: string | null;
  accepted_at: string;
  storage_until?: string | null;
  master_id?: string | null;
  eta_days?: number | null;
  eta_source?: string | null;
  price_min?: number | null;
  price_max?: number | null;
  price_final?: number | null;
  print_count: number;
  events: RepairEvent[];
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
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init.body && typeof init.body === "string") {
    headers["Content-Type"] = "application/json";
  }

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

  // Lookups (для формы приёмки — доступны всем ролям)
  cities: () => request<Lookup[]>("/api/lookups/cities"),
  branches: () => request<Lookup[]>("/api/lookups/branches"),
  masters: () => request<Lookup[]>("/api/lookups/masters"),
  complectationItems: () => request<Lookup[]>("/api/lookups/complectation-items"),

  // Chat
  channels: () => request<Channel[]>("/api/chat/channels"),
  messages: (channelId: string) =>
    request<Array<Record<string, unknown>>>(
      `/api/chat/channels/${channelId}/messages`,
    ),
  sendMessage: (channelId: string, text: string) =>
    request<Record<string, unknown>>(`/api/chat/channels/${channelId}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  // Repairs
  repairs: () => request<Repair[]>("/api/repairs"),
  repair: (id: string) => request<Repair>(`/api/repairs/${id}`),
  byNumber: (number: string) =>
    request<Repair>(`/api/repairs/by-number/${encodeURIComponent(number)}`),
  createRepair: (payload: Record<string, unknown>) =>
    request<Repair>("/api/repairs", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(payload),
    }),
  updateRepair: (id: string, payload: Record<string, unknown>) =>
    request<Repair>(`/api/repairs/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  comment: (id: string, message: string) =>
    request<Repair>(`/api/repairs/${id}/events`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  print: (repairId: string) =>
    request<{ job_id: string; status: string }>(
      `/api/repairs/${repairId}/print`,
      { method: "POST" },
    ),

  // Photos
  photos: (repairId: string) =>
    request<Photo[]>(`/api/repairs/${repairId}/photos`),
  uploadPhoto: (repairId: string, file: File, caption?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (caption) form.append("caption", caption);
    return request<Photo>(`/api/repairs/${repairId}/photos`, {
      method: "POST",
      body: form,
    });
  },

  // Call-center queue
  callcenterQueue: (kind: string) =>
    request<Repair[]>(`/api/callcenter/queue?kind=${kind}`),

  // Prices
  prices: (params: Record<string, string>) => {
    const qs = new URLSearchParams(params).toString();
    return request<PriceItem[]>(`/api/prices?${qs}`);
  },
  priceHint: (params: Record<string, string>) => {
    const qs = new URLSearchParams(params).toString();
    return request<{ hint: PriceHint | null; message?: string }>(
      `/api/prices/hint?${qs}`,
    );
  },

  // Stats + AI
  statsOverview: () =>
    request<{ total: number; active: number; overdue_storage: number }>(
      "/api/stats/overview",
    ),
  statsTiles: (params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request<StatTile[]>(`/api/stats/tiles?${qs}`);
  },
  predictEta: (payload: {
    device_type: string;
    brand?: string | null;
    fault?: string | null;
  }) =>
    request<EtaPrediction>("/api/ai/predict-eta", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  weeklySummary: () =>
    request<{
      accepted_week: number;
      ready_week: number;
      masters_week: Record<string, number>;
      note?: string | null;
    }>("/api/ai/weekly-summary", { method: "POST" }),

  // Print templates (admin)
  printTemplates: () =>
    request<
      Array<{
        id: string;
        name: string;
        is_default: boolean;
        body: Record<string, unknown>;
      }>
    >("/api/admin/print-templates"),
  printTemplatesMeta: () =>
    request<{ fields: string[]; default: Record<string, unknown> }>(
      "/api/admin/print-templates/meta",
    ),
  savePrintTemplate: (data: {
    id?: string;
    name?: string;
    body?: Record<string, unknown>;
    is_default?: boolean;
  }) =>
    request<Record<string, unknown>>(
      data.id ? `/api/admin/print-templates/${data.id}` : "/api/admin/print-templates",
      {
        method: data.id ? "PATCH" : "POST",
        body: JSON.stringify(data),
      },
    ),
  previewPrintTemplate: async (
    body: Record<string, unknown>,
    repairId?: string,
  ): Promise<Blob> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/api/admin/print-templates/preview`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ body, repair_id: repairId }),
    });
    if (!res.ok) throw new Error(`Ошибка превью: ${res.status}`);
    return res.blob();
  },
};

export function mediaUrl(path: string): string {
  return `${API_URL}${path}`;
}

// --- Public (no auth) ---
export interface PublicRepair {
  number: string;
  status: string;
  device_type: string;
  brand?: string | null;
  model?: string | null;
  complectation?: Record<string, unknown> | null;
  accepted_at: string;
  eta_days?: number | null;
  ready_at?: string | null;
  issued_at?: string | null;
  storage_until?: string | null;
  storage_text?: string | null;
  branch_name?: string | null;
  branch_phone?: string | null;
  city_stats?: {
    n: number;
    threshold: number;
    avg_days?: number | null;
    median_days?: number | null;
    avg_price?: number | null;
    message?: string | null;
  } | null;
}

export async function fetchPublicRepair(token: string): Promise<PublicRepair> {
  const res = await fetch(`${API_URL}/api/public/r/${encodeURIComponent(token)}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`,
    );
  }
  return res.json();
}
