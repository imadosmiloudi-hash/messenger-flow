import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.entities import ExecutionStatus, FlowExecution, IncomingMessage, Page, User
from app.schemas.common import ConversationOut, DashboardOut, PageOut, PublicSettingsOut
from app.security.auth import get_current_user
from app.services.events import event_bus

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def sse_events(request: Request, user: User = Depends(get_current_user)):
    """Server-Sent Events for inbox / execution updates."""

    async def gen():
        sid, queue = await event_bus.subscribe()
        try:
            yield f"data: {json.dumps({'type': 'connected', 'data': {}})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping', 'data': {}})}\n\n"
        finally:
            await event_bus.unsubscribe(sid)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models.entities import Conversation

    page = db.query(Page).filter(Page.is_connected.is_(True)).first()
    page_out = None
    if page:
        page_out = PageOut(
            id=page.id,
            page_id=page.page_id,
            name=page.name,
            is_connected=page.is_connected,
            connected_at=page.connected_at,
            last_error=page.last_error,
            has_token=bool(page.access_token),
        )
    unread = db.query(Conversation).with_entities(Conversation.unread_count).all()
    unread_total = sum(r[0] or 0 for r in unread)
    running = (
        db.query(FlowExecution)
        .filter(FlowExecution.status == ExecutionStatus.RUNNING)
        .count()
    )
    queued = (
        db.query(FlowExecution)
        .filter(FlowExecution.status == ExecutionStatus.QUEUED)
        .count()
    )
    recent = (
        db.query(Conversation)
        .order_by(Conversation.last_message_at.desc().nullslast())
        .limit(10)
        .all()
    )
    return DashboardOut(
        page_connected=bool(page and page.is_connected),
        page=page_out,
        unread_messages=unread_total,
        running_executions=running,
        queued_executions=queued,
        recent_conversations=[ConversationOut.model_validate(c) for c in recent],
    )


@router.get("/settings/public", response_model=PublicSettingsOut)
def public_settings(user: User = Depends(get_current_user)):
    settings = get_settings()
    token = settings.meta_verify_token
    hint = (token[:3] + "…" + token[-3:]) if len(token) > 8 else "***"
    base = settings.public_base_url.rstrip("/")
    return PublicSettingsOut(
        app_name=settings.app_name,
        meta_graph_api_version=settings.meta_graph_api_version,
        meta_verify_token_hint=hint,
        public_base_url=base,
        webhook_url=f"{base}/webhook",
        webhook_never_auto_replies=True,
    )
