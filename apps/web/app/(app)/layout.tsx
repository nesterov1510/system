"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearSession, getStoredUser, type User } from "@/lib/api";

const NAV_ITEMS = [
  {
    group: "Основное",
    items: [
      { href: "/repairs", label: "Доска", icon: "📋" },
      { href: "/repairs/new", label: "Приёмка", icon: "➕" },
      { href: "/callcenter", label: "Call-центр", icon: "📞" },
      { href: "/chat", label: "Чат", icon: "💬" },
      { href: "/dashboard", label: "Курс", icon: "📊" },
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
    ],
  },
];

const MOBILE_NAV = [
  { href: "/repairs", label: "Доска", icon: "📋" },
  { href: "/repairs/new", label: "Приёмка", icon: "➕" },
  { href: "/callcenter", label: "Центр", icon: "📞" },
  { href: "/chat", label: "Чат", icon: "💬" },
  { href: "/dashboard", label: "Курс", icon: "📊" },
];

const STATUS_BADGES: Record<string, string> = {
  admin: "bg-msb-600 text-white",
  manager: "bg-emerald-600 text-white",
  operator: "bg-cyan-600 text-white",
  master: "bg-amber-600 text-white",
  callcenter: "bg-purple-600 text-white",
};

const ROLE_LABELS: Record<string, string> = {
  admin: "Админ",
  manager: "Менеджер",
  operator: "Оператор",
  master: "Мастер",
  callcenter: "Call-центр",
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const u = getStoredUser();
    if (!u) {
      router.replace("/login");
      return;
    }
    setUser(u);
    setReady(true);
  }, [router]);

  function isActive(href: string) {
    if (href === "/repairs" && pathname === "/repairs") return true;
    if (href !== "/repairs" && pathname.startsWith(href)) return true;
    return false;
  }

  if (!ready || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-blue-50">
        <div className="flex flex-col items-center gap-3 text-slate-400">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-msb-500 border-t-transparent" />
          <span className="text-sm font-medium">Загрузка MSB…</span>
        </div>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50/30">
      {/* Desktop Header */}
      <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/90 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 lg:px-8">
          <div className="flex items-center gap-4">
            {/* Mobile menu toggle */}
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="lg:hidden msb-btn-ghost p-2"
              aria-label="Меню"
            >
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                {sidebarOpen ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                )}
              </svg>
            </button>

            {/* Logo */}
            <Link href="/repairs" className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-msb-600 to-msb-800 shadow-sm">
                <span className="text-sm font-extrabold text-white">MSB</span>
              </div>
              <div className="hidden sm:block">
                <span className="text-base font-bold text-slate-900">MSB</span>
                <span className="ml-2 text-xs text-slate-500">Мастер Сервис Бюро</span>
              </div>
            </Link>
          </div>

          {/* User area */}
          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 sm:flex">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-msb-500 to-msb-700 text-xs font-bold text-white shadow-sm">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="text-right">
                <div className="text-sm font-medium text-slate-800">{user.name}</div>
                <div className="text-xs text-slate-500">{user.email}</div>
              </div>
            </div>
            <span className={`hidden rounded-full px-2.5 py-0.5 text-xs font-semibold sm:inline-block ${STATUS_BADGES[user.role] ?? "bg-slate-100 text-slate-600"}`}>
              {ROLE_LABELS[user.role] ?? user.role}
            </span>
            <button
              onClick={() => {
                clearSession();
                router.replace("/login");
              }}
              className="msb-btn-ghost text-sm text-slate-500 hover:text-red-600"
              title="Выйти"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-7xl">
        {/* Desktop Sidebar */}
        <aside className="hidden shrink-0 lg:block lg:w-56 xl:w-64">
          <nav className="sticky top-16 space-y-6 overflow-y-auto px-4 py-6 lg:px-6" style={{ maxHeight: "calc(100vh - 4rem)" }}>
            {NAV_ITEMS.map((group) => {
              if (group.adminOnly && user.role !== "admin") return null;
              return (
                <div key={group.group}>
                  <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
                    {group.group}
                  </div>
                  <div className="space-y-0.5">
                    {group.items.map((item) => (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
                          isActive(item.href)
                            ? "bg-gradient-to-r from-msb-50 to-msb-100/50 text-msb-700 shadow-sm"
                            : "text-slate-600 hover:bg-slate-100 hover:text-slate-800"
                        }`}
                      >
                        <span className="text-base leading-none">{item.icon}</span>
                        <span>{item.label}</span>
                        {isActive(item.href) && (
                          <span className="ml-auto h-1.5 w-1.5 rounded-full bg-msb-600" />
                        )}
                      </Link>
                    ))}
                  </div>
                </div>
              );
            })}
          </nav>
        </aside>

        {/* Mobile Sidebar Overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-slate-900/30 backdrop-blur-sm lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Mobile Sidebar */}
        <aside
          className={`fixed inset-y-0 left-0 z-30 w-72 transform border-r border-slate-200 bg-white/95 backdrop-blur-xl transition-transform duration-300 lg:hidden ${
            sidebarOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex h-16 items-center justify-between border-b border-slate-200 px-4">
            <Link href="/repairs" className="flex items-center gap-2.5" onClick={() => setSidebarOpen(false)}>
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-msb-600 to-msb-800 shadow-sm">
                <span className="text-sm font-extrabold text-white">MSB</span>
              </div>
              <span className="text-base font-bold text-slate-900">MSB</span>
            </Link>
            <button
              onClick={() => setSidebarOpen(false)}
              className="msb-btn-ghost p-2"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <nav className="space-y-6 overflow-y-auto px-4 py-6" style={{ maxHeight: "calc(100vh - 4rem)" }}>
            {NAV_ITEMS.map((group) => {
              if (group.adminOnly && user.role !== "admin") return null;
              return (
                <div key={group.group}>
                  <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
                    {group.group}
                  </div>
                  <div className="space-y-0.5">
                    {group.items.map((item) => (
                      <Link
                        key={item.href}
                        href={item.href}
                        onClick={() => setSidebarOpen(false)}
                        className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
                          isActive(item.href)
                            ? "bg-gradient-to-r from-msb-50 to-msb-100/50 text-msb-700"
                            : "text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        <span className="text-base leading-none">{item.icon}</span>
                        <span>{item.label}</span>
                      </Link>
                    ))}
                  </div>
                </div>
              );
            })}

            {/* User info in mobile sidebar */}
            <div className="msb-divider pt-4" />
            <div className="flex items-center gap-3 px-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-msb-500 to-msb-700 text-xs font-bold text-white">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="flex-1">
                <div className="text-sm font-medium text-slate-800">{user.name}</div>
                <div className="text-xs text-slate-500">{ROLE_LABELS[user.role] ?? user.role}</div>
              </div>
              <button
                onClick={() => {
                  clearSession();
                  router.replace("/login");
                }}
                className="msb-btn-ghost p-2 text-red-500"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            </div>
          </nav>
        </aside>

        {/* Main Content */}
        <main className="min-h-[calc(100vh-4rem)] flex-1 px-4 pb-24 pt-6 lg:px-8 lg:pb-6">
          <div className="mx-auto max-w-5xl animate-fade-in">
            {children}
          </div>
        </main>
      </div>

      {/* Mobile Bottom Nav */}
      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200/70 bg-white/95 backdrop-blur-xl lg:hidden">
        <div className="flex items-center justify-around px-2 py-1">
          {MOBILE_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`flex flex-col items-center gap-0.5 rounded-xl px-3 py-2 transition-colors duration-200 ${
                isActive(item.href) ? "text-msb-600" : "text-slate-500"
              }`}
            >
              <span className="text-xl leading-none">{item.icon}</span>
              <span className="text-[10px] font-medium leading-tight">{item.label}</span>
              {isActive(item.href) && (
                <span className="h-0.5 w-4 rounded-full bg-msb-600" />
              )}
            </Link>
          ))}
        </div>
      </nav>
    </div>
  );
}