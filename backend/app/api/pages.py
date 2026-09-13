from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.entities import AuditLog, Page, User
from app.schemas.common import PageConnectRequest, PageOut
from app.security.auth import get_current_user
from app.services.meta_client import MetaAPIError, MetaClient

router = APIRouter(prefix="/api/pages", tags=["pages"])


def _page_out(page: Page) -> PageOut:
    return PageOut(
        id=page.id,
        page_id=page.page_id,
        name=page.name,
        is_connected=page.is_connected,
        connected_at=page.connected_at,
        last_error=page.last_error,
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
    # Optional verify with Meta
    name = body.name
    try:
        if body.access_token:
            client = MetaClient(access_token=body.access_token)
            info = client.get_page_info(body.page_id)
            name = name or info.get("name", "")
    except MetaAPIError as exc:
        # Allow saving token even if verify fails (offline / wrong perms) but record error
        page = db.query(Page).filter(Page.page_id == body.page_id).first()
        if not page:
            page = Page(page_id=body.page_id)
            db.add(page)
        page.name = name or body.page_id
        page.access_token = body.access_token
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
    page.is_connected = True
    page.connected_at = datetime.now(timezone.utc)
    page.last_error = None
    # Disconnect others
    for other in db.query(Page).filter(Page.page_id != body.page_id).all():
        other.is_connected = False
    db.add(
        AuditLog(
            user_id=user.id,
            action="page.connect",
            entity_type="page",
            entity_id=page.id,
            detail="ok",
        )
    )
    db.commit()
    db.refresh(page)
    return _page_out(page)


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
