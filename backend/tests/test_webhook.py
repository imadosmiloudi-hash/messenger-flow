import hashlib
import hmac
import json

from app.models.entities import IncomingMessage
from app.services.meta_client import MetaClient, map_meta_error, verify_signature


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_webhook_verify(client):
    r = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify_token_test",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 200
    assert r.text == "12345"


def test_webhook_verify_fail(client):
    r = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 403


def test_signature_verify():
    body = b'{"object":"page"}'
    sig = _sign("test_app_secret", body)
    assert verify_signature("test_app_secret", body, sig)
    assert not verify_signature("test_app_secret", body, "sha256=deadbeef")
    assert not verify_signature("test_app_secret", body, None)


def test_incoming_no_reply(client, db, monkeypatch):
    """Webhook stores message and must NOT call Meta send."""
    sent = {"called": False}

    def boom(*a, **k):
        sent["called"] = True
        raise AssertionError("send must not be called from webhook")

    monkeypatch.setattr(MetaClient, "send_text", boom)
    monkeypatch.setattr(MetaClient, "send_attachment", boom)

    payload = {
        "object": "page",
        "entry": [
            {
                "id": "PAGE1",
                "messaging": [
                    {
                        "sender": {"id": "PSID111"},
                        "recipient": {"id": "PAGE1"},
                        "timestamp": 123,
                        "message": {"mid": "m1", "text": "Hello"},
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode()
    r = client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign("test_app_secret", body),
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["auto_reply"] is False
    assert data["stored"] == 1
    assert sent["called"] is False
    assert db.query(IncomingMessage).count() == 1


def test_idempotent_webhook(client, db):
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "PAGE1",
                "messaging": [
                    {
                        "sender": {"id": "PSID222"},
                        "recipient": {"id": "PAGE1"},
                        "message": {"mid": "mid-dup", "text": "Hi"},
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": _sign("test_app_secret", body),
    }
    r1 = client.post("/webhook", content=body, headers=headers)
    r2 = client.post("/webhook", content=body, headers=headers)
    assert r1.json()["stored"] == 1
    assert r2.json()["skipped_dup"] == 1
    assert db.query(IncomingMessage).filter(IncomingMessage.meta_message_id == "mid-dup").count() == 1


def test_meta_error_mapping():
    assert "token" in map_meta_error(190, None, "err").lower()
    assert "24" in map_meta_error(551, None, "err").lower() or "window" in map_meta_error(
        551, None, "err"
    ).lower()
    assert "permission" in map_meta_error(10, None, "permission").lower()
    assert "media" in map_meta_error(100, None, "attachment url invalid").lower()
