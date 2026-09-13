"""Process Meta webhook events. NEVER sends auto-replies."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.entities import (
    Conversation,
    Customer,
    IncomingMessage,
    MessageDirection,
)
from app.services.events import event_bus


def process_webhook_payload(db: Session, payload: dict) -> dict:
    """
    Store customers/messages only. Do NOT call Meta send APIs.
    Returns summary of what was stored.
    """
    stored = 0
    skipped_dup = 0

    if payload.get("object") != "page":
        return {"stored": 0, "skipped_dup": 0, "note": "ignored non-page object"}

    for entry in payload.get("entry", []):
        page_id = str(entry.get("id", ""))
        for event in entry.get("messaging", []):
            result = _handle_messaging_event(db, page_id, event)
            if result == "stored":
                stored += 1
            elif result == "dup":
                skipped_dup += 1

    db.commit()
    return {"stored": stored, "skipped_dup": skipped_dup, "auto_reply": False}


def _handle_messaging_event(db: Session, page_id: str, event: dict) -> str:
    sender = event.get("sender", {})
    psid = str(sender.get("id", ""))
    if not psid or not page_id:
        return "ignored"

    # Delivery / read receipts — ignore (no reply)
    if "delivery" in event or "read" in event:
        return "ignored"

    message = event.get("message")
    if not message:
        # postback etc. — store as notification only if needed; skip auto actions
        return "ignored"

    # Echo of our own outbound — skip to avoid noise (still no reply)
    if message.get("is_echo"):
        return "ignored"

    meta_mid = message.get("mid")
    if meta_mid:
        existing = (
            db.query(IncomingMessage)
            .filter(IncomingMessage.meta_message_id == meta_mid)
            .first()
        )
        if existing:
            return "dup"

    customer = (
        db.query(Customer)
        .filter(Customer.page_id == page_id, Customer.psid == psid)
        .first()
    )
    now = datetime.now(timezone.utc)
    if not customer:
        customer = Customer(page_id=page_id, psid=psid, display_name=f"User {psid[-6:]}")
        db.add(customer)
        db.flush()

    customer.last_message_at = now

    conversation = (
        db.query(Conversation).filter(Conversation.customer_id == customer.id).first()
    )
    if not conversation:
        conversation = Conversation(customer_id=customer.id, page_id=page_id)
        db.add(conversation)
        db.flush()

    text = message.get("text")
    msg_type = "text"
    if message.get("attachments"):
        att = message["attachments"][0]
        msg_type = att.get("type", "attachment")
        if not text:
            text = f"[{msg_type} attachment]"

    preview = (text or f"[{msg_type}]")[:200]
    conversation.last_message_preview = preview
    conversation.last_message_at = now
    conversation.unread_count = (conversation.unread_count or 0) + 1

    incoming = IncomingMessage(
        customer_id=customer.id,
        conversation_id=conversation.id,
        page_id=page_id,
        psid=psid,
        meta_message_id=meta_mid,
        direction=MessageDirection.IN,
        message_type=msg_type,
        text=text,
        raw_payload=json.dumps(event),
    )
    db.add(incoming)
    db.flush()

    # Notify UI only — NEVER send a Messenger reply from webhook path
    event_bus.publish_sync(
        "inbox.message",
        {
            "conversation_id": conversation.id,
            "customer_id": customer.id,
            "message_id": incoming.id,
            "text": preview,
            "psid": psid,
        },
    )
    return "stored"
