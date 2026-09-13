"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";

type Dashboard = {
  page_connected: boolean;
  page: { name: string; page_id: string; last_error?: string } | null;
  unread_messages: number;
  running_executions: number;
  queued_executions: number;
  recent_conversations: Array<{
    id: string;
    last_message_preview: string;
    unread_count: number;
  }>;
};

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Dashboard>("/api/dashboard")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <AppShell title="Dashboard">
      {error && <div className="err-box">{error}</div>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && (
        <>
          <div className="card">
            <h2>Page status</h2>
            {data.page_connected ? (
              <p>
                <span className="badge ok">Connected</span>{" "}
                {data.page?.name || data.page?.page_id}
              </p>
            ) : (
              <p>
                <span className="badge warn">Not connected</span>{" "}
                <Link href="/settings">Connect page →</Link>
              </p>
            )}
            {data.page?.last_error && (
              <p className="muted">Last error: {data.page.last_error}</p>
            )}
          </div>
          <div className="row">
            <div className="card">
              <h3>Unread</h3>
              <p style={{ fontSize: "1.5rem", margin: 0 }}>{data.unread_messages}</p>
            </div>
            <div className="card">
              <h3>Running</h3>
              <p style={{ fontSize: "1.5rem", margin: 0 }}>{data.running_executions}</p>
            </div>
            <div className="card">
              <h3>Queued</h3>
              <p style={{ fontSize: "1.5rem", margin: 0 }}>{data.queued_executions}</p>
            </div>
          </div>
          <div className="card">
            <h2>Recent conversations</h2>
            {data.recent_conversations.length === 0 && (
              <p className="muted">No messages yet. Webhook stores inbox only (no auto-reply).</p>
            )}
            {data.recent_conversations.map((c) => (
              <Link key={c.id} href={`/inbox/${c.id}`} className="list-item">
                <strong>{c.last_message_preview || "(empty)"}</strong>
                {c.unread_count > 0 && (
                  <span className="badge warn"> {c.unread_count}</span>
                )}
              </Link>
            ))}
          </div>
        </>
      )}
    </AppShell>
  );
}
