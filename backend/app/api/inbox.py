from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.models.entities import (
    AuditLog,
    Conversation,
    Customer,
    ExecutionStatus,
    FlowExecution,
    IncomingMessage,
    MessageDirection,
    Page,
    Setting,
    User,
)
from app.schemas.common import (
    ConversationDetailOut,
    ConversationOut,
    CustomerOut,
    FlowExecutionOut,
    InboxSyncOut,
    MessageOut,
)
from app.security.auth import get_current_user
from app.services.composio_client import (
    ComposioAPIError,
    ComposioClient,
    parse_conversations_payload,
    parse_messages_payload,
)
from app.services.events import event_bus

router = APIRouter(prefix="/api", tags=["inbox"])

SYNC_SETTING_KEY = "inbox_last_sync"
DEFAULT_PAGE_ID = "106896232178599"


def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    # Support ISO-8601 with Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


@router.get("/inbox", response_model=list[ConversationOut])
def list_inbox(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(50, le=200),
):
    rows = (
        db.query(Conversation)
        .options(joinedload(Conversation.customer))
        .order_by(Conversation.last_message_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    out = []
    for c in rows:
        item = ConversationOut.model_validate(c)
        if c.customer:
            item.customer = CustomerOut.model_validate(c.customer)
        out.append(item)
    return out


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
def conversation_detail(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = (
        db.query(Conversation)
        .options(joinedload(Conversation.customer))
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.unread_count = 0
    db.commit()

    messages = (
        db.query(IncomingMessage)
        .filter(IncomingMessage.conversation_id == conversation_id)
        .order_by(IncomingMessage.created_at.asc())
        .all()
    )

    active = (
        db.query(FlowExecution)
        .options(joinedload(FlowExecution.steps))
        .filter(
            FlowExecution.customer_id == conv.customer_id,
            FlowExecution.status.in_([ExecutionStatus.QUEUED, ExecutionStatus.RUNNING]),
        )
        .order_by(FlowExecution.created_at.desc())
        .first()
    )

    conv_out = ConversationOut.model_validate(conv)
    if conv.customer:
        conv_out.customer = CustomerOut.model_validate(conv.customer)

    return ConversationDetailOut(
        conversation=conv_out,
        messages=[MessageOut.model_validate(m) for m in messages],
        active_execution=FlowExecutionOut.model_validate(active) if active else None,
    )


def _resolve_sync_page_id(db: Session) -> str:
    settings = get_settings()
    page = db.query(Page).filter(Page.is_connected.is_(True)).first()
    if page and page.page_id:
        return page.page_id
    return (settings.meta_page_id or DEFAULT_PAGE_ID).strip()


def _get_sync_status(db: Session) -> dict:
    row = db.query(Setting).filter(Setting.key == SYNC_SETTING_KEY).first()
    if not row or not row.value:
        return {}
    try:
        return json.loads(row.value)
    except Exception:
        return {}


def _set_sync_status(db: Session, payload: dict) -> None:
    row = db.query(Setting).filter(Setting.key == SYNC_SETTING_KEY).first()
    if not row:
        row = Setting(key=SYNC_SETTING_KEY, value="")
        db.add(row)
    row.value = json.dumps(payload)
    db.flush()


def _run_inbox_sync(db: Session, user: User) -> InboxSyncOut:
    settings = get_settings()
    if not settings.composio_api_key:
        raise HTTPException(
            status_code=400,
            detail="Composio is not configured. Set COMPOSIO_API_KEY to sync inbox.",
        )

    page_id = _resolve_sync_page_id(db)
    now = datetime.now(timezone.utc)
    conversations_upserted = 0
    messages_upserted = 0

    try:
        client = ComposioClient()
        raw = client.list_conversations(page_id)
        parsed = parse_conversations_payload(raw, page_id)

        for item in parsed:
            psid = item["psid"]
            customer = (
                db.query(Customer)
                .filter(Customer.page_id == page_id, Customer.psid == psid)
                .first()
            )
            updated_at = _parse_dt(item.get("updated_time")) or now
            if not customer:
                customer = Customer(
                    page_id=page_id,
                    psid=psid,
                    display_name=item.get("display_name") or f"User {psid[-6:]}",
                    last_message_at=updated_at,
                )
                db.add(customer)
                db.flush()
            else:
                if item.get("display_name") and (
                    not customer.display_name
                    or customer.display_name.startswith("User ")
                ):
                    customer.display_name = item["display_name"]
                if not customer.last_message_at or updated_at >= customer.last_message_at:
                    customer.last_message_at = updated_at

            conv = (
                db.query(Conversation)
                .filter(Conversation.customer_id == customer.id, Conversation.page_id == page_id)
                .first()
            )
            preview = item.get("preview") or ""

            try:
                msg_raw = client.get_conversation_messages(
                    page_id, item["conversation_id"], limit=5
                )
                messages = parse_messages_payload(msg_raw)
                if messages:
                    newest = messages[0]
                    if newest.get("text"):
                        preview = newest["text"]
                    for m in messages:
                        mid = m.get("id") or None
                        if mid:
                            existing = (
                                db.query(IncomingMessage)
                                .filter(IncomingMessage.meta_message_id == mid)
                                .first()
                            )
                            if existing:
                                continue
                        from_id = m.get("from_id") or ""
                        direction = (
                            MessageDirection.OUT
                            if from_id == page_id
                            else MessageDirection.IN
                        )
                        text = m.get("text") or ""
                        created = _parse_dt(m.get("created_time")) or updated_at
                        if not conv:
                            conv = Conversation(
                                customer_id=customer.id,
                                page_id=page_id,
                                last_message_preview=preview or text[:500],
                                last_message_at=created,
                                unread_count=0,
                            )
                            db.add(conv)
                            db.flush()
                            conversations_upserted += 1
                        db.add(
                            IncomingMessage(
                                customer_id=customer.id,
                                conversation_id=conv.id,
                                page_id=page_id,
                                psid=psid,
                                meta_message_id=mid,
                                direction=direction,
                                message_type="text",
                                text=text or None,
                                raw_payload=None,
                                created_at=created,
                            )
                        )
                        messages_upserted += 1
            except ComposioAPIError:
                pass

            if not conv:
                conv = Conversation(
                    customer_id=customer.id,
                    page_id=page_id,
                    last_message_preview=(preview or "")[:500],
                    last_message_at=updated_at,
                    unread_count=0,
                )
                db.add(conv)
                db.flush()
                conversations_upserted += 1
            else:
                conversations_upserted += 1
                if preview:
                    conv.last_message_preview = preview[:500]
                if not conv.last_message_at or updated_at >= conv.last_message_at:
                    conv.last_message_at = updated_at

            if preview and conv:
                has_msg = (
                    db.query(IncomingMessage)
                    .filter(IncomingMessage.conversation_id == conv.id)
                    .first()
                )
                if not has_msg:
                    db.add(
                        IncomingMessage(
                            customer_id=customer.id,
                            conversation_id=conv.id,
                            page_id=page_id,
                            psid=psid,
                            meta_message_id=f"sync-preview-{item['conversation_id']}",
                            direction=MessageDirection.IN,
                            message_type="text",
                            text=preview[:2000],
                            created_at=updated_at,
                        )
                    )
                    messages_upserted += 1

        status = {
            "ok": True,
            "page_id": page_id,
            "conversations_upserted": conversations_upserted,
            "messages_upserted": messages_upserted,
            "provider": "composio",
            "synced_at": now.isoformat(),
            "error": None,
        }
        _set_sync_status(db, status)
        db.add(
            AuditLog(
                user_id=user.id,
                action="inbox.sync",
                entity_type="inbox",
                entity_id=None,
                detail=f"conversations={conversations_upserted} messages={messages_upserted}",
            )
        )
        db.commit()
        event_bus.publish_sync("inbox.synced", status)
        return InboxSyncOut(
            ok=True,
            page_id=page_id,
            conversations_upserted=conversations_upserted,
            messages_upserted=messages_upserted,
            provider="composio",
            synced_at=now,
            error=None,
        )
    except ComposioAPIError as exc:
        status = {
            "ok": False,
            "page_id": page_id,
            "conversations_upserted": 0,
            "messages_upserted": 0,
            "provider": "composio",
            "synced_at": now.isoformat(),
            "error": exc.operator_message,
        }
        _set_sync_status(db, status)
        db.commit()
        raise HTTPException(status_code=400, detail=exc.operator_message)


@router.post("/inbox/sync", response_model=InboxSyncOut)
def sync_inbox_post(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Pull Page conversations via Composio and upsert inbox rows. Auth required. No auto-replies."""
    return _run_inbox_sync(db, user)


@router.get("/inbox/sync", response_model=InboxSyncOut)
def sync_inbox_get(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    run: bool = Query(False, description="If true, run sync; otherwise return last status"),
):
    """Button-friendly sync: GET ?run=true runs sync; default returns last sync status."""
    if run:
        return _run_inbox_sync(db, user)
    status = _get_sync_status(db)
    synced_at = None
    if status.get("synced_at"):
        synced_at = _parse_dt(status["synced_at"])
    page_id = status.get("page_id") or _resolve_sync_page_id(db)
    return InboxSyncOut(
        ok=bool(status.get("ok", False)) if status else True,
        page_id=page_id,
        conversations_upserted=int(status.get("conversations_upserted") or 0),
        messages_upserted=int(status.get("messages_upserted") or 0),
        provider=status.get("provider") or "composio",
        synced_at=synced_at,
        error=status.get("error"),
    )
