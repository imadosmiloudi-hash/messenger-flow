"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";

type Flow = { id: string; name: string; is_active: boolean };
type Detail = {
  conversation: {
    id: string;
    customer_id: string;
    customer?: { display_name: string; psid: string };
  };
  messages: Array<{ id: string; direction: string; text: string | null; created_at: string }>;
  active_execution: { id: string; status: string; flow_id: string } | null;
};

export default function ConversationPage() {
  const params = useParams();
  const id = params.id as string;
  const [detail, setDetail] = useState<Detail | null>(null);
  const [flows, setFlows] = useState<Flow[]>([]);
  const [flowId, setFlowId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const d = await api<Detail>(`/api/conversations/${id}`);
    setDetail(d);
    const f = await api<Flow[]>("/api/flows");
    setFlows(f.filter((x) => x.is_active));
    if (!flowId && f.length) setFlowId(f[0].id);
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const disabled = useMemo(() => {
    if (busy) return true;
    if (!flowId || !detail) return true;
    const st = detail.active_execution?.status;
    return st === "QUEUED" || st === "RUNNING";
  }, [busy, flowId, detail]);

  async function sendFlow() {
    if (!detail || !flowId) return;
    setBusy(true);
    setError("");
    try {
      const key = crypto.randomUUID();
      await api(`/api/flows/${flowId}/customers/${detail.conversation.customer_id}/send`, {
        method: "POST",
        headers: { "Idempotency-Key": key },
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title={detail?.conversation.customer?.display_name || "Conversation"}>
      {error && <div className="err-box">{error}</div>}
      <div className="card" style={{ minHeight: 240 }}>
        {detail?.messages.map((m) => (
          <div key={m.id} className={`msg ${m.direction === "IN" ? "in" : "out"}`}>
            {m.text || "(media)"}
          </div>
        ))}
        {!detail && <p className="muted">Loading…</p>}
      </div>

      <div className="card">
        <h2>SEND FLOW</h2>
        <p className="muted">
          Only this authenticated action starts sending. Webhook never auto-replies.
        </p>
        {detail?.active_execution && (
          <p>
            Active: <span className="badge warn">{detail.active_execution.status}</span>
          </p>
        )}
        <select
          className="input"
          value={flowId}
          onChange={(e) => setFlowId(e.target.value)}
          disabled={disabled && !!detail?.active_execution}
        >
          {flows.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <button className="btn lg" disabled={disabled} onClick={sendFlow}>
          {busy
            ? "Starting…"
            : detail?.active_execution
              ? "Flow running…"
              : "SEND FLOW"}
        </button>
      </div>
    </AppShell>
  );
}
