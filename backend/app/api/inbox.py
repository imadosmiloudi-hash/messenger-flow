from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models.entities import Conversation, ExecutionStatus, FlowExecution, IncomingMessage, User
from app.schemas.common import (
    ConversationDetailOut,
    ConversationOut,
    CustomerOut,
    FlowExecutionOut,
    MessageOut,
)
from app.security.auth import get_current_user

router = APIRouter(prefix="/api", tags=["inbox"])


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

    # Mark read
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
