"use client";

// Боковое меню (toolbar).
//
// Требования к поведению:
//  1. Панель прижата к САМОМУ ЛЕВОМУ краю экрана (fixed left-0), а не внутрь
//     центрированного контейнера — на широких мониторах слева больше нет дыры.
//  2. Открытие НЕ сдвигает контент: панель накладывается поверх страницы
//     (fixed + backdrop), основное содержимое всегда занимает всю ширину.
//
// Один и тот же компонент работает на десктопе и на телефоне — раньше их было
// два почти одинаковых блока в layout.tsx, которые расходились между собой.

import Link from "next/link";
import { useEffect } from "react";
import { canView, isAdminRole } from "@/lib/catalog";
import type { User } from "@/lib/api";

export interface NavItem {
  href: string;
  label: string;
  icon: string;
}

export interface NavGroup {
  group: string;
  adminOnly?: boolean;
  items: NavItem[];
}

export const NAV_ITEMS: NavGroup[] = [
  {
    group: "Основное",
    items: [
      { href: "/repairs", label: "Все ремонты", icon: "📋" },
      { href: "/repairs/new", label: "Приёмка", icon: "➕" },
      { href: "/clients", label: "Контакты", icon: "👥" },
      { href: "/callcenter", label: "Call-центр", icon: "📞" },
      { href: "/chat", label: "Чат", icon: "💬" },
      { href: "/dashboard", label: "Курс", icon: "📊" },
      { href: "/profile", label: "Профиль", icon: "👤" },
    ],
  },
  {
    group: "Админ",
    adminOnly: true,
    items: [
      { href: "/parts", label: "Склад", icon: "📦" },
      { href: "/admin/users", label: "Сотрудники", icon: "👥" },
      { href: "/admin/print-templates", label: "Шаблоны", icon: "🖨️" },
      { href: "/admin/printer", label: "Принтер", icon: "🖨️" },
      { href: "/admin/sms", label: "SMS", icon: "✉️" },
    ],
  },
];

const ROLE_LABELS: Record<string, string> = {
  admin: "Админ",
  manager: "Менеджер",
  operator: "Оператор",
  master: "Мастер",
  callcenter: "Call-центр",
};

interface Props {
  open: boolean;
  user: User;
  chatUnread: number;
  isActive: (href: string) => boolean;
  onClose: () => void;
  onLogout: () => void;
}

export default function SideDrawer({
  open,
  user,
  chatUnread,
  isActive,
  onClose,
  onLogout,
}: Props) {
  // Esc закрывает панель; прокрутка страницы блокируется, пока она открыта.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  return (
    <>
      {/* Подложка. Отдельный элемент, чтобы клик по ней закрывал меню.
          `aria-hidden` — под декоративным слоем не должно быть фокуса. */}
      <div
        onClick={onClose}
        aria-hidden="true"
        className={`fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-sm transition-opacity duration-200 ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      {/* Панель: fixed к левому краю ВЬЮПОРТА, во всю высоту, поверх контента.
          Открытие/закрытие — только transform, поэтому контент не смещается. */}
      <aside
        id="msb-side-drawer"
        aria-label="Основное меню"
        aria-hidden={!open}
        className={`fixed inset-y-0 left-0 z-50 flex w-[17rem] max-w-[85vw] transform flex-col border-r border-slate-200 bg-white shadow-2xl transition-transform duration-200 ease-out ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Шапка панели */}
        <div className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 px-4">
          <Link
            href="/repairs"
            onClick={onClose}
            className="flex items-center gap-2.5"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-msb-600 to-msb-800 text-sm font-extrabold text-white shadow-sm">
              MSB
            </span>
            <span className="text-base font-bold text-slate-900">MSB</span>
          </Link>
          <button
            onClick={onClose}
            className="msb-btn-ghost p-2 text-slate-500 hover:text-slate-700"
            aria-label="Закрыть меню"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Пункты меню */}
        <nav className="custom-scroll flex-1 space-y-6 overflow-y-auto px-3 py-5">
          {NAV_ITEMS.map((group) => {
            if (group.adminOnly && !isAdminRole(user.role, user.roles)) return null;
            const items = group.items.filter((item) =>
              canView(user.role, item.href, user.roles),
            );
            if (!items.length) return null;
            return (
              <div key={group.group}>
                <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
                  {group.group}
                </div>
                <div className="space-y-0.5">
                  {items.map((item) => {
                    const active = isActive(item.href);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        onClick={onClose}
                        aria-current={active ? "page" : undefined}
                        className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
                          active
                            ? "bg-gradient-to-r from-msb-50 to-msb-100/50 text-msb-700"
                            : "text-slate-600 hover:bg-slate-100 hover:text-slate-800"
                        }`}
                      >
                        <span className="relative text-base leading-none" aria-hidden="true">
                          {item.icon}
                          {active && item.href !== "/chat" && (
                            <span className="absolute -left-2 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-msb-600" />
                          )}
                        </span>
                        <span className="flex-1">{item.label}</span>
                        {item.href === "/chat" && chatUnread > 0 && (
                          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[11px] font-bold text-white ring-2 ring-red-300">
                            {chatUnread > 99 ? "99+" : chatUnread}
                          </span>
                        )}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        {/* Пользователь */}
        <div className="msb-divider flex shrink-0 items-center gap-3 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-msb-500 to-msb-700 text-xs font-bold text-white">
            {user.name.charAt(0).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-slate-800">
              {user.name}
            </span>
            <span className="block truncate text-xs text-slate-500">
              {ROLE_LABELS[user.role] ?? user.role}
            </span>
          </span>
          <button
            onClick={onLogout}
            className="msb-btn-ghost p-2 text-slate-500 hover:text-red-600"
            aria-label="Выйти"
            title="Выйти"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
          </button>
        </div>
      </aside>
    </>
  );
}
