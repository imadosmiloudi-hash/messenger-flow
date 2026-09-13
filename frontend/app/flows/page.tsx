"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";

type Flow = {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  steps: unknown[];
};

export default function FlowsPage() {
  const [flows, setFlows] = useState<Flow[]>([]);
  const [error, setError] = useState("");
  const [name, setName] = useState("");

  async function load() {
    setFlows(await api<Flow[]>("/api/flows"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function createFlow() {
    if (!name.trim()) return;
    try {
      await api("/api/flows", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: "",
          steps: [{ step_type: "TEXT", content: "Hello", delay_seconds: 0 }],
        }),
      });
      setName("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }

  return (
    <AppShell title="Flows">
      {error && <div className="err-box">{error}</div>}
      <div className="card">
        <h2>New flow</h2>
        <input
          className="input"
          placeholder="Flow name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn" onClick={createFlow}>
          Create
        </button>
      </div>
      <div className="card" style={{ padding: 0 }}>
        {flows.map((f) => (
          <Link key={f.id} href={`/flows/${f.id}`} className="list-item">
            <strong>{f.name}</strong>
            <div className="muted">
              {f.steps?.length || 0} steps · {f.is_active ? "active" : "inactive"}
            </div>
          </Link>
        ))}
      </div>
    </AppShell>
  );
}
