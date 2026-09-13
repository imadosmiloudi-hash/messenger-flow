# Messenger Flow Operator

Production-oriented **operator console** for sending sequenced Messenger messages (text / image / audio / video). Sends via **Composio** (preferred when configured) or the **official Meta Graph API** fallback.

> **Native Messenger custom “SEND FLOW” button is NOT possible.**  
> Meta Messenger does not allow third-party apps to inject custom action buttons into the native Messenger UI for page operators. This project ships a **mobile-first installable PWA** operator console instead. Operators open conversations in the PWA and tap a large **SEND FLOW** button.

## Critical product rules

1. **Webhook never auto-replies.** `GET/POST /webhook` only verifies the subscription and **stores** customers/messages, then notifies the UI (SSE). It never calls Graph `messages` send APIs.
2. **Only authenticated `POST /api/flows/{id}/customers/{customer_id}/send`** (Idempotency-Key supported) queues a flow execution.
3. **No Selenium / Playwright / scraping / unofficial APIs.** Official Meta Graph API (`META_GRAPH_API_VERSION` default **`v26.0`**).
4. Credentials are never invented — use placeholders in `.env.example` only.

## Final operator workflow

1. Customer messages your Facebook Page (opens the 24h messaging window).
2. Meta sends a webhook → this backend **stores** the message in inbox (no reply).
3. Operator opens the **PWA** → Inbox → conversation.
4. Operator selects a Flow → taps **SEND FLOW**.
5. API creates a `QUEUED` execution (blocks duplicate active runs per customer+flow with **409**).
6. RQ worker sends steps sequentially via Graph API (`messaging_type: RESPONSE`), updates progress, stops on failure.
7. Operator can **cancel** or **retry** from the API / UI.

## Meta limitations (important)

| Limitation | Impact |
|---|---|
| **24-hour messaging window** | You can only send `RESPONSE` messages after the user messaged the Page (standard messaging window). Outside the window, Meta returns errors mapped to a friendly operator message. |
| **Public HTTPS media URLs** | Image/audio/video attachments must be fetchable by Meta over public HTTPS. Local `localhost` URLs will fail — use ngrok/Cloudflare Tunnel or a CDN. |
| **App Review & permissions** | Production sending requires a Meta app with approved Messenger permissions and a Page access token. |
| **No native SEND FLOW button** | Build/use this PWA; do not attempt unofficial Messenger UI hacks. |
| **Rate limits** | Meta may rate-limit; worker stops on failure and surfaces the error. |

## Meta dashboard setup

