"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  api,
  clearSession,
  getStoredUser,
  getToken,
  type User,
} from "@/lib/api";
import { canView, isAdminRole } from "@/lib/catalog";
import { subscribeChat, connectChat, disconnectChat } from "@/lib/chatSocket";
import { playNotify, primeAudio } from "@/lib/sound";
import MobileNav from "@/components/MobileNav";

// role  -> какие страницы доступны. См. lib/catalog.ts (canView).
const NAV_ITEMS = [
  {
    group: "Основное",
    items: [
      { href: "/repairs", label: "Все ремонты", icon: "📋" },
      { href: "/repairs/new", label: "Приёмка", icon: "➕" },
      { href: "/clients", label: "Клиенты", icon: "👥" },
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
  const [chatUnread, setChatUnread] = useState(0);
  // Внутренние уведомления админам (напр. эскалация ошибки печати — item 4).
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifItems, setNotifItems] = useState<
    Array<{ id: string; title: string; body?: string | null; read_at?: string | null; created_at: string }>
  >([]);

  useEffect(() => {
    const u = getStoredUser();
    if (!u) {
      // QR на этикетке ведёт прямо в карточку. После входа возвращаем мастера
      // именно в отсканированный ремонт, а не на общий список.
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    setUser(u);
    setReady(true);
  }, [pathname, router]);

  const refreshUnread = useCallback(() => {
    api
      .chatUnreadTotal()
      .then((r) => setChatUnread(r.total))
      .catch(() => {});
  }, []);

  // Уведомления видны только тем, кто имеет роль admin (item 4: эскалация
  // ошибки печати главному разработчику через внутреннее уведомление).
  useEffect(() => {
    if (!ready || !user || !isAdminRole(user.role, user.roles)) return;
    const load = () => api.notifications().then(setNotifItems).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [ready, user]);

  const unreadNotifCount = notifItems.filter((n) => !n.read_at).length;

  async function openNotif(n: { id: string; read_at?: string | null }) {
    if (!n.read_at) {
      await api.markNotificationRead(n.id).catch(() => {});
      setNotifItems((prev) =>
        prev.map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)),
      );
    }
  }

  // Единый WebSocket на всё приложение: обновляем бейдж и звучим уведомлением,
  // когда приходит сообщение (напр. о назначении мастера на ремонт).
  useEffect(() => {
    if (!ready || !user || !canView(user.role, "/chat", user.roles)) return;
    const token = getToken();
    if (!token) return;
    connectChat(token);
    const unsub = subscribeChat((event) => {
      if (event?.type !== "chat.message") return;
      const authorId = event?.message?.author?.id;
      const isMine = authorId && authorId === user.id;
      if (isMine) return;
      // Если это сообщение в канал, который сейчас открыт у пользователя —
      // не звучим (он его уже видит), чат-страница сама помечает прочитанным.
      const active = (window as unknown as { __msbActiveChat?: string }).__msbActiveChat;
      const onScreen = active && active === event.channel_id;
      if (!onScreen) {
        playNotify();
      }
      // Лёгкая задержка — чтобы сервер успел записать сообщение.
      setTimeout(refreshUnread, 400);
    });
    refreshUnread();
    // Периодическая сверка как fallback.
    const t = setInterval(refreshUnread, 15000);
    // Слушаем ручное обновление от чат-страницы (после прочтения канала).
    const onUnreadRefresh = () => refreshUnread();
    window.addEventListener("msb:unread-refresh", onUnreadRefresh);
    return () => {
      unsub();
      clearInterval(t);
      window.removeEventListener("msb:unread-refresh", onUnreadRefresh);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, user?.id]);

  // Разблокируем аудио после первого клика по странице.
  useEffect(() => {
    const onFirst = () => primeAudio();
    window.addEventListener("pointerdown", onFirst, { once: true });
    return () => window.removeEventListener("pointerdown", onFirst);
  }, []);

  // На мобильных экранная клавиатура часто перекрывает поле, которое человек
  // заполняет (особенно у нижней части формы). Прокручиваем сфокусированное
  // поле в видимую область с запасом, когда клавиатура уже открылась.
  useEffect(() => {
    function onFocusIn(e: FocusEvent) {
      const el = e.target as HTMLElement | null;
      if (!el) return;
      const tag = el.tagName;
      if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") return;
      // Небольшая задержка — ждём анимацию появления клавиатуры на iOS/Android,
      // иначе scrollIntoView сработает до того, как вьюпорт уменьшится.
      window.setTimeout(() => {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 300);
    }
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, []);

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
                <span className="ml-2 text-xs text-slate-500"></span>
              </div>
            </Link>
          </div>

          {/* User area */}
          <div className="flex items-center gap-3">
            {isAdminRole(user.role, user.roles) && (
              <div className="relative">
                <button
                  onClick={() => setNotifOpen((v) => !v)}
                  className="msb-btn-ghost relative p-2 text-slate-500 hover:text-slate-700"
                  title="Уведомления"
                >
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                  </svg>
                  {unreadNotifCount > 0 && (
                    <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
                      {unreadNotifCount > 9 ? "9+" : unreadNotifCount}
                    </span>
                  )}
                </button>
                {notifOpen && (
                  <div className="absolute right-0 z-40 mt-2 w-80 rounded-2xl bg-white p-2 shadow-lg ring-1 ring-slate-200 animate-slide-up">
                    <p className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Уведомления
                    </p>
                    <div className="max-h-80 space-y-1 overflow-y-auto custom-scroll">
                      {notifItems.length === 0 && (
                        <p className="px-3 py-4 text-center text-sm text-slate-400">Пусто</p>
                      )}
                      {notifItems.map((n) => (
                        <button key={n.id} onClick={() => openNotif(n)}
                          className={`block w-full rounded-xl px-3 py-2.5 text-left text-sm transition-colors ${
                            n.read_at ? "text-slate-500 hover:bg-slate-50" : "bg-amber-50 text-slate-800 hover:bg-amber-100"}`}>
                          <div className="font-medium">{n.title}</div>
                          {n.body && <div className="mt-0.5 text-xs text-slate-500">{n.body}</div>}
                          <div className="mt-1 text-[10px] text-slate-400">
                            {new Date(n.created_at).toLocaleString("ru")}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            <Link href="/profile" title="Профиль"
              className="hidden items-center gap-2 sm:flex">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-msb-500 to-msb-700 text-xs font-bold text-white shadow-sm">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="text-right">
                <div className="text-sm font-medium text-slate-800">{user.name}</div>
                <div className="text-xs text-slate-500">{user.email}</div>
              </div>
            </Link>
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

      <div className="mx-auto flex min-w-0 max-w-7xl">
        {/* Desktop Sidebar */}
        <aside className="hidden shrink-0 lg:block lg:w-56 xl:w-64">
          <nav className="sticky top-16 space-y-6 overflow-y-auto px-4 py-6 lg:px-6" style={{ maxHeight: "calc(100vh - 4rem)" }}>
            {NAV_ITEMS.map((group) => {
              if (group.adminOnly && !isAdminRole(user.role, user.roles)) return null;
              return (
                <div key={group.group}>
                  <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
                    {group.group}
                  </div>
                  <div className="space-y-0.5">
                    {group.items.filter((item) => canView(user.role, item.href, user.roles)).map((item) => (
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
                        {item.href === "/chat" && chatUnread > 0 && (
                          <span className="ml-auto flex h-5 min-w-5 animate-pulse items-center justify-center rounded-full bg-red-500 px-1.5 text-[11px] font-bold text-white ring-2 ring-red-300">
                            {chatUnread > 99 ? "99+" : chatUnread}
                          </span>
                        )}
                        {isActive(item.href) && item.href !== "/chat" && (
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
              if (group.adminOnly && !isAdminRole(user.role, user.roles)) return null;
              return (
                <div key={group.group}>
                  <div className="mb-2 px-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
                    {group.group}
                  </div>
                  <div className="space-y-0.5">
                    {group.items.filter((item) => canView(user.role, item.href, user.roles)).map((item) => (
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
                        {item.href === "/chat" && chatUnread > 0 && (
                          <span className="ml-auto flex h-5 min-w-5 animate-pulse items-center justify-center rounded-full bg-red-500 px-1.5 text-[11px] font-bold text-white ring-2 ring-red-300">
                            {chatUnread > 99 ? "99+" : chatUnread}
                          </span>
                        )}
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
        <main className="min-h-[calc(100vh-4rem)] min-w-0 flex-1 px-3 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-4 sm:px-4 sm:pt-6 lg:px-8 lg:pb-6">
          <div className="mx-auto min-w-0 max-w-5xl animate-fade-in">
            {children}
          </div>
        </main>
      </div>

      <MobileNav />
    </div>
  );
}