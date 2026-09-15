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

## One-time Meta App owner steps

1. Open [Meta for Developers](https://developers.facebook.com/) → your app (or create one).
2. Add product **Facebook Login** (and Messenger / Webhooks as needed).
3. **Facebook Login → Settings → Valid OAuth Redirect URIs**  
   Add exactly:
   ```
   https://api-production-22f23.up.railway.app/api/integrations/facebook/callback
   ```
   (Or your `META_REDIRECT_URI` / `PUBLIC_BASE_URL` + `/api/integrations/facebook/callback`.)
4. **App Domains**: add your Railway / public host (e.g. `api-production-22f23.up.railway.app`).
5. **Webhooks** (Messenger / Page):
   - Callback URL: `https://api-production-22f23.up.railway.app/webhook`  
     (Alias also available: `/api/webhooks/facebook`.)
   - Verify token: value of Railway `META_VERIFY_TOKEN`.
   - Subscribe to `messages` (and related fields as required).
6. Copy **App ID** → `META_APP_ID`, **App Secret** → `META_APP_SECRET`.
7. Ensure Railway also has: `PUBLIC_BASE_URL`, `SECRET_KEY`, `REDIS_URL`, `META_VERIFY_TOKEN`.
   Optional: `META_REDIRECT_URI` (defaults to `PUBLIC_BASE_URL` + `/api/integrations/facebook/callback`).
8. **Permissions** used by Connect:
   - `pages_show_list`
   - `pages_messaging`
   - `pages_manage_metadata`
   - `pages_read_engagement`
   - `business_management`
9. **App Review**: for production messaging to customers who are not app roles/testers, submit `pages_messaging` (and related) for App Review. Until approved, only users with a role on the app / Page can fully exercise messaging.

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
| `PUBLIC_BASE_URL` | yes | HTTPS API origin |
| `META_REDIRECT_URI` | optional | Defaults from `PUBLIC_BASE_URL` |
| `META_OAUTH_SCOPES` | optional | Defaults listed above |
| `SECRET_KEY` | yes | Fernet key material + JWT |
| `REDIS_URL` | yes | OAuth state + pending Page select TTL |
| `META_GRAPH_API_VERSION` | optional | Default `v26.0` |

## Security notes

- OAuth `state` is bound to the logged-in operator (`Redis` preferred, DB fallback, 10 min TTL).
- Pending Page tokens live in Redis (`oauth:pending_pages:{user_id}`, 30 min) encrypted.
- Page `access_token` column stores Fernet ciphertext after OAuth select.
- API `/status` and `/pages` never include token fields.