1. Create a Meta App at [developers.facebook.com](https://developers.facebook.com/) → add **Messenger**.
2. Generate a **Page access token** for your Facebook Page.
3. In Messenger → Webhooks:
   - Callback URL: `https://<your-public-host>/webhook`
   - Verify token: same as `META_VERIFY_TOKEN` in `.env`
   - Subscribe to `messages` (and optionally `messaging_postbacks`)
4. Paste Page ID + Page access token into the PWA **Settings → Connect Page** (or set env vars for bootstrap).
5. Ensure media files are served under your public HTTPS base (`PUBLIC_BASE_URL`).

### Permissions list (typical)

- `pages_messaging`
- `pages_manage_metadata`
- `pages_read_engagement`
- `pages_show_list` (if listing pages)
- Advanced/optional depending on product: `pages_messaging_subscriptions`

Exact required permissions can vary with Meta product changes — follow the current Messenger Platform docs for Graph **v26.0**.

## Composio hybrid messaging

When `MESSAGING_PROVIDER=composio` (default) and `COMPOSIO_API_KEY` is set, SEND FLOW and inbox sync use Composio tools against the connected Facebook account (`COMPOSIO_CONNECTED_ACCOUNT_ID`, e.g. `facebook_alvar-therm`):

- Text: `FACEBOOK_SEND_MESSAGE`
- Image / audio / video: `FACEBOOK_SEND_MEDIA_MESSAGE`
- Inbox sync: `FACEBOOK_GET_PAGE_CONVERSATIONS` (+ optional `FACEBOOK_GET_CONVERSATION_MESSAGES`)

Set `MESSAGING_PROVIDER=meta` to force the direct Graph API path with a Page access token. Webhooks still never auto-reply — only authenticated **SEND FLOW** sends.

Default Page for Composio mode: **IMADS Agency** (`META_PAGE_ID=106896232178599`). Settings → **Connect via Composio** needs no Meta page token. Inbox → **Sync** pulls conversations into the operator UI.

Required env (see `.env.example`): `COMPOSIO_API_KEY`, `COMPOSIO_CONNECTED_ACCOUNT_ID`, `COMPOSIO_USER_ID`, `MESSAGING_PROVIDER`, `META_PAGE_ID`.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Redis + RQ, httpx, JWT auth
- **Operator UI (production):** Static mobile-first PWA served by FastAPI from `backend/app/static/` (no Node build)
- **Frontend (optional / local):** Next.js 14 App Router still in `frontend/` for local dual-port development
- **DB:** SQLite by default (`sqlite:///./data/app.db`); Postgres via `DATABASE_URL` in Docker Compose

## Project layout

```
messenger-flow/
  README.md
  .env.example
  docker-compose.yml
  backend/          # FastAPI API + RQ worker + static operator PWA (app/static)
  frontend/         # Next.js PWA (kept for local/dev; not required on Railway)
  scripts/          # seed_admin.py, setup_dev.sh
```

## Local development

### Option A — Docker Compose

```bash
cp .env.example .env
# edit ADMIN_*, META_*, SECRET_KEY, PUBLIC_BASE_URL
docker compose up --build
```

- API: http://localhost:8000  
- Frontend: http://localhost:3000  
- Postgres + Redis included  

### Option B — Uvicorn + RQ + ngrok

```bash
./scripts/setup_dev.sh
# Start Redis locally, then:
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
# other terminal:
rq worker messenger --url redis://localhost:6379/0
# tunnel for Meta webhooks + media:
ngrok http 8000
# set PUBLIC_BASE_URL to the ngrok HTTPS URL, restart API
cd frontend && npm install && npm run dev
```

Default admin (from `.env.example`): `admin@example.com` / `change-me-strong-password` — **change in production**.

### Tests

```bash
cd backend
pip install -r requirements.txt
APP_ENV=test pytest -q
```

## Exact manual steps for the operator

1. Install the PWA on your phone (browser → Add to Home Screen) or open the site.
2. Log in with your operator account.
3. **Settings** → paste Page ID + Page access token → Connect.
4. Confirm webhook URL with Meta (Settings shows the hint).
5. Wait for a customer message (appears in **Inbox** — no auto-reply).
6. Open the conversation → choose a flow (default **Welcome Flow** has 8 steps) → tap **SEND FLOW**.
7. Watch status (queued/running). If something fails (token, 24h window, media URL), fix and **Retry**.

## Production notes

### Railway / single-service operator UI

**Production on Railway serves the operator PWA from the FastAPI backend** (`backend/app/static/`), not the Next.js `frontend/` app. Open:

`https://api-production-22f23.up.railway.app/`

(or your Railway API public URL). Log in, then use Dashboard / Inbox / Flows / Settings. Same-origin relative `/api/*` calls — no separate frontend service or Node build on the Metal builder.

The Next.js app in `frontend/` remains in the repo for optional local development (`npm run dev` on :3000 talking to the API). Prefer the static UI on Railway until the frontend build is restored.


- Use Postgres (`DATABASE_URL`) and managed Redis.
- Set a strong `SECRET_KEY`, rotate Page tokens, restrict CORS.
- Terminate TLS at your reverse proxy; Meta requires HTTPS for webhooks.
- Run at least one RQ worker process per environment.
- Serve uploaded media on a stable public HTTPS hostname (`PUBLIC_BASE_URL`).
- Do not enable any auto-reply in the webhook path — keep send behind authenticated operator action.
- Monitor Graph API errors (190 token, messaging window, media URL).

## API overview

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/auth/login` | — | JWT |
| POST | `/api/auth/refresh` | — | |
| GET | `/api/auth/me` | ✓ | |
| GET/POST | `/api/pages/status\|connect\|disconnect` | ✓ | Manual token paste |
| GET | `/api/inbox`, `/api/conversations/{id}` | ✓ | |
| GET/POST | `/api/inbox/sync` | ✓ | Composio inbox sync (`?run=true` on GET) |
| POST | `/api/pages/connect-composio` | ✓ | Connect IMADS Agency without Meta token |
| CRUD | `/api/flows` (+ steps, reorder, duplicate) | ✓ | |
| POST | `/api/flows/{id}/customers/{customer_id}/send` | ✓ | Starts flow only |
| GET/POST | `/api/executions/{id}`, `…/cancel`, `…/retry` | ✓ | |
| POST/GET | `/api/media/upload`, `/api/media` | ✓ | |
| GET/POST | `/webhook` | Meta signature | **No auto-reply** |
| GET | `/api/events` | ✓ | SSE |

## License

Private repository — all rights reserved by the owner.
