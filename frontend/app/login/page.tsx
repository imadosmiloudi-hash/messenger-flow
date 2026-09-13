"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setTokens } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api<{ access_token: string; refresh_token: string }>(
        "/api/auth/login",
        { method: "POST", body: JSON.stringify({ email, password }) }
      );
      setTokens(data.access_token, data.refresh_token);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell" style={{ justifyContent: "center" }}>
      <main className="main">
        <div className="card">
          <h2>Messenger Flow Operator</h2>
          <p className="muted">
            Mobile PWA console. Native Messenger SEND FLOW button is not possible —
            use this operator app instead.
          </p>
          {error && <div className="err-box">{error}</div>}
          <form onSubmit={onSubmit}>
            <input
              className="input"
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
            />
            <input
              className="input"
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
            <button className="btn lg" type="submit" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
