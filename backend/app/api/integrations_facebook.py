"""Facebook OAuth Connect — Page select, encrypted tokens. Never return tokens to frontend."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.entities import AuditLog, ConnectedAccount, Page, User
from app.security.auth import get_current_user
from app.security.crypto import decrypt_maybe, encrypt_str
from app.services import facebook_oauth as fb
from app.services.meta_client import MetaAPIError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/facebook", tags=["integrations-facebook"])


class PageSelectRequest(BaseModel):
    page_id: str = Field(min_length=1)


def _settings_redirect(query: dict[str, str]) -> RedirectResponse:
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/") or ""
    # Prefer same-origin relative redirect for SPA
    qs = urlencode(query)
    # Absolute if PUBLIC_BASE_URL set (Railway / production)
    target = f"{base}/settings?{qs}" if base else f"/settings?{qs}"
    return RedirectResponse(url=target, status_code=302)


def _upsert_connected_account(
    db: Session,
    user_id: str,
    provider_user_id: str | None,
    encrypted_token: str,
    expires_in: int | None,
    scopes: str | None,
) -> ConnectedAccount:
    acct = (
        db.query(ConnectedAccount)
        .filter(ConnectedAccount.user_id == user_id, ConnectedAccount.provider == "facebook")
        .first()
    )
    if not acct:
        acct = ConnectedAccount(user_id=user_id, provider="facebook")
        db.add(acct)
    acct.provider_user_id = provider_user_id
    acct.status = "connected"
    acct.encrypted_user_access_token = encrypted_token
    acct.scopes = scopes
    acct.last_error = None
    if expires_in:
        acct.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    else:
        # Long-lived user tokens ~60 days
        acct.token_expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    db.flush()
    return acct


def _persist_selected_page(
    db: Session,
    *,
    user_id: str,
    account: ConnectedAccount | None,
    page_id: str,
    name: str,
    page_token: str,
    picture: str | None,
) -> Page:
    page = db.query(Page).filter(Page.page_id == page_id).first()
    if not page:
        page = Page(page_id=page_id)
        db.add(page)
    page.name = name or page_id
    page.access_token = encrypt_str(page_token) if page_token else ""
    page.provider = "meta"
    page.is_connected = True
    page.connected_at = datetime.now(timezone.utc)
    page.last_error = None
    page.page_image_url = picture or page.page_image_url
    page.connection_status = "connected"
    if account:
        page.connected_account_id = account.id

    for other in db.query(Page).filter(Page.page_id != page_id).all():
        other.is_connected = False
        if (other.provider or "").lower() == "meta":
            other.connection_status = "disconnected"

    webhook_ok = False
    try:
        fb.subscribe_page_webhooks(page_token, page_id)
        webhook_ok = True
        page.webhook_subscribed = True
        page.last_error = None
    except (MetaAPIError, Exception) as exc:
        msg = getattr(exc, "operator_message", None) or str(exc)
        page.webhook_subscribed = False
        page.last_error = f"Connected but webhook subscribe failed: {msg}"
        page.connection_status = "attention_required"
        logger.info("webhook subscribe failed for page_id=%s", page_id)

    db.add(
        AuditLog(
            user_id=user_id,
            action="facebook.page_select",
            entity_type="page",
            entity_id=page.id,
            detail=f"page_id={page_id};webhook={webhook_ok}",
        )
    )
    db.flush()
    return page


@router.get("/connect")
def facebook_connect(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    if not (settings.meta_app_id or "").strip() or not (settings.meta_app_secret or "").strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "META_APP_ID and META_APP_SECRET must be configured. "
                "Ask the app owner to set them in Railway and complete Meta App setup "
                "(see docs/CONNECT_FACEBOOK.md)."
            ),
        )
    state = fb.create_oauth_state(db, user.id)
    url = fb.build_authorize_url(state)
    db.add(
        AuditLog(
            user_id=user.id,
            action="facebook.connect_start",
            entity_type="user",
            entity_id=user.id,
            detail="authorize_url issued",
        )
    )
    db.commit()
    return {"authorize_url": url}


@router.get("/callback")
def facebook_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        reason = quote((error_description or error)[:200], safe="")
        return _settings_redirect({"facebook": "error", "reason": reason})

    user_id = fb.consume_oauth_state(db, state or "")
    if not user_id:
        return _settings_redirect({"facebook": "error", "reason": "invalid_or_expired_state"})

    if not code:
        return _settings_redirect({"facebook": "error", "reason": "missing_code"})

    try:
        short = fb.exchange_code(code)
        short_token = short["access_token"]
        long = fb.exchange_long_lived(short_token)
        user_token = long["access_token"]
        expires_in = long.get("expires_in") or short.get("expires_in")
        profile = fb.get_user_profile(user_token)
        pages = fb.list_pages(user_token)
    except Exception as exc:
        logger.info("facebook OAuth callback failed: %s", type(exc).__name__)
        # Clear any partial state
        reason = quote(str(exc)[:180], safe="")
        return _settings_redirect({"facebook": "error", "reason": reason or "oauth_exchange_failed"})

    settings = get_settings()
    acct = _upsert_connected_account(
        db,
        user_id=user_id,
        provider_user_id=str(profile.get("id") or ""),
        encrypted_token=encrypt_str(user_token),
        expires_in=int(expires_in) if expires_in else None,
        scopes=",".join(settings.meta_oauth_scope_list),
    )
    db.commit()

    if not pages:
        acct.status = "attention_required"
        acct.last_error = "No Facebook Pages available for this user"
        db.commit()
        return _settings_redirect({"facebook": "error", "reason": "no_pages"})

    fb.store_pending_pages(user_id, pages)

    if len(pages) == 1:
        p = pages[0]
        _persist_selected_page(
            db,
            user_id=user_id,
            account=acct,
            page_id=p["page_id"],
            name=p.get("name") or "",
            page_token=p.get("access_token") or "",
            picture=p.get("picture"),
        )
        fb.clear_pending_pages(user_id)
        db.commit()
        return _settings_redirect({"facebook": "connected"})

    db.commit()
    return _settings_redirect({"facebook": "select"})


@router.get("/status")
def facebook_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    acct = (
        db.query(ConnectedAccount)
        .filter(ConnectedAccount.user_id == user.id, ConnectedAccount.provider == "facebook")
        .first()
    )
    page = db.query(Page).filter(Page.is_connected.is_(True), Page.provider == "meta").first()
    if not page:
        page = (
            db.query(Page)
            .filter(Page.connected_account_id == (acct.id if acct else None))
            .first()
            if acct
            else None
        )
    pending = fb.load_pending_pages(user.id)
    attention = None
    if acct and acct.last_error:
        attention = acct.last_error
    if page and page.last_error:
        attention = page.last_error

    status = "disconnected"
    if page and page.is_connected and (page.provider or "").lower() == "meta":
        status = page.connection_status or "connected"
    elif acct and acct.status == "connected" and pending:
        status = "select_page"
    elif acct:
        status = acct.status or "disconnected"

    return {
        "provider": "facebook",
        "status": status,
        "account_status": acct.status if acct else "disconnected",
        "provider_user_id": acct.provider_user_id if acct else None,
        "page": (
            {
                "page_id": page.page_id,
                "name": page.name,
                "image_url": page.page_image_url,
                "webhook_subscribed": bool(page.webhook_subscribed),
                "provider": page.provider,
                "connection_status": page.connection_status,
                "is_connected": page.is_connected,
            }
            if page
            else None
        ),
        "pending_page_count": len(pending),
        "attention_message": attention,
        # Explicitly never include tokens
    }


@router.get("/pages")
def facebook_pages(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pending = fb.load_pending_pages(user.id)
    if pending:
        return {
            "mode": "select",
            "pages": [
                {
                    "page_id": p["page_id"],
                    "name": p.get("name") or "",
                    "picture": p.get("picture") or "",
                }
                for p in pending
            ],
        }
    # Currently connected / known meta pages (no tokens)
    pages = db.query(Page).filter(Page.provider == "meta").order_by(Page.name).all()
    return {
        "mode": "connected",
        "pages": [
            {
                "page_id": p.page_id,
                "name": p.name,
                "picture": p.page_image_url or "",
                "is_connected": p.is_connected,
                "webhook_subscribed": bool(p.webhook_subscribed),
            }
            for p in pages
        ],
    }


@router.post("/pages/select")
def facebook_select_page(
    body: PageSelectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pending = fb.load_pending_pages(user.id)
    match = next((p for p in pending if p.get("page_id") == body.page_id), None)
    if not match:
        raise HTTPException(status_code=400, detail="Page not in pending selection list. Reconnect Facebook.")
    token = match.get("access_token") or ""
    if not token:
        raise HTTPException(status_code=400, detail="Missing page token in pending selection")

    acct = (
        db.query(ConnectedAccount)
        .filter(ConnectedAccount.user_id == user.id, ConnectedAccount.provider == "facebook")
        .first()
    )
    page = _persist_selected_page(
        db,
        user_id=user.id,
        account=acct,
        page_id=match["page_id"],
        name=match.get("name") or "",
        page_token=token,
        picture=match.get("picture"),
    )
    fb.clear_pending_pages(user.id)
    db.commit()
    db.refresh(page)
    return {
        "ok": True,
        "page": {
            "page_id": page.page_id,
            "name": page.name,
            "image_url": page.page_image_url,
            "webhook_subscribed": bool(page.webhook_subscribed),
            "provider": page.provider,
            "connection_status": page.connection_status,
            "is_connected": page.is_connected,
        },
    }


@router.post("/disconnect")
def facebook_disconnect(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    acct = (
        db.query(ConnectedAccount)
        .filter(ConnectedAccount.user_id == user.id, ConnectedAccount.provider == "facebook")
        .first()
    )
    pages: list[Page] = []
    if acct:
        pages = db.query(Page).filter(Page.connected_account_id == acct.id).all()
    connected_meta = (
        db.query(Page).filter(Page.is_connected.is_(True), Page.provider == "meta").all()
    )
    seen = {p.id for p in pages}
    for p in connected_meta:
        if p.id not in seen:
            pages.append(p)

    for page in pages:
        raw = decrypt_maybe(page.access_token)
        if raw and page.page_id:
            fb.try_unsubscribe_page(raw, page.page_id)
        page.access_token = ""
        page.is_connected = False
        page.webhook_subscribed = False
        page.connection_status = "disconnected"
        page.connected_account_id = None
        page.last_error = None

    if acct:
        acct.status = "disconnected"
        acct.encrypted_user_access_token = None
        acct.last_error = None
        acct.token_expires_at = None

    fb.clear_pending_pages(user.id)
    db.add(
        AuditLog(
            user_id=user.id,
            action="facebook.disconnect",
            entity_type="connected_account",
            entity_id=acct.id if acct else None,
            detail="cleared",
        )
    )
    db.commit()
    return {"ok": True, "status": "disconnected"}


@router.post("/reconnect")
def facebook_reconnect(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Same as connect — return a fresh authorize_url."""
    return facebook_connect(db=db, user=user)
