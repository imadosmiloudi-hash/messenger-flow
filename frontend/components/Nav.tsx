"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "Home", ico: "🏠" },
  { href: "/inbox", label: "Inbox", ico: "💬" },
  { href: "/flows", label: "Flows", ico: "📋" },
  { href: "/media", label: "Media", ico: "🖼" },
  { href: "/settings", label: "Settings", ico: "⚙️" },
];

export function BottomNav() {
  const path = usePathname();
  if (path === "/login") return null;
  return (
    <nav className="nav-bottom">
      {items.map((it) => (
        <Link
          key={it.href}
          href={it.href}
          className={path === it.href || (it.href !== "/" && path.startsWith(it.href)) ? "active" : ""}
        >
          <span className="ico">{it.ico}</span>
          {it.label}
        </Link>
      ))}
    </nav>
  );
}
