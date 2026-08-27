// Mirrors packages/shared/constants.json for the TypeScript frontend.
// (For API types, generate from OpenAPI via `openapi-typescript` — see apps/web.)

export const ROLES = [
  "admin",
  "manager",
  "operator",
  "master",
  "callcenter",
] as const;
export type Role = (typeof ROLES)[number];

export const REPAIR_STATUSES = [
  "Принято",
  "Диагностика",
  "Согласование",
  "Ожидание запчастей",
  "В ремонте",
  "Готово к выдаче",
  "Выдано",
  "Не забрано",
  "Архив",
  "Отказ",
] as const;
export type RepairStatus = (typeof REPAIR_STATUSES)[number];

export const DEVICE_TYPES = ["ТВ", "Монитор", "Аудио", "Другое"] as const;
export type DeviceType = (typeof DEVICE_TYPES)[number];

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Админ",
  manager: "Менеджер",
  operator: "Оператор",
  master: "Мастер",
  callcenter: "Call-центр",
};
