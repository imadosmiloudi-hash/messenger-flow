# Connect Facebook (OAuth) — operator guide

This app is a **single-admin operator**. End users never create Meta apps.
The **app owner** configures one Meta App once; operators then click **Connect Facebook** in Settings.

## Assumptions

1. End users never create Meta apps; the app owner configures the Meta App once.
2. OAuth flow: Facebook Login → user token → `/me/accounts` → Page select → store Page token (encrypted).
3. When a Meta OAuth Page is selected, `page.provider=meta` and the worker prefers Meta Graph for that page (when a token is present).
4. Composio remains available under **Advanced / alternate** in Settings.
5. Tokens at rest are Fernet-encrypted using a key derived from `SECRET_KEY` (`cryptography`).
6. Tokens are **never** returned to the frontend.

## Production host (exact values)

There is **no custom domain**. The only public production API origin is:

```
https://api-production-22f23.up.railway.app
```

Copy these **exact** values into the Meta App dashboard:

| Meta field | Exact value |
|------------|-------------|
| **App Domains** | `api-production-22f23.up.railway.app` |
| **Valid OAuth Redirect URIs** | `https://api-production-22f23.up.railway.app/api/integrations/facebook/callback` |
| **Webhook Callback URL** | `https://api-production-22f23.up.railway.app/webhook` |

Railway env (already required for Connect):

```
PUBLIC_BASE_URL=https://api-production-22f23.up.railway.app
META_REDIRECT_URI=https://api-production-22f23.up.railway.app/api/integrations/facebook/callback
```

Do **not** invent alternate hosts. Trailing slashes are normalized by the API; Meta’s Valid OAuth Redirect URI must match the callback URL **without** a trailing slash after `callback`.

## One-time Meta App owner steps

1. Open [Meta for Developers](https://developers.facebook.com/) → your app (or create one).
2. Add product **Facebook Login** (Facebook Login for Business / Classic Login as offered). Also add **Messenger** / **Webhooks** if you use Page messaging webhooks.
3. **Facebook Login → Settings**
   - **Client OAuth Login**: Yes
   - **Web OAuth Login**: Yes
   - **Valid OAuth Redirect URIs** — add exactly:
     ```
     https://api-production-22f23.up.railway.app/api/integrations/facebook/callback
     ```
4. **Settings → Basic → App Domains** — add exactly:
   ```
   api-production-22f23.up.railway.app
   ```
5. **Webhooks** (Messenger / Page):
   - Callback URL: `https://api-production-22f23.up.railway.app/webhook`  
     (Alias also available: `/api/webhooks/facebook`.)
   - Verify token: value of Railway `META_VERIFY_TOKEN`.
   - Subscribe to `messages` (and related fields as required).
6. Copy **App ID** → `META_APP_ID`, **App Secret** → `META_APP_SECRET`.
7. Ensure Railway also has: `PUBLIC_BASE_URL`, `META_REDIRECT_URI`, `SECRET_KEY`, `REDIS_URL`, `META_VERIFY_TOKEN`.
8. **Permissions** used by Connect:
   - `pages_show_list`
   - `pages_messaging`
   - `pages_manage_metadata`
   - `pages_read_engagement`
   - `business_management`
9. **App Review**: for production messaging to customers who are not app roles/testers, submit `pages_messaging` (and related) for App Review. Until approved, only users with a role on the app / Page can fully exercise messaging.

### Why Meta shows “domain not in app domains”

Connect returns HTTP 200 and redirects the browser to Facebook. Meta then validates that the redirect URI’s **host** is listed under **App Domains** and that the **full redirect URI** is listed under **Valid OAuth Redirect URIs**. If either is missing or mistyped (custom domain, `http://`, trailing slash, localhost), Facebook shows a domain / redirect error even though our `/connect` endpoint succeeded.

## Operator flow (Settings)

1. Open **Settings** → **Connected Accounts** → **Connect Facebook**.
2. Approve Facebook Login and Page permissions.
3. If multiple Pages: select one → **Connect Selected Page**.
4. Confirm badge shows Connected, webhook subscribed (or attention note if subscribe failed).
5. To switch account/Page: **Reconnect**. To clear: **Disconnect**.

## Env vars checklist

| Variable | Required | Notes |
|----------|----------|-------|
| `META_APP_ID` | yes | Meta App ID |
| `META_APP_SECRET` | yes | Meta App Secret |
| `META_VERIFY_TOKEN` | yes | Webhook verify |
| `PUBLIC_BASE_URL` | yes (prod) | HTTPS API origin, no trailing slash |
| `META_REDIRECT_URI` | recommended (prod) | Exact callback URL; defaults from public origin + `/api/integrations/facebook/callback` |
| `META_OAUTH_SCOPES` | optional | Defaults listed above |
| `SECRET_KEY` | yes | Fernet key material + JWT |
| `REDIS_URL` | yes | OAuth state + pending Page select TTL |
| `META_GRAPH_API_VERSION` | optional | Default `v26.0` |

In production the API **rejects** OAuth connect if the resolved redirect uses `http://`, `localhost`, or placeholders such as `your-ngrok-or-domain.example`.

## Security notes

- OAuth `state` is bound to the logged-in operator (`Redis` preferred, DB fallback, 10 min TTL).
- Pending Page tokens live in Redis (`oauth:pending_pages:{user_id}`, 30 min) encrypted.
- Page `access_token` column stores Fernet ciphertext after OAuth select.
- API `/status` and `/pages` never include token fields.
- `/api/settings/public` exposes `oauth_redirect_uri` / `oauth_redirect_host` only (no secrets).
