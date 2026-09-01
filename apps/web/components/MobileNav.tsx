"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { getStoredUser } from "@/lib/api";

const ALL_ITEMS = [
  { href: "/repairs", label: "Ремонты", icon: "📋", roles: ["admin", "operator", "master"] },
  { href: "/repairs/new", label: "Приёмка", icon: "➕", roles: ["admin", "operator", "master"] },
  { href: "/clients", label: "Клиенты", icon: "👥", roles: ["admin", "operator"] },
  { href: "/chat", label: "Чат", icon: "💬", roles: ["admin", "operator", "master"] },
];

export default function MobileNav() {
  const pathname = usePathname();
  const [allowed, setAllowed] = useState<string[]>(ALL_ITEMS.map((i) => i.href));

  useEffect(() => {
    const u = getStoredUser();
    const role = u?.role;
    if (role) {
      setAllowed(ALL_ITEMS.filter((i) => i.roles.includes(role)).map((i) => i.href));
    }
  }, [pathname]);

  const items = ALL_ITEMS.filter((i) => allowed.includes(i.href));
  const active = (href: string) =>
    href === "/repairs" ? pathname === "/repairs" : pathname.startsWith(href);

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-200/80 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
      aria-label="Основная навигация"
    >
      <div className="grid px-1 py-1" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
        {items.map((item) => (
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
