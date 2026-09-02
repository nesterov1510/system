// Справочники и права по ролям (админ / оператор / мастер).
// Используются в навигации и на доске «Все ремонты».

// --- Классы техники, на которые делится приёмка и всё остальное.
export interface DeviceClass {
  value: string;
  label: string;
  icon: string;
}

export const DEVICE_CLASSES: DeviceClass[] = [
  { value: "Телевизоры", label: "Телевизоры", icon: "📺" },
  { value: "Компьютеры", label: "Компьютеры", icon: "🖥️" },
  { value: "Бытовая техника", label: "Бытовая техника", icon: "🧺" },
  { value: "Другое", label: "Другое", icon: "⚙️" },
];

// Старые значения device_type -> класс (маппинг для уже принятых ремонтов).
const LEGACY_CLASS: Record<string, string> = {
  ТВ: "Телевизоры",
  Монитор: "Компьютеры",
  "Компьютер": "Компьютеры",
  Ноутбук: "Компьютеры",
  Аудио: "Бытовая техника",
  "Бытовая": "Бытовая техника",
  Другое: "Другое",
};

export function normalizeClass(raw?: string | null): string {
  if (!raw) return "Другое";
  return LEGACY_CLASS[raw] ?? raw;
}

export function classIcon(raw?: string | null): string {
  const cls = DEVICE_CLASSES.find((c) => c.value === normalizeClass(raw));
  return cls?.icon ?? "⚙️";
}

// --- Права доступа по ролям.
const ROLE_ALL = "all";

const MAIN_NAV = ["/repairs", "/repairs/new", "/clients", "/callcenter", "/chat", "/dashboard", "/profile"] as const;
type Href = (typeof MAIN_NAV)[number] | string;

const ROLE_SCOPES: Record<string, Href[] | "all"> = {
  admin: ROLE_ALL,
  manager: ["/repairs", "/repairs/new", "/clients", "/callcenter", "/chat", "/dashboard", "/profile"],
  // Оператор — всё, кроме аналитики («Курс»/dashboard) и админ-разделов.
  operator: ["/repairs", "/repairs/new", "/clients", "/callcenter", "/chat", "/profile"],
  // Мастер — приёмка, свои ремонты, его чаты и свой профиль.
  master: ["/repairs", "/repairs/new", "/chat", "/profile"],
  callcenter: ["/repairs", "/clients", "/callcenter", "/chat", "/profile"],
};

export function canView(role?: string | null, href?: string): boolean {
  if (!role || !href) return false;
  const scope = ROLE_SCOPES[role];
  if (!scope) return false;
  if (scope === ROLE_ALL) return true;
  return (scope as string[]).includes(href);
}

export function isAdminRole(role?: string | null): boolean {
  return role === "admin";
}
