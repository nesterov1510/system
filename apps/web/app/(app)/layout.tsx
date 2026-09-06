"use client";

import { useCallback, useEffect, useState } from "react";
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
import SideDrawer from "@/components/SideDrawer";

const ROLE_LABELS: Record<string, string> = {
  admin: "Админ",
  manager: "Менеджер",
  operator: "Оператор",
  master: "Мастер",
  callcenter: "Call-центр",
};

const STATUS_BADGES: Record<string, string> = {
  admin: "bg-msb-600 text-white",
  manager: "bg-emerald-600 text-white",
  operator: "bg-cyan-600 text-white",
  master: "bg-amber-600 text-white",
  callcenter: "bg-purple-600 text-white",
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  // Меню открывается поверх страницы и НИКОГДА не сдвигает контент, поэтому
  // состояние всего одно: открыто/закрыто. Никакого «свёрнуто до иконок» —
  // именно оно раньше двигало таблицу при каждом клике.
  const [navOpen, setNavOpen] = useState(false);
  const [chatUnread, setChatUnread] = useState(0);
  // Внутренние уведомления админам (напр. эскалация ошибки печати).
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

  // Переход на другую страницу закрывает меню.
  useEffect(() => {
    setNavOpen(false);
    setNotifOpen(false);
  }, [pathname]);

  const refreshUnread = useCallback(() => {
    api
      .chatUnreadTotal()
      .then((r) => setChatUnread(r.total))
      .catch(() => {});
  }, []);

  // Уведомления видны только тем, кто имеет роль admin.
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
      if (authorId && authorId === user.id) return;
      // Если это сообщение в канал, который сейчас открыт, — не звучим
      // (пользователь его уже видит), чат-страница сама помечает прочитанным.
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
      disconnectChat();
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
  // заполняет. Прокручиваем сфокусированное поле в видимую область с запасом,
  // когда клавиатура уже открылась.
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
    if (href === "/repairs") return pathname === "/repairs";
    return pathname.startsWith(href);
  }

  const logout = useCallback(() => {
    clearSession();
    disconnectChat();
    router.replace("/login");
  }, [router]);

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
      <SideDrawer
        open={navOpen}
        user={user}
        chatUnread={chatUnread}
        isActive={isActive}
        onClose={() => setNavOpen(false)}
        onLogout={logout}
      />

      {/* Header */}
      <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/90 backdrop-blur-xl">
        <div className="flex h-16 items-center justify-between gap-2 px-3 sm:px-4 lg:px-6">
          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            {/* Кнопка меню видна на всех экранах: панель одна и та же,
                открывается поверх страницы и не смещает контент. */}
            <button
              onClick={() => setNavOpen((v) => !v)}
              className="msb-btn-ghost -ml-1 shrink-0 p-2 text-slate-600 hover:text-slate-900"
              aria-label={navOpen ? "Закрыть меню" : "Открыть меню"}
              aria-expanded={navOpen}
              aria-controls="msb-side-drawer"
              title="Меню"
            >
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                {navOpen ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                )}
              </svg>
            </button>

            <div className="flex min-w-0 items-center gap-2.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-msb-600 to-msb-800 text-sm font-extrabold text-white shadow-sm">
                MSB
              </span>
              <span className="hidden text-base font-bold text-slate-900 sm:block">MSB</span>
            </div>
          </div>

          {/* User area */}
          <div className="flex shrink-0 items-center gap-1 sm:gap-3">
            {isAdminRole(user.role, user.roles) && (
              <div className="relative">
                <button
                  onClick={() => setNotifOpen((v) => !v)}
                  className="msb-btn-ghost relative p-2 text-slate-500 hover:text-slate-700"
                  title="Уведомления"
                  aria-label="Уведомления"
                  aria-expanded={notifOpen}
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
                  <div className="animate-slide-up absolute right-0 z-40 mt-2 w-80 max-w-[calc(100vw-1.5rem)] rounded-2xl bg-white p-2 shadow-lg ring-1 ring-slate-200">
                    <p className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Уведомления
                    </p>
                    <div className="custom-scroll max-h-80 space-y-1 overflow-y-auto">
                      {notifItems.length === 0 && (
                        <p className="px-3 py-4 text-center text-sm text-slate-400">Пусто</p>
                      )}
                      {notifItems.map((n) => (
                        <button key={n.id} onClick={() => openNotif(n)}
                          className={`block w-full rounded-xl px-3 py-2.5 text-left text-sm transition-colors ${
                            n.read_at ? "text-slate-500 hover:bg-slate-50" : "bg-amber-50 text-slate-800 hover:bg-amber-100"}`}
                        >
                          <span className="block font-medium">{n.title}</span>
                          {n.body && <span className="mt-0.5 block text-xs text-slate-500">{n.body}</span>}
                          <span className="mt-1 block text-[10px] text-slate-400">
                            {new Date(n.created_at).toLocaleString("ru")}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            <button
              onClick={() => router.push("/profile")}
              title="Профиль"
              className="flex items-center gap-2 rounded-xl px-1 py-1 transition-colors hover:bg-slate-100 sm:px-2"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-msb-500 to-msb-700 text-xs font-bold text-white shadow-sm">
                {user.name.charAt(0).toUpperCase()}
              </span>
              <span className="hidden text-right lg:block">
                <span className="block max-w-[12rem] truncate text-sm font-medium text-slate-800">
                  {user.name}
                </span>
                <span className="block max-w-[12rem] truncate text-xs text-slate-500">
                  {user.email}
                </span>
              </span>
            </button>

            <span className={`hidden rounded-full px-2.5 py-0.5 text-xs font-semibold xl:inline-block ${STATUS_BADGES[user.role] ?? "bg-slate-100 text-slate-600"}`}>
              {ROLE_LABELS[user.role] ?? user.role}
            </span>

            <button
              onClick={logout}
              className="msb-btn-ghost p-2 text-slate-500 hover:text-red-600"
              title="Выйти"
              aria-label="Выйти"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* Контент занимает ВСЮ ширину всегда: меню накладывается поверх него,
          поэтому открытие/закрытие не вызывает ни малейшего сдвига. */}
      <main className="min-h-[calc(100vh-4rem)] min-w-0 px-3 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-4 sm:px-4 sm:pt-6 lg:px-6 lg:pb-6 xl:px-8">
        {/* Отдельные узкие формы (профиль, карточка ремонта) сами задают себе
            max-w на уровне страницы. */}
        <div className="animate-fade-in mx-auto min-w-0 max-w-[1400px]">{children}</div>
      </main>

      <MobileNav />
    </div>
  );
}
