"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";

type Conv = {
  id: string;
  last_message_preview: string;
  last_message_at: string | null;
  unread_count: number;
  customer?: { display_name: string; psid: string };
};

export default function InboxPage() {
  const [items, setItems] = useState<Conv[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Conv[]>("/api/inbox")
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <AppShell title="Inbox">
      {error && <div className="err-box">{error}</div>}
      <div className="card" style={{ padding: 0 }}>
        {items.length === 0 && <p className="muted" style={{ padding: 14 }}>No conversations</p>}
        {items.map((c) => (
          <Link key={c.id} href={`/inbox/${c.id}`} className="list-item">
            <div className="row">
              <div>
                <strong>{c.customer?.display_name || "Customer"}</strong>
                <div className="muted">{c.last_message_preview}</div>
              </div>
              {c.unread_count > 0 && <span className="badge warn">{c.unread_count}</span>}
            </div>
          </Link>
        ))}
      </div>
    </AppShell>
  );
}
