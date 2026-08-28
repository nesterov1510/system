// MSB — минимальный API-клиент. Токен хранится в localStorage (MVP);
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

export interface Part {
  id: string;
  name: string;
  sku?: string | null;
  category?: string | null;
  stock_qty: number;
  min_stock: number;
  cost_price?: number | null;
  sell_price?: number | null;
  supplier?: string | null;
  active: boolean;
}

export interface RepairPart {
  id: string;
  part_id: string;
  part_name: string;
  sku?: string | null;
  qty: number;
  price?: number | null;
}

export interface Payment {
  id: string;
  repair_id: string;
  amount: number;
  method: string;
  operator_id?: string | null;
  paid_at: string;
}

// Валюта: туркменский манат (TMT). Символ — «ман.».
export const CURRENCY = { code: "TMT", symbol: "ман." } as const;

export function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${Math.round(n).toLocaleString("ru")} ${CURRENCY.symbol}`;
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
  cost_amount?: number | null;
  paid: boolean;
  print_count: number;
  master_name?: string | null;
  events: RepairEvent[];
}

const TOKEN_KEY = "msb_token";
const USER_KEY = "msb_user";

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

  // Clients
  lookupClient: (phone: string) =>
    request<{
      found: boolean;
      phone?: string;
      phone_norm?: string;
      multiple?: boolean;
      candidates?: Array<{ id: string; full_name: string; phone: string; repairs_count: number }>;
      client?: { id: string; full_name: string; phone: string };
      repairs?: Array<{
        id: string; number: string; status: string;
        device_type: string; brand?: string | null; model?: string | null;
        accepted_at: string | null;
        price_final?: number | null;
        paid: boolean;
      }>;
      repairs_count?: number;
    }>(`/api/repairs/clients/lookup?phone=${encodeURIComponent(phone)}`),
  listClients: (q?: string) => {
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    return request<Array<{
      id: string; full_name: string; phone: string; repairs_count: number;
    }>>(`/api/repairs/clients/list${qs}`);
  },
  clientRepairs: (clientId: string) =>
    request<Repair[]>(`/api/repairs/clients/${clientId}/repairs`),
  createRepair: (payload: Record<string, unknown>) =>
    request<Repair>("/api/repairs", {
      method: "POST",
      headers: { "Idempotency-Key": uuid() },
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
    request<{ job_id: string; status: string; pdf_base64: string }>(
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

  // Parts (склад)
  parts: (params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request<Part[]>(`/api/parts?${qs}`);
  },
  partCategories: () => request<string[]>("/api/parts/categories"),
  createPart: (payload: Record<string, unknown>) =>
    request<Part>("/api/parts", { method: "POST", body: JSON.stringify(payload) }),
  updatePart: (id: string, payload: Record<string, unknown>) =>
    request<Part>(`/api/parts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  repairParts: (repairId: string) =>
    request<RepairPart[]>(`/api/repairs/${repairId}/parts`),
  addRepairPart: (repairId: string, partId: string, qty: number) =>
    request<RepairPart>(`/api/repairs/${repairId}/parts`, {
      method: "POST",
      body: JSON.stringify({ part_id: partId, qty }),
    }),
  removeRepairPart: (repairId: string, rpId: string) =>
    request<{ ok: boolean }>(`/api/repairs/${repairId}/parts/${rpId}`, {
      method: "DELETE",
    }),

  // Payments (касса)
  payments: (repairId: string) =>
    request<Payment[]>(`/api/repairs/${repairId}/payments`),
  addPayment: (repairId: string, amount: number, method: string) =>
    request<Payment>(`/api/repairs/${repairId}/payments`, {
      method: "POST",
      body: JSON.stringify({ amount, method }),
    }),
  deletePayment: (paymentId: string) =>
    request<{ ok: boolean }>(`/api/payments/${paymentId}`, { method: "DELETE" }),

  // Stats + AI
  statsOverview: () =>
    request<{
      total: number;
      active: number;
      overdue_storage: number;
      low_stock: number;
      revenue: number;
      revenue_30d: number;
      finished_count: number;
      finished_revenue: number;
      finished_cost: number;
      profit: number;
    }>("/api/stats/overview"),
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

  // Admin: users
  adminUsers: () => request<User[]>("/api/admin/users"),
  createUser: (payload: Record<string, unknown>) =>
    request<User>("/api/admin/users", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateUser: (id: string, payload: Record<string, unknown>) =>
    request<User>(`/api/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deactivateUser: (id: string) =>
    request<{ ok: boolean }>(`/api/admin/users/${id}`, { method: "DELETE" }),

  // Printer config (admin)
  getPrinter: () =>
    request<{
      printer: { ip: string; port: number; mode: string; name: string };
      recent_jobs: Array<{
        id: string;
        status: string;
        error?: string | null;
        created_at: string;
      }>;
    }>("/api/admin/printer"),
  savePrinter: (payload: {
    ip: string;
    port: number;
    mode: string;
    name: string;
  }) =>
    request<{ printer: Record<string, unknown> }>("/api/admin/printer", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  testPrint: () =>
    request<{ job_id: string; status: string }>("/api/admin/printer/test", {
      method: "POST",
    }),
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

// UUID для Idempotency-Key. `crypto.randomUUID()` доступен только в HTTPS/localhost,
// а на http://192.168.x.x:3000 его нет — поэтому свой генератор (работает везде).
export function uuid(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Скачать PDF-бланк из base64 (запасной вариант, если print-agent не работает).
export function downloadPdfBase64(pdfBase64: string, filename: string) {
  const bin = atob(pdfBase64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
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
