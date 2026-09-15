"""Facebook Login OAuth → Page token flow. Never log tokens/codes/secrets."""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from redis import Redis
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import OAuthState
from app.security.crypto import decrypt_str, encrypt_str

logger = logging.getLogger(__name__)

STATE_TTL_SEC = 600  # 10 minutes
PENDING_TTL_SEC = 1800  # 30 minutes
PENDING_KEY = "oauth:pending_pages:{user_id}"
STATE_KEY = "oauth:state:{state}"


def _graph_base() -> str:
    return get_settings().meta_graph_base


def _redis() -> Redis | None:
    try:
        r = Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=1.0,
            decode_responses=True,
        )
        r.ping()
        return r
    except Exception:
        logger.debug("Redis unavailable for OAuth state; using DB fallback")
        return None


def create_oauth_state(db: Session, user_id: str) -> str:
    state = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SEC)
    r = _redis()
    if r is not None:
        try:
            r.setex(STATE_KEY.format(state=state), STATE_TTL_SEC, user_id)
            return state
        except Exception:
            logger.debug("Redis setex failed; falling back to DB state")
    db.add(OAuthState(state=state, user_id=user_id, expires_at=expires))
    db.commit()
    return state


def consume_oauth_state(db: Session, state: str) -> str | None:
    """Validate and consume state; returns user_id or None."""
    if not state:
        return None
    r = _redis()
    if r is not None:
        try:
            key = STATE_KEY.format(state=state)
            user_id = r.get(key)
            if user_id:
                r.delete(key)
                return str(user_id)
        except Exception:
            logger.debug("Redis get/delete failed for OAuth state")
    row = db.get(OAuthState, state)
    if not row:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    user_id = row.user_id
    db.delete(row)
    db.commit()
    if expires < datetime.now(timezone.utc):
        return None
    return user_id


def store_pending_pages(user_id: str, pages: list[dict[str, Any]]) -> None:
    """Store selectable pages with encrypted page tokens (Redis preferred, DB via Setting not used)."""
    payload = []
    for p in pages:
        token = p.get("access_token") or ""
        payload.append(
            {
                "page_id": p.get("page_id") or p.get("id"),
                "name": p.get("name") or "",
                "access_token": encrypt_str(token) if token else "",
                "picture": p.get("picture") or p.get("page_image_url") or "",
            }
        )
    data = json.dumps(payload)
    r = _redis()
    if r is not None:
        try:
            r.setex(PENDING_KEY.format(user_id=user_id), PENDING_TTL_SEC, data)
            return
        except Exception:
            logger.warning("Failed to store pending pages in Redis")
    # Soft fallback: keep in-process only for tests (no Redis)
    _MEMORY_PENDING[user_id] = (data, datetime.now(timezone.utc) + timedelta(seconds=PENDING_TTL_SEC))


_MEMORY_PENDING: dict[str, tuple[str, datetime]] = {}


def load_pending_pages(user_id: str) -> list[dict[str, Any]]:
    raw = None
    r = _redis()
    if r is not None:
        try:
            raw = r.get(PENDING_KEY.format(user_id=user_id))
        except Exception:
            raw = None
    if raw is None and user_id in _MEMORY_PENDING:
        data, expires = _MEMORY_PENDING[user_id]
        if expires >= datetime.now(timezone.utc):
            raw = data
        else:
            _MEMORY_PENDING.pop(user_id, None)
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for p in items:
        enc = p.get("access_token") or ""
        token = ""
        if enc:
            try:
                token = decrypt_str(enc)
            except ValueError:
                token = enc  # should not happen
        out.append(
            {
                "page_id": p.get("page_id"),
                "name": p.get("name") or "",
                "access_token": token,
                "picture": p.get("picture") or "",
            }
        )
    return out


def clear_pending_pages(user_id: str) -> None:
    r = _redis()
    if r is not None:
        try:
            r.delete(PENDING_KEY.format(user_id=user_id))
        except Exception:
            pass
    _MEMORY_PENDING.pop(user_id, None)


def build_authorize_url(state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.resolved_meta_redirect_uri,
        "state": state,
        "scope": ",".join(settings.meta_oauth_scope_list),
        "response_type": "code",
    }
    return f"https://www.facebook.com/{settings.meta_graph_api_version}/dialog/oauth?{urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    """Exchange auth code for short-lived user access token."""
    settings = get_settings()
    params = {
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "redirect_uri": settings.resolved_meta_redirect_uri,
        "code": code,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{_graph_base()}/oauth/access_token", params=params)
        data = resp.json() if resp.content else {}
    if "access_token" not in data:
        err = data.get("error", {})
        raise RuntimeError(err.get("message") or "Failed to exchange OAuth code")
    return data


def exchange_long_lived(user_token: str) -> dict[str, Any]:
    """Exchange short-lived user token for long-lived (~60 days)."""
    settings = get_settings()
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "fb_exchange_token": user_token,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{_graph_base()}/oauth/access_token", params=params)
        data = resp.json() if resp.content else {}
    if "access_token" not in data:
        err = data.get("error", {})
        raise RuntimeError(err.get("message") or "Failed to exchange long-lived token")
    return data


def get_user_profile(user_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{_graph_base()}/me",
            params={"fields": "id,name", "access_token": user_token},
        )
        data = resp.json() if resp.content else {}
    if "error" in data:
        raise RuntimeError(data["error"].get("message") or "Failed to fetch user profile")
    return data


def list_pages(user_token: str) -> list[dict[str, Any]]:
    """GET /me/accounts?fields=id,name,access_token,picture{url}"""
    pages: list[dict[str, Any]] = []
    url = f"{_graph_base()}/me/accounts"
    params: dict[str, Any] = {
        "fields": "id,name,access_token,picture{url}",
        "access_token": user_token,
        "limit": 100,
    }
    with httpx.Client(timeout=30.0) as client:
        while url:
            resp = client.get(url, params=params)
            data = resp.json() if resp.content else {}
            if "error" in data:
                raise RuntimeError(data["error"].get("message") or "Failed to list pages")
            for item in data.get("data") or []:
                pic = ""
                picture = item.get("picture") or {}
                if isinstance(picture, dict):
                    pic = (picture.get("data") or {}).get("url") or picture.get("url") or ""
                pages.append(
                    {
                        "page_id": item.get("id"),
                        "name": item.get("name") or "",
                        "access_token": item.get("access_token") or "",
                        "picture": pic,
                    }
                )
            next_url = (data.get("paging") or {}).get("next")
            url = next_url
            params = {}  # next URL already has query params
    return pages


def subscribe_page_webhooks(page_token: str, page_id: str) -> dict[str, Any]:
    """Subscribe app to Page messages webhooks."""
    from app.services.meta_client import MetaClient

    return MetaClient(access_token=page_token).subscribe_app(
        page_id,
        ["messages", "messaging_postbacks", "message_deliveries", "message_reads"],
    )


def try_unsubscribe_page(page_token: str, page_id: str) -> bool:
    try:
        from app.services.meta_client import MetaClient

        MetaClient(access_token=page_token).unsubscribe_app(page_id)
        return True
    except Exception:
        logger.info("unsubscribe_app failed or unsupported for page_id=%s", page_id)
        return False
