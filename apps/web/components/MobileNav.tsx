"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { getStoredUser } from "@/lib/api";
import { canView } from "@/lib/catalog";

const ITEMS = [
  { href: "/repairs", label: "Все ремонты", icon: "📋" },
  { href: "/repairs/new", label: "Приёмка", icon: "➕" },
  { href: "/clients", label: "Клиенты", icon: "👥" },
  { href: "/chat", label: "Чат", icon: "💬" },
];

export default function MobileNav() {
  const pathname = usePathname();
  const user = getStoredUser();
  const active = (href: string) => href === "/repairs"
    ? pathname === "/repairs"
    : pathname.startsWith(href);

  const visible = ITEMS.filter((i) => canView(user?.role, i.href, user?.roles));

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200/80 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
      aria-label="Основная навигация"
    >
      <div className="grid grid-cols-4 px-1 py-1">
        {visible.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-xl px-1 py-1 transition-colors ${
              active(item.href) ? "text-msb-600" : "text-slate-500"
            }`}
            aria-current={active(item.href) ? "page" : undefined}
          >
            <span className="text-lg leading-none" aria-hidden="true">{item.icon}</span>
            <span className="text-[10px] font-semibold leading-tight">{item.label}</span>
            {active(item.href) && <span className="h-0.5 w-5 rounded-full bg-msb-600" />}
          </Link>
        ))}
      </div>
    </nav>
  );
}
