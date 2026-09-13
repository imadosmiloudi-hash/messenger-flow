"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { api, clearTokens } from "@/lib/api";
import { useRouter } from "next/navigation";

type PublicSettings = {
  app_name: string;
  meta_graph_api_version: string;
  meta_verify_token_hint: string;
  public_base_url: string;
  webhook_url: string;
  webhook_never_auto_replies: boolean;
};

type PageStatus = {
  page_id: string;
  name: string;
  is_connected: boolean;
  has_token: boolean;
  last_error: string | null;
} | null;

export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [page, setPage] = useState<PageStatus>(null);
  const [pageId, setPageId] = useState("");
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    setSettings(await api<PublicSettings>("/api/settings/public"));
    setPage(await api<PageStatus>("/api/pages/status"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function connect(e: FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      await api("/api/pages/connect", {
        method: "POST",
        body: JSON.stringify({ page_id: pageId, access_token: token, name }),
      });
      setToken("");
      setMsg("Page connected");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connect failed");
    }
  }

  async function disconnect() {
    await api("/api/pages/disconnect", { method: "POST" });
    await load();
  }

  function logout() {
    clearTokens();
    router.replace("/login");
  }

  return (
    <AppShell title="Settings">
      {error && <div className="err-box">{error}</div>}
      {msg && <div className="card" style={{ borderColor: "var(--success)" }}>{msg}</div>}

      <div className="card">
        <h2>Webhook (never auto-replies)</h2>
        {settings && (
          <>
            <p className="muted">Callback URL</p>
            <code style={{ wordBreak: "break-all" }}>{settings.webhook_url}</code>
            <p className="muted" style={{ marginTop: 8 }}>
              Verify token hint: {settings.meta_verify_token_hint}
            </p>
            <p className="muted">API version: {settings.meta_graph_api_version}</p>
            <p>
              <span className="badge ok">
                webhook_never_auto_replies = {String(settings.webhook_never_auto_replies)}
              </span>
            </p>
          </>
        )}
      </div>

      <div className="card">
        <h2>Connect Page (manual token)</h2>
        {page?.is_connected && (
          <p>
            <span className="badge ok">Connected</span> {page.name} ({page.page_id})
          </p>
        )}
        <form onSubmit={connect}>
          <input
            className="input"
            placeholder="Page ID"
            value={pageId}
            onChange={(e) => setPageId(e.target.value)}
            required
          />
          <input
            className="input"
            placeholder="Page name (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="input"
            placeholder="Page access token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
          <button className="btn" type="submit">
            Connect
          </button>
        </form>
        {page?.is_connected && (
          <button className="btn secondary" style={{ marginTop: 8 }} onClick={disconnect}>
            Disconnect
          </button>
        )}
      </div>

      <button className="btn danger" onClick={logout}>
        Log out
      </button>
    </AppShell>
  );
}
