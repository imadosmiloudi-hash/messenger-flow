"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";

type Step = {
  id: string;
  position: number;
  step_type: string;
  content: string | null;
  delay_seconds: number;
};

type Flow = {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  steps: Step[];
};

export default function FlowEditorPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [flow, setFlow] = useState<Flow | null>(null);
  const [error, setError] = useState("");
  const [stepType, setStepType] = useState("TEXT");
  const [content, setContent] = useState("");
  const [delay, setDelay] = useState(1);

  async function load() {
    setFlow(await api<Flow>(`/api/flows/${id}`));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [id]);

  async function addStep() {
    try {
      await api(`/api/flows/${id}/steps`, {
        method: "POST",
        body: JSON.stringify({
          step_type: stepType,
          content: stepType === "DELAY" ? null : content,
          delay_seconds: delay,
        }),
      });
      setContent("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  async function removeStep(stepId: string) {
    await api(`/api/flows/${id}/steps/${stepId}`, { method: "DELETE" });
    await load();
  }

  async function duplicate() {
    const copy = await api<Flow>(`/api/flows/${id}/duplicate`, { method: "POST" });
    router.push(`/flows/${copy.id}`);
  }

  async function saveMeta() {
    if (!flow) return;
    await api(`/api/flows/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name: flow.name, description: flow.description, is_active: flow.is_active }),
    });
    await load();
  }

  return (
    <AppShell title={flow?.name || "Flow"}>
      {error && <div className="err-box">{error}</div>}
      {flow && (
        <>
          <div className="card">
            <input
              className="input"
              value={flow.name}
              onChange={(e) => setFlow({ ...flow, name: e.target.value })}
            />
            <textarea
              className="input"
              rows={2}
              value={flow.description}
              onChange={(e) => setFlow({ ...flow, description: e.target.value })}
            />
            <label className="muted">
              <input
                type="checkbox"
                checked={flow.is_active}
                onChange={(e) => setFlow({ ...flow, is_active: e.target.checked })}
              />{" "}
              Active
            </label>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn secondary" onClick={saveMeta}>
                Save
              </button>
              <button className="btn secondary" onClick={duplicate}>
                Duplicate
              </button>
            </div>
          </div>

          <div className="card">
            <h2>Steps</h2>
            {flow.steps
              .slice()
              .sort((a, b) => a.position - b.position)
              .map((s) => (
                <div key={s.id} className="step-row">
                  <div style={{ flex: 1 }}>
                    <span className="badge">{s.step_type}</span>{" "}
                    <span className="muted">+{s.delay_seconds}s</span>
                    <div>{s.content || "—"}</div>
                  </div>
                  <button className="btn danger" style={{ width: "auto" }} onClick={() => removeStep(s.id)}>
                    Del
                  </button>
                </div>
              ))}
          </div>

          <div className="card">
            <h2>Add step</h2>
            <select className="input" value={stepType} onChange={(e) => setStepType(e.target.value)}>
              {["TEXT", "IMAGE", "AUDIO", "VIDEO", "DELAY"].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            {stepType !== "DELAY" && (
              <input
                className="input"
                placeholder={stepType === "TEXT" ? "Message text" : "Public HTTPS media URL"}
                value={content}
                onChange={(e) => setContent(e.target.value)}
              />
            )}
            <input
              className="input"
              type="number"
              min={0}
              value={delay}
              onChange={(e) => setDelay(Number(e.target.value))}
              placeholder="Delay seconds"
            />
            <button className="btn" onClick={addStep}>
              Add step
            </button>
          </div>
        </>
      )}
    </AppShell>
  );
}
