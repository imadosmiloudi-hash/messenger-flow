from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.entities import AuditLog, Page, User
from app.schemas.common import PageConnectRequest, PageOut
from app.security.auth import get_current_user
from app.security.crypto import decrypt_maybe
from app.services.meta_client import MetaAPIError, MetaClient

router = APIRouter(prefix="/api/pages", tags=["pages"])

DEFAULT_PAGE_ID = "106896232178599"
DEFAULT_PAGE_NAME = "IMADS Agency"


def _page_out(page: Page) -> PageOut:
    return PageOut(
        id=page.id,
        page_id=page.page_id,
        name=page.name,
        is_connected=page.is_connected,
        connected_at=page.connected_at,
        last_error=page.last_error,
        provider=page.provider or "meta",
        has_token=bool(page.access_token),
    )


@router.get("/status", response_model=PageOut | None)
def page_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    page = db.query(Page).filter(Page.is_connected.is_(True)).first()
    if not page:
        page = db.query(Page).first()
    return _page_out(page) if page else None


@router.post("/connect", response_model=PageOut)
def connect_page(
    body: PageConnectRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    provider = (body.provider or "meta").strip().lower()
    if provider not in ("meta", "composio"):
        raise HTTPException(status_code=400, detail="provider must be meta or composio")

    # Composio: page_id + name enough; token optional
    if provider == "composio" or (not body.access_token and settings.uses_composio()):
        provider = "composio"
        if not settings.composio_api_key:
            raise HTTPException(
                status_code=400,
                detail="Composio is not configured. Set COMPOSIO_API_KEY.",
            )
        page_id = (body.page_id or settings.meta_page_id or DEFAULT_PAGE_ID).strip()
        name = (body.name or DEFAULT_PAGE_NAME).strip() or DEFAULT_PAGE_NAME
        page = db.query(Page).filter(Page.page_id == page_id).first()
        if not page:
            page = Page(page_id=page_id)
            db.add(page)
        page.name = name
        if body.access_token:
            page.access_token = body.access_token
        page.provider = "composio"
        page.is_connected = True
        page.connected_at = datetime.now(timezone.utc)
        page.last_error = None
        for other in db.query(Page).filter(Page.page_id != page_id).all():
            other.is_connected = False
        db.add(
            AuditLog(
                user_id=user.id,
                action="page.connect",
                entity_type="page",
                entity_id=page.id,
                detail="provider=composio",
            )
        )
        db.commit()
        db.refresh(page)
        return _page_out(page)

    # Meta Graph path (token required)
    if not body.access_token:
        raise HTTPException(status_code=400, detail="access_token is required for Meta provider")

    name = body.name
    try:
        if body.access_token:
            client = MetaClient(access_token=body.access_token)
            info = client.get_page_info(body.page_id)
            name = name or info.get("name", "")
    except MetaAPIError as exc:
        page = db.query(Page).filter(Page.page_id == body.page_id).first()
        if not page:
            page = Page(page_id=body.page_id)
            db.add(page)
        page.name = name or body.page_id
        page.access_token = body.access_token
        page.provider = "meta"
        page.is_connected = True
        page.connected_at = datetime.now(timezone.utc)
        page.last_error = exc.operator_message
        db.add(
            AuditLog(
                user_id=user.id,
                action="page.connect",
                entity_type="page",
                entity_id=page.id,
                detail=exc.operator_message,
            )
        )
        db.commit()
        db.refresh(page)
        return _page_out(page)

    page = db.query(Page).filter(Page.page_id == body.page_id).first()
    if not page:
        page = Page(page_id=body.page_id)
        db.add(page)
    page.name = name or body.page_id
    page.access_token = body.access_token
    page.provider = "meta"
    page.is_connected = True
    page.connected_at = datetime.now(timezone.utc)
    page.last_error = None
    for other in db.query(Page).filter(Page.page_id != body.page_id).all():
        other.is_connected = False
    subscribe_detail = "ok"
    try:
        MetaClient(access_token=body.access_token).subscribe_app(body.page_id, ["messages"])
        subscribe_detail = "ok+subscribed"
    except MetaAPIError as sub_exc:
        page.last_error = sub_exc.operator_message
        subscribe_detail = f"connected but subscribe failed: {sub_exc.operator_message}"
    db.add(
        AuditLog(
            user_id=user.id,
            action="page.connect",
            entity_type="page",
            entity_id=page.id,
            detail=subscribe_detail,
        )
    )
    db.commit()
    db.refresh(page)
    return _page_out(page)


@router.post("/connect-composio", response_model=PageOut)
def connect_via_composio(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Connect IMADS Agency (or META_PAGE_ID) via Composio — no Meta page token required."""
    settings = get_settings()
    if not settings.composio_api_key:
        raise HTTPException(status_code=400, detail="COMPOSIO_API_KEY is not configured")
    page_id = (settings.meta_page_id or DEFAULT_PAGE_ID).strip()
    body = PageConnectRequest(
        page_id=page_id,
        name=DEFAULT_PAGE_NAME,
        access_token="",
        provider="composio",
    )
    return connect_page(body, db=db, user=user)


@router.post("/disconnect", response_model=PageOut | None)
def disconnect_page(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    page = db.query(Page).filter(Page.is_connected.is_(True)).first()
    if not page:
        raise HTTPException(status_code=404, detail="No connected page")
    page.is_connected = False
    page.access_token = ""
    page.last_error = None
    db.add(
        AuditLog(
            user_id=user.id,
            action="page.disconnect",
            entity_type="page",
            entity_id=page.id,
            detail=None,
        )
    )
    db.commit()
    db.refresh(page)
    return _page_out(page)


@router.post("/subscribe-webhooks", response_model=PageOut)
def subscribe_webhooks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Subscribe connected Page to messages webhooks using the stored Page token."""
    page = db.query(Page).filter(Page.is_connected.is_(True)).first()
    token = decrypt_maybe(page.access_token) if page and page.access_token else ""
    if not page or not token:
        raise HTTPException(status_code=400, detail="No connected page with token")
    try:
        MetaClient(access_token=token).subscribe_app(page.page_id, ["messages"])
        page.last_error = None
        detail = "subscribed"
    except MetaAPIError as exc:
        page.last_error = exc.operator_message
        detail = exc.operator_message
        db.add(
            AuditLog(
                user_id=user.id,
                action="page.subscribe_webhooks",
                entity_type="page",
                entity_id=page.id,
                detail=detail,
            )
        )
        db.commit()
        db.refresh(page)
        raise HTTPException(status_code=400, detail=exc.operator_message)
    db.add(
        AuditLog(
            user_id=user.id,
            action="page.subscribe_webhooks",
            entity_type="page",
            entity_id=page.id,
            detail=detail,
        )
    )
    db.commit()
    db.refresh(page)
    return _page_out(page)
