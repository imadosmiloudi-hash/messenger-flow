"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { api, API_URL, getToken } from "@/lib/api";

type Asset = {
  id: string;
  filename: string;
  media_type: string;
  public_url: string | null;
  size_bytes: number;
};

export default function MediaPage() {
  const [items, setItems] = useState<Asset[]>([]);
  const [error, setError] = useState("");

  async function load() {
    setItems(await api<Asset[]>("/api/media"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function onUpload(file: File | null) {
    if (!file) return;
    setError("");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`${API_URL}/api/media/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || "Upload failed");
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  return (
    <AppShell title="Media">
      {error && <div className="err-box">{error}</div>}
      <div className="card">
        <h2>Upload</h2>
        <p className="muted">
          Meta requires publicly reachable HTTPS URLs for attachments. Use ngrok/public
          base URL so Graph API can fetch files.
        </p>
        <input
          className="input"
          type="file"
          accept="image/*,audio/*,video/*"
          onChange={(e) => onUpload(e.target.files?.[0] || null)}
        />
      </div>
      <div className="card" style={{ padding: 0 }}>
        {items.map((a) => (
          <div key={a.id} className="list-item">
            <strong>{a.filename}</strong>
            <div className="muted">
              {a.media_type} · {Math.round(a.size_bytes / 1024)} KB
            </div>
            <div className="muted" style={{ wordBreak: "break-all" }}>
              {a.public_url}
            </div>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
