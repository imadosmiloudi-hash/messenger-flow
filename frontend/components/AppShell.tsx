"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { getToken } from "@/lib/api";
import { BottomNav } from "./Nav";

export function AppShell({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const path = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (path === "/login") {
      setReady(true);
      return;
    }
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [path, router]);

  if (!ready) {
    return (
      <div className="app-shell">
        <div className="main muted">Loading…</div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <h1>{title}</h1>
      </header>
      <main className="main">{children}</main>
      <BottomNav />
    </div>
  );
}
