"""Meta webhook — verify + store only. NEVER auto-reply."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.services.meta_client import verify_signature
from app.services.webhook_processor import process_webhook_payload

router = APIRouter(tags=["webhook"])


@router.get("/webhook")
def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    # In development without app secret, allow unsigned for local testing
    if settings.meta_app_secret:
        if not verify_signature(settings.meta_app_secret, body, signature):
            raise HTTPException(status_code=403, detail="Invalid signature")
    elif settings.app_env not in ("development", "test"):
        raise HTTPException(status_code=403, detail="META_APP_SECRET required")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    # CRITICAL: only store + notify UI — never send messages here
    result = process_webhook_payload(db, payload)
    return {"ok": True, **result}


@router.get("/api/webhooks/facebook")
def verify_webhook_alias(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    return verify_webhook(hub_mode=hub_mode, hub_verify_token=hub_verify_token, hub_challenge=hub_challenge)


@router.post("/api/webhooks/facebook")
async def receive_webhook_alias(request: Request, db: Session = Depends(get_db)):
    return await receive_webhook(request, db)

