/* Messenger Flow Operator — static SPA (same-origin API) */
(function () {
  "use strict";

  const TOKEN_KEY = "access_token";
  const REFRESH_KEY = "refresh_token";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }
  function setTokens(access, refresh) {
    localStorage.setItem(TOKEN_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  }
  function clearTokens() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (!headers.has("Content-Type") && !(options.body instanceof FormData) && options.body) {
      headers.set("Content-Type", "application/json");
    }
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);

    const res = await fetch(path, { ...options, headers });
    if (res.status === 401) {
      clearTokens();
      if (!location.pathname.startsWith("/login")) {
        navigate("/login");
      }
      throw new Error("Unauthorized — please log in");
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = j.detail ?? JSON.stringify(j);
      } catch (_) { /* ignore */ }
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (res.status === 204) return undefined;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return undefined;
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtTime(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch (_) {
      return iso;
    }
  }

  function statusBadge(st) {
    if (!st) return "";
    const cls = st === "COMPLETED" ? "ok" : st === "FAILED" || st === "CANCELLED" ? "err" : "warn";
    return `<span class="badge ${cls}">${esc(st)}</span>`;
  }

  function effectiveMediaIds(s) {
    if (s && Array.isArray(s.media_asset_ids) && s.media_asset_ids.length) return s.media_asset_ids;
    if (s && s.media_asset_id) return [s.media_asset_id];
    return [];
  }

  function mediaCountLabel(s) {
    const n = effectiveMediaIds(s).length;
    if (!n) return "";
    const map = { IMAGE: ["image", "images"], AUDIO: ["audio", "audios"], VIDEO: ["video", "videos"] };
    const pair = map[s.step_type] || ["file", "files"];
    const word = n === 1 ? pair[0] : pair[1];
    return `<span class="badge ok">📎 ${n} ${word}</span>`;
  }

  function isMediaType(t) {
    return t === "IMAGE" || t === "AUDIO" || t === "VIDEO";
  }

  function acceptFor(t) {
    if (t === "IMAGE") return "image/*";
    if (t === "AUDIO") return "audio/*";
    if (t === "VIDEO") return "video/*";
    return "";
  }

  function inboxItemHtml(c) {
    const name = c.customer?.display_name || c.customer?.psid || "Customer";
    return `
      <a href="/inbox/${esc(c.id)}" data-link class="list-item">
        <strong>${esc(name)} ${c.unread_count > 0 ? `<span class="badge warn">${c.unread_count}</span>` : ""}</strong>
        <div class="meta">${esc(c.last_message_preview || "")} · ${fmtTime(c.last_message_at)}</div>
      </a>`;
  }

  function bindLocalLinks(scope) {
    (scope || document).querySelectorAll("[data-link]").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        navigate(a.getAttribute("href"));
      });
    });
  }

  function attachMediaPicker({ fileEl, chipsEl, statusEl, typeEl, initial }) {
    const MAX = 50;
    let items = (initial || []).slice(0, MAX);
    let uploading = false;

    function renderChips() {
      if (!chipsEl) return;
      chipsEl.innerHTML = items.map((m, i) => {
        const isImg = (m.media_type === "image" || (typeEl && typeEl.value === "IMAGE")) && m.public_url;
        const icon = m.media_type === "audio" ? "♪" : m.media_type === "video" ? "▶" : "📎";
        return `<div class="media-chip" data-i="${i}">
          ${isImg ? `<img src="${esc(m.public_url)}" alt="">` : `<span class="media-chip-icon">${icon}</span>`}
          <span class="media-chip-name">${esc(m.filename || (m.id || "").slice(0, 8))}</span>
          <button type="button" class="media-chip-x" data-i="${i}" aria-label="Remove">×</button>
        </div>`;
      }).join("");
      chipsEl.querySelectorAll(".media-chip-x").forEach((btn) => {
        btn.addEventListener("click", () => {
          items.splice(Number(btn.dataset.i), 1);
          renderChips();
          updateStatus();
        });
      });
    }

    function updateStatus() {
      if (statusEl) statusEl.textContent = items.length ? `${items.length} / ${MAX} attached` : "";
    }

    async function uploadFiles(fileList) {
      const files = Array.from(fileList || []);
      const room = MAX - items.length;
      const batch = files.slice(0, room);
      if (!batch.length) {
        if (statusEl) statusEl.textContent = items.length >= MAX ? `Max ${MAX} files per step` : "";
        return;
      }
      uploading = true;
      for (let i = 0; i < batch.length; i++) {
        const file = batch[i];
        if (statusEl) statusEl.textContent = `Uploading ${i + 1}/${batch.length}: ${file.name}`;
        try {
          const fd = new FormData();
          fd.append("file", file);
          const asset = await api("/api/media/upload", { method: "POST", body: fd });
          items.push({
            id: asset.id,
            filename: asset.filename,
            public_url: asset.public_url,
            media_type: asset.media_type,
          });
          renderChips();
        } catch (e) {
          if (statusEl) statusEl.textContent = e.message || "Upload failed";
        }
      }
      uploading = false;
      updateStatus();
    }

    fileEl?.addEventListener("change", async () => {
      await uploadFiles(fileEl.files);
      if (fileEl) fileEl.value = "";
    });

    renderChips();
    updateStatus();
    return {
      getIds: () => items.map((m) => m.id),
      isUploading: () => uploading,
      clear() { items = []; renderChips(); updateStatus(); },
    };
  }

  /* ---------- Router ---------- */
  const root = document.getElementById("app");
  let state = { title: "Operator", showNav: true, showBack: false, backTo: "/" };

  function parseRoute() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    const parts = path.split("/").filter(Boolean);
    if (path === "/login") return { name: "login" };
    if (path === "/" || path === "/dashboard") return { name: "dashboard" };
    if (path === "/inbox") return { name: "inbox" };
    if (parts[0] === "inbox" && parts[1]) return { name: "conversation", id: parts[1] };
    if (path === "/flows") return { name: "flows" };
    if (parts[0] === "flows" && parts[1]) return { name: "flow", id: parts[1] };
    if (path === "/settings") return { name: "settings" };
    return { name: "dashboard" };
  }

  function navigate(path, replace) {
    if (replace) history.replaceState({}, "", path);
    else history.pushState({}, "", path);
    render();
  }

  window.addEventListener("popstate", () => render());

  function shell(inner, opts = {}) {
    const title = opts.title || "Operator";
    const showNav = opts.showNav !== false;
    const showBack = !!opts.showBack;
    const backTo = opts.backTo || "/";
    const route = parseRoute().name;
    const navActive = (n) => (route === n || (n === "dashboard" && route === "dashboard") ? "active" : "");

    if (!showNav) {
      return `<div class="login-wrap">${inner}</div>`;
    }

    return `
      <div class="app-shell">
        <header class="topbar">
          <div style="display:flex;align-items:center;gap:4px;min-width:0;flex:1">
            ${showBack ? `<button type="button" class="back" data-nav="${esc(backTo)}">←</button>` : ""}
            <h1>${esc(title)}</h1>
          </div>
        </header>
        <main class="main">${inner}</main>
        <nav class="nav-bottom">
          <a href="/" data-link class="${navActive("dashboard")}"><span class="ico">⌂</span>Home</a>
          <a href="/inbox" data-link class="${route === "inbox" || route === "conversation" ? "active" : ""}"><span class="ico">✉</span>Inbox</a>
          <a href="/flows" data-link class="${route === "flows" || route === "flow" ? "active" : ""}"><span class="ico">⟳</span>Flows</a>
          <a href="/settings" data-link class="${navActive("settings")}"><span class="ico">⚙</span>Settings</a>
        </nav>
      </div>`;
  }

  /* ---------- Views ---------- */
  async function viewLogin() {
    if (getToken()) {
      navigate("/", true);
      return shell("<p class='muted'>Redirecting…</p>");
    }
    return shell(
      `
      <div class="brand">
        <h1>Messenger Flow</h1>
        <p class="muted">Operator console · official Meta Graph API</p>
      </div>
      <div class="card">
        <form id="login-form">
          <input class="input" type="email" name="email" placeholder="Email" required autocomplete="username" />
          <input class="input" type="password" name="password" placeholder="Password" required autocomplete="current-password" />
          <div id="login-error" class="err-box hidden"></div>
          <button class="btn lg" type="submit">Log in</button>
        </form>
      </div>
      `,
      { showNav: false }
    );
  }

  function bindLogin() {
    const form = document.getElementById("login-form");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errEl = document.getElementById("login-error");
      errEl.classList.add("hidden");
      const fd = new FormData(form);
      try {
        const data = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({
            email: String(fd.get("email") || "").trim(),
            password: String(fd.get("password") || ""),
          }),
        });
        setTokens(data.access_token, data.refresh_token);
        navigate("/");
      } catch (err) {
        errEl.textContent = err.message || "Login failed";
        errEl.classList.remove("hidden");
      }
    });
  }

  async function viewDashboard() {
    let data = null;
    let error = "";
    try {
      data = await api("/api/dashboard");
    } catch (e) {
      error = e.message;
    }
    const page = data?.page;
    const recent = data?.recent_conversations || [];
    const inner = `
      ${error ? `<div class="err-box">${esc(error)}</div>` : ""}
      ${!data && !error ? `<p class="muted">Loading…</p>` : ""}
      ${data ? `
        <div class="card">
          <h2>Page status</h2>
          ${data.page_connected
            ? `<p><span class="badge ok">Connected</span> ${esc(page?.name || page?.page_id || "")}</p>`
            : `<p><span class="badge warn">Not connected</span> <a href="/settings" data-link>Connect page →</a></p>`}
          ${page?.last_error ? `<p class="muted">Last error: ${esc(page.last_error)}</p>` : ""}
        </div>
        <div class="row">
          <div class="card"><h3>Unread</h3><p style="font-size:1.5rem;margin:0">${data.unread_messages}</p></div>
          <div class="card"><h3>Running</h3><p style="font-size:1.5rem;margin:0">${data.running_executions}</p></div>
          <div class="card"><h3>Queued</h3><p style="font-size:1.5rem;margin:0">${data.queued_executions}</p></div>
        </div>
        <div class="card">
          <h2>Recent conversations</h2>
          ${recent.length === 0
            ? `<p class="muted">No messages yet. Webhook stores inbox only (no auto-reply).</p>`
            : recent.map((c) => `
                <a href="/inbox/${esc(c.id)}" data-link class="list-item">
                  <strong>${esc(c.last_message_preview || "(empty)")}</strong>
                  ${c.unread_count > 0 ? `<span class="badge warn">${c.unread_count}</span>` : ""}
                  <div class="meta">${fmtTime(c.last_message_at)}</div>
                </a>`).join("")}
        </div>
      ` : ""}
    `;
    return shell(inner, { title: "Dashboard" });
  }

  async function viewInbox() {
    let rows = [];
    let syncStatus = null;
    let error = "";
    try {
      rows = await api("/api/inbox");
      try {
        syncStatus = await api("/api/inbox/sync");
      } catch (_) {
        syncStatus = null;
      }
    } catch (e) {
      error = e.message;
    }
    const syncLine = syncStatus
      ? (syncStatus.error
          ? `Last sync failed: ${esc(syncStatus.error)}`
          : syncStatus.synced_at
            ? `Last sync: ${fmtTime(syncStatus.synced_at)} · ${esc(String(syncStatus.conversations_upserted || 0))} conversations`
            : "Not synced yet via Composio")
      : "";
    const inner = `
      ${error ? `<div class="err-box">${esc(error)}</div>` : ""}
      <div id="inbox-sync-msg" class="ok-box hidden"></div>
      <div id="inbox-sync-err" class="err-box hidden"></div>
      <div class="card">
        <div class="inbox-toolbar">
          <h2>Inbox</h2>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span class="sync-pill">Auto-sync every 5s</span>
            <button type="button" class="btn secondary sm" id="inbox-sync-btn">Sync</button>
          </div>
        </div>
        <p class="muted">Tap a conversation, then SEND FLOW. Webhook never auto-replies.</p>
        ${syncLine ? `<p class="muted" id="inbox-sync-status">${syncLine}</p>` : `<p class="muted" id="inbox-sync-status">Sync pulls conversations via Composio.</p>`}
        <div id="inbox-list">
          ${rows.length === 0 && !error ? `<p class="muted">No conversations yet.</p>` : rows.map(inboxItemHtml).join("")}
        </div>
      </div>
    `;
    return shell(inner, { title: "Inbox" });
  }

  function paintInboxRows(rows) {
    const list = document.getElementById("inbox-list");
    if (!list) return;
    if (!rows.length) {
      list.innerHTML = `<p class="muted">No conversations yet.</p>`;
      return;
    }
    list.innerHTML = rows.map(inboxItemHtml).join("");
    bindLocalLinks(list);
  }

  async function quietInboxSync(announce) {
    const msg = document.getElementById("inbox-sync-msg");
    const err = document.getElementById("inbox-sync-err");
    const statusEl = document.getElementById("inbox-sync-status");
    const data = await api("/api/inbox/sync", { method: "POST" });
    if (announce && msg) {
      msg.textContent = `Synced ${data.conversations_upserted || 0} conversations`;
      msg.classList.remove("hidden");
    }
    if (statusEl) {
      statusEl.textContent = data.error
        ? `Last sync failed: ${data.error}`
        : `Last sync: ${fmtTime(data.synced_at)} · ${data.conversations_upserted || 0} conversations`;
    }
    const rows = await api("/api/inbox");
    paintInboxRows(rows);
    return data;
  }

  function bindInbox() {
    document.getElementById("inbox-sync-btn")?.addEventListener("click", async () => {
      const btn = document.getElementById("inbox-sync-btn");
      const msg = document.getElementById("inbox-sync-msg");
      const err = document.getElementById("inbox-sync-err");
      msg?.classList.add("hidden");
      err?.classList.add("hidden");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Syncing…";
      }
      try {
        await quietInboxSync(true);
      } catch (ex) {
        if (err) {
          err.textContent = ex.message || "Sync failed";
          err.classList.remove("hidden");
        }
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Sync";
        }
      }
    });
    window.__inboxSyncTimer = setInterval(() => {
      quietInboxSync(false).catch(() => {});
    }, 5000);
  }

  async function viewConversation(id) {
    let detail = null;
    let flows = [];
    let error = "";
    try {
      detail = await api(`/api/conversations/${id}`);
      flows = (await api("/api/flows")).filter((f) => f.is_active);
    } catch (e) {
      error = e.message;
    }
    const title = detail?.conversation?.customer?.display_name || "Conversation";
    const active = detail?.active_execution;
    const busyActive = active && (active.status === "QUEUED" || active.status === "RUNNING");
    const msgs = detail?.messages || [];
    const inner = `
      ${error ? `<div class="err-box">${esc(error)}</div>` : ""}
      <div class="card">
        <div class="msgs" id="msgs">
          ${msgs.length === 0 && !error ? `<p class="muted">No messages.</p>` : ""}
          ${msgs.map((m) => `
            <div class="msg ${m.direction === "IN" ? "in" : "out"}">${esc(m.text || "(media)")}</div>
          `).join("")}
        </div>
      </div>
      <div class="card">
        <h2>SEND FLOW</h2>
        <p class="muted">Only this authenticated action starts sending. Webhook never auto-replies.</p>
        ${active ? `<p>Active: ${statusBadge(active.status)} <span class="muted">${esc(active.id.slice(0, 8))}…</span></p>` : ""}
        <div id="send-status" class="muted"></div>
        <div id="send-error" class="err-box hidden"></div>
        <select class="input" id="flow-select" ${busyActive ? "disabled" : ""}>
          ${flows.map((f, i) => `<option value="${esc(f.id)}" ${i === 0 ? "selected" : ""}>${esc(f.name)}</option>`).join("")}
        </select>
        <button class="btn lg" id="send-flow-btn"
          data-customer="${esc(detail?.conversation?.customer_id || "")}"
          ${!detail || !flows.length || busyActive ? "disabled" : ""}>
          ${busyActive ? "Flow running…" : "SEND FLOW"}
        </button>
        ${active && busyActive ? `
          <div class="flex-actions" style="margin-top:10px">
            <button class="btn secondary sm" id="cancel-exec" data-id="${esc(active.id)}">Cancel</button>
            <button class="btn secondary sm" id="refresh-conv">Refresh status</button>
          </div>
        ` : active && (active.status === "FAILED" || active.status === "CANCELLED") ? `
          <div class="flex-actions" style="margin-top:10px">
            <button class="btn secondary sm" id="retry-exec" data-id="${esc(active.id)}">Retry</button>
          </div>
        ` : ""}
      </div>
    `;
    return shell(inner, { title, showBack: true, backTo: "/inbox" });
  }

  function bindConversation() {
    const btn = document.getElementById("send-flow-btn");
    if (btn) {
      btn.addEventListener("click", async () => {
        const flowId = document.getElementById("flow-select")?.value;
        const customerId = btn.dataset.customer;
        if (!flowId || !customerId) return;
        const errEl = document.getElementById("send-error");
        const statusEl = document.getElementById("send-status");
        errEl.classList.add("hidden");
        btn.disabled = true;
        btn.textContent = "Starting…";
        statusEl.textContent = "Queuing execution…";
        try {
          const key = crypto.randomUUID();
          const res = await api(`/api/flows/${flowId}/customers/${customerId}/send`, {
            method: "POST",
            headers: { "Idempotency-Key": key },
          });
          const st = res?.execution?.status || "QUEUED";
          statusEl.innerHTML = `Execution ${statusBadge(st)}`;
          // Refresh view to show active execution
          setTimeout(() => render(), 400);
        } catch (e) {
          errEl.textContent = e.message || "Send failed";
          errEl.classList.remove("hidden");
          btn.disabled = false;
          btn.textContent = "SEND FLOW";
          statusEl.textContent = "";
        }
      });
    }
    document.getElementById("cancel-exec")?.addEventListener("click", async (e) => {
      const id = e.currentTarget.dataset.id;
      try {
        await api(`/api/executions/${id}/cancel`, { method: "POST" });
        render();
      } catch (err) {
        alert(err.message);
      }
    });
    document.getElementById("retry-exec")?.addEventListener("click", async (e) => {
      const id = e.currentTarget.dataset.id;
      try {
        await api(`/api/executions/${id}/retry`, { method: "POST" });
        render();
      } catch (err) {
        alert(err.message);
      }
    });
    document.getElementById("refresh-conv")?.addEventListener("click", () => render());
  }

  async function viewFlows() {
    let flows = [];
    let error = "";
    try {
      flows = await api("/api/flows");
    } catch (e) {
      error = e.message;
    }
    const inner = `
      ${error ? `<div class="err-box">${esc(error)}</div>` : ""}
      <div class="card">
        <h2>Flows</h2>
        <p class="muted">Create and edit message sequences.</p>
        ${flows.map((f) => `
          <a href="/flows/${esc(f.id)}" data-link class="list-item">
            <strong>${esc(f.name)} ${f.is_active ? '<span class="badge ok">Active</span>' : '<span class="badge">Inactive</span>'}</strong>
            <div class="meta">${esc(f.description || "")} · ${(f.steps || []).length} steps</div>
          </a>
        `).join("")}
        ${flows.length === 0 && !error ? `<p class="muted">No flows yet.</p>` : ""}
      </div>
      <div class="card">
        <h2>New flow</h2>
        <div id="new-flow-error" class="err-box hidden"></div>
        <input class="input" id="new-flow-name" placeholder="Flow name" />
        <textarea class="input" id="new-flow-desc" rows="2" placeholder="Description (optional)"></textarea>
        <button class="btn" id="create-flow-btn">Create flow</button>
      </div>
    `;
    return shell(inner, { title: "Flows" });
  }

  function bindFlows() {
    document.getElementById("create-flow-btn")?.addEventListener("click", async () => {
      const name = document.getElementById("new-flow-name")?.value?.trim();
      const description = document.getElementById("new-flow-desc")?.value || "";
      const errEl = document.getElementById("new-flow-error");
      if (!name) {
        errEl.textContent = "Name is required";
        errEl.classList.remove("hidden");
        return;
      }
      try {
        const flow = await api("/api/flows", {
          method: "POST",
          body: JSON.stringify({ name, description, is_active: true, steps: [] }),
        });
        navigate(`/flows/${flow.id}`);
      } catch (e) {
        errEl.textContent = e.message;
        errEl.classList.remove("hidden");
      }
    });
  }

  async function viewFlow(id) {
    let flow = null;
    let error = "";
    let mediaById = {};
    try {
      flow = await api(`/api/flows/${id}`);
      try {
        const assets = await api("/api/media");
        (assets || []).forEach((a) => { mediaById[a.id] = a; });
      } catch (_) { /* thumbnails optional */ }
    } catch (e) {
      error = e.message;
    }
    const steps = (flow?.steps || []).slice().sort((a, b) => a.position - b.position);
    window.__currentFlowSteps = steps;
    window.__currentFlowId = id;
    window.__mediaById = mediaById;
    const inner = `
      ${error ? `<div class="err-box">${esc(error)}</div>` : ""}
      ${flow ? `
        <div class="card">
          <div id="flow-meta-msg" class="ok-box hidden"></div>
          <div id="flow-meta-err" class="err-box hidden"></div>
          <input class="input" id="flow-name" value="${esc(flow.name)}" />
          <textarea class="input" id="flow-desc" rows="2">${esc(flow.description || "")}</textarea>
          <label class="check"><input type="checkbox" id="flow-active" ${flow.is_active ? "checked" : ""} /> Active</label>
          <div class="flex-actions">
            <button class="btn secondary" id="save-flow">Save</button>
            <button class="btn secondary" id="dup-flow">Duplicate</button>
            <button class="btn danger" id="del-flow">Delete</button>
          </div>
        </div>
        <div class="card">
          <h2>Steps</h2>
          ${steps.length === 0 ? `<p class="muted">No steps yet.</p>` : ""}
          ${steps.map((s, i) => `
            <div class="step-row" id="step-row-${esc(s.id)}" data-step-id="${esc(s.id)}">
              <div class="step-grip" aria-hidden="true">⋮⋮</div>
              <div class="step-body">
                <span class="badge type-${esc(s.step_type)}">${esc(s.step_type)}</span>
                ${s.delay_seconds ? `<span class="muted"> +${s.delay_seconds}s</span>` : ""}
                ${mediaCountLabel(s)}
                <div class="preview">${esc(s.content || (s.step_type === "DELAY" ? `(wait ${s.delay_seconds}s)` : ""))}</div>
              </div>
              <div class="step-actions">
                <button type="button" class="btn secondary sm icon step-up" data-id="${esc(s.id)}" ${i === 0 ? "disabled" : ""} title="Move up">↑</button>
                <button type="button" class="btn secondary sm icon step-down" data-id="${esc(s.id)}" ${i === steps.length - 1 ? "disabled" : ""} title="Move down">↓</button>
                <button type="button" class="btn secondary sm step-edit-btn" data-id="${esc(s.id)}">Edit</button>
                <button type="button" class="btn secondary sm del-step" data-id="${esc(s.id)}">✕</button>
              </div>
            </div>
            <div class="step-edit hidden" id="step-edit-${esc(s.id)}"></div>
          `).join("")}
        </div>
        <div class="card" id="add-step-card">
          <h2>Add step</h2>
          <div id="add-step-err" class="err-box hidden"></div>
          <label class="muted" for="step-type" style="display:block;margin-bottom:6px">Step type</label>
          <select class="input" id="step-type">
            <option value="TEXT">TEXT</option>
            <option value="IMAGE">IMAGE</option>
            <option value="AUDIO">AUDIO</option>
            <option value="VIDEO">VIDEO</option>
            <option value="DELAY">DELAY</option>
          </select>
          <p id="step-media-hint" class="muted" style="margin:0 0 10px">IMAGE / AUDIO / VIDEO: upload many files in one step (up to 50). SEND FLOW sends them one-by-one.</p>
          <div id="step-media-wrap" class="media-upload-wrap hidden">
            <p class="muted" style="margin:0 0 8px">Pick multiple files from gallery or Files</p>
            <label class="media-upload-label" for="step-file">📷 Upload from phone</label>
            <input type="file" id="step-file" class="media-file-input" accept="image/*,audio/*,video/*" multiple />
            <div id="step-media-chips" class="media-chips"></div>
            <div id="step-media-status" class="muted media-upload-status"></div>
          </div>
          <textarea class="input" id="step-content" rows="3" placeholder="Message text (Arabic OK)"></textarea>
          <input class="input" type="number" id="step-delay" min="0" value="0" placeholder="Delay seconds (0 = none)" />
          <button class="btn" id="add-step">Add step</button>
        </div>
      ` : ""}
    `;
    return shell(inner, { title: flow?.name || "Flow", showBack: true, backTo: "/flows" });
  }

  function bindFlow(id) {
    document.getElementById("save-flow")?.addEventListener("click", async () => {
      const msg = document.getElementById("flow-meta-msg");
      const err = document.getElementById("flow-meta-err");
      msg.classList.add("hidden");
      err.classList.add("hidden");
      try {
        await api(`/api/flows/${id}`, {
          method: "PATCH",
          body: JSON.stringify({
            name: document.getElementById("flow-name").value,
            description: document.getElementById("flow-desc").value,
            is_active: document.getElementById("flow-active").checked,
          }),
        });
        msg.textContent = "Saved";
        msg.classList.remove("hidden");
      } catch (e) {
        err.textContent = e.message;
        err.classList.remove("hidden");
      }
    });
    document.getElementById("dup-flow")?.addEventListener("click", async () => {
      try {
        const copy = await api(`/api/flows/${id}/duplicate`, { method: "POST" });
        navigate(`/flows/${copy.id}`);
      } catch (e) {
        alert(e.message);
      }
    });
    document.getElementById("del-flow")?.addEventListener("click", async () => {
      if (!confirm("Delete this flow?")) return;
      try {
        await api(`/api/flows/${id}`, { method: "DELETE" });
        navigate("/flows");
      } catch (e) {
        alert(e.message);
      }
    });
    document.querySelectorAll(".del-step").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/flows/${id}/steps/${btn.dataset.id}`, { method: "DELETE" });
          render();
        } catch (e) {
          alert(e.message);
        }
      });
    });

    async function swapStep(stepId, dir) {
      const steps = (window.__currentFlowSteps || []).slice().sort((a, b) => a.position - b.position);
      const i = steps.findIndex((s) => s.id === stepId);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= steps.length) return;
      const ids = steps.map((s) => s.id);
      const tmp = ids[i];
      ids[i] = ids[j];
      ids[j] = tmp;
      try {
        await api(`/api/flows/${id}/steps/reorder`, {
          method: "POST",
          body: JSON.stringify({ step_ids: ids }),
        });
        // Stay on the moved step — do not jump to Add step
        window.__focusStepId = stepId;
        render();
      } catch (e) {
        alert(e.message);
      }
    }
    document.querySelectorAll(".step-up").forEach((btn) => {
      btn.addEventListener("click", () => swapStep(btn.dataset.id, -1));
    });
    document.querySelectorAll(".step-down").forEach((btn) => {
      btn.addEventListener("click", () => swapStep(btn.dataset.id, 1));
    });

    // After ↑↓ reorder: keep the moved step in view and highlight it
    const focusId = window.__focusStepId;
    if (focusId) {
      window.__focusStepId = null;
      const row = document.getElementById(`step-row-${focusId}`);
      if (row) {
        row.classList.add("step-flash");
        row.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(() => row.classList.remove("step-flash"), 1200);
      }
    }

    function toggleEditPanel(stepId) {
      const panel = document.getElementById(`step-edit-${stepId}`);
      if (!panel) return;
      if (!panel.classList.contains("hidden") && panel.innerHTML) {
        panel.classList.add("hidden");
        panel.innerHTML = "";
        return;
      }
      document.querySelectorAll(".step-edit").forEach((el) => {
        el.classList.add("hidden");
        el.innerHTML = "";
      });
      const step = (window.__currentFlowSteps || []).find((s) => s.id === stepId);
      if (!step) return;
      const ids = effectiveMediaIds(step);
      const mediaById = window.__mediaById || {};
      const initial = ids.map((mid) => mediaById[mid] || {
        id: mid,
        filename: String(mid).slice(0, 8),
        public_url: null,
        media_type: String(step.step_type || "").toLowerCase(),
      });
      const types = ["TEXT", "IMAGE", "AUDIO", "VIDEO", "DELAY"];
      panel.innerHTML = `
        <div class="step-edit-err err-box hidden"></div>
        <select class="input edit-type">
          ${types.map((t) => `<option value="${t}" ${step.step_type === t ? "selected" : ""}>${t}</option>`).join("")}
        </select>
        <div class="media-upload-wrap edit-media-wrap hidden">
          <p class="muted" style="margin:0 0 8px">Add or remove files (max 50)</p>
          <label class="media-upload-label">📷 Upload more</label>
          <input type="file" class="media-file-input edit-file" accept="image/*,audio/*,video/*" multiple />
          <div class="media-chips edit-chips"></div>
          <div class="muted media-upload-status edit-media-status"></div>
        </div>
        <textarea class="input edit-content" rows="3">${esc(step.content || "")}</textarea>
        <input class="input edit-delay" type="number" min="0" value="${esc(String(step.delay_seconds || 0))}" placeholder="Delay seconds (0 = none)" />
        <div class="flex-actions">
          <button type="button" class="btn sm save-edit">Save</button>
          <button type="button" class="btn secondary sm cancel-edit">Cancel</button>
        </div>
      `;
      const label = panel.querySelector(".media-upload-label");
      const fileEl = panel.querySelector(".edit-file");
      if (label && fileEl) {
        const fid = `edit-file-${stepId}`;
        fileEl.id = fid;
        label.setAttribute("for", fid);
      }
      const picker = attachMediaPicker({
        fileEl,
        chipsEl: panel.querySelector(".edit-chips"),
        statusEl: panel.querySelector(".edit-media-status"),
        typeEl: panel.querySelector(".edit-type"),
        initial,
      });
      function syncEditMedia() {
        const t = panel.querySelector(".edit-type").value;
        const wrap = panel.querySelector(".edit-media-wrap");
        wrap.classList.toggle("hidden", !isMediaType(t));
        if (fileEl && isMediaType(t)) fileEl.accept = acceptFor(t);
        const content = panel.querySelector(".edit-content");
        if (t === "DELAY") content.placeholder = "Leave empty for DELAY";
        else if (isMediaType(t)) content.placeholder = "Optional caption";
        else content.placeholder = "Message text (Arabic OK)";
      }
      panel.querySelector(".edit-type").addEventListener("change", syncEditMedia);
      syncEditMedia();
      panel.querySelector(".cancel-edit").addEventListener("click", () => {
        panel.classList.add("hidden");
        panel.innerHTML = "";
      });
      panel.querySelector(".save-edit").addEventListener("click", async () => {
        const errEl = panel.querySelector(".step-edit-err");
        errEl.classList.add("hidden");
        if (picker.isUploading()) return;
        const step_type = panel.querySelector(".edit-type").value;
        const content = panel.querySelector(".edit-content").value;
        const delay_seconds = Number(panel.querySelector(".edit-delay").value) || 0;
        const mediaIds = picker.getIds();
        const body = { step_type, delay_seconds };
        if (step_type === "DELAY") {
          body.content = null;
          body.media_asset_ids = [];
          body.media_asset_id = null;
        } else if (isMediaType(step_type)) {
          if (!mediaIds.length) {
            const looksUrl = /^https?:\/\//i.test((content || "").trim());
            if (looksUrl) {
              body.content = content.trim();
              body.media_asset_ids = [];
              body.media_asset_id = null;
            } else {
              errEl.textContent = "Upload media first (or paste an https URL).";
              errEl.classList.remove("hidden");
              return;
            }
          } else {
            body.media_asset_ids = mediaIds;
            body.media_asset_id = mediaIds[0];
            body.content = (content || "").trim() || null;
          }
        } else {
          body.content = content || null;
          body.media_asset_ids = [];
          body.media_asset_id = null;
        }
        try {
          await api(`/api/flows/${id}/steps/${stepId}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          });
          render();
        } catch (e) {
          errEl.textContent = e.message;
          errEl.classList.remove("hidden");
        }
      });
      panel.classList.remove("hidden");
    }
    document.querySelectorAll(".step-edit-btn").forEach((btn) => {
      btn.addEventListener("click", () => toggleEditPanel(btn.dataset.id));
    });

    const typeEl = document.getElementById("step-type");
    const wrapEl = document.getElementById("step-media-wrap");
    const fileEl = document.getElementById("step-file");
    const statusEl = document.getElementById("step-media-status");
    const chipsEl = document.getElementById("step-media-chips");
    const contentEl = document.getElementById("step-content");
    const addBtn = document.getElementById("add-step");

    const addPicker = attachMediaPicker({
      fileEl,
      chipsEl,
      statusEl,
      typeEl,
      initial: [],
    });

    function updatePlaceholder() {
      if (!contentEl) return;
      const t = typeEl?.value;
      if (t === "DELAY") contentEl.placeholder = "Leave empty for DELAY";
      else if (isMediaType(t)) contentEl.placeholder = "Optional caption";
      else contentEl.placeholder = "Message text (Arabic OK)";
    }

    function syncMediaUi() {
      const t = typeEl?.value;
      const show = isMediaType(t);
      if (wrapEl) wrapEl.classList.toggle("hidden", !show);
      if (fileEl && show) fileEl.accept = acceptFor(t);
      updatePlaceholder();
      if (!show) addPicker.clear();
    }
    typeEl?.addEventListener("change", syncMediaUi);
    typeEl?.addEventListener("input", syncMediaUi);
    syncMediaUi();

    addBtn?.addEventListener("click", async () => {
      const errEl = document.getElementById("add-step-err");
      errEl.classList.add("hidden");
      if (addPicker.isUploading()) return;
      const step_type = typeEl.value;
      const content = contentEl.value;
      const delay_seconds = Number(document.getElementById("step-delay").value) || 0;
      const mediaIds = addPicker.getIds();
      const body = { step_type, delay_seconds };

      if (step_type === "DELAY") {
        body.content = null;
      } else if (isMediaType(step_type)) {
        if (!mediaIds.length) {
          const looksUrl = /^https?:\/\//i.test((content || "").trim());
          if (looksUrl) {
            body.content = content.trim();
            body.media_asset_id = null;
            body.media_asset_ids = [];
          } else {
            errEl.textContent = "Upload media from your phone first (or paste an https URL as fallback).";
            errEl.classList.remove("hidden");
            return;
          }
        } else {
          body.media_asset_ids = mediaIds;
          body.media_asset_id = mediaIds[0];
          body.content = (content || "").trim() || null;
        }
      } else {
        body.content = content || null;
      }

      try {
        addBtn.disabled = true;
        await api(`/api/flows/${id}/steps`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        render();
      } catch (e) {
        errEl.textContent = e.message;
        errEl.classList.remove("hidden");
        addBtn.disabled = false;
      }
    });
  }

  async function viewSettings() {
    let settings = null;
    let page = null;
    let error = "";
    try {
      settings = await api("/api/settings/public");
      page = await api("/api/pages/status");
    } catch (e) {
      error = e.message;
    }
    const originHint = `${location.origin}/webhook`;
    const defaultPageId = settings?.meta_page_id_default || "106896232178599";
    const inner = `
      ${error ? `<div class="err-box">${esc(error)}</div>` : ""}
      <div id="settings-msg" class="ok-box hidden"></div>
      <div id="settings-err" class="err-box hidden"></div>
      <div class="card">
        <h2>Webhook (never auto-replies)</h2>
        ${settings ? `
          <p class="muted">Callback URL</p>
          <code>${esc(settings.webhook_url || originHint)}</code>
          <p class="muted" style="margin-top:8px">Verify token hint: ${esc(settings.meta_verify_token_hint)}</p>
          <p class="muted">API version: ${esc(settings.meta_graph_api_version)}</p>
          <p class="muted">PUBLIC_BASE_URL: ${esc(settings.public_base_url)}</p>
          <p class="muted">Messaging provider: ${esc(settings.messaging_provider || "meta")}${settings.composio_configured ? " · Composio configured" : ""}</p>
          <p><span class="badge ok">webhook_never_auto_replies = ${esc(String(settings.webhook_never_auto_replies))}</span></p>
        ` : `
          <p class="muted">Callback URL (this origin)</p>
          <code>${esc(originHint)}</code>
        `}
      </div>
      <div class="card">
        <h2>Connect via Composio</h2>
        <p class="muted">Uses COMPOSIO_* env. No Meta page token required. Default page: IMADS Agency (${esc(defaultPageId)}).</p>
        <button type="button" class="btn" id="connect-composio-btn">Connect via Composio</button>
      </div>
      <div class="card">
        <h2>Connect Page (manual / Meta token)</h2>
        ${page?.is_connected
          ? `<p><span class="badge ok">Connected</span> ${esc(page.name)} (${esc(page.page_id)}) · ${esc(page.provider || "meta")}</p>
             ${page.last_error ? `<p class="muted">Last error: ${esc(page.last_error)}</p>` : ""}`
          : `<p><span class="badge warn">Not connected</span></p>`}
        <form id="connect-form">
          <input class="input" name="page_id" placeholder="Page ID" required value="${esc(page?.page_id || defaultPageId)}" />
          <input class="input" name="name" placeholder="Page name (optional)" value="${esc(page?.name || "IMADS Agency")}" />
          <input class="input" name="access_token" placeholder="Page access token (optional for Composio)" autocomplete="off" />
          <button class="btn" type="submit">Connect</button>
        </form>
        ${page?.is_connected ? `<button class="btn secondary" id="disconnect-btn" style="margin-top:8px">Disconnect</button>` : ""}
      </div>
      <button class="btn danger" id="logout-btn">Log out</button>
    `;
    return shell(inner, { title: "Settings" });
  }

  function bindSettings() {
    document.getElementById("connect-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const msg = document.getElementById("settings-msg");
      const err = document.getElementById("settings-err");
      msg.classList.add("hidden");
      err.classList.add("hidden");
      const token = String(fd.get("access_token") || "").trim();
      try {
        await api("/api/pages/connect", {
          method: "POST",
          body: JSON.stringify({
            page_id: String(fd.get("page_id") || "").trim(),
            name: String(fd.get("name") || "").trim(),
            access_token: token,
            provider: token ? "meta" : "composio",
          }),
        });
        msg.textContent = "Page connected";
        msg.classList.remove("hidden");
        render();
      } catch (ex) {
        err.textContent = ex.message;
        err.classList.remove("hidden");
      }
    });
    document.getElementById("connect-composio-btn")?.addEventListener("click", async () => {
      const msg = document.getElementById("settings-msg");
      const err = document.getElementById("settings-err");
      msg.classList.add("hidden");
      err.classList.add("hidden");
      try {
        await api("/api/pages/connect-composio", { method: "POST" });
        msg.textContent = "Connected via Composio (IMADS Agency)";
        msg.classList.remove("hidden");
        render();
      } catch (ex) {
        err.textContent = ex.message;
        err.classList.remove("hidden");
      }
    });
    document.getElementById("disconnect-btn")?.addEventListener("click", async () => {
      try {
        await api("/api/pages/disconnect", { method: "POST" });
        render();
      } catch (ex) {
        alert(ex.message);
      }
    });
    document.getElementById("logout-btn")?.addEventListener("click", () => {
      clearTokens();
      navigate("/login");
    });
  }

  /* ---------- Render ---------- */
  async function render() {
    if (window.__inboxSyncTimer) {
      clearInterval(window.__inboxSyncTimer);
      window.__inboxSyncTimer = null;
    }
    const route = parseRoute();
    if (route.name !== "login" && !getToken()) {
      navigate("/login", true);
      return;
    }

    root.innerHTML = shell(`<p class="muted">Loading…</p>`, {
      title: "…",
      showNav: route.name !== "login",
    });

    let html = "";
    try {
      switch (route.name) {
        case "login":
          html = await viewLogin();
          break;
        case "dashboard":
          html = await viewDashboard();
          break;
        case "inbox":
          html = await viewInbox();
          break;
        case "conversation":
          html = await viewConversation(route.id);
          break;
        case "flows":
          html = await viewFlows();
          break;
        case "flow":
          html = await viewFlow(route.id);
          break;
        case "settings":
          html = await viewSettings();
          break;
        default:
          html = await viewDashboard();
      }
    } catch (e) {
      html = shell(`<div class="err-box">${esc(e.message)}</div>`, { title: "Error" });
    }
    root.innerHTML = html;

    // Bind global nav
    root.querySelectorAll("[data-link]").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        navigate(a.getAttribute("href"));
      });
    });
    root.querySelectorAll("[data-nav]").forEach((btn) => {
      btn.addEventListener("click", () => navigate(btn.dataset.nav));
    });

    if (route.name === "login") bindLogin();
    if (route.name === "inbox") bindInbox();
    if (route.name === "conversation") bindConversation();
    if (route.name === "flows") bindFlows();
    if (route.name === "flow") bindFlow(route.id);
    if (route.name === "settings") bindSettings();

    // Scroll messages to bottom
    const msgs = document.getElementById("msgs");
    if (msgs) msgs.scrollTop = msgs.scrollHeight;
  }

  // Service worker
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.getRegistrations().then((regs) => {
      regs.forEach((r) => r.update());
    }).catch(() => {});
    navigator.serviceWorker.register("/sw.js?v=20260913f").catch(() => {});
    // Drop stale caches from older builds that hid media upload
    if (window.caches) {
      caches.keys().then((keys) =>
        Promise.all(keys.filter((k) => k !== "messenger-flow-static-v7").map((k) => caches.delete(k)))
      ).catch(() => {});
    }
  }

  render();
})();
