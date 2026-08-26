"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearSession, getStoredUser, type User } from "@/lib/api";

const NAV = [
  { href: "/repairs", label: "Доска", icon: "🔧" },
  { href: "/repairs/new", label: "Приёмка", icon: "➕" },
  { href: "/callcenter", label: "Call-центр", icon: "📞" },
  { href: "/chat", label: "Чат", icon: "💬" },
];

const ADMIN_NAV = [
  { href: "/admin/print-templates", label: "Бланк", icon: "🖨" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const u = getStoredUser();
    if (!u) {
      router.replace("/login");
      return;
    }
    setUser(u);
    setReady(true);
  }, [router]);

  if (!ready || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center text-gray-400">
        Загрузка…
      </main>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-slate-900">RemontFlow</span>
            <span className="hidden rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600 sm:inline">
              {user.role}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">{user.name}</span>
            <button
              onClick={() => {
                clearSession();
                router.replace("/login");
              }}
              className="rounded-lg px-3 py-2 text-sm text-gray-500 hover:bg-gray-100"
            >
              Выйти
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6">{children}</main>

      <nav className="fixed inset-x-0 bottom-0 border-t border-gray-200 bg-white sm:hidden">
        <div className="mx-auto flex max-w-3xl">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={`flex flex-1 flex-col items-center gap-0.5 py-3 text-xs ${
                pathname === n.href ? "text-slate-900" : "text-gray-500"
              }`}
            >
              <span className="text-lg leading-none">{n.icon}</span>
              {n.label}
            </Link>
          ))}
          {user.role === "admin" &&
            ADMIN_NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={`flex flex-1 flex-col items-center gap-0.5 py-3 text-xs ${
                  pathname.startsWith(n.href) ? "text-slate-900" : "text-gray-500"
                }`}
              >
                <span className="text-lg leading-none">{n.icon}</span>
                {n.label}
              </Link>
            ))}
        </div>
      </nav>

      <div className="hidden sm:block">
        <div className="fixed left-0 top-14 flex flex-col gap-1 p-3">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={`rounded-lg px-3 py-2 text-sm ${
                pathname === n.href
                  ? "bg-slate-900 text-white"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              {n.icon} {n.label}
            </Link>
          ))}
          {user.role === "admin" && (
            <div className="mt-2 border-t border-gray-200 pt-2">
              <div className="px-3 py-1 text-xs uppercase text-gray-400">
                Админ
              </div>
              {ADMIN_NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className={`block rounded-lg px-3 py-2 text-sm ${
                    pathname.startsWith(n.href)
                      ? "bg-slate-900 text-white"
                      : "text-gray-600 hover:bg-gray-100"
                  }`}
                >
                  {n.icon} {n.label}
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
